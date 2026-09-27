"""SAC and GTR for logs that don't carry them (Shearwater Cloud UDDF and
Subsurface exports - a Perdix computes both on the fly but logs neither),
the way the Perdix 2 manual defines them (p.41, "Surface Air Consumption"
and "Gas Time Remaining"):

- SAC is the rate of tank-pressure change over the last SAC_WINDOW_SEC
  (two minutes), normalised to 1 atmosphere: (P1 - P2) / (t2 - t1) /
  average ambient pressure over that window, in bar/min. Nothing is shown
  for the first SAC_WARMUP_SEC of a dive (the computer says "wait").
- GTR is the minutes that can be spent at the current depth until a direct
  ascent at ASCENT_RATE_M_PER_MIN would surface with the reserve pressure:
  (P - reserve - P_ascent) / (SAC x ambient), where P_ascent is what the
  ascent itself uses at the current SAC.

Sidemount (two tanks) is treated as the manual's SM mode does: the two
identical tanks' pressures are summed, so SAC covers both and GTR keeps a
reserve in each.
"""
from typing import Any, List, Optional, Sequence

SAC_WINDOW_SEC = 120
SAC_WARMUP_SEC = 30
ASCENT_RATE_M_PER_MIN = 10.0
DEFAULT_RESERVE_BAR = 50.0  # Perdix 2 "Reserve Pressure" default (p.53)


def _ambient_ata(depth_m: float) -> float:
    return 1.0 + max(0.0, depth_m) / 10.0


def _total_pressure(wp: Any) -> Optional[float]:
    tanks = getattr(wp, "tanks", None) or {}
    readings = [t.pressure_bar for t in tanks.values() if getattr(t, "pressure_bar", None) is not None]
    return sum(readings) if readings else None


def fill_sac_and_gtr(
    waypoints: Sequence[Any],
    reserve_bar: float = DEFAULT_RESERVE_BAR,
    window_sec: int = SAC_WINDOW_SEC,
    warmup_sec: int = SAC_WARMUP_SEC,
) -> None:
    """Sets pressure_sac (bar/min) and air_remaining (GTR, seconds) on every
    waypoint that has neither, from the tank pressures already on them.
    Waypoints must be in time order. Does nothing to values a log carries."""
    history: List[tuple] = []  # (t, total pressure, ambient)
    for wp in waypoints:
        t = getattr(wp, "time_since_start", None)
        depth = getattr(wp, "depth", None)
        pressure = _total_pressure(wp)
        if t is None or depth is None or pressure is None:
            continue
        ambient = _ambient_ata(float(depth))
        history.append((int(t), float(pressure), ambient))
        while history and history[0][0] < t - window_sec:
            history.pop(0)
        if getattr(wp, "pressure_sac", None) is not None:
            continue
        if t < warmup_sec or len(history) < 2:
            continue
        t0, p0, _ = history[0]
        span = t - t0
        if span < window_sec:
            continue  # the computer says "wait" until it has the full two minutes
        avg_ambient = sum(h[2] for h in history) / len(history)
        sac = (p0 - pressure) / (span / 60.0) / avg_ambient
        sac = max(0.0, sac)
        wp.pressure_sac = round(sac, 2)
        if getattr(wp, "air_remaining", None) is None:
            tank_count = max(1, len(getattr(wp, "tanks", None) or {}))
            ascent_min = float(depth) / ASCENT_RATE_M_PER_MIN
            p_ascent = sac * ascent_min * (1.0 + float(depth) / 20.0)  # average ambient on the way up
            remaining = pressure - reserve_bar * tank_count - p_ascent
            if sac > 0:
                gtr_min = remaining / (sac * ambient)
                wp.air_remaining = int(max(0.0, gtr_min) * 60)
