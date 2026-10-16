"""Values a computer shows that no log records, computed from what the log
has (simulator.md A6; the owner's decision: a computed value is always
shown where the log lacks one):

- the MOD of the breathed gas from its O2 fraction and the brand's MOD ppO2
  limit (Perdix 2 manual p.62: OC MOD PPO2 1.40 by default);
- a Shearwater's GTR from the tank pressure trend (Perdix 2 manual p.44-45
  and p.57): the SAC is the pressure drop over the last two minutes
  normalised to 1 ATA; the gas left after the reserve and a direct ascent
  at 10 m/min, divided by the SAC at the current ambient pressure, is the
  time in minutes; "wait" until two minutes of data exist, and no GTR once
  decompression stops are required (p.26, p.44).
"""
from typing import Any, List, Optional

from utils.hud_rules_engine import _cached_timeline, _num, get_rule_config, tank_reserve_thresholds


def gas_o2_fraction(waypoint: Any) -> Optional[float]:
    """O2 fraction of the gas breathed (the primary tank's mix), or None."""
    tanks = getattr(waypoint, "tanks", None) or {}
    for tank in tanks.values():
        o2 = _num(getattr(tank, "o2_percent", None))
        if o2 is not None and o2 > 0:
            return o2 / 100.0
    return None


def mod_metres(manufacturer: Optional[str], model: Optional[str], waypoint: Any) -> Optional[float]:
    """Maximum operating depth of the breathed gas at the brand's MOD ppO2
    limit (`po2_limits.mod`, 1.4 bar when the brand sets none)."""
    f_o2 = gas_o2_fraction(waypoint)
    if not f_o2:
        return None
    limits = get_rule_config(manufacturer, model, "po2_limits")
    limit = float(limits.get("mod", 1.4)) if isinstance(limits, dict) else 1.4
    return max(0.0, (limit / f_o2 - 1.0) * 10.0)


def _primary_pressure(wp: Any) -> Optional[float]:
    tanks = getattr(wp, "tanks", None) or {}
    for tank in tanks.values():
        return _num(getattr(tank, "pressure_bar", None))
    return None


def _build_gtr_timeline(manufacturer, model, waypoints, rule) -> dict:
    """{time_since_start: seconds or None} - None where the device would show
    "wait" (under two minutes of pressure data) or nothing (in deco)."""
    window = float(rule.get("sac_window_s", 120))
    ascent_rate = float(rule.get("ascent_m_per_min", 10.0))
    thresholds = tank_reserve_thresholds(manufacturer, model)
    reserve = thresholds[0] if thresholds else 50.0
    history: List[tuple] = []  # (t, pressure, ambient)
    timeline = {}
    for wp in waypoints:
        t = float(getattr(wp, "time_since_start", 0) or 0)
        depth = _num(getattr(wp, "depth", None)) or 0.0
        pressure = _primary_pressure(wp)
        ambient = 1.0 + depth / 10.0
        if pressure is None:
            timeline[int(t)] = None
            continue
        history.append((t, pressure, ambient))
        while history and t - history[0][0] > window:
            history.pop(0)
        in_deco = bool(_num(getattr(wp, "deco_stop_depth", None)) or 0)
        if in_deco or not history or t - history[0][0] < window - 1e-6:
            timeline[int(t)] = None
            continue
        t0, p0, _ = history[0]
        minutes = (t - t0) / 60.0
        mean_ambient = sum(h[2] for h in history) / len(history)
        sac = (p0 - pressure) / minutes / mean_ambient if minutes > 0 else 0.0  # bar/min at 1 ATA
        if sac <= 0.05:
            timeline[int(t)] = None  # no measurable consumption yet
            continue
        ascent_minutes = depth / ascent_rate
        p_ascent = sac * ascent_minutes * (ambient + 1.0) / 2.0
        remaining = pressure - reserve - p_ascent
        timeline[int(t)] = int(max(0.0, remaining / (sac * ambient)) * 60)
    return timeline


def gas_time_remaining(manufacturer: Optional[str], model: Optional[str], waypoint: Any, waypoints: Optional[List[Any]]) -> Optional[int]:
    """Seconds of gas time remaining as the brand's `gas_time` rule defines
    it, or None (no rule, no history yet, in deco). Only the Shearwater GTR
    formula exists so far."""
    rule = get_rule_config(manufacturer, model, "gas_time")
    if not isinstance(rule, dict) or rule.get("formula") != "shearwater_gtr" or not waypoints or waypoint is None:
        return None
    timeline = _cached_timeline("gtr", manufacturer, model, waypoints, lambda: _build_gtr_timeline(manufacturer, model, waypoints, rule))
    return timeline.get(int(getattr(waypoint, "time_since_start", 0) or 0))
