"""Synthetic dive telemetry for the Overlay Designer's standalone canvas -
overlay_rework.md Phase 1 (decision Q12: a full synthetic dive the time slider
scrubs, plus a state override so badges/blink colours can be previewed on
demand). No Qt imports; pure models.dive objects, deterministic output.

The dive is deliberately "textbook": a multi-level recreational profile to
24 m with a 3-minute safety stop, one Nx32 cylinder (or two for the sidemount
variant) draining at a depth-weighted rate, NDL/TTS that shrink and grow the
way a real computer's would, and a few of the extended Garmin/Shearwater
fields (heart rate, PO2, GF, CNS) populated so every bundled template shows a
plausible number rather than "--".
"""
import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from models.dive import Dive, TankData, Waypoint

DUMMY_START = datetime(2026, 1, 1, 10, 0, 0)
DUMMY_DURATION_S = 45 * 60
DUMMY_SAMPLE_S = 10

# (elapsed seconds, depth m) breakpoints - linearly interpolated between.
_PROFILE = [
    (0, 0.0),
    (3 * 60, 24.0),      # descent
    (15 * 60, 24.0),     # bottom
    (17 * 60, 18.0),     # first ascent
    (30 * 60, 18.0),     # second level
    (32 * 60, 12.0),
    (36 * 60, 12.0),     # third level
    (39 * 60, 5.0),      # ascent to safety stop
    (42 * 60, 5.0),      # safety stop
    (45 * 60, 0.0),      # surface
]

STATE_OPTIONS = ["auto", "normal", "safety_stop", "deco", "clear"]
STATE_LABELS = {
    "auto": "Auto (from data)",
    "normal": "Normal",
    "safety_stop": "Safety stop",
    "deco": "Deco",
    "clear": "Clear",
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


def build_dummy_dive(variant: Optional[str] = "single_tank") -> Dive:
    """A deterministic 45-minute synthetic dive. `variant` only decides the
    tank count (2 for "sidemount", else 1) so resolve_tank_variant() on the
    result round-trips to the same variant."""
    keys = _tank_keys(variant)
    pressures: Dict[str, float] = {k: 200.0 for k in keys}
    waypoints: List[Waypoint] = []
    max_depth = 0.0
    bottom_time_s = 0.0
    prev_depth = 0.0

    for t in range(0, DUMMY_DURATION_S + 1, DUMMY_SAMPLE_S):
        depth = round(_depth_at(t), 1)
        max_depth = max(max_depth, depth)
        ambient = 1.0 + depth / 10.0

        # Gas: ~1.1 bar/min at the surface, scaled by ambient pressure;
        # sidemount alternates cylinders every 5 minutes.
        rate_bar_per_s = 1.1 / 60.0 * ambient
        if len(keys) == 2:
            active = keys[(t // 300) % 2]
            pressures[active] = max(20.0, pressures[active] - rate_bar_per_s * DUMMY_SAMPLE_S)
        else:
            pressures[keys[0]] = max(20.0, pressures[keys[0]] - rate_bar_per_s * DUMMY_SAMPLE_S)

        if depth >= 10.0:
            bottom_time_s += DUMMY_SAMPLE_S

        # NDL: generous at the surface, tightening with depth and bottom time,
        # clamped to the 99+ ceiling real computers show when shallow.
        ndl_min = 99.0 - depth * 2.6 - bottom_time_s / 60.0 * 0.6
        ndl_s = int(max(3.0, min(99.0, ndl_min)) * 60)
        # TTS: direct ascent at 9 m/min plus the 3-minute safety stop.
        tts_s = int(depth / 9.0 * 60 + (180 if max_depth >= 10.0 else 0))

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

        waypoints.append(
            Waypoint(
                timestamp=DUMMY_START + timedelta(seconds=t),
                depth=depth,
                temp=round(27.0 - depth * 0.12, 1),
                max_depth=max_depth,
                deco_stop_depth=None,
                tts=tts_s,
                ndl=ndl_s,
                time_since_start=t,
                dive_time=t,
                tanks=tanks,
                air_remaining=air_remaining_s,
                ascent_rate=round(ascent_rate, 1),
                n2_tissue_load=round(min(150.0, depth * 3.0 + bottom_time_s / 60.0 * 1.5), 1),
                heart_rate=int(78 + 10 * math.sin(t / 240.0)),
                cns=int(min(30, bottom_time_s / 60.0 * 0.6)),
                po2=round(0.32 * ambient, 2),
                divemode="OC",
                gf=round(min(85.0, depth * 1.8 + bottom_time_s / 60.0 * 0.9), 1),
                battery=87.0,
            )
        )

    return Dive(
        start_time=DUMMY_START,
        end_time=DUMMY_START + timedelta(seconds=DUMMY_DURATION_S),
        waypoints=waypoints,
        device="Synthetic dive computer",
        manufactor="UWMedia",
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


def apply_state(waypoint: Waypoint, state: str) -> Waypoint:
    """A copy of `waypoint` adjusted so hud_rules_engine.resolve_state() reports
    `state` for every manufacturer (both the Garmin dive_alerts path and the
    Shearwater/UDDF depth-band heuristic are satisfied at once). "auto" (or
    anything unknown) returns the waypoint unchanged."""
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
        # 0.5 m above the 6 m stop: inside Shearwater's 1.0 m "clear" margin,
        # and Garmin's own deco_stop_cleared alert for the alert-driven path.
        update.update({
            "depth": 6.5,
            "max_depth": max(waypoint.max_depth, 30.0),
            "deco_stop_depth": 6.0,
            "next_stop_depth": 6.0,
            "next_stop_time": 45,
            "ndl": None,
            "tts": 300,
            "dive_alerts": ["deco_stop_cleared"],
        })

    adjusted = waypoint.model_copy(update=update)
    # model_copy() keeps private attributes, but be explicit so log_filename
    # (a _dive-backed property) keeps working on the copy.
    adjusted._dive = waypoint._dive
    return adjusted
