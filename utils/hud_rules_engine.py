import json
from typing import Dict, Any, List, Optional, Tuple

from utils.resource_paths import find_resource

_rules_cache = None

def load_rules_json() -> Dict[str, Any]:
    global _rules_cache
    if _rules_cache is not None:
        return _rules_cache

    rules_name = "hud_rules.json"
    path = find_resource(rules_name, __file__)

    if path is not None:
        try:
            with open(path, 'r') as f:
                _rules_cache = json.load(f)
                return _rules_cache
        except Exception as e:
            print(f"Error loading rules from {path}: {e}")

    # Fallback to hardcoded default rules if file is missing
    print("Warning: Could not find hud_rules.json, using hardcoded default rules.")
    _rules_cache = {
        "default": {
            "ndl": [
                {"max": 10, "color": "#FF0000"},
                {"min": 10, "max": 30, "color": "#FFFF00"},
                {"min": 30, "color": "#FFFFFF"}
            ],
            "tank_pressure": [
                {"max": 60, "color": "#FF0000"},
                {"max": 70, "color": "#FFA500"}
            ],
            "tank_pressure_fill": [
                {"max": 50, "color": "#FF0000"},
                {"max": 70, "color": "#FFFF00"}
            ],
            "safety_stop": {
                "text": "SAFETY STOP",
                "color": "#FFFF00",
                "trigger_max_depth": 10.0,
                "min_depth": 3.0,
                "max_depth": 6.0
            },
            "badge_states": {
                "safety_stop": {"label": "STOP", "color": "#00FF00"},
                "deco": {"label": "DECO", "color": "#FFA500"}
            }
        }
    }
    return _rules_cache

def get_rule_config(manufacturer: Optional[str], model: Optional[str], rule_key: str) -> Any:
    rules = load_rules_json()
    
    # 1. Try finding rule in manufacturer -> model
    if manufacturer and manufacturer in rules:
        mfg_block = rules[manufacturer]
        if model and model in mfg_block:
            model_block = mfg_block[model]
            if isinstance(model_block, dict) and rule_key in model_block:
                return model_block[rule_key]
        
        # 2. Try finding rule directly under manufacturer
        if rule_key in mfg_block:
            return mfg_block[rule_key]
            
        # 3. Try finding rule under manufacturer -> default
        if "default" in mfg_block:
            mfg_default = mfg_block["default"]
            if isinstance(mfg_default, dict) and rule_key in mfg_default:
                return mfg_default[rule_key]
                
    # 4. Try finding rule in global default
    global_default = rules.get("default", {})
    if rule_key in global_default:
        return global_default[rule_key]
        
    return None

def get_dynamic_color(manufacturer: Optional[str], model: Optional[str], field: str, value: Any, default_color: str) -> str:
    if value is None:
        return default_color

    # Normalize field name to match JSON keys
    rule_key = None
    if field in ("ndl", "ndl_before_clear"):
        rule_key = "ndl"
    elif field in ("primary_tank_pressure", "secondary_tank_pressure") or field.startswith("tank_pressure:"):
        rule_key = "tank_pressure"
    elif field in ("po2", "po2_1", "po2_2", "po2_3"):
        rule_key = "po2"
    elif field == "safety_stop":
        rule_key = "safety_stop"
        
    if not rule_key:
        return default_color

    config = get_rule_config(manufacturer, model, rule_key)
    if not config:
        return default_color
        
    if rule_key == "safety_stop":
        if isinstance(config, dict):
            return config.get("color", "#FFFF00")
        return "#FFFF00"

    rules_list = config
    if not isinstance(rules_list, list):
        return default_color
        
    if rule_key == "ndl":
        try:
            val_mins = float(value) / 60.0
            # NDL <= 0 means no time remaining - actively in deco, not "safe" -
            # distinct from the >= 99 (unlimited/surface) case below, which
            # legitimately is safe. Only manufacturers with a configured
            # "ndl_zero" color get this distinction; others keep the prior
            # (>=99-style) fallback so this is additive, not a behavior change,
            # for anyone without it configured.
            if val_mins <= 0:
                zero_color = get_rule_config(manufacturer, model, "ndl_zero")
                if zero_color:
                    return zero_color
                for rule in rules_list:
                    if rule.get("min", 0) >= 30:
                        return rule["color"]
                return default_color

            # >= 99 indicates unlimited NDL (displayed as "99+") - genuinely safe
            if val_mins >= 99:
                for rule in rules_list:
                    if rule.get("min", 0) >= 30:
                        return rule["color"]
                return default_color

            for rule in rules_list:
                match = True
                if "min" in rule and val_mins < rule["min"]:
                    match = False
                if "max" in rule and val_mins >= rule["max"]:
                    match = False
                if match:
                    return rule["color"]
        except (ValueError, TypeError):
            pass
            
    elif rule_key == "tank_pressure":
        try:
            val_bar = float(value)
            for rule in rules_list:
                match = True
                if "min" in rule and val_bar < rule["min"]:
                    match = False
                if "max" in rule and val_bar >= rule["max"]:
                    match = False
                if match:
                    return rule["color"]
        except (ValueError, TypeError):
            pass

    elif rule_key == "po2":
        try:
            val_bar = float(value)
            for rule in rules_list:
                match = True
                if "min" in rule and val_bar < rule["min"]:
                    match = False
                if "max" in rule and val_bar >= rule["max"]:
                    match = False
                if match:
                    return rule["color"]
        except (ValueError, TypeError):
            pass

    return default_color

def get_safety_stop_text(manufacturer: Optional[str], model: Optional[str], waypoint: Any) -> str:
    if waypoint is None:
        return ""
        
    safety_stop_config = get_rule_config(manufacturer, model, "safety_stop")
    if not safety_stop_config or not isinstance(safety_stop_config, dict):
        return ""
        
    trigger_max_depth = safety_stop_config.get("trigger_max_depth", 10.0)
    min_depth = safety_stop_config.get("min_depth", 3.0)
    max_depth = safety_stop_config.get("max_depth", 6.0)
    text = safety_stop_config.get("text", "SAFETY STOP")
    
    max_depth_reached = getattr(waypoint, "max_depth", 0.0) or 0.0
    current_depth = getattr(waypoint, "depth", 0.0) or 0.0
    
    if max_depth_reached >= trigger_max_depth and min_depth <= current_depth <= max_depth:
        return text

    return ""

# Dive-alert event names (Garmin FIT event_mesgs "dive_alert" field, confirmed against a
# real log - see rework_hud.md) that resolve_state() trusts as a direct state signal,
# ahead of the depth-band heuristic below.
_DECO_ALERTS = {"deco_ceiling_broken", "approaching_first_deco_stop"}
# Garmin's own direct "clear" signal - confirmed against a real mk3i FIT log
# (submersion_dives/005_oc-trimix-two-deco-gases.fit). A different mechanism
# than Shearwater's depth-margin heuristic (is_clearing_deco_stop) below, but
# resolves to the same "clear" state name - see shearwater_rework.md's scope
# note on keeping the two manufacturers' rules independent.
_DECO_CLEARED_ALERTS = {"deco_stop_cleared"}
_DECO_COMPLETE_ALERTS = {"deco_complete"}
_SAFETY_STOP_START_ALERTS = {"safety_stop_started"}
_SAFETY_STOP_END_ALERTS = {"safety_stop_complete"}

def _num(value: Any) -> Optional[float]:
    """A real number or None - waypoint attributes may be missing, None or
    (in tests) mocks."""
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def deco_stop_phase(manufacturer: Optional[str], model: Optional[str], waypoint: Any) -> Optional[str]:
    """Where the diver is relative to a mandatory deco stop, for computers
    with a `deco_stop` rule (Perdix 2 manual p.28): 'far' (deeper than the
    approach margin), 'approach' (within `approach_m` above... i.e. deeper
    than the stop by at most approach_m - the title turns yellow and the
    up-arrow flashes), 'at_stop' (at the stop or up to `at_stop_m` deeper -
    green title with a check mark) or 'violation' (shallower than the
    stop - red flashing). None outside deco or without the rule."""
    if waypoint is None:
        return None
    rule = get_rule_config(manufacturer, model, "deco_stop")
    if not isinstance(rule, dict):
        return None
    stop = _num(getattr(waypoint, "next_stop_depth", None)) or _num(getattr(waypoint, "deco_stop_depth", None))
    depth = _num(getattr(waypoint, "depth", None))
    if not stop or stop <= 0 or depth is None:
        return None
    above = depth - stop  # positive = deeper than the stop
    if above < 0:
        return "violation"
    if above <= float(rule.get("at_stop_m", 1.5)):
        return "at_stop"
    if above <= float(rule.get("approach_m", 5.1)):
        return "approach"
    return "far"


def sidemount_switch_target(manufacturer: Optional[str], model: Optional[str], waypoint: Any) -> Optional[str]:
    """'primary' or 'secondary' - the tank to breathe from when the two
    sidemount tanks differ by more than the manufacturer's `sidemount_switch`
    threshold (Perdix 2 manual p.42, "Sidemount Tank Switch Notifications":
    a green box highlights that tank's label). None without the rule, a
    second tank, or a difference within the threshold."""
    if waypoint is None:
        return None
    rule = get_rule_config(manufacturer, model, "sidemount_switch")
    if not isinstance(rule, dict):
        return None
    tanks = list((getattr(waypoint, "tanks", None) or {}).values())
    if len(tanks) < 2:
        return None
    p1, p2 = _num(getattr(tanks[0], "pressure_bar", None)), _num(getattr(tanks[1], "pressure_bar", None))
    if p1 is None or p2 is None:
        return None
    threshold = float(rule.get("threshold_bar", 21.0))
    if p2 - p1 > threshold:
        return "secondary"
    if p1 - p2 > threshold:
        return "primary"
    return None


def ceiling_broken(manufacturer: Optional[str], model: Optional[str], waypoint: Any) -> bool:
    """True while the diver is more than the manufacturer's `ceiling_broken`
    margin above a mandatory deco stop (Descent Mk3 manual p.10: ascend
    more than 0.6 m above the ceiling and the depth and ceiling flash red
    until back within it). Only manufacturers with a `ceiling_broken` rule
    ever report it."""
    if waypoint is None:
        return False
    rule = get_rule_config(manufacturer, model, "ceiling_broken")
    if not isinstance(rule, dict):
        return False
    ceiling = getattr(waypoint, "deco_stop_depth", None) or getattr(waypoint, "next_stop_depth", None)
    depth = getattr(waypoint, "depth", None)
    if not ceiling or ceiling <= 0 or depth is None:
        return False
    return depth < ceiling - float(rule.get("margin", 0.6))


def ceiling_broken_color(manufacturer: Optional[str], model: Optional[str]) -> str:
    rule = get_rule_config(manufacturer, model, "ceiling_broken")
    return rule.get("color", "#FF0000") if isinstance(rule, dict) else "#FF0000"


# Per-dive timelines, cached per waypoint list. Holding the list keeps its
# id from being reused by a later dive of the same length (a re-saved plan,
# a test's identical profile) while the entry is cached.
_timeline_cache: Dict[Any, Tuple[List[Any], Any]] = {}


def _cached_timeline(kind: str, manufacturer: Optional[str], model: Optional[str], waypoints: List[Any], build) -> Any:
    key = (kind, id(waypoints), len(waypoints), manufacturer, model)
    cached = _timeline_cache.get(key)
    if cached is not None and cached[0] is waypoints:
        return cached[1]
    result = build()
    if len(_timeline_cache) > 24:
        _timeline_cache.clear()
    _timeline_cache[key] = (waypoints, result)
    return result


def _in_deco(manufacturer: Optional[str], model: Optional[str], wp: Any) -> bool:
    alerts = set(getattr(wp, "dive_alerts", None) or [])
    if alerts & _DECO_COMPLETE_ALERTS:
        return False
    if alerts & (_DECO_CLEARED_ALERTS | _DECO_ALERTS):
        return True
    return bool(_num(getattr(wp, "deco_stop_depth", None)) or 0)


# Safety-stop phases a timeline reports: None = nothing shown.
SS_PENDING, SS_COUNTING, SS_PAUSED, SS_COMPLETE = "pending", "counting", "paused", "complete"


def _garmin_safety_timeline(cfg: Dict[str, Any], manufacturer, model, waypoints) -> Dict[int, Tuple[Optional[str], int]]:
    """Garmin Descent (X50i manual, "Performing a Safety Stop"): after a
    dive deeper than trigger_max_depth the stop is armed; its timer starts
    once within `start_window` m of `stop_depth`, pauses while more than
    `pause_above` m above it, and the whole stop resets when descending
    below trigger_max_depth. Mandatory deco ends the safety stop for good:
    a Descent asks for none after deco (confirmed against the real Mk3i
    log test_data/logs/submersion_dives/005_oc-trimix-two-deco-gases.fit -
    no safety_stop_started after its deco_complete even though the diver
    then hung at 6 m). Surfacing (shallower than min_depth) after the timer
    started ends it too, rather than flickering the box as the depth bobs
    around the threshold. The computer's own safety_stop_started /
    safety_stop_complete alerts (FIT dive_alerts) override the depth rules
    where present, so a real log renders exactly what the computer showed.
    Only 'counting' is ever reported - the Descent shows nothing before or
    after the countdown."""
    duration = int(cfg["duration_sec"])
    trigger = float(cfg.get("trigger_max_depth", 11.0))
    stop_depth = float(cfg.get("stop_depth", 5.0))
    start_window = float(cfg.get("start_window", 1.0))
    pause_above = float(cfg.get("pause_above", 3.0))
    surface = float(cfg.get("min_depth", 1.2))

    timeline: Dict[int, Tuple[Optional[str], int]] = {}
    armed, started, left, prev_t, had_deco = False, False, duration, None, False
    for wp in waypoints:
        t = getattr(wp, "time_since_start", 0) or 0
        depth = getattr(wp, "depth", 0.0) or 0.0
        dt = 0 if prev_t is None else max(0, t - prev_t)
        prev_t = t
        if _in_deco(manufacturer, model, wp):
            had_deco = True
        if depth > trigger or had_deco:
            armed = (getattr(wp, "max_depth", 0.0) or 0.0) >= trigger and not had_deco
            started, left = False, duration
            timeline[t] = (None, left)
            continue
        if not armed and (getattr(wp, "max_depth", 0.0) or 0.0) >= trigger:
            armed = True
        alerts = set(getattr(wp, "dive_alerts", None) or [])
        if alerts & _SAFETY_STOP_START_ALERTS:
            armed, started, left = True, True, duration
        if armed and left > 0:
            if started and depth < surface:
                left = 0  # surfaced - the stop is over, whatever was left
            elif not started and abs(depth - stop_depth) <= start_window:
                started = True
            if started and left > 0 and depth >= stop_depth - pause_above:
                left = max(0, left - dt)
        if alerts & _SAFETY_STOP_END_ALERTS:
            left = 0
        timeline[t] = (SS_COUNTING if armed and started and left > 0 else None, left)
    return timeline


def _shearwater_safety_timeline(cfg: Dict[str, Any], manufacturer, model, waypoints) -> Dict[int, Tuple[Optional[str], int]]:
    """Shearwater (Perdix 2 manual p.27, "Safety stops behave as follows"):
    once the depth exceeds trigger_max_depth (11 m) the counter appears
    showing the planned time ('pending'); the countdown begins once
    shallower than `start_below` (6 m) and runs while the depth stays
    inside `count_range` (2.4-8.3 m), 'paused' outside it (time in
    yellow); 'complete' once it reaches zero. Adapt (`adapt`): the planned
    time becomes adapt.duration_sec (5:00) once the dive goes deeper than
    adapt.deep_m or the NDL drops under adapt.low_ndl_sec. Mandatory deco
    replaces the safety stop and, once cleared, the deco-clear counter
    takes its place (p.28) - nothing here after deco."""
    duration = int(cfg.get("duration_sec", 180))
    trigger = float(cfg.get("trigger_max_depth", 11.0))
    start_below = float(cfg.get("start_below", 6.0))
    lo, hi = cfg.get("count_range", [2.4, 8.3])
    lo, hi = float(lo), float(hi)
    adapt = cfg.get("adapt") if isinstance(cfg.get("adapt"), dict) else None

    timeline: Dict[int, Tuple[Optional[str], int]] = {}
    armed, started, planned, left, prev_t, had_deco = False, False, duration, duration, None, False
    for wp in waypoints:
        t = getattr(wp, "time_since_start", 0) or 0
        depth = getattr(wp, "depth", 0.0) or 0.0
        dt = 0 if prev_t is None else max(0, t - prev_t)
        prev_t = t
        if _in_deco(manufacturer, model, wp):
            had_deco = True
        if had_deco:
            timeline[t] = (None, 0)
            continue
        max_depth = getattr(wp, "max_depth", 0.0) or 0.0
        if not armed and max(max_depth, depth) > trigger:
            armed = True
        elif armed and depth > trigger and (started or left < planned):
            started, left = False, planned  # "Countdown Reset": deeper than 11 m again (Teric manual p.25)
        if adapt and not started and planned != int(adapt.get("duration_sec", 300)):
            ndl = _num(getattr(wp, "ndl", None))
            if max(max_depth, depth) > float(adapt.get("deep_m", 30.0)) or (
                ndl is not None and 0 < ndl < int(adapt.get("low_ndl_sec", 300))
            ):
                planned = left = int(adapt.get("duration_sec", 300))
        if not armed:
            timeline[t] = (None, planned)
            continue
        if not started:
            if depth < start_below:
                started = True
            else:
                timeline[t] = (SS_PENDING, planned)
                continue
        if left <= 0:
            timeline[t] = (SS_COMPLETE, 0)
            continue
        if lo <= depth <= hi:
            left = max(0, left - dt)
            timeline[t] = (SS_COMPLETE if left == 0 else SS_COUNTING, left)
        else:
            timeline[t] = (SS_PAUSED, left)
    return timeline


def safety_stop_timeline(manufacturer: Optional[str], model: Optional[str], waypoints: Optional[List[Any]]) -> Optional[Dict[int, Tuple[Optional[str], int]]]:
    """{time_since_start: (phase, seconds_left)} for the whole dive, from
    the manufacturer's `safety_stop` rule - the Shearwater dialect when it
    has `start_below`, the Garmin one when it has `stop_depth` /
    `duration_sec` (see the two builders above). None when the rule has no
    timer or there are no waypoints."""
    if not waypoints:
        return None
    cfg = get_rule_config(manufacturer, model, "safety_stop")
    if not isinstance(cfg, dict):
        return None
    if "start_below" in cfg:
        return _cached_timeline("ss", manufacturer, model, waypoints,
                                lambda: _shearwater_safety_timeline(cfg, manufacturer, model, waypoints))
    if cfg.get("duration_sec"):
        return _cached_timeline("ss", manufacturer, model, waypoints,
                                lambda: _garmin_safety_timeline(cfg, manufacturer, model, waypoints))
    return None


def safety_stop_phase(manufacturer: Optional[str], model: Optional[str], waypoint: Any, waypoints: Optional[List[Any]]) -> Optional[Tuple[Optional[str], int]]:
    """(phase, seconds_left) at this waypoint, or None when no timeline
    applies. phase None = nothing to show at this waypoint."""
    timeline = safety_stop_timeline(manufacturer, model, waypoints)
    if timeline is None or waypoint is None:
        return None
    return timeline.get(getattr(waypoint, "time_since_start", None))


def safety_stop_status(manufacturer: Optional[str], model: Optional[str], waypoint: Any, waypoints: Optional[List[Any]]) -> Optional[Tuple[bool, int]]:
    """(counting, seconds_left) - the Garmin-style view of safety_stop_phase."""
    phase = safety_stop_phase(manufacturer, model, waypoint, waypoints)
    if phase is None:
        return None
    return phase[0] == SS_COUNTING, phase[1]


def deco_clear_timeline(manufacturer: Optional[str], model: Optional[str], waypoints: Optional[List[Any]]) -> Optional[Dict[int, int]]:
    """{time_since_start: seconds since the last deco stop cleared} for
    every waypoint after a deco run, for computers with a `deco_clear`
    rule (Perdix 2 manual p.28: the deco-clear counter counts up from zero
    once all decompression obligation is cleared). A later deco run
    restarts it. None without the rule or waypoints."""
    if not waypoints:
        return None
    rule = get_rule_config(manufacturer, model, "deco_clear")
    if not isinstance(rule, dict):
        return None

    def build():
        timeline: Dict[int, int] = {}
        cleared_at: Optional[int] = None
        was_in_deco = False
        for wp in waypoints:
            t = getattr(wp, "time_since_start", 0) or 0
            in_deco = _in_deco(manufacturer, model, wp)
            if in_deco:
                cleared_at = None
                was_in_deco = True
            elif was_in_deco and cleared_at is None:
                cleared_at = t
            if cleared_at is not None and (getattr(wp, "depth", 0.0) or 0.0) > 0:
                timeline[t] = t - cleared_at
        return timeline

    return _cached_timeline("dc", manufacturer, model, waypoints, build)


def deco_clear_seconds(manufacturer: Optional[str], model: Optional[str], waypoint: Any, waypoints: Optional[List[Any]]) -> Optional[int]:
    timeline = deco_clear_timeline(manufacturer, model, waypoints)
    if timeline is None or waypoint is None:
        return None
    return timeline.get(getattr(waypoint, "time_since_start", None))


def resolve_state(manufacturer: Optional[str], model: Optional[str], waypoint: Any, waypoints: Optional[List[Any]] = None) -> str:
    """Resolves the current HUD state - 'deco', 'clear', 'safety_stop', or
    'normal' - for one waypoint. 'deco' is any mandatory deco obligation;
    'clear' is deco done: on Garmin the computer's own deco_stop_cleared
    alert (one waypoint), on Shearwater the deco-clear counter that runs
    from the last stop to the surface (deco_clear_timeline); 'safety_stop'
    follows the manufacturer's safety_stop timeline (a Perdix shows the
    counter from 11 m on, a Descent only while it counts) or, without the
    whole dive at hand, the depth band of get_safety_stop_text. Prefers the
    waypoint's own dive_alerts (Garmin FIT event_mesgs) where present.
    Where the deco stop sits relative to the diver (approach / at stop /
    violation) is not a state but deco_stop_phase()."""
    if waypoint is None:
        return "normal"

    alerts = set(getattr(waypoint, "dive_alerts", None) or [])
    # deco_complete checked first: clearing the *last* stop fires both
    # deco_stop_cleared and deco_complete in the same window (confirmed
    # against the real mk3i log), and "fully done" is the more specific,
    # final signal of the two.
    if alerts & _DECO_COMPLETE_ALERTS:
        return "normal"
    if alerts & _DECO_CLEARED_ALERTS:
        return "clear"
    if alerts & _DECO_ALERTS:
        return "deco"
    if alerts & _SAFETY_STOP_START_ALERTS:
        return "safety_stop"
    if alerts & _SAFETY_STOP_END_ALERTS:
        return "normal"

    deco_depth = _num(getattr(waypoint, "deco_stop_depth", None))
    if deco_depth is not None and deco_depth > 0:
        return "deco"

    if deco_clear_seconds(manufacturer, model, waypoint, waypoints) is not None:
        return "clear"

    # With the whole dive at hand, a timed safety stop knows when the stop
    # is pending, counting or done - the depth band alone would keep showing it.
    phase = safety_stop_phase(manufacturer, model, waypoint, waypoints)
    if phase is not None:
        return "safety_stop" if phase[0] is not None else "normal"

    if get_safety_stop_text(manufacturer, model, waypoint):
        return "safety_stop"

    return "normal"


def stop_phase(manufacturer: Optional[str], model: Optional[str], waypoint: Any, waypoints: Optional[List[Any]] = None) -> Tuple[str, Optional[str], Optional[int], Optional[float]]:
    """(state, phase, seconds, stop_depth) - everything a stop badge needs:
    the resolved state; its phase (safety stop: pending/counting/paused/
    complete, deco: far/approach/at_stop/violation, clear: 'clear'; None
    when the manufacturer's rules don't distinguish); the seconds to show
    (time left on a safety or deco stop, time elapsed on a deco-clear
    count-up); and the stop depth (None for a Shearwater safety stop, which
    names no depth)."""
    state = resolve_state(manufacturer, model, waypoint, waypoints)
    if state == "normal" or waypoint is None:
        return state, None, None, None
    if state == "safety_stop":
        phase = safety_stop_phase(manufacturer, model, waypoint, waypoints)
        cfg = get_rule_config(manufacturer, model, "safety_stop")
        cfg = cfg if isinstance(cfg, dict) else {}
        if phase is not None and phase[0] is not None:
            depth = None if "start_below" in cfg else float(cfg.get("stop_depth", 5.0))
            return state, phase[0], phase[1], depth
        # alert-driven or depth-band safety stop without a timeline
        return state, SS_COUNTING, getattr(waypoint, "next_stop_time", None), getattr(waypoint, "next_stop_depth", None) or cfg.get("stop_depth")
    if state == "clear":
        elapsed = deco_clear_seconds(manufacturer, model, waypoint, waypoints)
        if elapsed is not None:
            return state, "clear", elapsed, None
        return state, "clear", getattr(waypoint, "next_stop_time", None), getattr(waypoint, "next_stop_depth", None)
    return state, deco_stop_phase(manufacturer, model, waypoint), getattr(waypoint, "next_stop_time", None), getattr(waypoint, "next_stop_depth", None)


def get_ndl_before_clear(manufacturer: Optional[str], model: Optional[str], waypoint: Any, waypoints: Optional[List[Any]]) -> Optional[int]:
    """NDL (seconds) frozen at the moment a deco stop's 'clear' countdown
    began - Phase 2 item 4 of shearwater_rework.md. `ndl` is None for the
    entire deco+clear run (a diver in mandatory deco has no NDL), so the
    last non-None `ndl` found scanning backward from the current waypoint is
    exactly the value from just before deco started - and it stays that same
    value for every waypoint in the run, which *is* the 'frozen' semantics,
    with no separate transition-detection needed. Only returns a value while
    the waypoint's resolved state is 'clear' (not 'deco' - the plan calls for
    the clear countdown specifically); returns None otherwise so a
    linked_element placed on top of the always-rendered `ndl` field only
    shows this during 'clear', without a design decision on how they'd look
    stacked at any other time."""
    if waypoint is None or not waypoints:
        return None
    if resolve_state(manufacturer, model, waypoint) != "clear":
        return None

    current_time = getattr(waypoint, "time_since_start", None)
    if current_time is None:
        return None

    last_ndl = None
    for wp in waypoints:
        wp_time = getattr(wp, "time_since_start", None)
        if wp_time is None or wp_time > current_time:
            break
        wp_ndl = getattr(wp, "ndl", None)
        if wp_ndl is not None:
            last_ndl = wp_ndl
    return last_ndl

def get_badge_config(manufacturer: Optional[str], model: Optional[str], state: str) -> Optional[Dict[str, Any]]:
    """Label/color (and optional blink_depth flag) for a resolved 'safety_stop'/'deco'/
    'clear' state's badge, from hud_rules.json's badge_states block - same
    manufacturer -> model -> default hierarchy as get_rule_config(). Returns None for
    'normal' (no badge) or when no config is defined for that state."""
    if state not in ("safety_stop", "deco", "clear"):
        return None
    rules = load_rules_json()
    brand = rules.get(manufacturer) if manufacturer else None
    brand = brand if isinstance(brand, dict) else {}
    merged: Dict[str, Any] = {}
    found = False
    # Brand-level entry first, then the model's own entry layered on top (a
    # key set to null removes it) - so a Teric only says what differs from
    # the Perdix family: "SAFETY" for "SAFETY STOP", no check mark.
    for block in (rules.get("default", {}), brand.get("default", {}), brand, brand.get(model, {}) if model else {}):
        states = block.get("badge_states") if isinstance(block, dict) else None
        cfg = states.get(state) if isinstance(states, dict) else None
        if isinstance(cfg, dict):
            found = True
            for key, value in cfg.items():
                if value is None:
                    merged.pop(key, None)
                else:
                    merged[key] = value
    return merged if found else None

def resolve_blink_color(base_color: str, blink_color: str, elapsed_seconds: Optional[float], period: float = 1.0) -> str:
    """Time-based color toggle for 'flashing' HUD elements (e.g. depth/ceiling flashing
    red until within the safe margin - see rework_hud.md). Driven by dive-elapsed time
    (waypoint.dive_time/time_since_start), not wall-clock, so the blink phase is
    deterministic per waypoint and stays in sync across a rendered video regardless of
    how fast rendering runs."""
    if not elapsed_seconds or period <= 0:
        elapsed_seconds = 0.0
    phase = (elapsed_seconds % period) / period
    return blink_color if phase < 0.5 else base_color

def get_tank_fill_color(manufacturer: Optional[str], model: Optional[str], value: Any) -> Optional[str]:
    """Solid fill color for a tank-pressure icon (a status indicator, not the
    tank_pressure text-color rule's 'only recolor when low' behavior - this always
    returns a color): red below the low band, yellow in the warning band, green
    otherwise, from hud_rules.json's tank_pressure_fill bands. Returns None when
    value is None (no reading yet - draw no fill at all) or bands aren't configured."""
    if value is None:
        return None
    bands = get_rule_config(manufacturer, model, "tank_pressure_fill")
    if not isinstance(bands, list):
        return None
    try:
        val_bar = float(value)
    except (ValueError, TypeError):
        return None
    for band in bands:
        match = True
        if "min" in band and val_bar < band["min"]:
            match = False
        if "max" in band and val_bar >= band["max"]:
            match = False
        if match:
            return band["color"]
    return "#00FF00"

def resolve_tank_variant(dive: Any) -> str:
    """'single_tank' vs 'sidemount' page variant, resolved once for the whole dive from
    its logged tank count (2+ unique tanks -> sidemount), not a per-frame rule and not
    an end-user choice - see rework_hud.md's 'Independent axes above the base page'."""
    waypoints = getattr(dive, "waypoints", None) if dive is not None else None
    if not waypoints:
        return "single_tank"
    unique_tanks: set = set()
    for wp in waypoints:
        unique_tanks.update(wp.tanks.keys())
    return "sidemount" if len(unique_tanks) >= 2 else "single_tank"
