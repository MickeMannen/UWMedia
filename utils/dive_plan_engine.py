import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

from models.dive_plan import DiveProfilePlan, PlannedGas, PlannedWaypoint
from utils.deco_engine import BuhlmannEngine, ccr_effective_fractions

SURFACE_PRESSURE_BAR = 1.01325

# Matches DiveDecompressor's own `simulation_interval` convention
# (utils/deco_engine.py) - a full NDL/deco-stop lookahead is only worth
# re-running this often; the value is held/decremented by 1 in between, the
# same tradeoff that module already makes for real-log TTS.
RECOMPUTE_INTERVAL_SEC = 10


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
    tank_pressure_bar: float


def expand_plan(plan: DiveProfilePlan) -> Tuple[List[Tuple[int, float, str]], List[str]]:
    """Turns the sparse waypoint list into one (time_sec, depth_m, gas_id)
    entry per second. Segment rule (matches Subsurface's own planner, which
    this codebase already parses): the transition from waypoint i-1 to i
    happens immediately, at the applicable rate; whatever time remains is
    spent holding at waypoint i's depth. The gas assigned to a waypoint
    takes effect once that depth is reached (not during the transit itself)
    - this matches real Perdix 2 export evidence, where a <switchmix> always
    lands on the waypoint already at the new depth, not mid-ascent."""
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

    timeline: List[Tuple[int, float, str]] = [(points[0].runtime_sec, points[0].depth_m, points[0].gas_id)]
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
                gas_id = prev.gas_id
            else:
                depth = cur.depth_m
                gas_id = cur.gas_id
            timeline.append((absolute_t, depth, gas_id))

    return timeline, warnings


def _effective_fractions(gas: PlannedGas, ambient_pressure_bar: float) -> Tuple[float, float]:
    if gas.is_ccr:
        return ccr_effective_fractions(gas.ccr_setpoint or 1.3, ambient_pressure_bar, gas.f_o2, gas.f_he)
    return gas.f_o2, gas.f_he


def _mandatory_stop_schedule(
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
    is just another waypoint the user places by hand. Returns
    (tts_seconds, first_stop_depth_m, first_stop_duration_sec)."""
    if engine.get_ceiling(gf_low) <= 0:
        return 0, 0.0, 0

    sim = engine.clone()
    total_time = 0
    cur_depth = depth_m
    first_stop_depth = 0.0
    first_stop_duration = 0
    seen_first_stop = False

    while cur_depth > 0 and total_time < max_seconds:
        target_ceiling = sim.get_ceiling(gf_low)
        if cur_depth > target_ceiling:
            step = min(cur_depth, ascent_rate_mps)
            cur_depth -= step
            f_o2, f_he = _effective_fractions(gas, SURFACE_PRESSURE_BAR + cur_depth / 10.0)
            sim.update(cur_depth, 1.0, f_o2, f_he)
            total_time += 1
            continue

        stop_depth = math.ceil(cur_depth / 3.0) * 3.0
        if stop_depth < 3.0:
            break

        duration = 0
        while total_time < max_seconds:
            if sim.get_ceiling(gf_high) <= stop_depth - 3.0:
                break
            f_o2, f_he = _effective_fractions(gas, SURFACE_PRESSURE_BAR + stop_depth / 10.0)
            sim.update(stop_depth, 10.0, f_o2, f_he)
            total_time += 10
            duration += 10

        if not seen_first_stop:
            first_stop_depth = stop_depth
            first_stop_duration = duration
            seen_first_stop = True

        cur_depth = stop_depth - 3.0
        total_time += 20  # time to move between stops, matching DiveDecompressor's own convention

    return total_time, first_stop_depth, first_stop_duration


def simulate(plan: DiveProfilePlan, resolution_sec: int = 1) -> Tuple[List[SimulatedSample], List[str]]:
    """Runs the full per-second Buhlmann simulation for `plan`, sampling
    every `resolution_sec`-th second into the returned list. Tissue loading
    is always integrated per-second internally regardless of
    `resolution_sec` (it's path-dependent, can't be skipped) - resolution
    only controls how many samples are kept, e.g. resolution_sec=60 for a
    cheap interactive preview vs resolution_sec=1 for the final UDDF save."""
    if not plan.gases:
        raise ValueError("Define at least one gas before simulating a profile")

    timeline, warnings = expand_plan(plan)
    if not timeline:
        return [], warnings

    engine = BuhlmannEngine(SURFACE_PRESSURE_BAR)
    gf_low = plan.gf_low / 100.0
    gf_high = plan.gf_high / 100.0
    tank_pressure = {g.id: g.start_pressure_bar for g in plan.gases}

    samples: List[SimulatedSample] = []
    last_ndl: Optional[int] = None
    last_tts = 0
    last_stop_depth = 0.0
    last_stop_duration = 0

    for i, (t, depth, gas_id) in enumerate(timeline):
        gas = plan.gas_by_id(gas_id)
        ambient = SURFACE_PRESSURE_BAR + depth / 10.0
        f_o2, f_he = _effective_fractions(gas, ambient)
        engine.update(depth, 1.0, f_o2, f_he)

        if gas.sac_lpm > 0:
            drop_bar = (gas.sac_lpm / 60.0 * ambient) / gas.tank_size_l
            tank_pressure[gas_id] = max(0.0, tank_pressure[gas_id] - drop_bar)

        ceiling = engine.get_ceiling(gf_high)
        if t % RECOMPUTE_INTERVAL_SEC == 0 or i == 0:
            if ceiling <= 0:
                last_ndl = engine.compute_ndl_seconds(depth, f_o2, f_he, gf_low)
                last_tts, last_stop_depth, last_stop_duration = 0, 0.0, 0
            else:
                last_ndl = None
                last_tts, last_stop_depth, last_stop_duration = _mandatory_stop_schedule(
                    engine, depth, gas, gf_low, gf_high
                )
        elif ceiling <= 0:
            last_ndl = max(0, last_ndl - 1) if last_ndl is not None else None
        else:
            last_tts = max(0, last_tts - 1)
            last_stop_duration = max(0, last_stop_duration - 1)

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
                    divemode="closedcircuit" if gas.is_ccr else "opencircuit",
                    tank_pressure_bar=round(tank_pressure[gas_id], 1),
                )
            )

    return samples, warnings
