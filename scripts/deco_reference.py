"""Reference dives for tuning the deco model against Subsurface's planner.

Each dive is a Subsurface plan pasted verbatim into
tests/deco_reference/raw/<name>.txt (optionally below a few
`key: value` lines, see HEADER_KEYS), converted to
tests/deco_reference/<name>.json - the dive's inputs and Subsurface's
schedule - and compared stop by stop with our planner
(utils.dive_plan_engine.plan_ascent). tests/test_deco_reference.py runs the
comparison for every JSON file.

    python scripts/deco_reference.py convert           # every raw file -> JSON
    python scripts/deco_reference.py compare [name...] # side-by-side tables
    python scripts/deco_reference.py port [name...]    # ours vs the Subsurface port
"""
import json
import math
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from models.dive_plan import DiveProfilePlan, PlannedGas, PlannedWaypoint  # noqa: E402
from utils.dive_plan_engine import plan_ascent, simulate  # noqa: E402
from scripts.subsurface_port import plan_reference  # noqa: E402

REFERENCE_DIR = REPO_ROOT / "tests" / "deco_reference"
RAW_DIR = REFERENCE_DIR / "raw"

# Segment symbols in Subsurface's plan table: descent, level, ascent, stop.
DESCENT, LEVEL, ASCENT, STOP = "➘", "➙", "➚", "-"
SEGMENT_SYMBOLS = {DESCENT, LEVEL, ASCENT, STOP, "–"}

# `key: value` lines allowed above the paste.
HEADER_KEYS = {
    "name": "Readable title (default: the file name)",
    "ascent_rate": "Our planner's single ascent rate, m/min (default 9)",
    "descent_rate": "m/min (default 18, Subsurface's default)",
    "notes": "Free text - Subsurface settings that differ from its defaults, etc.",
    "known_gap": "Why we don't match yet - the test then reports it as expected to fail",
    "surface_interval_ok": "Why a plan with 'surface interval' in its title can still be used (it is refused otherwise)",
    "tolerance_first_stop_m": "How far our first stop may be from Subsurface's (default 3)",
    "tolerance_stop_min": "Per-depth stop time difference allowed, minutes (default 2)",
    "tolerance_runtime_pct": "Total runtime difference allowed, percent (default 10)",
}
DEFAULT_TOLERANCE = {"first_stop_m": 3.0, "stop_min": 2.0, "runtime_pct": 10.0}


class ReferenceError(ValueError):
    """A raw file that can't be turned into a reference dive."""


# ---------------------------------------------------------------------------
# Raw Subsurface text -> reference dict
# ---------------------------------------------------------------------------

def gas_fractions(name: str) -> Tuple[float, float]:
    """(O2 %, He %) from a Subsurface gas name: air, EAN32, oxygen, 21/35."""
    key = name.strip().lower()
    if key == "air":
        return 21.0, 0.0
    if key in ("oxygen", "o2"):
        return 100.0, 0.0
    m = re.fullmatch(r"ean\s*(\d+(?:\.\d+)?)", key)
    if m:
        return float(m.group(1)), 0.0
    m = re.fullmatch(r"(?:tx\s*)?(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)", key)
    if m:
        return float(m.group(1)), float(m.group(2))
    raise ReferenceError(f"Unknown gas name '{name}' - expected air, EANxx, oxygen or O2/He like 21/35")


def _minutes(field: str) -> float:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*min", field.strip())
    if not m:
        raise ReferenceError(f"Expected a time like '3min', got '{field}'")
    return float(m.group(1))


def _metres(field: str) -> float:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*m", field.strip())
    if not m:
        raise ReferenceError(f"Expected a depth like '18m', got '{field}'")
    return float(m.group(1))


def _table_rows(text: str) -> List[Tuple[str, float, float, float, str]]:
    """(symbol, depth_m, duration_min, runtime_min, gas or "") per row. The
    copy from Subsurface's planner puts each cell on a line of its own; a
    copy with tab-separated rows works too."""
    fields: List[str] = []
    for line in text.splitlines():
        fields.extend(line.split("\t") if "\t" in line else [line])
    fields = [f.strip() for f in fields]
    try:
        i = next(k for k in range(len(fields) - 3) if fields[k:k + 4] == ["depth", "duration", "runtime", "gas"]) + 4
    except StopIteration:
        raise ReferenceError("No 'depth / duration / runtime / gas' table found in the paste") from None
    while i < len(fields) and fields[i] == "":
        i += 1
    rows = []
    while i < len(fields) and fields[i] in SEGMENT_SYMBOLS:
        symbol = STOP if fields[i] == "–" else fields[i]
        cells = (fields[i + 1:i + 5] + [""] * 4)[:4]
        rows.append((symbol, _metres(cells[0]), _minutes(cells[1]), _minutes(cells[2]), cells[3]))
        i += 5
    if not rows:
        raise ReferenceError("The plan table has no rows")
    return rows


def parse_raw(text: str, name: str) -> Dict:
    """A raw file's text -> the reference dict written as JSON."""
    lines = text.splitlines()
    start = next((k for k, line in enumerate(lines) if line.strip().startswith("Subsurface")), None)
    if start is None:
        raise ReferenceError("No Subsurface plan found - paste starts with 'Subsurface (<version>) dive plan'")
    header: Dict[str, str] = {}
    for line in lines[:start]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition(":")
        key = key.strip()
        if not sep or key not in HEADER_KEYS:
            raise ReferenceError(f"Unknown header line '{line.strip()}' - allowed keys: {', '.join(HEADER_KEYS)}")
        header[key] = value.strip()
    plan_text = "\n".join(lines[start:])
    title = lines[start]

    version = re.search(r"Subsurface \(([^)]+)\)", title)
    if re.search(r"surface interval", title, re.I) and not header.get("surface_interval_ok"):
        raise ReferenceError(
            "This plan follows another dive in the Subsurface logbook ('surface interval' in its title), "
            "so its tissues may not be fresh - replan it with no dive before it, or add a "
            "'surface_interval_ok: <why>' line if the earlier dive can't matter"
        )
    model = re.search(r"Deco model:\s*(.+)", plan_text)
    gf = re.search(r"GFLow\s*=\s*(\d+)%\s*and\s*GFHigh\s*=\s*(\d+)%", plan_text)
    if not model or "ZHL-16C" not in model.group(1) or not gf:
        raise ReferenceError("Only Bühlmann ZHL-16C plans with GF low/high can be used as references")
    runtime = re.search(r"Runtime:\s*(\d+)\s*min", plan_text)
    cns = re.search(r"CNS:\s*(\d+)\s*%", plan_text)
    otu = re.search(r"OTU:\s*(\d+)", plan_text)
    atm = re.search(r"ATM pressure:\s*([\d\s \xa0.,]+)mbar", plan_text)

    rows = _table_rows(plan_text)
    # The bottom is every row before the first ascent; after it, a stop row
    # is a deco stop and a level row is the no-deco safety stop.
    first_ascent = next((k for k, r in enumerate(rows) if r[0] == ASCENT), None)
    if not first_ascent:
        raise ReferenceError("The plan has no ascent (➚) after the bottom")
    last_bottom = first_ascent - 1

    gases: List[Dict] = []
    current = ""
    bottom, stops = [], []
    for k, (symbol, depth, duration, run, gas) in enumerate(rows):
        if gas and gas != current:
            if k > last_bottom:
                switch = depth  # first used on the ascent: where Subsurface picks it up
            elif not gases:
                switch = None
            else:
                raise ReferenceError(f"Gas change to {gas} before the end of the bottom isn't supported yet")
            o2, he = gas_fractions(gas)
            if not any(g["name"] == gas for g in gases):
                gases.append({"name": gas, "o2_percent": o2, "he_percent": he, "switch_depth_m": switch})
            current = gas
        if k <= last_bottom:
            bottom.append({"depth_m": depth, "runtime_min": run})
        elif symbol in (STOP, LEVEL):
            stops.append({"depth_m": depth, "minutes": duration, "gas": current})
    if not gases:
        raise ReferenceError("No gas named in the plan table")

    tolerance = dict(DEFAULT_TOLERANCE)
    for key in DEFAULT_TOLERANCE:
        if f"tolerance_{key}" in header:
            tolerance[key] = float(header[f"tolerance_{key}"])
    return {
        "name": header.get("name", name),
        "source": f"raw/{name}.txt",
        "subsurface_version": version.group(1) if version else None,
        "notes": header.get("notes", ""),
        "surface_interval_ok": header.get("surface_interval_ok", ""),
        "known_gap": header.get("known_gap", ""),
        "settings": {
            "gf_low": float(gf.group(1)),
            "gf_high": float(gf.group(2)),
            "ascent_rate": float(header.get("ascent_rate", 9)),
            "descent_rate": float(header.get("descent_rate", 18)),
            "surface_pressure_mbar": float(re.sub(r"[^\d.]", "", atm.group(1))) if atm else None,
        },
        "gases": gases,
        "bottom": bottom,
        "expected": {
            "stops": stops,
            "runtime_min": float(runtime.group(1)) if runtime else rows[-1][3],
            "cns_pct": float(cns.group(1)) if cns else None,
            "otu": float(otu.group(1)) if otu else None,
        },
        "tolerance": tolerance,
    }


def convert_file(raw_path: Path) -> Dict:
    return parse_raw(raw_path.read_text(encoding="utf-8"), raw_path.stem)


def json_text(ref: Dict) -> str:
    return json.dumps(ref, indent=2, ensure_ascii=False) + "\n"


def load_references() -> List[Dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(REFERENCE_DIR.glob("*.json"))]


# ---------------------------------------------------------------------------
# Our planner on the same dive
# ---------------------------------------------------------------------------

def build_plan(ref: Dict) -> DiveProfilePlan:
    """The reference's bottom as a DiveProfilePlan: first gas for the
    bottom, each later gas picked up on the ascent at Subsurface's switch
    depth. Subsurface's planner goes in a straight line from one waypoint to
    the next ("30m 40min" after 15 m is a 40-minute slope), so each
    waypoint's rate is set to cover its whole segment, not the plan's
    descend-then-hold."""
    s = ref["settings"]
    gases = []
    for k, g in enumerate(ref["gases"]):
        o2, he = g["o2_percent"], g["he_percent"]
        gases.append(PlannedGas(
            id=g["name"],
            gas_type="trimix" if he > 0 else ("air" if (o2, he) == (21.0, 0.0) else "nitrox"),
            o2_percent=o2,
            he_percent=he,
            tank_ref=f"T{k + 1}",
            use_max_depth_m=g["switch_depth_m"],
            use_phase="ascent" if g["switch_depth_m"] is not None else "any",
        ))
    waypoints = []
    prev_sec, prev_depth = 0, 0.0
    for wp in ref["bottom"]:
        # Subsurface shows a quick descent as 0min; a waypoint needs a moment
        # after the implicit surface start.
        runtime = max(int(round(wp["runtime_min"] * 60)), prev_sec + 1)
        change = abs(wp["depth_m"] - prev_depth)
        waypoints.append(PlannedWaypoint(
            runtime_sec=runtime, depth_m=wp["depth_m"], gas_id=gases[0].id, gas_auto=True,
            rate_m_per_min=change / (runtime - prev_sec) * 60.0 if change else None,
        ))
        prev_sec, prev_depth = runtime, wp["depth_m"]
    return DiveProfilePlan(
        name=ref["name"],
        gf_low=s["gf_low"],
        gf_high=s["gf_high"],
        default_ascent_rate=s["ascent_rate"],
        default_descent_rate=s["descent_rate"],
        gases=gases,
        waypoints=waypoints,
    )


def our_schedule(ref: Dict) -> Dict:
    """Our plan_ascent on the reference dive: stops (gas switch holds
    included, as Subsurface lists them), runtime and CNS."""
    plan = build_plan(ref)
    ascent, _, stops = plan_ascent(plan)
    plan.waypoints.extend(ascent)
    samples, _ = simulate(plan, resolution_sec=10)
    return {
        "stops": [{"depth_m": d, "minutes": sec / 60.0, "gas": gas} for d, sec, gas in stops],
        "runtime_min": ascent[-1].runtime_sec / 60.0 if ascent else 0.0,
        "cns_pct": samples[-1].cns_pct if samples else None,
    }


def port_schedule(ref: Dict) -> Optional[Dict]:
    """The Subsurface port (scripts/subsurface_port.py) on the same bottom
    as build_plan, fresh tissues; None for a dive the port can't plan."""
    plan = build_plan(ref)
    result = plan_reference(ref, [(wp.runtime_sec, wp.depth_m) for wp in plan.waypoints])
    if result is None:
        return None
    stops, runtime = result
    gas = ref["gases"][0]["name"]
    return {"stops": [{"depth_m": d, "minutes": m, "gas": gas} for d, m in stops], "runtime_min": runtime}


def _per_depth(stops: List[Dict]) -> Dict[float, float]:
    out: Dict[float, float] = {}
    for s in stops:
        out[s["depth_m"]] = out.get(s["depth_m"], 0.0) + s["minutes"]
    return out


def compare(ref: Dict, ours: Optional[Dict] = None) -> Tuple[List[str], str]:
    """(problems beyond the reference's tolerance, printable table)."""
    ours = ours or our_schedule(ref)
    tol = {**DEFAULT_TOLERANCE, **ref.get("tolerance", {})}
    exp = ref["expected"]
    theirs_d, ours_d = _per_depth(exp["stops"]), _per_depth(ours["stops"])
    gas_of = lambda stops, d: next((s["gas"] for s in stops if s["depth_m"] == d), "")  # noqa: E731

    problems = []
    first_theirs = max(theirs_d, default=0.0)
    first_ours = max(ours_d, default=0.0)
    if abs(first_theirs - first_ours) > tol["first_stop_m"]:
        problems.append(f"first stop {first_ours:g} m, Subsurface {first_theirs:g} m")
    lines = [
        f"{ref['name']}  (GF {ref['settings']['gf_low']:g}/{ref['settings']['gf_high']:g})",
        f"  {'depth':>6}  {'Subsurface':<16}{'ours':<16}{'diff':>6}",
    ]
    for d in sorted(set(theirs_d) | set(ours_d), reverse=True):
        t, o = theirs_d.get(d, 0.0), ours_d.get(d, 0.0)
        diff = o - t
        flag = ""
        if abs(diff) > tol["stop_min"]:
            problems.append(f"{d:g} m stop {o:.0f} min, Subsurface {t:.0f} min")
            flag = "  !"
        cell = lambda m, g: f"{m:.0f} min {g}" if m else "-"  # noqa: E731
        lines.append(
            f"  {d:>4g} m  {cell(t, gas_of(exp['stops'], d)):<16}{cell(o, gas_of(ours['stops'], d)):<16}{diff:>+6.0f}{flag}"
        )
    rt_t, rt_o = exp["runtime_min"], ours["runtime_min"]
    rt_pct = (rt_o - rt_t) / rt_t * 100 if rt_t else 0.0
    if abs(rt_pct) > tol["runtime_pct"]:
        problems.append(f"runtime {rt_o:.0f} min, Subsurface {rt_t:.0f} min ({rt_pct:+.0f}%)")
    lines.append(f"  runtime   {rt_t:.0f} min{'':<9}{rt_o:.1f} min{'':<7}{rt_pct:+.0f}%")
    if exp.get("cns_pct") is not None and ours.get("cns_pct") is not None:
        lines.append(f"  CNS       {exp['cns_pct']:.0f} %{'':<11}{ours['cns_pct']:.0f} %")
    if ref.get("known_gap"):
        lines.append(f"  known gap: {ref['known_gap']}")
    lines.append("  " + ("OK" if not problems else "DIFFERS: " + "; ".join(problems)))
    return problems, "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cmd_convert() -> int:
    raws = sorted(RAW_DIR.glob("*.txt"))
    if not raws:
        print(f"No raw files in {RAW_DIR}")
        return 0
    status = 0
    for raw in raws:
        try:
            ref = convert_file(raw)
        except ReferenceError as e:
            print(f"{raw.name}: {e}")
            status = 1
            continue
        out = REFERENCE_DIR / f"{raw.stem}.json"
        out.write_text(json_text(ref), encoding="utf-8")
        print(f"{raw.name} -> {out.relative_to(REPO_ROOT)}")
    return status


def _cmd_compare(names: List[str]) -> int:
    refs = [r for r in load_references() if not names or Path(r["source"]).stem in names]
    if not refs:
        print("No reference dives - run 'convert' first")
        return 1
    status = 0
    for ref in refs:
        problems, table = compare(ref)
        print(table + "\n")
        status |= bool(problems)
    return status


def _cmd_port(names: List[str]) -> int:
    refs = [r for r in load_references() if not names or Path(r["source"]).stem in names]
    for ref in refs:
        port = port_schedule(ref)
        if port is None:
            print(f"{ref['name']}: the port plans single-gas air/nitrox dives only\n")
            continue
        fmt = lambda stops: ", ".join(f"{s['depth_m']:g} m {s['minutes']:.0f} min" for s in stops) or "-"  # noqa: E731
        ours = our_schedule(ref)
        print(f"{ref['name']}  (GF {ref['settings']['gf_low']:g}/{ref['settings']['gf_high']:g})")
        print(f"  Subsurface paste  {fmt(ref['expected']['stops']):<40}{ref['expected']['runtime_min']:.0f} min")
        print(f"  Subsurface port   {fmt(port['stops']):<40}{port['runtime_min']:.1f} min")
        print(f"  ours              {fmt(ours['stops']):<40}{ours['runtime_min']:.1f} min\n")
    return 0


def main(argv: List[str]) -> int:
    commands = {"convert": lambda: _cmd_convert(), "compare": lambda: _cmd_compare(argv[1:]), "port": lambda: _cmd_port(argv[1:])}
    if not argv or argv[0] not in commands:
        print(__doc__)
        return 2
    return commands[argv[0]]()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
