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
    assert max(depths) == 24.0
    # max_depth is cumulative and never decreases
    max_depths = [w.max_depth for w in dive.waypoints]
    assert max_depths == sorted(max_depths)
    # every field a bundled template shows is populated mid-dive
    wp = waypoint_at(dive, 12 * 60)
    assert wp.ndl and wp.tts and wp.dive_time == 12 * 60
    assert wp.primary_tank_pressure and wp.gasmix == "Nx32"
    assert wp.air_remaining and wp.heart_rate and wp.po2 and wp.gf is not None


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


@pytest.mark.parametrize("state", [s for s in STATE_OPTIONS if s != "auto"])
@pytest.mark.parametrize("manufacturer,model", [("Shearwater", "Perdix 2"), ("Garmin", "x50i"), (None, None)])
def test_apply_state_resolves_for_every_rule_set(state, manufacturer, model):
    dive = build_dummy_dive("single_tank")
    base = waypoint_at(dive, 12 * 60)  # naturally "normal": 24 m on the bottom
    forced = apply_state(base, state)
    assert resolve_state(manufacturer, model, forced) == state
    # original untouched
    assert base.deco_stop_depth is None and base.dive_alerts == []
    assert forced.log_filename == "dummy_telemetry"


def test_apply_state_normal_suppresses_natural_safety_stop():
    dive = build_dummy_dive("single_tank")
    at_stop = waypoint_at(dive, 40 * 60)  # 5 m after a 24 m dive
    assert resolve_state("Shearwater", "Perdix 2", at_stop) == "safety_stop"
    assert resolve_state("Shearwater", "Perdix 2", apply_state(at_stop, "normal")) == "normal"


def test_apply_state_auto_returns_same_waypoint():
    dive = build_dummy_dive("single_tank")
    wp = waypoint_at(dive, 600)
    assert apply_state(wp, "auto") is wp
    assert apply_state(wp, "not-a-state") is wp
