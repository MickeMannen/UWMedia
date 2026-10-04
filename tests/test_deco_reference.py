"""
Reference dives (tests/deco_reference, see its README): our planner
against Subsurface's, stop by stop, within each dive's tolerance. A dive
with a `known_gap` is expected to differ until the gap is fixed.
"""
import pytest

from scripts.deco_reference import (
    RAW_DIR, REFERENCE_DIR, ReferenceError, compare, convert_file, json_text, load_references, parse_raw,
    port_schedule,
)
from utils.dive_plan_engine import SAFETY_STOP_SEC

REFERENCES = load_references()


@pytest.mark.parametrize("raw", sorted(RAW_DIR.glob("*.txt")), ids=lambda p: p.stem)
def test_reference_json_is_converted_from_its_raw_file(raw):
    out = REFERENCE_DIR / f"{raw.stem}.json"
    assert out.exists(), f"run: python scripts/deco_reference.py convert"
    assert out.read_text(encoding="utf-8") == json_text(convert_file(raw)), (
        f"{out.name} is out of date - run: python scripts/deco_reference.py convert"
    )


@pytest.mark.parametrize("ref", REFERENCES, ids=lambda r: r["source"])
def test_planner_matches_subsurface(ref):
    problems, table = compare(ref)
    if ref.get("known_gap"):
        if problems:
            pytest.xfail(ref["known_gap"])
        pytest.fail(f"{ref['source']} matches now - remove its known_gap line\n{table}")
    assert not problems, table


@pytest.mark.parametrize("ref", [r for r in REFERENCES if port_schedule(r)], ids=lambda r: r["source"])
def test_planner_matches_the_subsurface_port(ref):
    """Same bottom, fresh tissues: our planner against the port of
    Subsurface's planner (scripts/subsurface_port.py), within the dive's
    tolerance. Our last stop is never shorter than the safety stop, which
    the port leaves out, so its 3 m stop is lengthened to match first."""
    port = port_schedule(ref)
    stops = [dict(s) for s in port["stops"]]
    last = next((s for s in stops if s["depth_m"] == 3.0), None)
    if last is None:
        last = {"depth_m": 3.0, "minutes": 0.0, "gas": ref["gases"][0]["name"]}
        stops.append(last)
    added = max(0.0, SAFETY_STOP_SEC / 60.0 - last["minutes"])
    last["minutes"] += added
    as_reference = {**ref, "known_gap": "", "expected": {"stops": stops, "runtime_min": port["runtime_min"] + added}}
    problems, table = compare(as_reference)
    assert not problems, table


# --- the converter itself -------------------------------------------------

SAMPLE = """name: sample
notes: tab-separated rows
Subsurface (6.0.5576) dive plan created on 2026-10-04
Runtime: 50min

depth\tduration\truntime\tgas
➘\t30m\t2min\t2min\t21/35
➙\t30m\t28min\t30min\t
➚\t21m\t1min\t31min\t
-\t21m\t1min\t32min\tEAN50
➚\t3m\t2min\t34min\t
-\t3m\t16min\t50min\t
➚\t0m\t0min\t50min\t

CNS: 9%
OTU: 20

Deco model: Bühlmann ZHL-16C with GFLow = 40% and GFHigh = 85%
ATM pressure: 1 013mbar (0m)
"""


def test_converter_reads_the_plan_table():
    ref = parse_raw(SAMPLE, "sample")
    assert ref["settings"]["gf_low"] == 40 and ref["settings"]["gf_high"] == 85
    assert [(g["name"], g["o2_percent"], g["he_percent"], g["switch_depth_m"]) for g in ref["gases"]] == [
        ("21/35", 21.0, 35.0, None), ("EAN50", 50.0, 0.0, 21.0),
    ]
    assert ref["bottom"] == [{"depth_m": 30.0, "runtime_min": 2.0}, {"depth_m": 30.0, "runtime_min": 30.0}]
    assert [(s["depth_m"], s["minutes"], s["gas"]) for s in ref["expected"]["stops"]] == [
        (21.0, 1.0, "EAN50"), (3.0, 16.0, "EAN50"),
    ]
    assert (ref["expected"]["runtime_min"], ref["expected"]["cns_pct"], ref["expected"]["otu"]) == (50, 9, 20)


def test_converter_refuses_a_plan_that_follows_another_dive():
    text = SAMPLE.replace("dive plan created", "dive plan (surface interval 0:03) created")
    with pytest.raises(ReferenceError, match="surface interval"):
        parse_raw(text, "sample")


def test_converter_accepts_a_surface_interval_with_a_reason():
    text = SAMPLE.replace("dive plan created", "dive plan (surface interval 0:03) created")
    ref = parse_raw("surface_interval_ok: first dive of the day\n" + text, "sample")
    assert ref["surface_interval_ok"] == "first dive of the day"


NO_LEVEL_BOTTOM = """Subsurface (6.0.5576) dive plan created on 2026-10-04
Runtime: 26min

depth\tduration\truntime\tgas
➘\t15m\t0min\t0min\tair
➘\t18m\t20min\t20min\t
➚\t3m\t2min\t22min\t
➙\t3m\t3min\t25min\t
➚\t0m\t1min\t26min\t

Deco model: Bühlmann ZHL-16C with GFLow = 40% and GFHigh = 85%
"""


def test_converter_ends_the_bottom_at_the_first_ascent_and_keeps_the_safety_stop():
    ref = parse_raw(NO_LEVEL_BOTTOM, "sample")
    assert ref["bottom"] == [{"depth_m": 15.0, "runtime_min": 0.0}, {"depth_m": 18.0, "runtime_min": 20.0}]
    assert ref["expected"]["stops"] == [{"depth_m": 3.0, "minutes": 3.0, "gas": "air"}]


def test_converter_refuses_unknown_header_lines():
    with pytest.raises(ReferenceError, match="Unknown header line"):
        parse_raw("gf: 30/70\n" + SAMPLE, "sample")
