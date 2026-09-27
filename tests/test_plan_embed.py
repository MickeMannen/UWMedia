"""
Open log for the Dive Profile Builder: the plan embedded in every saved log
(parsers/plan_embed.py), the UWMedia-only gate, and the rebuild from an
older log without an embedded plan (utils/dive_plan_import.py).
"""
import io
import contextlib
from datetime import datetime
from pathlib import Path

import pytest

from models.dive_plan import DiveProfilePlan, PlannedGas, PlannedWaypoint
from parsers.fit_writer import write_fit
from parsers.garmin import GarminParser
from parsers.plan_embed import read_log_origin
from parsers.subsurface import SubsurfaceParser
from parsers.subsurface_writer import write_subsurface
from parsers.uddf import UDDFParser
from parsers.uddf_writer import write_uddf
from utils.dive_plan_engine import plan_ascent, simulate
from utils.dive_plan_import import plan_from_log, simplify_profile

WRITERS = {
    "uddf": (write_uddf, UDDFParser),
    "fit": (write_fit, GarminParser),
    "ssrf": (write_subsurface, SubsurfaceParser),
}
START = datetime(2026, 9, 27, 10, 0, 0)


def _deco_plan(dive_type="sidemount"):
    """A 45 m dive that needs deco and switches to EAN50 on the way up."""
    plan = DiveProfilePlan(
        name="Embed test", dive_type=dive_type, gf_low=40, gf_high=85, sac_lpm=15, water_temp_c=27.0,
        computer="Garmin Descent X50i", computer_serial="4242", start_time=START,
        gases=[
            PlannedGas(id="EAN32", gas_type="nitrox", o2_percent=32.0, sidemount_pair=dive_type == "sidemount",
                       start_pressure_bar=200, use_max_depth_m=33.0),
            PlannedGas(id="EAN50", gas_type="nitrox", o2_percent=50.0, tank_ref="T2", use_max_depth_m=21.0,
                       use_phase="ascent", start_pressure_bar=180),
        ],
        waypoints=[
            PlannedWaypoint(runtime_sec=150, depth_m=33.0, gas_id="EAN32", gas_auto=True),
            PlannedWaypoint(runtime_sec=1800, depth_m=33.0, gas_id="EAN32", gas_auto=True),
        ],
    )
    ascent, deco_needed, _ = plan_ascent(plan)
    assert deco_needed
    plan.waypoints.extend(ascent)
    assert any(wp.gas_id == "EAN50" for wp in plan.waypoints)
    return plan


def _write(plan, fmt, tmp_path):
    samples, _ = simulate(plan, resolution_sec=1)
    writer, _parser = WRITERS[fmt]
    path = tmp_path / f"dive.{fmt}"
    writer(plan, samples, path)
    return path


def _parse(fmt, path):
    with contextlib.redirect_stdout(io.StringIO()):
        return WRITERS[fmt][1]().parse(path)[0]


@pytest.mark.parametrize("fmt", WRITERS)
def test_saved_log_carries_the_plan_and_restores_it_exactly(fmt, tmp_path):
    plan = _deco_plan()
    path = _write(plan, fmt, tmp_path)
    origin = read_log_origin(path)
    assert origin.created_by_uwmedia
    assert origin.plan is not None
    assert origin.plan.model_dump() == plan.model_dump()
    # ...without upsetting the ordinary parser
    assert len(_parse(fmt, path).waypoints) > 1000


@pytest.mark.parametrize("path", [
    "test_data/logs/fit/489 Camera Bay_new.fit",
    "test_data/logs/submersion_dives/005_oc-trimix-two-deco-gases--perdix2.uddf",
    "test_data/logs/submersion_dives/001_short_deco_single_gas_switch.ssrf.xml",
])
def test_real_computer_logs_are_not_uwmedias(path):
    origin = read_log_origin(path)
    assert not origin.created_by_uwmedia
    assert origin.plan is None


def test_unknown_or_missing_file_is_not_uwmedias(tmp_path):
    assert not read_log_origin(tmp_path / "missing.uddf").created_by_uwmedia
    junk = tmp_path / "junk.fit"
    junk.write_bytes(b"not a fit file")
    assert not read_log_origin(junk).created_by_uwmedia


def test_older_uddf_without_embedded_plan_is_still_uwmedias():
    # Saved by 0.7's builder: generator name only.
    origin = read_log_origin("test_data/logs/DecoTest.uddf")
    assert origin.created_by_uwmedia
    assert origin.plan is None


def _strip_embedded_plan(path):
    """The same file as an older builder wrote it: marker kept, plan gone."""
    if path.suffix == ".fit":
        return  # FIT has no older marker: a pre-0.8 FIT simply isn't recognised
    text = path.read_text()
    if path.suffix == ".uddf":
        start, end = text.index("<applicationdata>"), text.index("</applicationdata>") + len("</applicationdata>")
    else:
        start = text.index('<extradata key="UWMedia plan"')
        end = text.index("/>", start) + 2
    path.write_text(text[:start] + text[end:])


@pytest.mark.parametrize("fmt", ["uddf", "ssrf", "fit"])
def test_rebuilt_plan_from_a_log_without_the_embedded_plan(fmt, tmp_path):
    plan = _deco_plan()
    path = _write(plan, fmt, tmp_path)
    _strip_embedded_plan(path)
    if fmt != "fit":
        assert read_log_origin(path).created_by_uwmedia
        assert read_log_origin(path).plan is None
    rebuilt = plan_from_log(path, _parse(fmt, path), DiveProfilePlan(sac_lpm=17.0))

    assert rebuilt.computer == "Garmin Descent X50i"
    assert rebuilt.dive_type == "sidemount"
    assert rebuilt.start_time == START
    assert (rebuilt.gf_low, rebuilt.gf_high) == (40, 85)
    assert rebuilt.sac_lpm == 17.0  # not in a log - the base plan's
    assert rebuilt.water_temp_c == 27.0
    gases = {g.id: g for g in rebuilt.gases}
    assert set(gases) == {"EAN32", "EAN50"}
    assert gases["EAN32"].sidemount_pair and gases["EAN32"].tank_ref == "T1"
    assert gases["EAN32"].start_pressure_bar == 200
    assert gases["EAN50"].tank_ref == "T2" and not gases["EAN50"].sidemount_pair
    assert gases["EAN50"].start_pressure_bar == 180
    assert gases["EAN50"].use_phase == "ascent"

    wps = rebuilt.waypoints
    assert 4 <= len(wps) <= 60
    assert max(wp.depth_m for wp in wps) == 33.0
    switch = [wp for wp in wps if wp.gas_id == "EAN50"]
    assert switch and min(wp.runtime_sec for wp in switch) > 1800
    assert all(wp.gas_id == "EAN32" for wp in wps if wp.runtime_sec <= 1800)
    # the rebuilt profile follows the logged one within the simplification tolerance
    logged = [(wp.time_since_start, wp.depth) for wp in _parse(fmt, path).waypoints]
    knots = [(0, 0.0)] + [(wp.runtime_sec, wp.depth_m) for wp in wps]
    for t, depth in logged[::30]:
        after = next((k for k in knots if k[0] >= t), knots[-1])
        before = max((k for k in knots if k[0] <= t), key=lambda k: k[0])
        span = after[0] - before[0]
        rebuilt_depth = before[1] if span == 0 else before[1] + (after[1] - before[1]) * (t - before[0]) / span
        assert abs(rebuilt_depth - depth) <= 1.0, (t, depth, rebuilt_depth)
    # ...and the rebuilt plan simulates without complaint about its gases
    samples, warnings = simulate(rebuilt, resolution_sec=10)
    assert samples


def test_simplify_profile_keeps_corners_and_drops_straight_runs():
    points = [(t, 0.0 if t == 0 else 20.0 if t <= 600 else 20.0 - (t - 600) / 10.0) for t in range(0, 801, 10)]
    points = [(t, max(0.0, d)) for t, d in points]
    kept = simplify_profile(points)
    assert kept[0] == points[0] and kept[-1] == points[-1]
    assert (600, 20.0) in kept
    assert len(kept) <= 5
