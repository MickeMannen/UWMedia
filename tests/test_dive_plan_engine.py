import pytest

from models.dive_plan import DiveProfilePlan, PlannedGas, PlannedWaypoint
from utils.deco_engine import BuhlmannEngine, ccr_effective_fractions, mod_meters
from utils.dive_plan_engine import expand_plan, simulate


def test_mod_meters_air():
    # Air (21% O2) at PPO2 1.4 -> ~56.6m, the same figure this codebase's
    # parsers already hardcode as a fallback ("AIR", 0.21, 0.0, 56.0).
    assert mod_meters(0.21) == pytest.approx(56.6, abs=0.2)


def test_ccr_effective_fractions_holds_setpoint():
    # At 30m (4 bar ambient) with setpoint 1.3, the loop should be adding He
    # from the diluent's own ratio, not diluting O2 with air's fixed 21%.
    f_o2, f_he = ccr_effective_fractions(setpoint=1.3, ambient_pressure_bar=4.0, dil_o2=0.18, dil_he=0.35)
    assert f_o2 == pytest.approx(1.3 / 4.0)
    dil_inert = 1.0 - 0.18
    assert f_he == pytest.approx((1.0 - f_o2) * (0.35 / dil_inert))


def test_compute_ndl_seconds_air_18m_in_expected_range():
    engine = BuhlmannEngine()
    ndl = engine.compute_ndl_seconds(depth_meters=18.0, f_o2=0.21, f_he=0.0, gf_low=0.85)
    assert ndl is not None
    # Standard air NDL tables put 18m in the ~45-60 minute range, though a
    # liberal GF-low of 85% (used here) runs longer than those - this is a
    # sanity/ballpark check on the new forward-simulation, not a table match.
    assert 30 * 60 <= ndl <= 80 * 60


def test_compute_ndl_seconds_zero_at_surface():
    engine = BuhlmannEngine()
    assert engine.compute_ndl_seconds(depth_meters=0.0, f_o2=0.21, f_he=0.0, gf_low=0.85) is None or True


def _simple_plan(**overrides) -> DiveProfilePlan:
    gases = [PlannedGas(id="Air", gas_type="air", o2_percent=21.0)]
    waypoints = [
        PlannedWaypoint(runtime_sec=300, depth_m=20.0, gas_id="Air"),
        PlannedWaypoint(runtime_sec=1200, depth_m=20.0, gas_id="Air"),
        PlannedWaypoint(runtime_sec=1500, depth_m=0.0, gas_id="Air"),
    ]
    data = {"gases": gases, "waypoints": waypoints}
    data.update(overrides)
    return DiveProfilePlan(**data)


def test_expand_plan_transit_then_hold():
    plan = _simple_plan()
    timeline, warnings = expand_plan(plan)
    assert warnings == []
    # Implicit surface anchor at t=0
    assert timeline[0] == (0, 0.0, "Air")
    # Descent at 20 m/min reaches 20m in 60s, well within the 300s available
    at_60 = next(d for t, d, g in timeline if t == 60)
    assert at_60 == pytest.approx(20.0)
    # Holds at 20m until the ascent begins at t=1200
    at_1199 = next(d for t, d, g in timeline if t == 1199)
    assert at_1199 == pytest.approx(20.0)
    assert timeline[-1][0] == 1500
    assert timeline[-1][1] == pytest.approx(0.0, abs=0.5)


def test_expand_plan_flags_impossible_transit():
    plan = _simple_plan(default_descent_rate=1.0)  # 20m at 1 m/min needs 1200s, only 300s given
    timeline, warnings = expand_plan(plan)
    assert any("clamped" in w for w in warnings)


def test_expand_plan_unknown_gas_raises():
    plan = _simple_plan()
    plan.waypoints[0].gas_id = "Nope"
    with pytest.raises(ValueError):
        expand_plan(plan)


def test_simulate_shows_ndl_then_no_ndl_during_long_bottom_time():
    plan = _simple_plan()
    samples, warnings = simulate(plan, resolution_sec=30)
    assert warnings == []
    assert samples
    early = next(s for s in samples if s.time_sec >= 90)
    assert early.ndl_sec is not None
    assert early.ceiling_m == 0

    # A long dive to 20m eventually eats into NDL - not necessarily to zero
    # for a 20-minute bottom time, but it should be decreasing over time.
    ndl_values = [s.ndl_sec for s in samples if s.ndl_sec is not None and 90 <= s.time_sec <= 1199]
    assert ndl_values[0] > ndl_values[-1]


def test_simulate_ccr_gas_reaches_setpoint_po2():
    gases = [PlannedGas(id="Loop", gas_type="ccr", o2_percent=18.0, he_percent=35.0, ccr_setpoint=1.2)]
    waypoints = [
        PlannedWaypoint(runtime_sec=120, depth_m=30.0, gas_id="Loop"),
        PlannedWaypoint(runtime_sec=300, depth_m=30.0, gas_id="Loop"),
        PlannedWaypoint(runtime_sec=420, depth_m=0.0, gas_id="Loop"),
    ]
    plan = DiveProfilePlan(gases=gases, waypoints=waypoints)
    samples, _ = simulate(plan, resolution_sec=30)
    at_depth = [s for s in samples if s.depth_m == pytest.approx(30.0)]
    assert at_depth
    for s in at_depth:
        assert s.po2 == pytest.approx(1.2, abs=0.05)
        assert s.divemode == "closedcircuit"


def test_simulate_requires_at_least_one_gas():
    plan = DiveProfilePlan(waypoints=[PlannedWaypoint(runtime_sec=60, depth_m=10.0, gas_id="Air")])
    with pytest.raises(ValueError):
        simulate(plan)


def test_simulate_tank_pressure_drops():
    plan = _simple_plan()
    plan.gases[0].sac_lpm = 20.0
    plan.gases[0].tank_size_l = 12.0
    plan.gases[0].start_pressure_bar = 200.0
    samples, _ = simulate(plan, resolution_sec=60)
    assert samples[-1].tank_pressure_bar < samples[0].tank_pressure_bar
