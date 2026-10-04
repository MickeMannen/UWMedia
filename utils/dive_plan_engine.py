import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from models.dive_plan import DiveProfilePlan, PlannedGas, PlannedWaypoint
from utils.deco_engine import BuhlmannEngine, ccr_effective_fractions

SURFACE_PRESSURE_BAR = 1.01325

# Matches DiveDecompressor's own `simulation_interval` convention
# (utils/deco_engine.py) - a full NDL/deco-stop lookahead is only worth
# re-running this often; the value is held/decremented by 1 in between, the
# same tradeoff that module already makes for real-log TTS.
RECOMPUTE_INTERVAL_SEC = 10
# Rough gas drawn from the diluent tank while on the loop, in surface L/min
# scaled by ambient pressure like SAC (loop volume top-ups on descent,
# flushes) - a rebreather uses a small fraction of open-circuit gas.
CCR_LOOP_LPM = 1.0
# O2 the diver metabolises, drawn from a CCR dive's O2 cylinder in L/min -
# independent of depth.
CCR_METABOLIC_O2_LPM = 1.0


@dataclass
class SimulatedSample:
    time_sec: int
    depth_m: float
    gas_id: str
    ceiling_m: float
    ndl_sec: Optional[int]
    tts_sec: int
    stop_depth_m: float
    stop_duration_sec: int
    cns_pct: float
    po2: float
    divemode: str
    tank_pressure_bar: float  # the tank breathed from (tank_ref)
    tank_ref: str = ""
    tank_pressures: Dict[str, float] = field(default_factory=dict)  # every tank, DiveProfilePlan.tank_specs() order
    # ceiling_m is at GF high (may the diver surface?); this one at GF low,
    # which is what places the first stop (plan_ascent).
    ceiling_gf_low_m: float = 0.0


def waypoint_phases(waypoints: List[PlannedWaypoint]) -> List[str]:
    """"descent" or "ascent" for each (time-sorted) waypoint: everything up
    to and including the first visit to the dive's deepest point is the
    descent/bottom phase, anything shallower after it is the ascent - so a
    deco gas limited to "ascent" never gets picked on the way down, even
    though its depth range covers the descent too. A waypoint's own
    `phase` wins over this."""
    if not waypoints:
        return []
    deepest = max(wp.depth_m for wp in waypoints)
    deepest_idx = next(i for i, wp in enumerate(waypoints) if wp.depth_m == deepest)
    return [
        wp.phase or ("ascent" if i > deepest_idx and wp.depth_m < deepest else "descent")
        for i, wp in enumerate(waypoints)
    ]


def auto_gas_for_waypoint(plan: DiveProfilePlan, depth_m: float, phase: str) -> Optional[PlannedGas]:
    """Picks the gas whose depth range, phase and MOD (at the plan's max PO2
    for this phase) cover this waypoint. A gas with an explicit range beats
    one without (an unranged gas is the catch-all), a gas limited to this
    phase beats an "any" gas, and among equals the richest O2 wins - e.g.
    on the ascent at 6m with Air (no range), EAN50 (21-0m, ascent) and O2
    (6-0m, ascent) available, O2 is picked. None when no gas is usable.
    A CCR dive stays on the loop (its diluent) - bailout is only ever
    picked by hand."""
    loop = plan.diluent_gas()
    if loop is not None:
        return loop
    candidates = [g for g in plan.breathed_gases() if plan.gas_usable_at(g, depth_m, phase)]
    if not candidates:
        return None
    return max(candidates, key=lambda g: (g.has_depth_range, g.use_phase == phase, g.o2_percent))


def apply_auto_gases(plan: DiveProfilePlan) -> List[str]:
    """Re-derives gas_id for every waypoint flagged gas_auto, in place. A
    waypoint no gas covers keeps the previous waypoint's gas (or the first
    gas for the very first one) and gets a warning, as does a hand-picked
    gas breathed deeper than its MOD. Returns the warnings."""
    warnings: List[str] = []
    if not plan.gases:
        return warnings
    wps = plan.sorted_waypoints()
    previous_gas_id = plan.breathed_gases()[0].id
    for wp, phase in zip(wps, waypoint_phases(wps)):
        when = f"{wp.runtime_sec // 60}:{wp.runtime_sec % 60:02d}"
        if wp.gas_auto:
            gas = auto_gas_for_waypoint(plan, wp.depth_m, phase)
            if gas is None:
                warnings.append(
                    f"No gas is usable at {wp.depth_m:g}m ({phase}, max PO2 {plan.max_po2_for(phase):g}) at {when} "
                    f"- staying on {previous_gas_id}"
                )
                wp.gas_id = previous_gas_id
            else:
                wp.gas_id = gas.id
        else:
            gas = plan.gas_by_id(wp.gas_id)
            mod = plan.gas_mod_m(gas, phase) if gas is not None else None
            if mod is not None and wp.depth_m > mod:
                warnings.append(
                    f"{gas.id} at {wp.depth_m:g}m ({when}) is past its MOD of {mod:g}m "
                    f"at max PO2 {plan.max_po2_for(phase):g}"
                )
        previous_gas_id = wp.gas_id
    return warnings


def expand_plan(plan: DiveProfilePlan) -> Tuple[List[Tuple[int, float, str]], List[str]]:
    """Turns the sparse waypoint list into one (time_sec, depth_m, gas_id)
    entry per second. Segment rule (matches Subsurface's own planner, which
    this codebase already parses): the transition from waypoint i-1 to i
    happens immediately, at the applicable rate; whatever time remains is
    spent holding at waypoint i's depth. The gas assigned to a waypoint
    takes effect once that depth is reached (not during the transit itself)
    - this matches real Perdix 2 export evidence, where a <switchmix> always
    lands on the waypoint already at the new depth, not mid-ascent.
    A waypoint on a sidemount dive's right tank is on the pair's gas (the
    left tank's id) - simulate picks the side."""
    warnings: List[str] = []
    wps = plan.sorted_waypoints()
    if not wps:
        return [], warnings

    for gas_id in {wp.gas_id for wp in wps}:
        if plan.gas_by_id(gas_id) is None:
            raise ValueError(f"Waypoint references unknown gas '{gas_id}'")

    points: List[PlannedWaypoint] = list(wps)
    if points[0].runtime_sec > 0:
        points.insert(0, PlannedWaypoint(runtime_sec=0, depth_m=0.0, gas_id=points[0].gas_id))

    gas_of = {wp.gas_id: plan.breathed_gas_id(wp.gas_id) for wp in points}
    timeline: List[Tuple[int, float, str]] = [(points[0].runtime_sec, points[0].depth_m, gas_of[points[0].gas_id])]
    for prev, cur in zip(points, points[1:]):
        dt_total = cur.runtime_sec - prev.runtime_sec
        if dt_total <= 0:
            warnings.append(
                f"Waypoint at {cur.runtime_sec}s does not come after the previous one "
                f"({prev.runtime_sec}s) - skipped"
            )
            continue

        depth_delta = cur.depth_m - prev.depth_m
        transit_sec = 0.0
        if depth_delta != 0:
            default_rate = plan.default_descent_rate if depth_delta > 0 else plan.default_ascent_rate
            rate = cur.rate_m_per_min or default_rate
            transit_sec = abs(depth_delta) / rate * 60.0
            if transit_sec > dt_total:
                warnings.append(
                    f"Waypoint at {cur.runtime_sec}s: reaching {cur.depth_m}m needs "
                    f"~{transit_sec:.0f}s at {rate:.0f} m/min but only {dt_total}s is "
                    f"available before it - clamped, the transit runs late"
                )
                transit_sec = dt_total

        for t in range(1, dt_total + 1):
            absolute_t = prev.runtime_sec + t
            if transit_sec > 0 and t <= transit_sec:
                depth = prev.depth_m + depth_delta * (t / transit_sec)
                gas_id = gas_of[prev.gas_id]
            else:
                depth = cur.depth_m
                gas_id = gas_of[cur.gas_id]
            timeline.append((absolute_t, depth, gas_id))

    return timeline, warnings


def _effective_fractions(plan: DiveProfilePlan, gas: PlannedGas, depth_m: float) -> Tuple[float, float]:
    if plan.on_loop(gas):
        ambient = SURFACE_PRESSURE_BAR + depth_m / 10.0
        return ccr_effective_fractions(plan.setpoint_at(depth_m), ambient, gas.f_o2, gas.f_he)
    return gas.f_o2, gas.f_he


def _mandatory_stop_schedule(
    plan: DiveProfilePlan,
    engine: BuhlmannEngine,
    depth_m: float,
    gas: PlannedGas,
    gf_low: float,
    gf_high: float,
    ascent_rate_mps: float = 0.15,
    max_seconds: int = 20000,
) -> Tuple[int, float, int]:
    """Virtual ascent to the surface from `depth_m`, staying on `gas` the
    whole way - deliberately ignorant of any later gas switch the plan
    itself defines further along, the same way a real dive computer can't
    see the diver's own future intentions and only reacts once a switch
    actually happens. No recreational safety-stop heuristic is layered on
    (unlike DiveDecompressor._simulate_tts, which this deliberately doesn't
    reuse - it also auto-picks gas by MOD, which conflicts with an
    explicitly authored profile, and has no CCR notion): here, a safety stop
    is just another waypoint the user places by hand. Stops are held with
    the GF interpolated from GF low at the first stop to GF high at the
    surface, as in plan_ascent. Returns (tts_seconds, first_stop_depth_m,
    first_stop_duration_sec), the first stop's time in whole minutes (at
    least one), the way a dive computer shows it."""
    if engine.get_ceiling(gf_low) <= 0:
        return 0, 0.0, 0

    sim = engine.clone()
    total_time = 0
    cur_depth = depth_m
    first_stop = 0.0  # where the GF-low ceiling first stops the ascent
    first_stop_depth = 0.0
    first_stop_duration = 0

    def gf_at(d: float) -> float:
        # Same interpolation as plan_ascent: GF low at the first stop, GF high at the surface.
        return gf_high + (gf_low - gf_high) * (d / first_stop)

    while cur_depth > 0 and total_time < max_seconds:
        target_ceiling = sim.get_ceiling(gf_at(cur_depth) if first_stop else gf_low)
        if cur_depth > target_ceiling:
            step = min(cur_depth, ascent_rate_mps)
            cur_depth -= step
            f_o2, f_he = _effective_fractions(plan, gas, cur_depth)
            sim.update(cur_depth, 1.0, f_o2, f_he)
            total_time += 1
            continue

        stop_depth = math.ceil(cur_depth / 3.0) * 3.0
        if stop_depth < 3.0:
            break
        first_stop = first_stop or stop_depth
        next_level = stop_depth - 3.0

        duration = 0
        while total_time < max_seconds and sim.get_ceiling(gf_at(next_level)) > next_level:
            f_o2, f_he = _effective_fractions(plan, gas, stop_depth)
            sim.update(stop_depth, 10.0, f_o2, f_he)
            total_time += 10
            duration += 10

        if not first_stop_depth:
            # Like a dive computer's display: whole minutes, at least one -
            # a deep first stop can clear almost at once under GF low.
            first_stop_depth = stop_depth
            first_stop_duration = max(60, math.ceil(duration / 60.0) * 60)

        cur_depth = next_level
        total_time += 20  # time to move between stops, matching DiveDecompressor's own convention

    return total_time, first_stop_depth, first_stop_duration


def simulate(plan: DiveProfilePlan, resolution_sec: int = 1) -> Tuple[List[SimulatedSample], List[str]]:
    """Runs the full per-second Buhlmann simulation for `plan`, sampling
    every `resolution_sec`-th second into the returned list. Tissue loading
    is always integrated per-second internally regardless of
    `resolution_sec` (it's path-dependent, can't be skipped) - resolution
    only controls how many samples are kept, e.g. resolution_sec=60 for a
    cheap interactive preview vs resolution_sec=1 for the final UDDF save.

    Tank pressures are tracked per tank (DiveProfilePlan.tank_specs): each
    second's gas is drawn at its SAC from the tank it's breathed from - on
    a CCR loop CCR_LOOP_LPM from the diluent, plus CCR_METABOLIC_O2_LPM
    from the O2 cylinder. A sidemount pair starts on the left tank and
    switches side whenever the one breathed drops sidemount_switch_bar
    below the other."""
    if not plan.gases:
        raise ValueError("Define at least one gas before simulating a profile")
    if plan.is_ccr and plan.diluent_gas() is None:
        raise ValueError("A CCR dive needs a diluent - mark one gas as the diluent")
    if plan.sidemount_error():
        raise ValueError(plan.sidemount_error())

    timeline, warnings = expand_plan(plan)
    if not timeline:
        return [], warnings

    engine = BuhlmannEngine(SURFACE_PRESSURE_BAR)
    gf_low = plan.gf_low / 100.0
    gf_high = plan.gf_high / 100.0
    tank_specs = plan.tank_specs()
    tank_pressure = {t.ref: t.start_pressure_bar for t in tank_specs}
    o2_tank = next((t for t in tank_specs if t.role == "oxygen"), None)
    tank_size = {t.ref: t.size_l for t in tank_specs}
    breathing_from = {g.id: plan.tank_refs_for(g)[0] for g in plan.breathed_gases()}

    samples: List[SimulatedSample] = []
    last_ndl: Optional[int] = None
    last_tts = 0
    last_stop_depth = 0.0
    last_stop_duration = 0
    in_deco = False
    had_deco = False
    running_max = 0.0

    for i, (t, depth, gas_id) in enumerate(timeline):
        gas = plan.gas_by_id(gas_id)
        ambient = SURFACE_PRESSURE_BAR + depth / 10.0
        f_o2, f_he = _effective_fractions(plan, gas, depth)
        engine.update(depth, 1.0, f_o2, f_he)

        tank = breathing_from[gas_id]
        sac = CCR_LOOP_LPM if plan.on_loop(gas) else plan.sac_for(gas)
        if sac > 0:
            drop_bar = (sac / 60.0 * ambient) / tank_size[tank]
            tank_pressure[tank] = max(0.0, tank_pressure[tank] - drop_bar)
        if o2_tank is not None and plan.on_loop(gas):
            drop_bar = CCR_METABOLIC_O2_LPM / 60.0 / o2_tank.size_l
            tank_pressure[o2_tank.ref] = max(0.0, tank_pressure[o2_tank.ref] - drop_bar)
        pair = plan.tank_refs_for(gas)
        if len(pair) == 2:
            other = pair[1] if tank == pair[0] else pair[0]
            if tank_pressure[tank] <= tank_pressure[other] - plan.sidemount_switch_bar:
                breathing_from[gas_id] = other  # from the next second on

        ceiling = engine.get_ceiling(gf_high)
        running_max = max(running_max, depth)
        # Also recompute the moment deco starts or clears, so no sample
        # carries a ceiling with the NDL-mode stop (0 m) or the other way round.
        if t % RECOMPUTE_INTERVAL_SEC == 0 or i == 0 or (ceiling > 0) != in_deco:
            in_deco = ceiling > 0
            if not in_deco:
                # None = unbounded (99+), e.g. at the 3 m stop once deco has cleared.
                last_ndl = engine.compute_ndl_seconds(depth, f_o2, f_he, gf_high)
                last_stop_depth, last_stop_duration = 0.0, 0
            else:
                had_deco = True
                last_ndl = None
                last_tts, last_stop_depth, last_stop_duration = _mandatory_stop_schedule(
                    plan, engine, depth, gas, gf_low, gf_high
                )
        elif not in_deco:
            last_ndl = max(0, last_ndl - 1) if last_ndl is not None else None
        else:
            last_tts = max(0, last_tts - 1)
            last_stop_duration = max(0, last_stop_duration - 1)
        if not in_deco:
            # No stops owed: TTS is the direct ascent, plus the safety stop a
            # computer would still ask for after a dive past 11 m - but not
            # once deco has been done (a Descent asks for none then).
            last_tts = _no_deco_tts(plan, depth, running_max, had_deco)

        if i % resolution_sec == 0 or i == len(timeline) - 1:
            samples.append(
                SimulatedSample(
                    time_sec=t,
                    depth_m=depth,
                    gas_id=gas_id,
                    ceiling_m=ceiling,
                    ndl_sec=last_ndl,
                    tts_sec=last_tts,
                    stop_depth_m=last_stop_depth,
                    stop_duration_sec=last_stop_duration,
                    cns_pct=engine.cns,
                    po2=round(ambient * f_o2, 3),
                    divemode="closedcircuit" if plan.on_loop(gas) else "opencircuit",
                    tank_pressure_bar=round(tank_pressure[tank], 1),
                    tank_ref=tank,
                    tank_pressures={ref: round(p, 1) for ref, p in tank_pressure.items()},
                    ceiling_gf_low_m=engine.get_ceiling(gf_low),
                )
            )

    return samples, warnings


STOP_INTERVAL_M = 3.0
SAFETY_STOP_DEPTH_M = 3.0
SAFETY_STOP_SEC = 180
SAFETY_STOP_TRIGGER_M = 11.0  # a computer asks for a safety stop after a dive past this


def _no_deco_tts(plan: DiveProfilePlan, depth_m: float, running_max_m: float, had_deco: bool) -> int:
    """Time to surface when no deco is owed: a direct ascent at the plan's
    ascent rate, plus the safety stop still to come after a dive past
    SAFETY_STOP_TRIGGER_M (none after mandatory deco - the stops were it).
    Shallower than the safety stop, the stop's own remaining time isn't
    known here, so only the ascent counts."""
    if depth_m <= 0:
        return 0
    ascent = int(math.ceil(depth_m / plan.default_ascent_rate * 60.0))
    if running_max_m >= SAFETY_STOP_TRIGGER_M and not had_deco and depth_m > SAFETY_STOP_DEPTH_M:
        ascent += SAFETY_STOP_SEC
    return ascent
GAS_SWITCH_HOLD_SEC = 60
MAX_ASCENT_PLAN_SEC = 6 * 3600


def _loaded_engine(plan: DiveProfilePlan, until_sec: Optional[float] = None) -> Tuple[BuhlmannEngine, Optional[Tuple[int, float, str]]]:
    """Tissue state at `until_sec` (default: the end of the plan's last
    waypoint) - the same per-second loading simulate() does, without its
    NDL/TTS lookahead. Also returns the (time, depth, gas_id) timeline entry
    reached, None for an empty plan."""
    timeline, _ = expand_plan(plan)
    engine = BuhlmannEngine(SURFACE_PRESSURE_BAR)
    reached = None
    for entry in timeline:
        t, depth, gas_id = entry
        if until_sec is not None and t > until_sec:
            break
        f_o2, f_he = _effective_fractions(plan, plan.gas_by_id(gas_id), depth)
        engine.update(depth, 1.0, f_o2, f_he)
        reached = entry
    return engine, reached


def plan_ascent(plan: DiveProfilePlan) -> Tuple[List[PlannedWaypoint], bool, List[Tuple[float, int, str]]]:
    """Waypoints that end the dive from its last waypoint: a direct ascent at
    the plan's default ascent rate with a 3m/3min safety stop when no deco
    is needed, otherwise the Buhlmann GF deco schedule - first stop from GF
    low, stops on 3m levels (last at 3m), each held until the ceiling for
    the next level clears with the GF interpolated between GF low at the
    first stop and GF high at the surface, rounded up to whole minutes.
    The 3m stop lasts at least the safety stop's 3 minutes.

    Unlike _mandatory_stop_schedule (which models a dive computer that can't
    see ahead), this is a plan, so it switches gas on the way up: each
    ascent-range gas (auto_gas_for_waypoint, phase "ascent") is picked up at
    the deep end of its range or its MOD at the deco PO2, whichever is
    shallower, with a waypoint placed there. If the last
    waypoint's gas was chosen by hand, the ascent stays on that gas.
    Returns (waypoints, deco_needed, stops) with stops as
    (depth_m, duration_sec, gas_id) - the safety stop or the deco stops,
    not the zero-hold gas-switch waypoints. Empty if the dive already ends
    at the surface."""
    wps = plan.sorted_waypoints()
    if not wps or wps[-1].depth_m <= 0:
        return [], False, []

    apply_auto_gases(plan)
    last = wps[-1]
    engine, _ = _loaded_engine(plan)
    return _ascent_from(plan, engine, last.depth_m, last.runtime_sec, plan.breathed_gas(plan.gas_by_id(last.gas_id)), last.gas_auto)


def ascent_from_time(plan: DiveProfilePlan, time_sec: float) -> Tuple[bool, List[Tuple[float, int, str]], int]:
    """"If I started the ascent right now": (deco_needed, stops, tts_sec) from any
    point of the plan, same schedule rules as plan_ascent - for the chart's
    hover readout. Uses the tissue state, depth and gas at `time_sec`; gas
    switches follow the waypoint covering that moment (auto or by hand).
    Plan waypoints are not changed (beyond apply_auto_gases, which
    simulate's caller already ran)."""
    engine, reached = _loaded_engine(plan, until_sec=time_sec)
    if reached is None or reached[1] <= 0:
        return False, [], 0
    t, depth, gas_id = reached
    covering = next((wp for wp in plan.sorted_waypoints() if wp.runtime_sec >= t), None)
    auto = covering.gas_auto if covering is not None else True
    waypoints, deco_needed, stops = _ascent_from(plan, engine, depth, t, plan.gas_by_id(gas_id), auto)
    tts = waypoints[-1].runtime_sec - t if waypoints else 0
    return deco_needed, stops, tts


DECO_SCHEDULE_INTERVAL_SEC = 60


def deco_schedule_timeline(
    plan: DiveProfilePlan, interval_sec: int = DECO_SCHEDULE_INTERVAL_SEC,
) -> List[Tuple[int, List[Tuple[float, int, str]]]]:
    """How the deco plan develops over the dive: every `interval_sec` while
    deco is needed (a GF-high ceiling), the full stop schedule an ascent
    started right then would get - (time_sec, stops), stops as
    ascent_from_time/plan_ascent give them, (depth_m, duration_sec, gas_id),
    gas-switch holds included. One pass over the dive, so it's cheaper than
    calling ascent_from_time per point. Times out of deco are left out."""
    timeline, _ = expand_plan(plan)
    wps = plan.sorted_waypoints()
    engine = BuhlmannEngine(SURFACE_PRESSURE_BAR)
    gf_high = plan.gf_high / 100.0
    out: List[Tuple[int, List[Tuple[float, int, str]]]] = []
    for t, depth, gas_id in timeline:
        gas = plan.gas_by_id(gas_id)
        f_o2, f_he = _effective_fractions(plan, gas, depth)
        engine.update(depth, 1.0, f_o2, f_he)
        if t % interval_sec or depth <= 0 or engine.get_ceiling(gf_high) <= 0:
            continue
        covering = next((wp for wp in wps if wp.runtime_sec >= t), None)
        auto = covering.gas_auto if covering is not None else True
        _, _, stops = _ascent_from(plan, engine.clone(), depth, t, gas, auto)
        out.append((t, stops))
    return out


def _ascent_from(
    plan: DiveProfilePlan,
    engine: BuhlmannEngine,
    depth: float,
    start_sec: float,
    gas: PlannedGas,
    auto: bool,
) -> Tuple[List[PlannedWaypoint], bool, List[Tuple[float, int, str]]]:
    """plan_ascent's schedule from an arbitrary (tissues, depth, time, gas)
    state; `engine` is advanced in place."""
    gf_low, gf_high = plan.gf_low / 100.0, plan.gf_high / 100.0
    rate_mps = plan.default_ascent_rate / 60.0
    t = float(start_sec)
    out: List[PlannedWaypoint] = []
    stops: List[Tuple[float, int, str]] = []

    def gas_for(d: float) -> PlannedGas:
        if not auto:
            return gas
        return auto_gas_for_waypoint(plan, d, "ascent") or gas

    def add_waypoint(d: float, hold_until: float, g: PlannedGas) -> None:
        runtime = int(math.ceil(hold_until))
        if out and out[-1].depth_m == round(d, 1) and out[-1].gas_id == g.id:
            # Same depth and gas as the previous waypoint (a stop that began
            # with a gas-switch hold) - extend that hold instead.
            out[-1].runtime_sec = max(out[-1].runtime_sec, runtime)
            return
        if out and runtime <= out[-1].runtime_sec:
            runtime = out[-1].runtime_sec + 1
        out.append(PlannedWaypoint(
            runtime_sec=runtime, depth_m=round(d, 1), gas_id=g.id, gas_auto=auto, phase="ascent",
        ))

    def breathe(d: float, seconds: float) -> None:
        f_o2, f_he = _effective_fractions(plan, gas, d)
        engine.update(d, seconds, f_o2, f_he)

    def switch_depths_between(shallow: float, deep: float) -> List[float]:
        """Where each ascent gas becomes usable - the deep end of its range,
        capped at its MOD for the deco PO2 - strictly inside (shallow,
        deep), deepest first. The ascent pauses there to switch gas. A
        CCR dive stays on the loop - no switches."""
        if not auto or plan.is_ccr:
            return []
        found = {
            plan.gas_deepest_use_m(g, "ascent") for g in plan.breathed_gases()
            if g.use_phase in ("any", "ascent")
        }
        return sorted((d for d in found if shallow < d < deep), reverse=True)

    def ascend_to(target: float, stop_at_target: bool = False) -> float:
        """Ascend from `depth` to `target` at the ascent rate, loading
        tissues per second. Each gas switch on the way gets a
        GAS_SWITCH_HOLD_SEC hold on the new gas, ending in a waypoint (the
        engine applies a waypoint's gas once its depth is reached, so the
        whole hold is on the new gas). Returns when `target` was reached -
        before any switch hold there, so a stop at `target` counts it (and
        reports it in `stops` itself, hence stop_at_target)."""
        nonlocal depth, t, gas

        def switch_if_needed() -> None:
            nonlocal t, gas
            new_gas = gas_for(depth)
            if new_gas.id != gas.id and depth > 0:
                gas = new_gas
                breathe(depth, GAS_SWITCH_HOLD_SEC)
                t += GAS_SWITCH_HOLD_SEC
                add_waypoint(depth, t, gas)
                if not (stop_at_target and depth == target):
                    stops.append((depth, GAS_SWITCH_HOLD_SEC, gas.id))

        switch_if_needed()  # already inside a better gas's range where we are
        reached = t
        for leg_end in switch_depths_between(target, depth) + [target]:
            while depth > leg_end:
                step = min(rate_mps, depth - leg_end)
                depth -= step
                t += step / rate_mps
                breathe(depth, step / rate_mps)
            reached = t
            switch_if_needed()
        return reached

    # Deco is needed when the diver can't surface directly - the GF-high
    # ceiling, the same one the chart colours red (simulate's ceiling_m).
    # The first stop itself is then placed from the GF-low ceiling.
    first_stop = 0.0
    deco_needed = engine.get_ceiling(gf_high) > 0

    # Free ascent, one second at a time, until the GF-low ceiling calls
    # for a first stop - or, with no deco, down to the safety stop.
    while depth > 0 and t - start_sec < MAX_ASCENT_PLAN_SEC:
        ceiling = engine.get_ceiling(gf_low) if deco_needed else 0.0
        if ceiling > 0:
            candidate = math.ceil(ceiling / STOP_INTERVAL_M) * STOP_INTERVAL_M
            if depth - rate_mps <= candidate:
                first_stop = candidate
                break
            ascend_to(depth - rate_mps)
        elif depth <= SAFETY_STOP_DEPTH_M:
            break
        else:
            ascend_to(max(depth - rate_mps, SAFETY_STOP_DEPTH_M))

    if not deco_needed or first_stop <= 0:
        # No deco: 3m / 3min safety stop, then surface.
        arrive = ascend_to(SAFETY_STOP_DEPTH_M, stop_at_target=True) if depth > SAFETY_STOP_DEPTH_M else t
        if depth >= SAFETY_STOP_DEPTH_M:
            remaining = max(0.0, arrive + SAFETY_STOP_SEC - t)  # a switch hold here counts
            breathe(depth, remaining)
            t += remaining
            add_waypoint(depth, t, gas)
            stops.append((depth, SAFETY_STOP_SEC, gas.id))
        ascend_to(0.0)
        add_waypoint(0.0, t, gas)
        return out, False, stops

    # Deco stops on 3m levels. A first stop shallower than the current depth
    # but not on it (depth not a multiple of 3) is reached first.
    stop = first_stop if first_stop < depth else math.floor(depth / STOP_INTERVAL_M) * STOP_INTERVAL_M
    stop = max(stop, STOP_INTERVAL_M)
    first_stop = max(first_stop, stop)

    def gf_at(d: float) -> float:
        return gf_high + (gf_low - gf_high) * (d / first_stop)

    while stop > 0 and t - start_sec < MAX_ASCENT_PLAN_SEC:
        arrive = ascend_to(stop, stop_at_target=True)
        next_level = stop - STOP_INTERVAL_M
        while engine.get_ceiling(gf_at(next_level)) > next_level and t - arrive < MAX_ASCENT_PLAN_SEC:
            breathe(depth, 10.0)
            t += 10.0
        held = t - arrive
        if next_level <= 0 and held < SAFETY_STOP_SEC:
            # The last stop is never shorter than a no-deco dive's safety
            # stop - a small obligation a deco gas clears on the way up
            # would otherwise leave no stop at all.
            breathe(depth, SAFETY_STOP_SEC - held)
            t = arrive + SAFETY_STOP_SEC
            held = SAFETY_STOP_SEC
        rounded = math.ceil(held / 60.0) * 60.0 if held > 0 else 0.0
        if rounded > held:
            breathe(depth, rounded - held)
            t = arrive + rounded
        if rounded > 0:
            add_waypoint(stop, t, gas)
            stops.append((stop, int(rounded), gas.id))
        stop = next_level

    ascend_to(0.0)
    add_waypoint(0.0, t, gas)
    return out, True, stops
