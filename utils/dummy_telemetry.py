"""Synthetic dive telemetry for the Overlay Designer's standalone canvas -
overlay_rework.md Phase 1 (decision Q12: a full synthetic dive the time slider
scrubs, plus a state override so badges, notices and colours can be
previewed on demand). No Qt imports; pure models.dive objects, deterministic
output.

The dive passes through every situation a template has to be checked in
(simulator.md, A3), in this order: descent, bottom at 30 m, the NDL running
down (Low NDL Alert at 5 min), a deep excursion to 42 m (Depth Alert, HIGH
PPO2), a deco obligation with a 6 m stop, the ascent towards it (a 25 s fast
ascent on the way), the approach, the stop, a 40 s violation (MISSED DECO
STOP), the stop clearing, the safety stop counting at 5 m, a pause at 1.8 m,
the stop completing, and the surface. One Nx32 cylinder (or two for the
sidemount variant) drains into the reserve during the safety stop. Garmin-
style dive alerts are set where the watch would raise them, so the Garmin
rules see the same dive.

`forced_dive()` builds a short synthetic history for one state so that the
timelines (safety stop, deco clear, notices) report that state whatever the
slider says; `apply_state()` is the older single-waypoint form kept for the
four original states.
"""
import math
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from models.dive import Dive, TankData, Waypoint

DUMMY_START = datetime(2026, 1, 1, 10, 0, 0)
DUMMY_DURATION_S = 32 * 60
DUMMY_SAMPLE_S = 10

# (elapsed seconds, depth m) breakpoints - linearly interpolated between.
_PROFILE = [
    (0, 0.0),
    (180, 30.0),      # descent
    (840, 30.0),      # bottom: the NDL runs out at 14:00
    (900, 42.0),      # excursion below the MOD
    (960, 42.0),
    (1020, 30.0),
    (1140, 12.0),     # ascent at 9 m/min
    (1165, 7.0),      # 25 s at 12 m/min: fast ascent
    (1200, 6.0),      # at the 6 m stop
    (1260, 6.0),
    (1270, 4.5),      # 40 s above the stop
    (1310, 4.5),
    (1320, 6.0),      # back at the stop until it clears (24:00)
    (1440, 6.0),
    (1500, 5.0),      # safety stop
    (1560, 5.0),
    (1570, 1.8),      # 40 s too shallow: paused
    (1610, 1.8),
    (1620, 5.0),
    (1860, 5.0),      # counting to the end (5 min: the dive went below 30 m)
    (1920, 0.0),      # surface
]
# Moments the watch would raise its own alerts (Garmin FIT dive_alert names).
_ALERTS = {
    510: ["approaching_ndl"],
    680: ["approaching_ndl"],
    840: ["ndl_reached"],
    1140: ["approaching_first_deco_stop"],
    1150: ["ascent_critical"],
    1270: ["deco_ceiling_broken"],
    1440: ["deco_stop_cleared"],
    1450: ["deco_complete"],
    # no safety_stop_started after deco: a Descent asks for no safety stop
    # once a deco obligation has been cleared (hud_rules_engine, real Mk3i log)
}
_NDL_OUT_S = 840      # NDL reaches zero
_DECO_CLEAR_S = 1440  # last stop cleared
_STOP_DEPTH = 6.0
_CEILING = 5.0

STATE_OPTIONS = [
    "auto", "normal", "descent", "ndl_low",
    "deco", "deco_approach", "deco_at_stop", "deco_violation", "deco_ceiling_violation", "clear",
    "safety_pending", "safety_stop", "safety_paused", "safety_done",
    "fast_ascent", "high_ppo2", "high_cns", "low_gas", "critical_gas", "surfacing",
]
STATE_LABELS = {
    "auto": "Auto (from data)",
    "normal": "Normal",
    "descent": "Descent",
    "ndl_low": "Low NDL",
    "deco": "Deco (far from the stop)",
    "deco_approach": "Deco: approaching the stop",
    "deco_at_stop": "Deco: at the stop",
    "deco_violation": "Deco: above the stop",
    "deco_ceiling_violation": "Deco: above the ceiling",
    "clear": "Clear (deco done)",
    "safety_pending": "Safety stop pending",
    "safety_stop": "Safety stop counting",
    "safety_paused": "Safety stop paused",
    "safety_done": "Safety stop complete",
    "fast_ascent": "Fast ascent",
    "high_ppo2": "High PPO2 / deep",
    "high_cns": "High CNS",
    "low_gas": "Low gas (reserve)",
    "critical_gas": "Critical gas",
    "surfacing": "Surfacing",
}
# The HUD state (hud_rules_engine.resolve_state) each forced state is a case of.
# (on a Shearwater any dive past 11 m is in the "safety_stop" state - the
# counter is shown, pending - until the stop is done: resolve_state() says so
# for the Perdix 2 cases below that a Descent reports as "normal")
STATE_OUTER = {
    "normal": "normal", "descent": "normal", "ndl_low": "normal",
    "deco": "deco", "deco_approach": "deco", "deco_at_stop": "deco", "deco_violation": "deco", "deco_ceiling_violation": "deco",
    "clear": "clear",
    "safety_pending": "safety_stop", "safety_stop": "safety_stop", "safety_paused": "safety_stop", "safety_done": "safety_stop",
    "fast_ascent": "normal", "high_ppo2": "normal", "high_cns": "normal", "low_gas": "normal", "critical_gas": "normal", "surfacing": "normal",
}


def _depth_at(t: float) -> float:
    if t <= _PROFILE[0][0]:
        return _PROFILE[0][1]
    for (t0, d0), (t1, d1) in zip(_PROFILE, _PROFILE[1:]):
        if t0 <= t <= t1:
            if t1 == t0:
                return d1
            frac = (t - t0) / (t1 - t0)
            return d0 + (d1 - d0) * frac
    return _PROFILE[-1][1]


def _tank_keys(variant: Optional[str]) -> List[str]:
    return ["Left", "Right"] if variant == "sidemount" else ["T1"]


def _stop_time_left(t: int) -> Optional[int]:
    """Seconds left at the 6 m stop: 180 until the diver gets there (20:00),
    counting down while at the stop, frozen during the violation."""
    if t < _NDL_OUT_S or t >= _DECO_CLEAR_S:
        return None
    if t < 1200:
        return 180
    if t < 1260:
        return 180 - (t - 1200)
    if t < 1320:
        return 120
    return max(0, 120 - (t - 1320))


# A rebreather version of the same dive (build_dummy_dive(ccr=True), for the
# CC pages): a 0.7 bar setpoint switched to 1.3 below 6 m on the way down
# (the Builder's and a Descent's default switch depth) and back to 0.7 at the
# 1.8 m pause; three cells around the setpoint, cell 3 drifting low during
# the deep excursion (out of the vote); a bailout to EAN50 for the deco stop
# and its violation, back on the loop when the stop clears.
_CCR_DILUENT = (18.0, 45.0)
_CCR_BAILOUT = (50.0, 0.0)
_CCR_HIGH_SP_S = 40        # passing 6 m on the way down
_CCR_LOW_SP_S = 1570       # the pause at 1.8 m
_CCR_BAILOUT_S = (1200, 1440)
_CCR_ALERTS = {
    _CCR_HIGH_SP_S: ["setpoint_switch_auto_high"],
    _CCR_LOW_SP_S: ["setpoint_switch_auto_low"],
    _CCR_BAILOUT_S[0]: ["switched_to_open_circuit"],
    _CCR_BAILOUT_S[1]: ["switched_to_closed_circuit"],
}


def _ccr_fields(t: int, depth: float, ambient: float) -> Dict[str, Any]:
    bailout = _CCR_BAILOUT_S[0] <= t < _CCR_BAILOUT_S[1]
    gas = _CCR_BAILOUT if bailout else _CCR_DILUENT
    fields: Dict[str, Any] = {
        "divemode": "opencircuit" if bailout else "closedcircuit",
        "gas_o2_percent": gas[0], "gas_he_percent": gas[1],
        "diluent_o2_percent": _CCR_DILUENT[0], "diluent_he_percent": _CCR_DILUENT[1],
    }
    setpoint = 1.3 if _CCR_HIGH_SP_S <= t < _CCR_LOW_SP_S else 0.7
    setpoint = min(setpoint, round(ambient * 0.98, 2))  # pure O2 at the surface cannot reach more
    drift = 0.45 if 900 <= t < 990 else 0.0
    fields.update(po2_1=round(setpoint + 0.02, 2), po2_2=round(setpoint - 0.01, 2), po2_3=round(setpoint - 0.03 - drift, 2))
    if bailout:
        fields.update(setpoint=None, po2=round(ambient * gas[0] / 100.0, 2))
    else:
        fields.update(setpoint=setpoint, po2=setpoint)
    return fields


def build_dummy_dive(variant: Optional[str] = "single_tank", ccr: bool = False) -> Dive:
    """A deterministic 32-minute synthetic dive (see the module docstring).
    `variant` only decides the tank count (2 for "sidemount", else 1) so
    resolve_tank_variant() on the result round-trips to the same variant.
    `ccr`: the rebreather version (see _CCR_DILUENT) with an O2 cylinder and
    the diluent as its tanks."""
    keys = ["O2", "DIL"] if ccr else _tank_keys(variant)
    pressures: Dict[str, float] = {k: 200.0 for k in keys}
    waypoints: List[Waypoint] = []
    max_depth = 0.0
    bottom_time_s = 0.0
    prev_depth = 0.0

    for t in range(0, DUMMY_DURATION_S + 1, DUMMY_SAMPLE_S):
        depth = round(_depth_at(t), 1)
        max_depth = max(max_depth, depth)
        ambient = 1.0 + depth / 10.0
        in_deco = _NDL_OUT_S <= t < _DECO_CLEAR_S

        # Gas: ~1.8 bar/min at the surface, scaled by ambient pressure, so the
        # single cylinder is into the reserve (under 50 bar) by the safety stop;
        # sidemount alternates cylinders every 5 minutes.
        rate_bar_per_s = 1.8 / 60.0 * ambient
        if len(keys) == 2:
            active = keys[(t // 300) % 2]
            pressures[active] = max(20.0, pressures[active] - rate_bar_per_s * DUMMY_SAMPLE_S)
        else:
            pressures[keys[0]] = max(20.0, pressures[keys[0]] - rate_bar_per_s * DUMMY_SAMPLE_S)

        if depth >= 10.0:
            bottom_time_s += DUMMY_SAMPLE_S
        bottom_min = bottom_time_s / 60.0

        # NDL: by depth on the way down, then 20 min at 14:00 ... 0 at 14:00
        # (the Low NDL Alert fires at 5 min, 11:15), none in deco, 99+ after.
        if t < 180:
            ndl_s: Optional[int] = int(max(3.0, min(99.0, 99.0 - depth * 2.6)) * 60)
        elif t < _NDL_OUT_S:
            ndl_s = int(round(20.0 * (_NDL_OUT_S - t) / (_NDL_OUT_S - 180) * 60))
        elif in_deco:
            ndl_s = None
        else:
            ndl_s = 99 * 60
        stop_left = _stop_time_left(t)
        # TTS: direct ascent at 9 m/min plus the stop and the safety stop.
        tts_s = int(depth / 9.0 * 60 + (stop_left or 0) + (180 if max_depth >= 10.0 else 0))

        primary_pressure = pressures[keys[0]]
        air_remaining_s = int(max(0.0, primary_pressure - 50.0) / rate_bar_per_s) if rate_bar_per_s else None
        ascent_rate = (prev_depth - depth) / DUMMY_SAMPLE_S * 60.0 if t else 0.0
        prev_depth = depth

        tanks = {
            key: TankData(
                pressure_bar=round(pressures[key], 1),
                o2_percent=32.0,
                he_percent=0.0,
                name=key,
                mode="OC",
                enabled=True,
            )
            for key in keys
        }
        extra: Dict[str, Any] = {}
        alerts = list(_ALERTS.get(t, []))
        if ccr:
            # the loop uses little gas: O2 and diluent drain slowly and evenly
            for key, mix in (("O2", (100.0, 0.0)), ("DIL", _CCR_DILUENT)):
                tanks[key] = tanks[key].model_copy(update={"o2_percent": mix[0], "he_percent": mix[1], "mode": "CC",
                                                           "pressure_bar": round(200.0 - t / DUMMY_DURATION_S * (40.0 if key == "O2" else 25.0), 1)})
            extra = _ccr_fields(t, depth, ambient)
            alerts += _CCR_ALERTS.get(t, [])

        waypoints.append(
            Waypoint(
                timestamp=DUMMY_START + timedelta(seconds=t),
                depth=depth,
                temp=round(27.0 - depth * 0.12, 1),
                max_depth=max_depth,
                deco_stop_depth=_STOP_DEPTH if in_deco else (0.0 if t == _DECO_CLEAR_S else None),
                ceiling=_CEILING if in_deco else None,
                next_stop_depth=_STOP_DEPTH if in_deco else (0.0 if t == _DECO_CLEAR_S else None),
                next_stop_time=stop_left if in_deco else (0 if t == _DECO_CLEAR_S else None),
                tts=tts_s,
                ndl=ndl_s,
                time_since_start=t,
                dive_time=t,
                tanks=tanks,
                air_remaining=air_remaining_s,
                ascent_rate=round(ascent_rate, 1),
                n2_tissue_load=round(min(150.0, depth * 3.0 + bottom_min * 1.5), 1),
                heart_rate=int(78 + 10 * math.sin(t / 240.0)),
                cns=int(min(45, bottom_min * 1.4 + (10 if max_depth > 40 else 0))),
                **({"po2": round(0.32 * ambient, 2), "divemode": "OC"} if not ccr else extra),
                gf=round(min(110.0 if in_deco else 85.0, depth * 1.8 + bottom_min * 1.2), 1),
                battery=87.0,
                dive_alerts=alerts,
            )
        )

    return Dive(
        start_time=DUMMY_START,
        end_time=DUMMY_START + timedelta(seconds=DUMMY_DURATION_S),
        waypoints=waypoints,
        device="Synthetic dive computer",
        manufactor="UWMedia",
        gf_low=40, gf_high=85,  # a Shearwater's default conservatism, Med (Perdix 2 manual p.18)
        duration_seconds=DUMMY_DURATION_S,
        log_filename="dummy_telemetry",
    )


def waypoint_at(dive: Dive, seconds: float) -> Optional[Waypoint]:
    """First waypoint at or after `seconds` of dive time, else the last one -
    the same nearest-forward rule the designer's log scrubbing uses."""
    if not dive or not dive.waypoints:
        return None
    for wp in dive.waypoints:
        if wp.time_since_start >= seconds:
            return wp
    return dive.waypoints[-1]


# --- forced states ---------------------------------------------------------

_QUIET: Dict[str, Any] = {"deco_stop_depth": None, "next_stop_depth": None, "next_stop_time": None, "ceiling": None, "ndl": 600, "tts": 300, "dive_alerts": []}
_DECO: Dict[str, Any] = {"deco_stop_depth": _STOP_DEPTH, "next_stop_depth": _STOP_DEPTH, "next_stop_time": 180, "ceiling": _CEILING, "ndl": None, "tts": 600, "dive_alerts": []}

# state -> segments (seconds, depth or (from, to) ramp, extras) ending at the
# forced waypoint, plus extras for that last waypoint only. Every history
# starts deeper than the safety-stop trigger where the state needs it armed.
_FORCED: Dict[str, Tuple[List[Tuple[int, Any, Dict[str, Any]]], Dict[str, Any]]] = {
    "descent": ([(60, (0.0, 10.0), dict(_QUIET))], {"ascent_rate": -10.0, "max_depth": 10.0}),
    "ndl_low": ([(120, 30.0, dict(_QUIET, ndl=600))], {"ndl": 240}),
    "deco": ([(60, 30.0, dict(_DECO))], {"depth": 20.0}),
    "deco_approach": ([(60, 30.0, dict(_DECO))], {"depth": 9.0}),
    "deco_at_stop": ([(60, 30.0, dict(_DECO))], {"depth": 6.4}),
    "deco_violation": ([(60, 30.0, dict(_DECO)), (30, 6.0, dict(_DECO)), (40, 5.6, dict(_DECO))], {"dive_alerts": ["deco_ceiling_broken"]}),
    "deco_ceiling_violation": ([(60, 30.0, dict(_DECO)), (30, 6.0, dict(_DECO)), (40, 4.5, dict(_DECO))], {"dive_alerts": ["deco_ceiling_broken"]}),
    "clear": ([(60, 30.0, dict(_DECO)), (60, 6.0, dict(_DECO, next_stop_time=30)), (10, 4.5, dict(_QUIET, deco_stop_depth=0.0, next_stop_depth=0.0, next_stop_time=0, ndl=99 * 60, tts=30))],
              {"dive_alerts": ["deco_stop_cleared"]}),
    "safety_pending": ([(120, 20.0, dict(_QUIET)), (10, 8.0, dict(_QUIET))], {}),
    "safety_stop": ([(120, 20.0, dict(_QUIET)), (60, 5.0, dict(_QUIET, next_stop_depth=5.0, next_stop_time=120))], {"dive_alerts": ["safety_stop_started"]}),
    "safety_paused": ([(120, 20.0, dict(_QUIET)), (60, 5.0, dict(_QUIET, dive_alerts=["safety_stop_started"])), (30, 1.8, dict(_QUIET))], {}),
    "safety_done": ([(120, 20.0, dict(_QUIET)), (320, 5.0, dict(_QUIET, dive_alerts=["safety_stop_started"]))], {}),
    "fast_ascent": ([(60, 20.0, dict(_QUIET)), (20, (20.0, 16.0), dict(_QUIET))], {"dive_alerts": ["ascent_critical"]}),  # 12 m/min for 10 s
    "high_ppo2": ([(40, 42.0, dict(_QUIET, po2=1.7))], {"max_depth": 42.0}),  # 30 s above the limit, then shown
    "high_cns": ([(30, 20.0, dict(_QUIET))], {"cns": 95, "dive_alerts": ["cns_critical"]}),
    "low_gas": ([(30, 20.0, dict(_QUIET))], {"_tank_bar": 47.0}),
    "critical_gas": ([(30, 20.0, dict(_QUIET))], {"_tank_bar": 23.0}),
    "surfacing": ([(120, 20.0, dict(_QUIET)), (200, 5.0, dict(_QUIET, dive_alerts=["safety_stop_started"])), (10, 0.3, dict(_QUIET))], {}),
}


def _with_tanks(wp: Waypoint, bar: float) -> Dict[str, Any]:
    tanks = {name: tank.model_copy(update={"pressure_bar": bar}) for name, tank in (wp.tanks or {}).items()}
    return {"tanks": tanks or {"T1": TankData(pressure_bar=bar, o2_percent=32.0, name="T1", mode="OC", enabled=True)}}


def forced_dive(waypoint: Waypoint, state: str) -> Tuple[Waypoint, Optional[List[Waypoint]]]:
    """(waypoint, history) for a forced `state`: a short synthetic dive ending
    in that situation, built from `waypoint`'s own values (tanks, temperature,
    CNS...). The history is what the timelines - safety stop, deco clear,
    notices - need to report the state; "auto" returns the waypoint untouched
    and no history, "normal" the single-waypoint form of apply_state()."""
    if waypoint is None or state not in STATE_OPTIONS or state == "auto":
        return waypoint, None
    if state == "normal":
        return apply_state(waypoint, "normal"), None
    segments, final = _FORCED[state]
    history: List[Waypoint] = []
    t = 0
    max_depth = 0.0
    prev_d: Optional[float] = None
    for seconds, depth, extras in segments:
        steps = max(1, int(seconds // DUMMY_SAMPLE_S))
        for i in range(steps):
            d = depth if not isinstance(depth, tuple) else depth[0] + (depth[1] - depth[0]) * (i + 1) / steps
            max_depth = max(max_depth, d)
            update = dict(extras)
            update["dive_alerts"] = list(extras.get("dive_alerts", [])) if i == 0 else []
            update.update({"depth": round(d, 1), "max_depth": max(max_depth, waypoint.max_depth if state in ("low_gas", "critical_gas", "high_cns", "ndl_low") else 0.0),
                           "ascent_rate": round((prev_d - d) / DUMMY_SAMPLE_S * 60.0, 1) if prev_d is not None else 0.0,
                           "time_since_start": t, "dive_time": t, "timestamp": DUMMY_START + timedelta(seconds=t)})
            history.append(waypoint.model_copy(update=update))
            prev_d = d
            t += DUMMY_SAMPLE_S
    last = history[-1]
    update = {k: v for k, v in final.items() if not k.startswith("_")}
    if "_tank_bar" in final:
        update.update(_with_tanks(last, final["_tank_bar"]))
    if "max_depth" in update:
        update["max_depth"] = max(update["max_depth"], last.max_depth)
    forced = last.model_copy(update=update)
    forced._dive = waypoint._dive
    for wp in history:
        wp._dive = waypoint._dive
    history[-1] = forced
    return forced, history


def apply_state(waypoint: Waypoint, state: str) -> Waypoint:
    """A copy of `waypoint` adjusted so hud_rules_engine.resolve_state() reports
    `state` from this one waypoint (both the Garmin dive_alerts path and the
    Shearwater/UDDF depth-band heuristic are satisfied at once) for the four
    original states; the other states come from forced_dive()'s last
    waypoint. "auto" (or anything unknown) returns the waypoint unchanged."""
    if state not in STATE_OPTIONS or state == "auto":
        return waypoint

    update: Dict[str, object] = {
        "deco_stop_depth": None,
        "next_stop_depth": None,
        "next_stop_time": None,
        "dive_alerts": [],
    }
    if state == "normal":
        # Kill the safety-stop band trigger (max_depth >= 10 while in 3-6 m)
        # without moving the diver somewhere implausible.
        if waypoint.depth is not None and 3.0 <= waypoint.depth <= 6.0:
            update["max_depth"] = min(waypoint.max_depth, 9.9)
    elif state == "safety_stop":
        update.update({
            "depth": 5.0,
            "max_depth": max(waypoint.max_depth, 18.0),
            "next_stop_depth": 5.0,
            "next_stop_time": 120,
            "dive_alerts": ["safety_stop_started"],
        })
    elif state == "deco":
        update.update({
            "depth": 12.0,
            "max_depth": max(waypoint.max_depth, 30.0),
            "deco_stop_depth": 6.0,
            "next_stop_depth": 6.0,
            "next_stop_time": 180,
            "ndl": None,
            "tts": 600,
            "dive_alerts": ["approaching_first_deco_stop"],
        })
    elif state == "clear":
        # Deco just cleared: Garmin's own deco_stop_cleared alert drives the
        # alert path; a Shearwater badge shows its deco-clear count-up (from
        # zero here, with no dive around this one waypoint).
        update.update({
            "depth": 4.5,
            "max_depth": max(waypoint.max_depth, 30.0),
            "deco_stop_depth": 0.0,
            "next_stop_depth": 0.0,
            "next_stop_time": 0,
            "ndl": 99 * 60,
            "tts": 30,
            "dive_alerts": ["deco_stop_cleared"],
        })
    else:
        return forced_dive(waypoint, state)[0]

    adjusted = waypoint.model_copy(update=update)
    # model_copy() keeps private attributes, but be explicit so log_filename
    # (a _dive-backed property) keeps working on the copy.
    adjusted._dive = waypoint._dive
    return adjusted
