"""utils/dummy_telemetry.py - the Overlay Designer's synthetic dive
(overlay_rework.md Phase 1, decision Q12)."""
import pytest

from utils.dummy_telemetry import (
    DUMMY_DURATION_S,
    STATE_OPTIONS,
    apply_state,
    build_dummy_dive,
    waypoint_at,
)
from utils.hud_rules_engine import resolve_state, resolve_tank_variant


def test_dummy_dive_is_deterministic():
    a = build_dummy_dive("single_tank")
    b = build_dummy_dive("single_tank")
    # Waypoint == recurses through the _dive back-reference, so compare dumps.
    assert [w.model_dump() for w in a.waypoints] == [w.model_dump() for w in b.waypoints]


def test_dummy_dive_profile_shape():
    dive = build_dummy_dive("single_tank")
    times = [w.time_since_start for w in dive.waypoints]
    assert times[0] == 0 and times[-1] == DUMMY_DURATION_S
    assert times == sorted(times) and len(set(times)) == len(times)
    depths = [w.depth for w in dive.waypoints]
    assert depths[0] == 0.0 and depths[-1] == 0.0
    assert max(depths) == 42.0
    # max_depth is cumulative and never decreases
    max_depths = [w.max_depth for w in dive.waypoints]
    assert max_depths == sorted(max_depths)
    # every field a bundled template shows is populated mid-dive
    wp = waypoint_at(dive, 12 * 60)
    assert wp.ndl and wp.tts and wp.dive_time == 12 * 60 and wp.depth == 30.0
    assert wp.primary_tank_pressure and wp.gasmix == "Nx32"
    assert wp.air_remaining and wp.heart_rate and wp.po2 and wp.gf is not None


def test_dummy_dive_passes_through_every_state_in_order():
    """simulator.md A3: the time slider alone visits the situations a template
    is checked in, on both brands' rules."""
    from utils.hud_notices import active_notice
    from utils.hud_rules_engine import stop_phase
    dive = build_dummy_dive("single_tank")
    wps = dive.waypoints

    def at(t, brand=("Shearwater", "Perdix 2")):
        wp = waypoint_at(dive, t)
        state, phase, _, _ = stop_phase(brand[0], brand[1], wp, wps)
        notice = active_notice(brand[0], brand[1], wp, wps)
        return state, phase, notice["text"] if notice else None

    assert at(60) == ("normal", None, None) and waypoint_at(dive, 60).ascent_rate < 0  # descent
    # past 11 m a Perdix shows the safety-stop counter (pending) for the rest of the dive (manual p.27)
    assert at(400) == ("safety_stop", "pending", None)  # bottom, plenty of NDL
    assert at(680)[2] == "Low NDL Alert" and waypoint_at(dive, 680).ndl <= 300  # NDL at 5 min
    assert at(900)[2] == "Depth Alert"  # below 40 m
    assert at(930)[2] == "HIGH PPO2"  # 30 s above the limit on Nx32 at 42 m
    assert at(1000) == ("deco", "far", None)
    assert at(1160) == ("deco", "approach", "FAST ASCENT")  # 12 m/min for more than 10 s, within 5.1 m of the 6 m stop
    assert at(1230)[:2] == ("deco", "at_stop")
    assert at(1280)[:2] == ("deco", "ceiling_violation")  # 4.5 m, shallower than the 5 m ceiling
    assert at(1300)[2] == "MISSED DECO STOP"  # 30 s above the stop
    assert at(1400)[:2] == ("deco", "at_stop")
    assert at(1440)[0] == "clear"  # the last stop cleared
    assert at(1520)[:2] == ("safety_stop", "counting")  # after deco the safety stop counts down (manual p.28)
    assert at(1590)[:2] == ("safety_stop", "paused")
    assert at(1900) == ("safety_stop", "complete", None)  # "Complete" until the dive ends

    # Garmin reads the same dive through its own alerts and margins
    g = ("Garmin", "mk3i")
    assert at(510, g)[2] == "Approaching NDL"
    assert at(840, g)[:2] == ("deco", "far") and at(840, g)[2] == "NDL exceeded. Decompression now required."
    assert at(1150, g)[2] == "Ascending too fast. Slow your ascent."  # the watch's own alert
    assert at(1280, g)[:2] == ("deco", "violation") and at(1270, g)[2] == "Descend below deco ceiling."
    assert at(1440, g)[0] == "clear" and at(1450, g)[2] == "Decompression Cleared"
    assert at(1530, g)[0] == "normal"  # a Descent asks for no safety stop after a deco dive (real Mk3i log)
    # the single cylinder reaches the reserve during the safety stop
    assert waypoint_at(dive, 1600).primary_tank_pressure < 50 < waypoint_at(dive, 1300).primary_tank_pressure


@pytest.mark.parametrize("variant,expected_tanks", [("single_tank", 1), ("sidemount", 2), (None, 1)])
def test_dummy_dive_tank_count_follows_variant(variant, expected_tanks):
    dive = build_dummy_dive(variant)
    assert all(len(w.tanks) == expected_tanks for w in dive.waypoints)
    assert resolve_tank_variant(dive) == ("sidemount" if expected_tanks == 2 else "single_tank")


def test_dummy_dive_tank_pressure_only_drops():
    dive = build_dummy_dive("single_tank")
    pressures = [w.primary_tank_pressure for w in dive.waypoints]
    assert all(later <= earlier for earlier, later in zip(pressures, pressures[1:]))
    assert pressures[0] < 200.0 and pressures[-1] > 20.0


def test_waypoint_at_nearest_forward_then_last():
    dive = build_dummy_dive("single_tank")
    assert waypoint_at(dive, 0).time_since_start == 0
    assert waypoint_at(dive, 95).time_since_start == 100
    assert waypoint_at(dive, 10 ** 6).time_since_start == DUMMY_DURATION_S
    assert waypoint_at(None, 10) is None


@pytest.mark.parametrize("state", ["normal", "safety_stop", "deco", "clear"])
@pytest.mark.parametrize("manufacturer,model", [("Shearwater", "Perdix 2"), ("Garmin", "x50i"), (None, None)])
def test_apply_state_resolves_for_every_rule_set(state, manufacturer, model):
    dive = build_dummy_dive("single_tank")
    base = waypoint_at(dive, 12 * 60)  # naturally "normal": 30 m on the bottom
    forced = apply_state(base, state)
    assert resolve_state(manufacturer, model, forced) == state
    # original untouched
    assert base.deco_stop_depth is None and base.dive_alerts == []
    assert forced.log_filename == "dummy_telemetry"


# What each forced state reports on a Perdix 2 (state, phase, notice) and on a Descent.
_FORCED_EXPECT = {
    "descent": (("normal", None, None), ("normal", None, None)),
    "ndl_low": (("safety_stop", "pending", "Low NDL Alert"), ("normal", None, None)),
    "deco": (("deco", "far", None), ("deco", "far", None)),
    "deco_approach": (("deco", "approach", None), ("deco", "approach", None)),
    "deco_at_stop": (("deco", "at_stop", None), ("deco", "at_stop", None)),
    "deco_violation": (("deco", "violation", "MISSED DECO STOP"), ("deco", "at_stop", "Descend below deco ceiling.")),
    "deco_ceiling_violation": (("deco", "ceiling_violation", "MISSED DECO STOP"), ("deco", "violation", "Descend below deco ceiling.")),
    "clear": (("clear", "clear", None), ("clear", "clear", None)),
    "safety_pending": (("safety_stop", "pending", None), ("normal", None, None)),
    "safety_stop": (("safety_stop", "counting", None), ("safety_stop", "counting", "Safety Stop Started")),
    "safety_paused": (("safety_stop", "paused", None), ("safety_stop", "warn", None)),
    "safety_done": (("safety_stop", "complete", None), ("normal", None, None)),
    "fast_ascent": (("safety_stop", "pending", "FAST ASCENT"), ("normal", None, "Ascending too fast. Slow your ascent.")),
    "high_ppo2": (("safety_stop", "pending", "HIGH PPO2"), ("normal", None, None)),
    "high_cns": (("safety_stop", "pending", "HIGH CNS"), ("normal", None, "CNS toxicity at 95%. End your dive now.")),
    "low_gas": (("safety_stop", "pending", None), ("normal", None, None)),
    "critical_gas": (("safety_stop", "pending", "T1 CRITICAL PRES"), ("normal", None, None)),
    "surfacing": (("safety_stop", "complete", None), ("normal", None, None)),
}


@pytest.mark.parametrize("state", [s for s in STATE_OPTIONS if s not in ("auto", "normal")])
def test_forced_dive_reports_the_state_through_the_timelines(state):
    from utils.dummy_telemetry import STATE_OUTER, forced_dive
    from utils.hud_notices import active_notice
    from utils.hud_rules_engine import stop_phase, tank_pressure_state
    dive = build_dummy_dive("single_tank")
    base = waypoint_at(dive, 12 * 60)
    wp, history = forced_dive(base, state)
    assert history and history[-1] is wp and wp.log_filename == "dummy_telemetry"
    assert [w.time_since_start for w in history] == sorted(w.time_since_start for w in history)
    for brand, expected in zip((("Shearwater", "Perdix 2"), ("Garmin", "mk3i")), _FORCED_EXPECT[state]):
        s, phase, _, _ = stop_phase(brand[0], brand[1], wp, history)
        notice = active_notice(brand[0], brand[1], wp, history)
        assert (s, phase, notice["text"] if notice else None) == expected, (brand, state)
        assert s == STATE_OUTER[state] or s == "safety_stop" or (brand[0] == "Garmin" and state in ("safety_pending", "safety_done"))
    if state == "low_gas":
        assert tank_pressure_state("Shearwater", "Perdix 2", wp.primary_tank_pressure) == "reserve"
    # the original is untouched
    assert base.deco_stop_depth is None and base.dive_alerts == []


def test_forced_dive_auto_and_normal():
    from utils.dummy_telemetry import forced_dive
    dive = build_dummy_dive("single_tank")
    wp = waypoint_at(dive, 600)
    assert forced_dive(wp, "auto") == (wp, None)
    normal, history = forced_dive(waypoint_at(dive, 1530), "normal")
    assert history is None and resolve_state("Shearwater", "Perdix 2", normal) == "normal"


def test_apply_state_normal_suppresses_natural_safety_stop():
    dive = build_dummy_dive("single_tank")
    at_stop = waypoint_at(dive, 1530)  # 5 m after a 30 m dive
    assert resolve_state("Shearwater", "Perdix 2", at_stop) == "safety_stop"
    assert resolve_state("Shearwater", "Perdix 2", apply_state(at_stop, "normal")) == "normal"


def test_apply_state_auto_returns_same_waypoint():
    dive = build_dummy_dive("single_tank")
    wp = waypoint_at(dive, 600)
    assert apply_state(wp, "auto") is wp
    assert apply_state(wp, "not-a-state") is wp
