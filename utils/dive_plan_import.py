"""Rebuilding a DiveProfilePlan from a log the Dive Profile Builder wrote
before it embedded the plan itself (parsers/plan_embed.py) - Open log's
fallback for those older files - and from any other log Open log
imports: another program's UDDF/FIT/SSRF (read by the same per-format
code below, which doesn't depend on UWMedia's own layout) or a Shearwater
Cloud XML/CSV / Subsurface CSV export (_shearwater_parts/
_subsurface_csv_parts).

The three writers (parsers/uddf_writer.py, subsurface_writer.py,
fit_writer.py) lay their files out the same way every time, so this reads
the plan's ingredients straight from that structure rather than from the
flattened models.dive.Dive the general parsers produce (which lose which
tank a gas is in and when it was switched):

- gases and tanks: UDDF <gasdefinitions>/<tankdata>, Subsurface
  <cylinder>s, FIT dive_gas + the tank pods' device_info descriptors
  (assigned to gases in tank_specs() order, a sidemount pair as <ref>L/
  <ref>R); a CCR dive's diluent and O2 cylinder are recognised too.
- gas switches: UDDF <switchmix>, Subsurface gaschange events, FIT
  dive_gas_switched events - each becomes a waypoint, so the profile is
  split into single-gas segments.
- GF (UDDF <decomodel>, Subsurface "Deco model" extradata, FIT
  dive_settings) and, from FIT, the PO2 limits.
- depth profile: the parsed Dive's samples, simplified (Douglas-Peucker,
  PROFILE_TOLERANCE_M) to a few dozen waypoints per gas segment.

Everything else a log doesn't hold - SAC, ascent/descent rates, gas depth
ranges - stays as in the `base` plan (the builder's current settings). A
gas first breathed after the deepest point is marked an ascent/deco gas so
End dive keeps picking it on the way up.
"""
import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from lxml import etree

from models.dive import Dive
from models.dive_plan import CCR_O2_TANK_REF, DiveProfilePlan, PlannedGas, PlannedWaypoint
from utils.dive_computers import DIVE_COMPUTERS

PROFILE_TOLERANCE_M = 0.6
MAX_PROFILE_WAYPOINTS = 60
# (x, y) space the simplifier measures distances in: minutes vs metres, so
# one metre of depth counts like one minute of time.
_TIME_SCALE_PER_M = 60.0
SUBSURFACE_SUFFIXES = {".ssrf", ".xml"}


@dataclass
class LoggedGas:
    name: str
    o2_percent: float
    he_percent: float
    tank_ref: str = "T1"
    tank_size_l: Optional[float] = None
    start_pressure_bar: Optional[float] = None
    sidemount_pair: bool = False
    diluent: bool = False


@dataclass
class LoggedPlanParts:
    """What one format's file says about the plan, before the profile."""
    gases: List[LoggedGas] = field(default_factory=list)
    switches: List[Tuple[int, str]] = field(default_factory=list)  # (seconds, gas name) incl. the first gas at 0
    dive_type: str = "oc"
    gf_low: Optional[float] = None
    gf_high: Optional[float] = None
    max_po2_bottom: Optional[float] = None
    max_po2_deco: Optional[float] = None
    ccr_o2_tank_size_l: Optional[float] = None
    ccr_o2_start_pressure_bar: Optional[float] = None
    water_temp_c: Optional[float] = None


def _norm(text: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def computer_label_for(dive: Dive, fallback: str) -> str:
    """The utils.dive_computers label matching the log's device name
    ("descent_x50i", "Descent X50i", "Perdix 2", ...), else `fallback`."""
    device = _norm(dive.device)
    if not device:
        return fallback
    for label, computer in DIVE_COMPUTERS.items():
        model = _norm(computer.model)
        if model and (model in device or device in model):
            return label
    return fallback


def mix_name(o2_percent: float, he_percent: float) -> str:
    """'Air', 'EAN32', 'Tx18/45' - a gas name for a file that has none."""
    if he_percent > 0:
        return f"Tx{o2_percent:g}/{he_percent:g}"
    if abs(o2_percent - 21.0) < 0.5:
        return "Air"
    return f"EAN{o2_percent:g}"


def gas_type_for(o2_percent: float, he_percent: float) -> str:
    if he_percent > 0:
        return "trimix"
    if abs(o2_percent - 21.0) < 0.5:
        return "air"
    return "nitrox"


def _mmss_seconds(text: str) -> int:
    """'12:34 min' / '45 s' / '12:34' -> seconds."""
    text = (text or "").strip()
    if text.endswith("min"):
        text = text[:-3].strip()
    elif text.endswith("s"):
        text = text[:-1].strip()
    if ":" in text:
        minutes, seconds = text.split(":", 1)
        return int(minutes) * 60 + int(float(seconds))
    return int(float(text or 0))


def _pair_up(refs: List[str]) -> List[Tuple[str, bool]]:
    """Tank refs in file order -> (gas tank_ref, is_pair) per gas, joining
    a <ref>L immediately followed by its <ref>R - the writers' own order."""
    out: List[Tuple[str, bool]] = []
    i = 0
    while i < len(refs):
        ref = refs[i]
        if ref.endswith("L") and i + 1 < len(refs) and refs[i + 1] == ref[:-1] + "R":
            out.append((ref[:-1], True))
            i += 2
        else:
            out.append((ref, False))
            i += 1
    return out


# ---------------------------------------------------------------------------
# UDDF
# ---------------------------------------------------------------------------

def _uddf_parts(path: Path) -> LoggedPlanParts:
    root = etree.parse(str(path)).getroot()
    parts = LoggedPlanParts()

    def text(node, xp):
        return node.xpath(f"string({xp})")

    mixes: Dict[str, Tuple[str, float, float]] = {}
    for mix in root.xpath(".//*[local-name()='gasdefinitions']/*[local-name()='mix']"):
        mix_id = mix.get("id", "")
        name = text(mix, "*[local-name()='name']") or mix_id.split(":")[0]
        o2 = float(text(mix, "*[local-name()='o2']") or 0.21) * 100.0
        he = float(text(mix, "*[local-name()='he']") or 0.0) * 100.0
        mixes[mix_id] = (name, o2, he)

    tanks: List[Tuple[str, Optional[str], Optional[float], Optional[float]]] = []  # ref, mix id, size l, start bar
    for tankdata in root.xpath(".//*[local-name()='informationbeforedive']/*[local-name()='tankdata']"):
        ref = tankdata.get("id", "")
        link = tankdata.xpath("string(*[local-name()='link']/@ref)") or None
        volume = text(tankdata, "*[local-name()='tankvolume']")
        begin = text(tankdata, "*[local-name()='tankpressurebegin']")
        tanks.append((ref, link, float(volume) * 1000.0 if volume else None, float(begin) / 100000.0 if begin else None))

    modes = {(_norm(m) or "") for m in root.xpath(".//*[local-name()='waypoint']/*[local-name()='divemode']/@type")}
    ccr = "closedcircuit" in modes
    parts.dive_type = "ccr" if ccr else "oc"
    o2_tank = next((t for t in tanks if t[0] == CCR_O2_TANK_REF and t[1] is None), None) if ccr else None
    if o2_tank:
        parts.ccr_o2_tank_size_l, parts.ccr_o2_start_pressure_bar = o2_tank[2], o2_tank[3]
    gas_tanks = [t for t in tanks if t is not o2_tank and t[1] in mixes]
    by_mix: Dict[str, List[Tuple[str, Optional[float], Optional[float]]]] = {}
    for ref, link, size, start in gas_tanks:
        by_mix.setdefault(link, []).append((ref, size, start))
    for mix_id, (name, o2, he) in mixes.items():
        own = by_mix.get(mix_id) or []
        refs = [ref for ref, _, _ in own] or ["T1"]
        tank_ref, pair = _pair_up(refs)[0]
        parts.gases.append(LoggedGas(
            name=name, o2_percent=o2, he_percent=he, tank_ref=tank_ref, sidemount_pair=pair,
            tank_size_l=own[0][1] if own else None, start_pressure_bar=own[0][2] if own else None,
        ))
    if any(g.sidemount_pair for g in parts.gases) and not ccr:
        parts.dive_type = "sidemount"

    name_of_mix = {mix_id: name for mix_id, (name, _, _) in mixes.items()}
    cc_gases = set()
    for wp in root.xpath(".//*[local-name()='samples']/*[local-name()='waypoint']"):
        ref = wp.xpath("string(*[local-name()='switchmix']/@ref)")
        if ref and ref in name_of_mix:
            when = int(float(text(wp, "*[local-name()='divetime']") or 0))
            parts.switches.append((when, name_of_mix[ref]))
        if ccr and parts.switches and _norm(wp.xpath("string(*[local-name()='divemode']/@type)")) == "closedcircuit":
            cc_gases.add(parts.switches[-1][1])
    for g in parts.gases:
        g.diluent = ccr and g.name in cc_gases

    parts.gf_high = float(text(root, ".//*[local-name()='decomodel']//*[local-name()='gradientfactorhigh']") or 0) or None
    parts.gf_low = float(text(root, ".//*[local-name()='decomodel']//*[local-name()='gradientfactorlow']") or 0) or None
    temps = [float(t) - 273.15 for t in root.xpath(".//*[local-name()='waypoint']/*[local-name()='temperature']/text()")[:1]]
    parts.water_temp_c = round(temps[0], 1) if temps else None
    return parts


# ---------------------------------------------------------------------------
# Subsurface XML
# ---------------------------------------------------------------------------

def _subsurface_parts(path: Path) -> LoggedPlanParts:
    root = etree.parse(str(path)).getroot()
    parts = LoggedPlanParts()
    dive = root.xpath(".//dive")[0]
    cylinders = []
    for cyl in dive.xpath("cylinder"):
        def num(attr, default=None):
            value = cyl.get(attr)
            return float(re.sub(r"[^0-9.]", "", value)) if value else default
        cylinders.append({
            "ref": cyl.get("description") or f"T{len(cylinders) + 1}",
            "o2": num("o2", 21.0), "he": num("he", 0.0), "size": num("size"), "start": num("start"),
            "use": cyl.get("use", "oc"),
        })
    divecomputer = dive.xpath("divecomputer")[0]
    ccr = (divecomputer.get("dctype") or "").upper() == "CCR"
    parts.dive_type = "ccr" if ccr else "oc"
    o2_cyl = next((c for c in cylinders if c["use"] == "oxygen"), None)
    if o2_cyl:
        parts.ccr_o2_tank_size_l, parts.ccr_o2_start_pressure_bar = o2_cyl["size"], o2_cyl["start"]
    gas_cyls = [c for c in cylinders if c is not o2_cyl]
    # Cylinders of one mix, in order: a <ref>L/<ref>R pair is one gas.
    refs = [c["ref"] for c in gas_cyls]
    ref_of_cyl: Dict[int, str] = {}
    i = 0
    for tank_ref, pair in _pair_up(refs):
        c = gas_cyls[i]
        name = mix_name(c["o2"], c["he"])
        parts.gases.append(LoggedGas(
            name=name, o2_percent=c["o2"], he_percent=c["he"], tank_ref=tank_ref, sidemount_pair=pair,
            tank_size_l=c["size"], start_pressure_bar=c["start"], diluent=c["use"] == "diluent",
        ))
        for _ in range(2 if pair else 1):
            ref_of_cyl[cylinders.index(gas_cyls[i])] = name
            i += 1
    if any(g.sidemount_pair for g in parts.gases) and not ccr:
        parts.dive_type = "sidemount"
    for ev in divecomputer.xpath("event[@name='gaschange']"):
        idx = int(ev.get("cylinder", 0))
        if idx in ref_of_cyl:
            parts.switches.append((_mmss_seconds(ev.get("time", "0:00 min")), ref_of_cyl[idx]))
    deco = divecomputer.xpath("string(extradata[@key='Deco model']/@value)")
    # "GF 40/85" (UWMedia's writer) or "Buhlmann ZHL-16C 40/85" (Subsurface's
    # own) - the pair around the slash, not the first two numbers.
    gf = re.search(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", deco or "")
    if gf:
        parts.gf_low, parts.gf_high = float(gf.group(1)), float(gf.group(2))
    temp = divecomputer.xpath("string(temperature/@water)")
    parts.water_temp_c = float(re.sub(r"[^0-9.\-]", "", temp)) if temp else None
    return parts


# ---------------------------------------------------------------------------
# Garmin FIT
# ---------------------------------------------------------------------------

def _fit_parts(path: Path) -> LoggedPlanParts:
    from garmin_fit_sdk import Decoder, Stream

    messages, _errors = Decoder(Stream.from_file(str(path))).read()
    parts = LoggedPlanParts()
    gases = messages.get("dive_gas_mesgs", [])
    pods = [m for m in messages.get("device_info_mesgs", []) if m.get("descriptor")]
    pods.sort(key=lambda m: m.get("device_index", 0) if isinstance(m.get("device_index"), int) else 0)
    starts = {m.get("sensor"): m.get("start_pressure") for m in messages.get("tank_summary_mesgs", [])}
    refs = [str(m["descriptor"]) for m in pods]
    start_of_ref = {str(m["descriptor"]): starts.get(m.get("serial_number")) for m in pods}
    ccr = any(str(g.get("mode", "")).startswith("closed_circuit") for g in gases)
    parts.dive_type = "ccr" if ccr else "oc"
    if ccr and refs and refs[0] == CCR_O2_TANK_REF:
        parts.ccr_o2_start_pressure_bar = start_of_ref.get(CCR_O2_TANK_REF)
        refs = refs[1:]
    assignments = _pair_up(refs)
    for i, g in enumerate(gases):
        o2, he = float(g.get("oxygen_content", 21) or 21), float(g.get("helium_content", 0) or 0)
        tank_ref, pair = assignments[i] if i < len(assignments) else (f"T{i + 1}", False)
        name = mix_name(o2, he)
        parts.gases.append(LoggedGas(
            name=name, o2_percent=o2, he_percent=he, tank_ref=tank_ref, sidemount_pair=pair,
            start_pressure_bar=start_of_ref.get(f"{tank_ref}L" if pair else tank_ref),
            diluent=str(g.get("mode", "")).startswith("closed_circuit"),
        ))
    if any(g.sidemount_pair for g in parts.gases) and not ccr:
        parts.dive_type = "sidemount"

    records = messages.get("record_mesgs", [])
    first = records[0].get("timestamp") if records else None
    if parts.gases:
        parts.switches.append((0, parts.gases[0].name))
    for ev in messages.get("event_mesgs", []):
        if ev.get("event") != "dive_gas_switched":
            continue
        idx = ev.get("data")
        if isinstance(idx, int) and 0 <= idx < len(parts.gases) and first is not None:
            parts.switches.append((int((ev["timestamp"] - first).total_seconds()), parts.gases[idx].name))

    settings = messages.get("dive_settings_mesgs", [])
    if settings:
        s = settings[0]
        parts.gf_low, parts.gf_high = s.get("gf_low"), s.get("gf_high")
        parts.max_po2_bottom, parts.max_po2_deco = s.get("po2_warn"), s.get("po2_deco")
    if records and records[0].get("temperature") is not None:
        parts.water_temp_c = float(records[0]["temperature"])
    return parts


# ---------------------------------------------------------------------------
# Shearwater Cloud XML/CSV, Subsurface CSV (imported, never written by UWMedia)
# ---------------------------------------------------------------------------

def _float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _shearwater_parts(path: Path) -> LoggedPlanParts:
    """Gases and switches from each record's O2/He fractions (one tank, T1
    - the export doesn't say which transmitter breathes which gas), GF and
    start pressure from the header/first record."""
    from parsers.shearwater import PSI_TO_BAR, read_tables

    header, rows = read_tables(path)
    parts = LoggedPlanParts()
    imperial = str(header.get("Imperial Units", "")).strip().lower() == "true"
    gases: Dict[Tuple[float, float], str] = {}
    current = None
    ccr = False
    for row in rows:
        seconds = row.get("Time (sec)")
        if seconds is None:
            continue
        o2 = round((_float(row.get("Fraction O2")) or 0.21) * 100.0, 1)
        he = round((_float(row.get("Fraction He")) or 0.0) * 100.0, 1)
        name = gases.setdefault((o2, he), mix_name(o2, he))
        if name != current:
            parts.switches.append((int(seconds), name))
            current = name
        mode = str(row.get("Current Circuit Mode", "")).strip().upper()
        ccr = ccr or mode.startswith(("CC", "SC")) or mode == "0"
    start_psi = next((p for p in (_float(r.get("Tank 1 pressure (PSI)")) for r in rows) if p), None)
    for i, ((o2, he), name) in enumerate(gases.items()):
        parts.gases.append(LoggedGas(
            name=name, o2_percent=o2, he_percent=he, tank_ref="T1" if i == 0 else f"T{i + 1}",
            start_pressure_bar=start_psi * PSI_TO_BAR if i == 0 and start_psi else None,
            diluent=ccr and i == 0,
        ))
    parts.dive_type = "ccr" if ccr else "oc"
    parts.gf_low, parts.gf_high = _float(header.get("GF Minimum")), _float(header.get("GF Maximum"))
    temp = next((t for t in (_float(r.get("Water Temp")) for r in rows) if t is not None), None)
    if temp is not None:
        parts.water_temp_c = (temp - 32.0) * 5.0 / 9.0 if imperial else temp
    return parts


def _subsurface_csv_parts(dive: Dive) -> LoggedPlanParts:
    """A Subsurface CSV profile has no gas, cylinder or GF information - the
    builder's own settings stand for those, the water temperature comes
    from the first sample that has one."""
    parts = LoggedPlanParts()
    parts.water_temp_c = next((wp.temp for wp in dive.waypoints if wp.temp is not None), None)
    return parts


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

def simplify_profile(points: Sequence[Tuple[float, float]], tolerance_m: float = PROFILE_TOLERANCE_M) -> List[Tuple[float, float]]:
    """Douglas-Peucker over (seconds, metres) points, distances measured in
    a (minutes, metres) space so a metre of depth weighs like a minute of
    time. Always keeps the first and last point."""
    if len(points) <= 2:
        return list(points)
    xs = [t / _TIME_SCALE_PER_M for t, _ in points]
    ys = [d for _, d in points]
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        ax, ay, bx, by = xs[a], ys[a], xs[b], ys[b]
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy)
        best, best_i = 0.0, -1
        for i in range(a + 1, b):
            if length == 0:
                dist = math.hypot(xs[i] - ax, ys[i] - ay)
            else:
                dist = abs(dy * xs[i] - dx * ys[i] + bx * ay - by * ax) / length
            if dist > best:
                best, best_i = dist, i
        if best > tolerance_m:
            keep[best_i] = True
            stack.append((a, best_i))
            stack.append((best_i, b))
    return [p for p, k in zip(points, keep) if k]


def profile_waypoints(dive: Dive, switches: Sequence[Tuple[int, str]], first_gas: str) -> List[PlannedWaypoint]:
    """The dive's depth samples as simplified PlannedWaypoints, split at
    every gas switch (which gets a waypoint of its own on the new gas)."""
    samples = sorted(((int(wp.time_since_start), round(float(wp.depth), 1)) for wp in dive.waypoints if wp.depth is not None))
    if not samples:
        return []
    if samples[0][0] < 0:
        # Times measured from a start the parser put after the samples (an
        # older Garmin FIT): count from the first sample instead, which is
        # what the FIT gas switches are measured from too.
        offset = samples[0][0]
        samples = [(t - offset, d) for t, d in samples]
    switches = sorted((max(0, t), g) for t, g in switches)
    depth_at = dict(samples)

    def depth_near(t: int) -> float:
        if t in depth_at:
            return depth_at[t]
        before = [s for s in samples if s[0] <= t]
        return before[-1][1] if before else samples[0][1]

    gas = switches[0][1] if switches and switches[0][0] == 0 else first_gas
    boundaries = []
    current = gas
    for t, g in switches:
        if t > 0 and g != current:  # a sidemount side swap is the same gas, not a switch
            boundaries.append((t, g))
        current = g
    segments: List[Tuple[str, List[Tuple[float, float]]]] = [(gas, [])]
    bi = 0
    for t, d in samples:
        while bi < len(boundaries) and boundaries[bi][0] <= t:
            switch_t, new_gas = boundaries[bi]
            point = (float(switch_t), depth_near(switch_t))
            segments[-1][1].append(point)
            segments.append((new_gas, [point]))
            bi += 1
        segments[-1][1].append((float(t), d))

    tolerance = PROFILE_TOLERANCE_M
    while True:
        out: List[PlannedWaypoint] = []
        seen: set = set()
        for seg_gas, points in segments:
            for t, d in simplify_profile(points, tolerance):
                runtime = int(round(t))
                if runtime in seen:
                    continue
                seen.add(runtime)
                out.append(PlannedWaypoint(runtime_sec=runtime, depth_m=max(0.0, d), gas_id=seg_gas))
        if len(out) <= MAX_PROFILE_WAYPOINTS or tolerance > 20:
            break
        tolerance *= 1.5
    # The builder's first waypoint is where the descent arrives; the surface start is implied.
    if len(out) > 1 and out[0].runtime_sec == 0 and out[0].depth_m <= 0:
        out = out[1:]
    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def logged_plan_parts(path, dive: Optional[Dive] = None) -> LoggedPlanParts:
    from parsers.registry import SHEARWATER_CSV, SHEARWATER_XML, SUBSURFACE_CSV, detect_log_format

    path = Path(path)
    log_format = detect_log_format(path)
    if log_format in (SHEARWATER_XML, SHEARWATER_CSV):
        return _shearwater_parts(path)
    if log_format == SUBSURFACE_CSV:
        return _subsurface_csv_parts(dive) if dive is not None else LoggedPlanParts()
    suffix = path.suffix.lower()
    if suffix == ".uddf":
        return _uddf_parts(path)
    if suffix in SUBSURFACE_SUFFIXES:
        return _subsurface_parts(path)
    if suffix == ".fit":
        return _fit_parts(path)
    raise ValueError(f"Unknown log format '{path.suffix}' - use .uddf, .fit, .ssrf or a Shearwater/Subsurface .xml/.csv export")


def plan_from_log(path, dive: Dive, base: Optional[DiveProfilePlan] = None) -> DiveProfilePlan:
    """A DiveProfilePlan reproducing the log at `path`
    (parsed as `dive` by the matching parser): its gases, tanks, gas
    switches, GF, computer, start time and simplified profile, with
    `base`'s settings for what the log doesn't record."""
    base = base or DiveProfilePlan()
    plan = base.model_copy(deep=True)
    parts = logged_plan_parts(path, dive)

    used: set = set()
    gases: List[PlannedGas] = []
    rename: Dict[str, str] = {}
    for lg in parts.gases:
        name, n = (lg.name.strip() or "Gas"), 2
        while name in used:
            name = f"{lg.name.strip() or 'Gas'} {n}"
            n += 1
        used.add(name)
        rename[lg.name] = name
        gases.append(PlannedGas(
            id=name, gas_type=gas_type_for(lg.o2_percent, lg.he_percent),
            o2_percent=round(lg.o2_percent, 1), he_percent=round(lg.he_percent, 1),
            tank_ref=lg.tank_ref, sidemount_pair=lg.sidemount_pair, diluent=lg.diluent,
            tank_size_l=lg.tank_size_l or PlannedGas.model_fields["tank_size_l"].default,
            start_pressure_bar=round(lg.start_pressure_bar) if lg.start_pressure_bar else PlannedGas.model_fields["start_pressure_bar"].default,
        ))
    if not gases:
        gases = [PlannedGas(id="Air", gas_type="air", o2_percent=21.0)]
    switches = [(t, rename.get(g, g)) for t, g in parts.switches if rename.get(g, g) in used]
    plan.gases = gases
    plan.dive_type = parts.dive_type
    if plan.is_ccr and not any(g.diluent for g in gases):
        gases[0].diluent = True
    plan.waypoints = profile_waypoints(dive, switches, gases[0].id)

    # A gas first breathed after the deepest point is an ascent/deco gas.
    if plan.waypoints:
        deepest_t = max(plan.waypoints, key=lambda w: (w.depth_m, -w.runtime_sec)).runtime_sec
        first_use = {}
        for w in sorted(plan.waypoints, key=lambda w: w.runtime_sec):
            first_use.setdefault(w.gas_id, w.runtime_sec)
        for g in gases:
            if first_use.get(g.id, 0) > deepest_t:
                g.use_phase = "ascent"

    if parts.gf_low and parts.gf_high and parts.gf_low <= parts.gf_high:
        plan.gf_low, plan.gf_high = float(parts.gf_low), float(parts.gf_high)
    if parts.max_po2_bottom and 0.5 <= parts.max_po2_bottom <= 2.0:
        plan.max_po2_bottom = float(parts.max_po2_bottom)
    if parts.max_po2_deco and 0.5 <= parts.max_po2_deco <= 2.0:
        plan.max_po2_deco = float(parts.max_po2_deco)
    if parts.ccr_o2_tank_size_l:
        plan.ccr_o2_tank_size_l = float(parts.ccr_o2_tank_size_l)
    if parts.ccr_o2_start_pressure_bar:
        plan.ccr_o2_start_pressure_bar = float(parts.ccr_o2_start_pressure_bar)
    if parts.water_temp_c is not None and -5 < parts.water_temp_c < 45:
        plan.water_temp_c = round(parts.water_temp_c, 1)

    if dive.log_filename:
        plan.name = Path(dive.log_filename).stem.replace("_", " ") or plan.name
    if isinstance(dive.start_time, datetime):
        first = min(dive.waypoints, key=lambda wp: wp.time_since_start, default=None)
        start = first.timestamp if first is not None and first.time_since_start < 0 else dive.start_time
        plan.start_time = start.replace(tzinfo=None, microsecond=0)
    plan.computer = computer_label_for(dive, base.computer)
    max_depth = max((wp.depth_m for wp in plan.waypoints), default=0.0)
    if max_depth > 0:
        plan.max_depth_m = float(math.ceil(max_depth / 5.0) * 5)
    runtime = max((wp.runtime_sec for wp in plan.waypoints), default=0)
    if runtime > 0:
        plan.planned_runtime_sec = int(math.ceil(runtime / 300.0) * 300)
    return plan
