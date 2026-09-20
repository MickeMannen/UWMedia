import pytest
from unittest.mock import MagicMock
from utils.hud_rules_engine import (
    get_dynamic_color,
    get_safety_stop_text,
    get_rule_config,
    resolve_state,
    get_badge_config,
    resolve_blink_color,
    resolve_tank_variant,
    get_tank_fill_color,
    is_clearing_deco_stop,
    get_ndl_before_clear,
)

def test_rules_loading_and_hierarchical_fallback():
    # 1. Exact model-level override check (Shearwater Perdix 2 has its own tank_pressure)
    perdix_tp = get_rule_config("Shearwater", "Perdix 2", "tank_pressure")
    assert perdix_tp is not None

    # 2. Manufacturer-level fallback (Shearwater has ndl, but Perdix 2's block doesn't)
    perdix_ndl = get_rule_config("Shearwater", "Perdix 2", "ndl")
    assert perdix_ndl is not None
    
    # 3. Global fallback (Shearwater has no generic tank_pressure, nor does a generic model, so fallback to default)
    fallback_tp = get_rule_config("Shearwater", "UnknownModel", "tank_pressure")
    assert fallback_tp is not None
    assert isinstance(fallback_tp, list)
    
    # 4. Unknown manufacturer completely falls back to default
    unknown_ndl = get_rule_config("UnknownMfg", "Model", "ndl")
    assert unknown_ndl is not None

    # 5. Generic manufacturer with empty model falls back to default
    generic_ndl = get_rule_config("Generic", "", "ndl")
    assert generic_ndl is not None

def test_ndl_dynamic_colors():
    # 0 seconds = no NDL time left, actively in deco - Shearwater has a
    # dedicated "ndl_zero" color for this, distinct from the safe/unlimited
    # case below (was incorrectly sharing the white "safe" color before)
    assert get_dynamic_color("Shearwater", "Perdix 2", "ndl", 0, "#FFFFFF") == "#FF0000"

    # Manufacturers without a configured "ndl_zero" keep the prior behavior:
    # NDL=0 falls back to the same color as unlimited/safe (>=30 min tier)
    assert get_dynamic_color("Garmin", "x50i", "ndl", 0, "#FFFFFF") == "#FFFFFF"

    # 35 minutes = 2100 seconds (above 30, genuinely unlimited/safe) -> #FFFFFF
    assert get_dynamic_color("Shearwater", "Perdix 2", "ndl", 2100, "#BLUE") == "#FFFFFF"

    # 20 minutes = 1200 seconds (10 to 30) -> #FFFF00
    assert get_dynamic_color("Shearwater", "Perdix 2", "ndl", 1200, "#BLUE") == "#FFFF00"

    # 5 minutes = 300 seconds (below 10) -> #FF0000
    assert get_dynamic_color("Shearwater", "Perdix 2", "ndl", 300, "#BLUE") == "#FF0000"

def test_po2_dynamic_colors():
    # Standard high-PPO2 alarm threshold (1.6 bar) - Shearwater-configured
    assert get_dynamic_color("Shearwater", "Perdix 2", "po2", 1.3, "#FFFFFF") == "#FFFFFF"
    assert get_dynamic_color("Shearwater", "Perdix 2", "po2", 1.6, "#FFFFFF") == "#FF0000"
    assert get_dynamic_color("Shearwater", "Perdix 2", "po2", 1.8, "#FFFFFF") == "#FF0000"
    # Same band applies to each CCR cell field
    assert get_dynamic_color("Shearwater", "Perdix 2", "po2_1", 1.7, "#FFFFFF") == "#FF0000"
    assert get_dynamic_color("Shearwater", "Perdix 2", "po2_2", 1.7, "#FFFFFF") == "#FF0000"
    assert get_dynamic_color("Shearwater", "Perdix 2", "po2_3", 1.7, "#FFFFFF") == "#FF0000"

def test_garmin_po2_dynamic_colors_are_two_tier_and_independent_of_shearwater():
    # Real Garmin dive_settings_mesgs thresholds (po2_warn=1.4, po2_critical=1.6),
    # confirmed against a real mk3i FIT log - deliberately a separate,
    # two-tier hud_rules.json entry from Shearwater's single 1.6 band
    assert get_dynamic_color("Garmin", "x50i", "po2", 1.3, "#FFFFFF") == "#FFFFFF"
    assert get_dynamic_color("Garmin", "x50i", "po2", 1.4, "#FFFFFF") == "#FFFF00"
    assert get_dynamic_color("Garmin", "x50i", "po2", 1.5, "#FFFFFF") == "#FFFF00"
    assert get_dynamic_color("Garmin", "x50i", "po2", 1.6, "#FFFFFF") == "#FF0000"
    assert get_dynamic_color("Garmin", "x50i", "po2", 1.8, "#FFFFFF") == "#FF0000"

def test_tank_pressure_dynamic_colors():
    # 150 bar -> default_color
    assert get_dynamic_color("Shearwater", "Perdix 2", "primary_tank_pressure", 150, "#BLUE") == "#BLUE"
    
    # 65 bar (below 70, but not below 60) -> #FFA500
    assert get_dynamic_color("Shearwater", "Perdix 2", "primary_tank_pressure", 65, "#BLUE") == "#FFA500"
    
    # 50 bar (below 60) -> #FF0000
    assert get_dynamic_color("Shearwater", "Perdix 2", "primary_tank_pressure", 50, "#BLUE") == "#FF0000"

def test_secondary_tank_pressure_dynamic_colors():
    # secondary_tank_pressure (sidemount's second cylinder) follows the same
    # tank_pressure rule bands as primary_tank_pressure
    assert get_dynamic_color("Shearwater", "Perdix 2", "secondary_tank_pressure", 150, "#BLUE") == "#BLUE"
    assert get_dynamic_color("Shearwater", "Perdix 2", "secondary_tank_pressure", 65, "#BLUE") == "#FFA500"
    assert get_dynamic_color("Shearwater", "Perdix 2", "secondary_tank_pressure", 50, "#BLUE") == "#FF0000"

def test_safety_stop_text():
    wp_no_trigger = MagicMock()
    wp_no_trigger.max_depth = 5.0
    wp_no_trigger.depth = 5.0
    assert get_safety_stop_text("Shearwater", "Perdix 2", wp_no_trigger) == ""
    
    wp_triggered_and_in_range = MagicMock()
    wp_triggered_and_in_range.max_depth = 12.0
    wp_triggered_and_in_range.depth = 5.0
    assert get_safety_stop_text("Shearwater", "Perdix 2", wp_triggered_and_in_range) == "SAFETY STOP"

def _wp(**kwargs):
    wp = MagicMock()
    wp.dive_alerts = []
    wp.deco_stop_depth = 0.0
    wp.max_depth = 0.0
    wp.depth = 0.0
    for key, value in kwargs.items():
        setattr(wp, key, value)
    return wp

def test_resolve_state_priority_and_fallback():
    # Deco alert event wins outright, even with a low-ish deco_stop_depth
    assert resolve_state("Garmin", "x50i", _wp(dive_alerts=["approaching_first_deco_stop"])) == "deco"
    assert resolve_state("Garmin", "x50i", _wp(dive_alerts=["deco_ceiling_broken"])) == "deco"

    # safety_stop_started/complete alerts
    assert resolve_state("Garmin", "x50i", _wp(dive_alerts=["safety_stop_started"])) == "safety_stop"
    assert resolve_state("Garmin", "x50i", _wp(dive_alerts=["safety_stop_complete"])) == "normal"

    # No alert events -> falls back to the depth-band heuristic
    assert resolve_state("Garmin", "x50i", _wp(deco_stop_depth=6.0)) == "deco"
    assert resolve_state(
        "Shearwater", "Perdix 2", _wp(max_depth=12.0, depth=5.0)
    ) == "safety_stop"
    assert resolve_state("Shearwater", "Perdix 2", _wp()) == "normal"

    assert resolve_state("Garmin", "x50i", None) == "normal"

def test_resolve_state_garmin_deco_cleared_and_complete_alerts():
    # Garmin's own direct "clear"/"complete" signals (confirmed against a
    # real mk3i FIT log), independent of Shearwater's depth-margin heuristic
    assert resolve_state("Garmin", "x50i", _wp(dive_alerts=["deco_stop_cleared"])) == "clear"
    assert resolve_state("Garmin", "x50i", _wp(dive_alerts=["deco_complete"])) == "normal"
    # deco_stop_cleared takes priority even alongside a generic deco alert
    assert resolve_state(
        "Garmin", "x50i", _wp(dive_alerts=["deco_ceiling_broken", "deco_stop_cleared"])
    ) == "clear"
    # Clearing the *last* stop fires both alerts in the same window (confirmed
    # against a real mk3i log) - deco_complete wins as the more final signal
    assert resolve_state(
        "Garmin", "x50i", _wp(dive_alerts=["deco_stop_cleared", "deco_complete"])
    ) == "normal"

def test_is_clearing_deco_stop():
    # 0.5m shallower than the deco stop, within Shearwater's 1.0m margin -> clearing
    assert is_clearing_deco_stop("Shearwater", "Perdix 2", _wp(deco_stop_depth=6.0, depth=5.5)) is True

    # Still 2m below the stop - outside the margin, not yet clearing
    assert is_clearing_deco_stop("Shearwater", "Perdix 2", _wp(deco_stop_depth=6.0, depth=4.0)) is False

    # Already at or past the stop depth (distance <= 0) - not "clearing", already there
    assert is_clearing_deco_stop("Shearwater", "Perdix 2", _wp(deco_stop_depth=6.0, depth=6.0)) is False
    assert is_clearing_deco_stop("Shearwater", "Perdix 2", _wp(deco_stop_depth=6.0, depth=7.0)) is False

    # No deco stop active -> never clearing
    assert is_clearing_deco_stop("Shearwater", "Perdix 2", _wp(deco_stop_depth=0.0, depth=0.5)) is False

    # Garmin has no configured "clear" margin (defaults to 0) -> never clearing
    assert is_clearing_deco_stop("Garmin", "x50i", _wp(deco_stop_depth=6.0, depth=5.9)) is False

def test_resolve_state_clear_refines_deco():
    # Within the clear margin of the deco stop -> "clear", not plain "deco"
    assert resolve_state("Shearwater", "Perdix 2", _wp(deco_stop_depth=6.0, depth=5.5)) == "clear"
    # Outside the margin -> still plain "deco"
    assert resolve_state("Shearwater", "Perdix 2", _wp(deco_stop_depth=6.0, depth=4.0)) == "deco"
    # Same distinction via the deco alert-event path, not just the depth-band fallback
    assert resolve_state(
        "Shearwater", "Perdix 2", _wp(dive_alerts=["deco_ceiling_broken"], deco_stop_depth=6.0, depth=5.5)
    ) == "clear"
    # Garmin has no "clear" margin configured -> stays plain "deco"
    assert resolve_state("Garmin", "x50i", _wp(deco_stop_depth=6.0, depth=5.9)) == "deco"

def test_get_ndl_before_clear():
    # Waypoints in order: normal NDL countdown, then deco starts (ndl goes
    # None), then close enough to the stop to be "clearing" it.
    waypoints = [
        _wp(time_since_start=0, ndl=1800, depth=20.0),
        _wp(time_since_start=60, ndl=600, depth=25.0),  # last real NDL: 10 min
        _wp(time_since_start=120, ndl=None, deco_stop_depth=6.0, depth=15.0),  # deco, not clearing
        _wp(time_since_start=180, ndl=None, deco_stop_depth=6.0, depth=6.5),  # still deco
        _wp(time_since_start=240, ndl=None, deco_stop_depth=6.0, depth=5.5),  # now clearing
        _wp(time_since_start=300, ndl=None, deco_stop_depth=6.0, depth=5.7),  # still clearing
    ]

    # Frozen at the last real NDL (600s) for every waypoint in the "clear" run
    assert get_ndl_before_clear("Shearwater", "Perdix 2", waypoints[4], waypoints) == 600
    assert get_ndl_before_clear("Shearwater", "Perdix 2", waypoints[5], waypoints) == 600

    # None while still plain "deco" (not yet clearing) or "normal" - only
    # meaningful during "clear" itself
    assert get_ndl_before_clear("Shearwater", "Perdix 2", waypoints[2], waypoints) is None
    assert get_ndl_before_clear("Shearwater", "Perdix 2", waypoints[3], waypoints) is None
    assert get_ndl_before_clear("Shearwater", "Perdix 2", waypoints[0], waypoints) is None

    # No waypoint list, or no waypoint at all -> None, doesn't blow up
    assert get_ndl_before_clear("Shearwater", "Perdix 2", waypoints[4], None) is None
    assert get_ndl_before_clear("Shearwater", "Perdix 2", None, waypoints) is None

def test_get_badge_config():
    stop_cfg = get_badge_config("Garmin", "x50i", "safety_stop")
    assert stop_cfg == {"label": "STOP", "color": "#00FF00"}

    deco_cfg = get_badge_config("Garmin", "x50i", "deco")
    assert deco_cfg == {"label": "DECO", "color": "#FFA500"}

    clear_cfg = get_badge_config("Shearwater", "Perdix 2", "clear")
    assert clear_cfg == {"label": "CLEAR", "color": "#00C800"}

    # Unknown manufacturer/model still falls back to the global default block
    assert get_badge_config("UnknownMfg", "UnknownModel", "safety_stop") is not None

    # Not a badge-eligible state
    assert get_badge_config("Garmin", "x50i", "normal") is None

def test_resolve_blink_color():
    # First half of the period -> blink color, second half -> base color
    assert resolve_blink_color("#00FF00", "#FF0000", elapsed_seconds=0.0, period=1.0) == "#FF0000"
    assert resolve_blink_color("#00FF00", "#FF0000", elapsed_seconds=0.75, period=1.0) == "#00FF00"
    # Deterministic across periods (elapsed=2.25 -> same phase as 0.25)
    assert resolve_blink_color("#00FF00", "#FF0000", elapsed_seconds=2.25, period=1.0) == "#FF0000"
    # None/zero elapsed doesn't crash
    assert resolve_blink_color("#00FF00", "#FF0000", elapsed_seconds=None, period=1.0) == "#FF0000"

def test_resolve_tank_variant():
    dive_single = MagicMock()
    wp1 = MagicMock()
    wp1.tanks = {"Back": object()}
    dive_single.waypoints = [wp1]
    assert resolve_tank_variant(dive_single) == "single_tank"

    dive_sidemount = MagicMock()
    wp2 = MagicMock()
    wp2.tanks = {"Left": object(), "Right": object()}
    dive_sidemount.waypoints = [wp2]
    assert resolve_tank_variant(dive_sidemount) == "sidemount"

    dive_empty = MagicMock()
    dive_empty.waypoints = []
    assert resolve_tank_variant(dive_empty) == "single_tank"

    assert resolve_tank_variant(None) == "single_tank"

def test_get_tank_fill_color():
    # No reading yet -> no fill at all (not even green)
    assert get_tank_fill_color("Garmin", "x50i", None) is None

    # Below the low band -> red
    assert get_tank_fill_color("Garmin", "x50i", 40) == "#FF0000"
    # Warning band -> yellow
    assert get_tank_fill_color("Garmin", "x50i", 60) == "#FFFF00"
    # Healthy pressure -> green (no band matches, falls through to the default)
    assert get_tank_fill_color("Garmin", "x50i", 150) == "#00FF00"
    # Boundary: exactly at the low-band ceiling counts as the warning band, not red
    assert get_tank_fill_color("Garmin", "x50i", 50) == "#FFFF00"
    # Boundary: exactly at the warning-band ceiling counts as healthy
    assert get_tank_fill_color("Garmin", "x50i", 70) == "#00FF00"

    # Unknown manufacturer/model still falls back to the global default bands
    assert get_tank_fill_color("UnknownMfg", "UnknownModel", 40) == "#FF0000"
