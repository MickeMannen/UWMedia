import json
from typing import Dict, Any, List, Optional

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

def is_clearing_deco_stop(manufacturer: Optional[str], model: Optional[str], waypoint: Any) -> bool:
    """True while ascending into a deco stop and just shy of reaching it - within
    the manufacturer's configured 'clear' margin, but not yet at or past it:
    0 < (deco_stop_depth - depth) < margin. Shearwater's own real threshold is
    1.0m; manufacturers without a 'clear' config never report this (margin
    defaults to 0, which no positive distance is ever less than)."""
    deco_depth = getattr(waypoint, "deco_stop_depth", None) if waypoint is not None else None
    if not deco_depth or deco_depth <= 0:
        return False
    current_depth = getattr(waypoint, "depth", None)
    if current_depth is None:
        return False
    clear_config = get_rule_config(manufacturer, model, "clear")
    margin = clear_config.get("margin", 0.0) if isinstance(clear_config, dict) else 0.0
    distance = deco_depth - current_depth
    return 0 < distance < margin

def resolve_state(manufacturer: Optional[str], model: Optional[str], waypoint: Any) -> str:
    """Resolves the current HUD state - 'deco', 'clear', 'safety_stop', or 'normal' -
    for one waypoint, deco -> clear -> safety_stop -> normal priority ('clear' is a
    refinement of 'deco': still ascending into a deco stop, but within the
    manufacturer's 'clear' margin of reaching it - see is_clearing_deco_stop).
    Prefers the waypoint's own dive_alerts (populated from Garmin FIT event_mesgs
    where available) as the signal; falls back to the depth-band heuristic
    (deco_stop_depth / the safety_stop rule bands already used by
    get_safety_stop_text) for sources that don't carry alert events, e.g.
    Subsurface/UDDF."""
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
        return "clear" if is_clearing_deco_stop(manufacturer, model, waypoint) else "deco"
    if alerts & _SAFETY_STOP_START_ALERTS:
        return "safety_stop"
    if alerts & _SAFETY_STOP_END_ALERTS:
        return "normal"

    deco_depth = getattr(waypoint, "deco_stop_depth", None)
    if deco_depth is not None and deco_depth > 0:
        return "clear" if is_clearing_deco_stop(manufacturer, model, waypoint) else "deco"

    if get_safety_stop_text(manufacturer, model, waypoint):
        return "safety_stop"

    return "normal"

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
    states_config = get_rule_config(manufacturer, model, "badge_states")
    if not isinstance(states_config, dict):
        return None
    cfg = states_config.get(state)
    return cfg if isinstance(cfg, dict) else None

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
