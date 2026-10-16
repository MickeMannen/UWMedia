import pytest
from unittest.mock import MagicMock
from conftest import LOGS_DIR
from utils.hud_rules_engine import (
    get_dynamic_color,
    get_safety_stop_text,
    get_rule_config,
    resolve_state,
    get_badge_config,
    resolve_blink_color,
    resolve_tank_variant,
    get_tank_fill_color,
    deco_stop_phase,
    deco_clear_seconds,
    stop_phase,
    safety_stop_phase,
    get_ndl_before_clear,
    safety_stop_status,
    safety_stop_timeline,
)

def test_rules_loading_and_hierarchical_fallback():
    # 1. Exact model-level override check (Shearwater Perdix 3 has its own badge_states)
    perdix_tp = get_rule_config("Shearwater", "Perdix 3", "badge_states")
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

    # Perdix 2 manual p.31: the NDL turns yellow below 5 minutes, white otherwise
    assert get_dynamic_color("Shearwater", "Perdix 2", "ndl", 2100, "#BLUE") == "#FFFFFF"
    assert get_dynamic_color("Shearwater", "Perdix 2", "ndl", 1200, "#BLUE") == "#FFFFFF"
    assert get_dynamic_color("Shearwater", "Perdix 2", "ndl", 300, "#BLUE") == "#FFFFFF"
    assert get_dynamic_color("Shearwater", "Perdix 2", "ndl", 240, "#BLUE") == "#FFFF00"

def test_po2_dynamic_colors():
    # Perdix 2 manual p.19 / p.62: the PPO2 flashes red outside the PPO2
    # limits; the OC Deco limit (1.61 by default) is the band used so a deco
    # gas is not flagged (the bottom gas's 1.40 limit needs the gas list).
    assert get_dynamic_color("Shearwater", "Perdix 2", "po2", 1.3, "#FFFFFF") == "#FFFFFF"
    assert get_dynamic_color("Shearwater", "Perdix 2", "po2", 1.6, "#FFFFFF") == "#FFFFFF"
    assert get_dynamic_color("Shearwater", "Perdix 2", "po2", 1.61, "#FFFFFF") == "#FF0000"
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
    # Perdix 2 manual p.57: a Reserve Pressure warning below the reserve
    # setting (50 bar by default) and a Critical Pressure warning below the
    # larger of 21 bar or half the reserve; p.40: yellow box, then red box.
    assert get_dynamic_color("Shearwater", "Perdix 2", "primary_tank_pressure", 150, "#BLUE") == "#BLUE"
    assert get_dynamic_color("Shearwater", "Perdix 2", "primary_tank_pressure", 65, "#BLUE") == "#BLUE"
    assert get_dynamic_color("Shearwater", "Perdix 2", "primary_tank_pressure", 50, "#BLUE") == "#BLUE"
    assert get_dynamic_color("Shearwater", "Perdix 2", "primary_tank_pressure", 49, "#BLUE") == "#FFFF00"
    assert get_dynamic_color("Shearwater", "Perdix 2", "primary_tank_pressure", 25, "#BLUE") == "#FFFF00"
    assert get_dynamic_color("Shearwater", "Perdix 2", "primary_tank_pressure", 24, "#BLUE") == "#FF0000"
    # Every Shearwater shares the rule (the Peregrine TX manual p.56 says the same)
    assert get_dynamic_color("Shearwater", "Peregrine TX", "primary_tank_pressure", 24, "#BLUE") == "#FF0000"
    assert get_dynamic_color("Shearwater", "Petrel", "primary_tank_pressure", 40, "#BLUE") == "#FFFF00"

def test_secondary_tank_pressure_dynamic_colors():
    # secondary_tank_pressure (sidemount's second cylinder) follows the same
    # tank_reserve rule as primary_tank_pressure
    assert get_dynamic_color("Shearwater", "Perdix 2", "secondary_tank_pressure", 150, "#BLUE") == "#BLUE"
    assert get_dynamic_color("Shearwater", "Perdix 2", "secondary_tank_pressure", 49, "#BLUE") == "#FFFF00"
    assert get_dynamic_color("Shearwater", "Perdix 2", "secondary_tank_pressure", 20, "#BLUE") == "#FF0000"


def test_tank_reserve_thresholds_follow_the_manuals():
    from utils.hud_rules_engine import tank_reserve_thresholds, tank_pressure_state
    # Shearwater: critical = max(21, reserve / 2) - the manual's own examples
    # (p.57): reserve 48 -> critical 24; reserve 27 -> critical 21.
    assert tank_reserve_thresholds("Shearwater", "Perdix 2") == (50.0, 25.0)
    assert tank_reserve_thresholds("Shearwater", "Perdix 2", reserve_bar=48) == (48.0, 24.0)
    assert tank_reserve_thresholds("Shearwater", "Perdix 2", reserve_bar=27) == (27.0, 21.0)
    assert tank_pressure_state("Shearwater", "Teric", 47) == "reserve"
    assert tank_pressure_state("Shearwater", "Teric", 23) == "critical"
    assert tank_pressure_state("Shearwater", "Teric", 50) is None
    assert tank_pressure_state("Shearwater", "Teric", None) is None
    # Garmin: reserve and critical are two settings (Mk3 manual p.6); the
    # value turns yellow below the reserve and flashes red below critical
    # (p.14). Defaults are not in the manual: 50 / 25 bar assumed.
    assert tank_reserve_thresholds("Garmin", "mk3i") == (50.0, 25.0)
    assert get_dynamic_color("Garmin", "x50i", "tank_pressure:T1", 49, "#FFFFFF") == "#FFFF00"
    assert get_dynamic_color("Garmin", "x50i", "tank_pressure:T1", 24, "#FFFFFF") == "#FF0000"
    assert get_dynamic_color("Garmin", "x50i", "tank_pressure:T1", 120, "#FFFFFF") == "#FFFFFF"
    # No rule: no thresholds, and the generic bands still apply
    assert tank_reserve_thresholds("UnknownMfg", None) is None
    assert get_dynamic_color("UnknownMfg", None, "primary_tank_pressure", 55, "#FFFFFF") == "#FF0000"


def test_garmin_deco_stop_phases_use_the_descent_margins():
    # Mk3 manual p.10 / p.13: Approaching Deco Stop within one stop interval
    # (3 m); stay within 0.6 m of the ceiling; more than 0.6 m above it is a
    # violation. A Perdix (p.28) objects as soon as the diver is shallower.
    def at(depth, stop=6.0):
        wp = MagicMock()
        wp.depth, wp.next_stop_depth, wp.deco_stop_depth = depth, stop, stop
        return wp
    assert deco_stop_phase("Garmin", "mk3i", at(12.0)) == "far"
    assert deco_stop_phase("Garmin", "mk3i", at(8.5)) == "approach"
    assert deco_stop_phase("Garmin", "mk3i", at(6.5)) == "at_stop"
    assert deco_stop_phase("Garmin", "mk3i", at(5.5)) == "at_stop"  # 0.5 m above: within the margin
    assert deco_stop_phase("Garmin", "mk3i", at(5.3)) == "violation"
    assert deco_stop_phase("Shearwater", "Perdix 2", at(5.9)) == "violation"


def test_teric_and_tern_badges_box_the_title_and_say_paused():
    # Teric manual p.25 / Tern manual p.24 figures: "SAFETY" in a green box,
    # "SAFETY / PAUSED" in yellow, "SAFETY / CLEAR" when done; p.26 / p.25:
    # the stop info is yellow when shallower than the stop but deeper than
    # the ceiling, and flashes red above the ceiling.
    for model in ("Teric", "Tern"):
        ss = get_badge_config("Shearwater", model, "safety_stop")
        assert ss["paused_label"] == "PAUSED" and ss["title_box"] is True
        deco = get_badge_config("Shearwater", model, "deco")
        assert deco["violation_color"] == "#FFFF00" and deco["ceiling_violation_color"] == "#FF0000"
    # A Perdix 2 keeps its red violation and plain title
    perdix = get_badge_config("Shearwater", "Perdix 2", "deco")
    assert perdix["violation_color"] == "#FF0000" and "title_box" not in get_badge_config("Shearwater", "Perdix 2", "safety_stop")

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

def test_get_badge_config():
    stop_cfg = get_badge_config("Garmin", "x50i", "safety_stop")
    # Mk3 manual p.13: depth and stop depth turn yellow more than 2 m above the ceiling (phase "warn")
    assert stop_cfg == {"label": "STOP", "color": "#00FF00", "warn_color": "#FFFF00", "warn_value_color": "#FFFF00"}

    deco_cfg = get_badge_config("Garmin", "x50i", "deco")
    assert deco_cfg == {"label": "DECO", "color": "#FFA500"}

    clear_cfg = get_badge_config("Shearwater", "Perdix 2", "clear")
    assert (clear_cfg["label"], clear_cfg["color"]) == ("CLEAR", "#00C800")

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

def _profile(points):
    """Per-second waypoints linearly interpolated through (time, depth) points."""
    wps, max_depth = [], 0.0
    for (t0, d0), (t1, d1) in zip(points, points[1:]):
        for t in range(t0, t1):
            depth = d0 + (d1 - d0) * (t - t0) / (t1 - t0)
            max_depth = max(max_depth, depth)
            wps.append(_wp(time_since_start=t, depth=depth, max_depth=max_depth))
    return wps

def test_garmin_safety_stop_timer_counts_down_and_completes():
    # X50i manual p.10: after >11 m, the 3:00 timer starts within 1 m of 5 m.
    wps = _profile([(0, 0), (60, 20), (600, 20), (700, 5), (1000, 5), (1060, 0)])
    at = {w.time_since_start: w for w in wps}
    assert resolve_state("Garmin", "x50i", at[500], wps) == "normal"
    assert safety_stop_status("Garmin", "x50i", at[750], wps)[0] is True
    assert safety_stop_status("Garmin", "x50i", at[750], wps)[1] < 180
    assert resolve_state("Garmin", "x50i", at[750], wps) == "safety_stop"
    # 3 minutes after reaching the stop band it's done - back to normal (NDL).
    assert resolve_state("Garmin", "x50i", at[900], wps) == "normal"

def test_garmin_safety_stop_resets_below_11m_and_skips_shallow_dives():
    wps = _profile([(0, 0), (60, 20), (300, 20), (400, 5), (460, 5), (520, 15), (600, 15), (700, 5), (760, 5), (800, 0)])
    at = {w.time_since_start: w for w in wps}
    # Descending below 11 m resets the stop to a full 3:00.
    assert safety_stop_status("Garmin", "x50i", at[600], wps) == (False, 180)
    assert resolve_state("Garmin", "x50i", at[750], wps) == "safety_stop"

    shallow = _profile([(0, 0), (60, 9), (600, 9), (700, 5), (900, 5), (960, 0)])
    assert resolve_state("Garmin", "x50i", shallow[750], shallow) == "normal"

def test_safety_stop_timer_only_for_rules_with_a_duration():
    wps = _profile([(0, 0), (60, 20), (600, 20), (700, 5), (1000, 5)])
    assert safety_stop_timeline("Shearwater", "Perdix 2", wps) is not None  # the Perdix dialect
    assert safety_stop_timeline("NoSuchBrand", "", wps) is None

def test_garmin_safety_stop_not_shown_after_a_3m_deco_stop():
    # A deco dive whose last stop is at 3 m: once the ceiling clears the diver
    # is already shallower than the 5 m ± 1 m start window, so no safety stop
    # timer ever starts - the HUD goes straight back to NDL, not to a stop box
    # with a frozen 3:00.
    wps = _profile([(0, 0), (120, 45), (1500, 45), (1800, 9), (2100, 6), (2400, 3), (3000, 3), (3030, 0)])
    for w in wps:
        if 1700 <= w.time_since_start < 2700:
            w.deco_stop_depth = 3.0
    at = {w.time_since_start: w for w in wps}
    assert resolve_state("Garmin", "x50i", at[2000], wps) == "deco"
    assert resolve_state("Garmin", "x50i", at[2800], wps) == "normal"
    assert safety_stop_status("Garmin", "x50i", at[2800], wps)[0] is False
    assert resolve_state("Garmin", "x50i", at[3020], wps) == "normal"

def test_garmin_safety_stop_timeline_follows_the_computers_own_alerts():
    # The X50i's own started/complete alerts win over the depth rules: a stop
    # the computer ended early stays ended, and the NDL comes back for good.
    wps = _profile([(0, 0), (60, 20), (600, 20), (700, 5), (1000, 5), (1060, 0)])
    at = {w.time_since_start: w for w in wps}
    at[720].dive_alerts = ["safety_stop_started"]
    at[800].dive_alerts = ["safety_stop_complete"]
    assert resolve_state("Garmin", "x50i", at[750], wps) == "safety_stop"
    assert resolve_state("Garmin", "x50i", at[800], wps) == "normal"
    assert resolve_state("Garmin", "x50i", at[850], wps) == "normal"
    assert resolve_state("Garmin", "x50i", at[990], wps) == "normal"

@pytest.mark.requires_media
def test_garmin_no_safety_stop_after_deco_in_a_real_mk3i_log():
    # test_data/logs/submersion_dives/005_oc-trimix-two-deco-gases.fit: the
    # computer fires deco_complete at 6.9 m and no safety_stop_started for the
    # rest of the dive - so neither does the HUD, even as the diver hangs at
    # 6 m on the way up, and the last 1.0-1.5 m never flicker a stop box.
    import io, contextlib
    from pathlib import Path
    from parsers.garmin import GarminParser
    with contextlib.redirect_stdout(io.StringIO()):
        dive = GarminParser().parse(LOGS_DIR / "submersion_dives/005_oc-trimix-two-deco-gases.fit")[0]
    wps = dive.waypoints
    states = [(wp.time_since_start, resolve_state("Garmin", "Descent Mk3i", wp, wps)) for wp in wps]
    complete = next(t for t, wp in zip((s[0] for s in states), wps) if "deco_complete" in wp.dive_alerts)
    assert any(s == "deco" for _, s in states)
    assert all(s == "normal" for t, s in states if t >= complete)

def test_garmin_safety_stop_ends_on_surfacing_without_flicker():
    wps = _profile([(0, 0), (60, 20), (600, 20), (700, 5), (760, 5), (800, 1.0), (820, 1.4), (840, 1.0), (900, 1.4)])
    at = {w.time_since_start: w for w in wps}
    assert resolve_state("Garmin", "x50i", at[750], wps) == "safety_stop"
    assert all(resolve_state("Garmin", "x50i", at[t], wps) == "normal" for t in range(801, 900))


# --- Shearwater (Perdix 2 manual p.27-28, p.31-33) -----------------------------

def test_deco_stop_phase_follows_the_perdix_margins():
    stop = lambda depth: _wp(deco_stop_depth=6.0, next_stop_depth=6.0, depth=depth)
    assert deco_stop_phase("Shearwater", "Perdix 2", stop(15.0)) == "far"       # > 5.1 m below the stop
    assert deco_stop_phase("Shearwater", "Perdix 2", stop(10.0)) == "approach"  # within 5.1 m: yellow, flashing arrow
    assert deco_stop_phase("Shearwater", "Perdix 2", stop(7.4)) == "at_stop"    # up to 1.5 m deeper: green + check
    assert deco_stop_phase("Shearwater", "Perdix 2", stop(6.0)) == "at_stop"
    assert deco_stop_phase("Shearwater", "Perdix 2", stop(5.5)) == "violation"  # shallower than the stop
    assert deco_stop_phase("Shearwater", "Perdix 2", _wp(depth=5.0)) is None
    assert deco_stop_phase("Garmin", "x50i", stop(7.0)) == "approach"  # a Descent has its own margins (3 m / 0.6 m)
    assert deco_stop_phase("UnknownMfg", None, stop(7.0)) is None  # no such rule without a brand
    assert resolve_state("Shearwater", "Perdix 2", stop(5.5)) == "deco"  # not a state of its own


def test_shearwater_safety_stop_counter_appears_at_11m_and_counts_under_6m():
    wps = _profile([(0, 0), (60, 20), (600, 20), (700, 5), (1000, 5), (1060, 0)])
    at = {w.time_since_start: w for w in wps}
    assert resolve_state("Shearwater", "Perdix 2", at[30], wps) == "normal"       # not yet past 11 m
    assert safety_stop_phase("Shearwater", "Perdix 2", at[300], wps) == ("pending", 180)
    assert resolve_state("Shearwater", "Perdix 2", at[300], wps) == "safety_stop"  # shown at depth, planned 3:00
    assert safety_stop_phase("Shearwater", "Perdix 2", at[750], wps)[0] == "counting"
    assert safety_stop_phase("Shearwater", "Perdix 2", at[750], wps)[1] < 180
    assert safety_stop_phase("Shearwater", "Perdix 2", at[950], wps) == ("complete", 0)
    assert resolve_state("Shearwater", "Perdix 2", at[950], wps) == "safety_stop"  # complete still shows, with the check
    assert stop_phase("Shearwater", "Perdix 2", at[750], wps)[3] is None  # a Perdix names no stop depth


def test_shearwater_safety_stop_pauses_outside_2_4_to_8_3m_and_adapts_to_5min():
    wps = _profile([(0, 0), (60, 20), (600, 20), (700, 5), (760, 5), (800, 1.0), (860, 1.0), (900, 5), (1100, 5)])
    at = {w.time_since_start: w for w in wps}
    assert safety_stop_phase("Shearwater", "Perdix 2", at[830], wps)[0] == "paused"  # shallower than 2.4 m
    left_before = safety_stop_phase("Shearwater", "Perdix 2", at[805], wps)[1]
    assert safety_stop_phase("Shearwater", "Perdix 2", at[855], wps)[1] == left_before  # paused at 1 m: no countdown
    assert safety_stop_phase("Shearwater", "Perdix 2", at[950], wps)[0] == "counting"
    # Deco Setup (manual p.55) offers 3 min, Adapt and CntUp: 3 min fixed is the
    # default, so a dive past 30 m still plans 3:00 ...
    deep = _profile([(0, 0), (60, 32), (300, 32), (600, 5), (1000, 5)])
    assert safety_stop_phase("Shearwater", "Perdix 2", deep[200], deep) == ("pending", 180)
    # ... and Adapt's 5:00 past 30 m (or under 5 min of NDL) applies once a page enables it
    from utils.hud_rules_engine import rule_overrides
    adapt_rule = dict(get_rule_config("Shearwater", "Perdix 2", "safety_stop"))
    adapt_rule["adapt"] = {**adapt_rule["adapt"], "enabled": True}
    low_ndl = _profile([(0, 0), (60, 20), (600, 20), (700, 5), (1000, 5)])
    low_ndl[300].ndl = 240
    with rule_overrides({"safety_stop": adapt_rule}):
        assert safety_stop_phase("Shearwater", "Perdix 2", deep[200], deep) == ("pending", 300)
        assert safety_stop_phase("Shearwater", "Perdix 2", low_ndl[400], low_ndl) == ("pending", 300)
    assert safety_stop_phase("Shearwater", "Perdix 2", low_ndl[400], low_ndl) == ("pending", 180)


def test_shearwater_deco_clear_counts_up_on_a_page_that_asks_for_it():
    # Perdix 3 manual p.60: the deco clear counter is on by default in the
    # technical modes only; a Tec page turns it on with a layout rule override.
    from utils.hud_rules_engine import rule_overrides
    with rule_overrides({"deco_clear": {"count_up": True}}):
        wps = _check_deco_clear_count_up()
    at = {w.time_since_start: w for w in wps}
    assert resolve_state("Garmin", "x50i", at[2300], wps) == "normal"  # a Descent has no deco-clear counter


def _check_deco_clear_count_up():
    wps = _profile([(0, 0), (120, 40), (1500, 40), (1700, 6), (2000, 6), (2100, 3), (2400, 3), (2430, 0)])
    for w in wps:
        if 1400 <= w.time_since_start < 2000:
            w.deco_stop_depth = w.next_stop_depth = 6.0
            w.next_stop_time = 2000 - w.time_since_start
    at = {w.time_since_start: w for w in wps}
    assert resolve_state("Shearwater", "Perdix 2", at[1800], wps) == "deco"
    assert stop_phase("Shearwater", "Perdix 2", at[1800], wps)[1] == "at_stop"
    assert resolve_state("Shearwater", "Perdix 2", at[2000], wps) == "clear"
    assert deco_clear_seconds("Shearwater", "Perdix 2", at[2000], wps) == 0
    assert deco_clear_seconds("Shearwater", "Perdix 2", at[2300], wps) == 300
    assert stop_phase("Shearwater", "Perdix 2", at[2300], wps) == ("clear", "clear", 300, None)
    # the safety stop runs after deco too (manual p.28), but on this page the clear counter wins
    assert safety_stop_phase("Shearwater", "Perdix 2", at[2300], wps)[0] in ("counting", "complete")
    return wps


def test_sidemount_switch_target_follows_the_21_bar_threshold():
    from utils.hud_rules_engine import sidemount_switch_target
    from models.dive import TankData

    def wp(p1, p2=None):
        tanks = {"T1": TankData(pressure_bar=p1, o2_percent=21.0)}
        if p2 is not None:
            tanks["T2"] = TankData(pressure_bar=p2, o2_percent=21.0)
        return _wp(tanks=tanks)

    assert sidemount_switch_target("Shearwater", "Perdix 2", wp(175, 153)) == "primary"    # breathe the fuller T1
    assert sidemount_switch_target("Shearwater", "Perdix 2", wp(150, 180)) == "secondary"
    assert sidemount_switch_target("Shearwater", "Perdix 2", wp(170, 160)) is None         # within 21 bar
    assert sidemount_switch_target("Shearwater", "Perdix 2", wp(170)) is None              # one tank
    assert sidemount_switch_target("Garmin", "x50i", wp(175, 100)) is None                 # no such rule


def test_teric_and_tern_badges_override_only_what_differs_from_the_perdix_family():
    # Teric manual p.25-26: "SAFETY" / "DECO" titles, no check mark, green
    # while counting, yellow when paused, "SAFETY / CLEAR" once done.
    for model in ("Teric", "Tern"):
        ss = get_badge_config("Shearwater", model, "safety_stop")
        assert ss["label"] == "SAFETY" and "check_mark" not in ss
        assert ss["counting_value_color"] == "#00C800" and ss["paused_color"] == "#FFFF00"
        assert ss["complete_value_text"] == "CLEAR"
        assert ss["show_depth"] is False and ss["timer_format"] == "m:ss"  # inherited from the brand entry
        deco = get_badge_config("Shearwater", model, "deco")
        assert deco["label"] == "DECO" and deco["inline"] is True and "approach_color" not in deco
    perdix = get_badge_config("Shearwater", "Perdix 2", "safety_stop")
    assert perdix["label"] == "SAFETY STOP" and perdix["check_mark"] is True


def test_shearwater_safety_stop_resets_when_deeper_than_11m_again():
    wps = _profile([(0, 0), (60, 20), (600, 20), (700, 5), (760, 5), (820, 15), (900, 15), (1000, 5), (1300, 5)])
    at = {w.time_since_start: w for w in wps}
    assert safety_stop_phase("Shearwater", "Perdix 2", at[750], wps)[0] == "counting"
    assert safety_stop_phase("Shearwater", "Perdix 2", at[850], wps) == ("pending", 180)  # back below 11 m: full 3:00 again
    assert safety_stop_phase("Shearwater", "Perdix 2", at[1050], wps)[0] == "counting"
    assert safety_stop_phase("Shearwater", "Perdix 2", at[1050], wps)[1] > 100


def test_perdix_3_badge_is_a_boxed_title_that_replaces_the_ndl():
    # Perdix 3 manual p.58-60: "SAFETY" in a green box with the time in green,
    # "PAUSED" in yellow, "SAFETY / CLEAR" when done; deco as a blue "DECO"
    # label over "18m 1min" like the Tec layout's top row.
    ss = get_badge_config("Shearwater", "Perdix 3", "safety_stop")
    assert ss["label"] == "SAFETY" and ss["paused_label"] == "PAUSED" and ss["title_box"] is True
    assert "check_mark" not in ss and ss["complete_value_text"] == "CLEAR"
    deco = get_badge_config("Shearwater", "Perdix 3", "deco")
    assert deco["label"] == "DECO" and deco["color"] == "#00ADED" and deco["inline"] is True
    assert "approach_color" not in deco


def test_underscore_keys_in_rules_are_annotations_not_config(monkeypatch):
    # hud_rules.json cannot carry comments; a key starting with "_" at any
    # level ("_source": "manual p.27") cites the rule next to it and must be
    # invisible to every lookup and merge (hud_rules_sources.md).
    import utils.hud_rules_engine as engine
    rules = {
        "_source": "hud_rules_sources.md",
        "Shearwater": {
            "_manual": "Perdix 2 Recreational manual Rev C",
            "ndl": [{"max": 5, "color": "#FFFF00"}, {"min": 5, "color": "#FFFFFF"}],
            "_ndl": "p.31",
            "badge_states": {
                "_source": "p.27-28",
                "safety_stop": {"label": "SAFETY STOP", "color": "#00ADED", "_source": "p.27"},
            },
            "Perdix 2": {"tank_pressure": [{"max": 60, "color": "#FF0000"}], "_source": "unverified"},
        },
        "default": {"ndl": [{"max": 10, "color": "#FF0000"}]},
    }
    monkeypatch.setattr(engine, "_rules_cache", rules)
    assert engine.is_annotation_key("_source") and not engine.is_annotation_key("ndl")
    assert engine.get_rule_config("Shearwater", "Perdix 2", "ndl")[0]["max"] == 5
    assert engine.get_rule_config("Shearwater", "Perdix 2", "_ndl") is None
    assert engine.get_rule_config("Shearwater", "_source", "ndl")[0]["max"] == 5  # not a model
    assert engine.get_rule_config("_source", None, "ndl")[0]["max"] == 10  # not a brand
    badge = engine.get_badge_config("Shearwater", "Perdix 2", "safety_stop")
    assert badge == {"label": "SAFETY STOP", "color": "#00ADED"}
    assert engine.get_dynamic_color("Shearwater", "Perdix 2", "ndl", 240, "#000000") == "#FFFF00"



def test_shearwater_safety_stop_follows_deco_on_a_recreational_page():
    # Perdix 2 manual p.28: once all decompression stops are complete, the
    # safety stop begins counting down (the main page; the simulator's Perdix 2
    # agrees, A7). No count-up unless the page runs the deco clear counter.
    wps = _profile([(0, 0), (60, 36), (1080, 36), (1200, 6), (1500, 6), (1510, 4.5), (1560, 4.5), (1600, 1.8), (1640, 1.8), (1650, 4.5), (1900, 4.5), (1950, 0)])
    for w in wps:
        if 1100 <= w.time_since_start <= 1500:
            w.deco_stop_depth = w.next_stop_depth = 6.0
            w.next_stop_time = 60
    at = {w.time_since_start: w for w in wps}
    assert resolve_state("Shearwater", "Perdix 2", at[1300], wps) == "deco"
    assert stop_phase("Shearwater", "Perdix 2", at[1530], wps)[:2] == ("safety_stop", "counting")
    assert stop_phase("Shearwater", "Perdix 2", at[1620], wps)[:2] == ("safety_stop", "paused")
    assert stop_phase("Shearwater", "Perdix 2", at[1880], wps)[:2] == ("safety_stop", "complete")  # 3 min fixed by default
    assert deco_clear_seconds("Shearwater", "Perdix 2", at[1530], wps) is None
