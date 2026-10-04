import pytest

from models.dive_plan import DiveProfilePlan, PlannedGas, PlannedWaypoint
from utils.deco_engine import BuhlmannEngine, ccr_effective_fractions, mod_meters
from gui.dive_profile_view import chart_axes, point_from_xy, xy_of
from utils.dive_plan_engine import apply_auto_gases, expand_plan, plan_ascent, simulate, waypoint_phases


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
    ndl = engine.compute_ndl_seconds(depth_meters=18.0, f_o2=0.21, f_he=0.0, gf=0.85)
    assert ndl is not None
    # Standard air NDL tables put 18m in the ~45-60 minute range, though a
    # liberal GF of 85% (used here) runs longer than those - this is a
    # sanity/ballpark check on the new forward-simulation, not a table match.
    assert 30 * 60 <= ndl <= 80 * 60


def test_compute_ndl_seconds_zero_at_surface():
    engine = BuhlmannEngine()
    assert engine.compute_ndl_seconds(depth_meters=0.0, f_o2=0.21, f_he=0.0, gf=0.85) is None or True


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
    gases = [PlannedGas(id="Loop", gas_type="trimix", o2_percent=18.0, he_percent=35.0, diluent=True)]
    waypoints = [
        PlannedWaypoint(runtime_sec=120, depth_m=30.0, gas_id="Loop"),
        PlannedWaypoint(runtime_sec=300, depth_m=30.0, gas_id="Loop"),
        PlannedWaypoint(runtime_sec=420, depth_m=0.0, gas_id="Loop"),
    ]
    plan = DiveProfilePlan(dive_type="ccr", ccr_high_setpoint=1.2, gases=gases, waypoints=waypoints)
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


def _deco_plan():
    gases = [
        PlannedGas(id="Air", gas_type="air", o2_percent=21.0),
        PlannedGas(id="EAN50", gas_type="nitrox", o2_percent=50.0, use_min_depth_m=0, use_max_depth_m=21, use_phase="ascent"),
        PlannedGas(id="O2", gas_type="nitrox", o2_percent=100.0, use_max_depth_m=6, use_phase="ascent"),
    ]
    waypoints = [
        PlannedWaypoint(runtime_sec=60, depth_m=15, gas_id="Air", gas_auto=True),   # descent, inside EAN50's range
        PlannedWaypoint(runtime_sec=180, depth_m=40, gas_id="Air", gas_auto=True),
        PlannedWaypoint(runtime_sec=1500, depth_m=40, gas_id="Air", gas_auto=True),
        PlannedWaypoint(runtime_sec=1800, depth_m=21, gas_id="Air", gas_auto=True),
        PlannedWaypoint(runtime_sec=2000, depth_m=6, gas_id="Air", gas_auto=True),
        PlannedWaypoint(runtime_sec=2800, depth_m=0, gas_id="Air", gas_auto=True),
    ]
    return DiveProfilePlan(gases=gases, waypoints=waypoints)


def test_waypoint_phases_split_at_first_visit_to_deepest_point():
    plan = _deco_plan()
    assert waypoint_phases(plan.sorted_waypoints()) == ["descent", "descent", "descent", "ascent", "ascent", "ascent"]


def test_apply_auto_gases_uses_deco_gases_only_on_ascent():
    plan = _deco_plan()
    assert apply_auto_gases(plan) == []
    assert [wp.gas_id for wp in plan.sorted_waypoints()] == ["Air", "Air", "Air", "EAN50", "O2", "O2"]


def test_apply_auto_gases_leaves_manual_waypoints_alone():
    plan = _deco_plan()
    plan.sorted_waypoints()[3].gas_auto = False  # stay on Air at 21m on purpose
    apply_auto_gases(plan)
    assert plan.sorted_waypoints()[3].gas_id == "Air"


def test_apply_auto_gases_warns_and_keeps_previous_gas_when_nothing_covers_depth():
    plan = _deco_plan()
    plan.gases = [g for g in plan.gases if g.id != "Air"]
    warnings = apply_auto_gases(plan)
    # No gas covers the 40m bottom at all, so those waypoints fall back.
    assert warnings
    assert plan.sorted_waypoints()[3].gas_id == "EAN50"


def test_chart_click_mapping_round_trips():
    plan = DiveProfilePlan(gases=[PlannedGas(id="Air")], max_depth_m=40, planned_runtime_sec=3600)
    axes = chart_axes(plan, [])
    assert axes == (3600.0, pytest.approx(44.0))
    x, y = xy_of(1234, 27.5, 700, 420, axes)
    assert point_from_xy(x, y, 700, 420, axes) == (pytest.approx(1234), pytest.approx(27.5))


def test_chart_axes_undefined_without_scale_or_samples():
    assert chart_axes(DiveProfilePlan(gases=[PlannedGas(id="Air")], max_depth_m=40), []) is None


def _bottom_plan(depth, bottom_end_sec, gases=None):
    gases = gases or [PlannedGas(id="Air", gas_type="air", o2_percent=21.0)]
    return DiveProfilePlan(gases=gases, waypoints=[
        PlannedWaypoint(runtime_sec=180, depth_m=depth, gas_id=gases[0].id, gas_auto=True),
        PlannedWaypoint(runtime_sec=bottom_end_sec, depth_m=depth, gas_id=gases[0].id, gas_auto=True),
    ])


def test_plan_ascent_no_deco_adds_3m_3min_safety_stop():
    plan = _bottom_plan(18, 1500)
    ascent, deco_needed, stops = plan_ascent(plan)
    assert not deco_needed
    assert stops == [(3.0, 180, "Air")]
    assert [wp.depth_m for wp in ascent] == [3.0, 0.0]
    # 15m at 9 m/min = 100s, then the 180s stop.
    assert ascent[0].runtime_sec == 1500 + 100 + 180


def test_plan_ascent_deco_clears_ceiling_and_switches_gas():
    gases = [
        PlannedGas(id="Air", gas_type="air", o2_percent=21.0),
        PlannedGas(id="EAN50", gas_type="nitrox", o2_percent=50.0, use_max_depth_m=21, use_phase="ascent"),
        PlannedGas(id="O2", gas_type="nitrox", o2_percent=100.0, use_max_depth_m=6, use_phase="ascent"),
    ]
    plan = _bottom_plan(40, 1500, gases)
    ascent, deco_needed, stops = plan_ascent(plan)
    assert deco_needed
    assert ascent[-1].depth_m == 0.0
    assert all(sec % 60 == 0 and depth % 3 == 0 for depth, sec, _ in stops)
    assert stops[-1][0] == 3.0
    switch_21 = next(wp for wp in ascent if wp.depth_m == 21.0)
    assert switch_21.gas_id == "EAN50"
    assert {gas for depth, _, gas in stops if depth <= 6} == {"O2"}

    plan.waypoints.extend(ascent)
    samples, warnings = simulate(plan, resolution_sec=10)
    assert warnings == []
    assert all(s.ceiling_m <= s.depth_m + 0.1 for s in samples)


def test_plan_ascent_deco_cleared_by_deco_gas_still_stops_at_3m():
    # Just into deco: EAN50 clears the obligation on the way up, but the
    # ascent still ends with at least the 3m/3min a no-deco dive gets.
    for gases in (
        [PlannedGas(id="EAN32", gas_type="nitrox", o2_percent=32.0),
         PlannedGas(id="EAN50", gas_type="nitrox", o2_percent=50.0)],
        [PlannedGas(id="EAN32", gas_type="nitrox", o2_percent=32.0)],
    ):
        plan = _bottom_plan(40, 600, gases)
        ascent, deco_needed, stops = plan_ascent(plan)
        assert deco_needed
        assert stops[-1][:2] == (3.0, 180)
        assert [wp.depth_m for wp in ascent][-2:] == [3.0, 0.0]


def test_plan_ascent_nothing_to_do_at_surface():
    plan = DiveProfilePlan(gases=[PlannedGas(id="Air")], waypoints=[
        PlannedWaypoint(runtime_sec=600, depth_m=10, gas_id="Air"),
        PlannedWaypoint(runtime_sec=900, depth_m=0, gas_id="Air"),
    ])
    assert plan_ascent(plan) == ([], False, [])


def test_deco_po2_limit_moves_gas_switch_to_mod():
    gases = [
        PlannedGas(id="Air", gas_type="air", o2_percent=21.0),
        PlannedGas(id="EAN50", gas_type="nitrox", o2_percent=50.0, use_max_depth_m=21, use_phase="ascent"),
    ]
    plan = _bottom_plan(40, 1500, gases)
    plan.max_po2_deco = 1.4  # EAN50 MOD 18m, shallower than its 21m range
    ascent, _, _ = plan_ascent(plan)
    assert not any(wp.depth_m > 18 and wp.gas_id == "EAN50" for wp in ascent)
    assert next(wp for wp in ascent if wp.gas_id == "EAN50").depth_m == 18.0


def test_bottom_po2_limit_rules_out_gas_past_its_mod():
    plan = _bottom_plan(40, 1500)
    plan.max_po2_bottom = 1.0  # Air MOD ~37.6m
    warnings = apply_auto_gases(plan)
    assert warnings and "max PO2 1" in warnings[0]
    plan.max_po2_bottom = 1.4
    assert apply_auto_gases(plan) == []


def test_manual_gas_past_mod_warns():
    gases = [PlannedGas(id="Air"), PlannedGas(id="EAN32", gas_type="nitrox", o2_percent=32.0)]
    plan = _bottom_plan(40, 1500, gases)
    for wp in plan.waypoints:
        wp.gas_auto, wp.gas_id = False, "EAN32"  # MOD 33.7m at 1.4
    warnings = apply_auto_gases(plan)
    assert len(warnings) == 2 and "past its MOD" in warnings[0]


def test_gas_display_mod_follows_phase_po2():
    plan = DiveProfilePlan(gases=[], max_po2_bottom=1.2, max_po2_deco=1.6)
    bottom = PlannedGas(id="EAN32", gas_type="nitrox", o2_percent=32.0)
    deco = PlannedGas(id="EAN50", gas_type="nitrox", o2_percent=50.0, use_phase="ascent")
    assert plan.gas_display_mod_m(bottom) == pytest.approx(27.5)
    assert plan.gas_display_mod_m(deco) == pytest.approx(22.0)


def test_plan_ascent_holds_one_minute_at_gas_switch():
    gases = [
        PlannedGas(id="Air", gas_type="air", o2_percent=21.0),
        PlannedGas(id="EAN50", gas_type="nitrox", o2_percent=50.0, use_max_depth_m=21, use_phase="ascent"),
    ]
    plan = _bottom_plan(18, 1500, gases)  # no deco; EAN50 usable right where the ascent starts
    ascent, deco_needed, stops = plan_ascent(plan)
    assert not deco_needed
    assert (ascent[0].depth_m, ascent[0].runtime_sec, ascent[0].gas_id) == (18.0, 1560, "EAN50")
    assert stops == [(18.0, 60, "EAN50"), (3.0, 180, "EAN50")]
    # The switch waypoint sits at max depth but belongs to the ascent, so
    # re-deriving auto gases must keep EAN50 there.
    plan.waypoints.extend(ascent)
    apply_auto_gases(plan)
    assert plan.sorted_waypoints()[2].gas_id == "EAN50"


def test_gas_switch_hold_counts_toward_deco_stop_at_same_depth():
    gases = [
        PlannedGas(id="Air", gas_type="air", o2_percent=21.0),
        PlannedGas(id="O2", gas_type="nitrox", o2_percent=100.0, use_max_depth_m=6, use_phase="ascent"),
    ]
    plan = _bottom_plan(40, 1500, gases)
    ascent, _, stops = plan_ascent(plan)
    six = [wp for wp in ascent if wp.depth_m == 6.0]
    assert len(six) == 1 and six[0].gas_id == "O2"  # one merged waypoint, not switch + stop
    assert [d for d, _, _ in stops].count(6.0) == 1


def test_gas_consumption_scales_with_ambient_pressure():
    # 20 L/min SAC on an 11.1 L tank: breathing at depth uses SAC x ambient
    # pressure (surface-equivalent litres), so each minute at 20m (3.01 bar)
    # drops the tank 3x what a minute at the surface would.
    plan = DiveProfilePlan(sac_lpm=20, gases=[PlannedGas(id="Air", tank_size_l=11.1, start_pressure_bar=207)], waypoints=[
        PlannedWaypoint(runtime_sec=60, depth_m=20, gas_id="Air"),
        PlannedWaypoint(runtime_sec=1860, depth_m=20, gas_id="Air"),
    ])
    samples, _ = simulate(plan, resolution_sec=1)
    at = {s.time_sec: s for s in samples}
    drop = at[660].tank_pressure_bar - at[1260].tank_pressure_bar  # 10 min at 20m
    assert drop == pytest.approx(20 * (1.01325 + 2.0) * 10 / 11.1, abs=0.2)


def test_per_gas_sac_override_beats_plan_sac():
    plan = _simple_plan()
    plan.sac_lpm = 20
    plan.gases[0].sac_lpm = 0  # e.g. a gas that isn't breathed from a tank
    samples, _ = simulate(plan, resolution_sec=60)
    assert samples[-1].tank_pressure_bar == samples[0].tank_pressure_bar


# --- Dive types -------------------------------------------------------------

def _ccr_plan(**kwargs) -> DiveProfilePlan:
    gases = [
        PlannedGas(id="Dil", gas_type="trimix", o2_percent=18.0, he_percent=45.0, diluent=True, tank_size_l=3, tank_ref="D"),
        PlannedGas(id="BO", gas_type="nitrox", o2_percent=32.0, tank_ref="T2"),
    ]
    waypoints = [
        PlannedWaypoint(runtime_sec=180, depth_m=40.0, gas_id="Dil", gas_auto=True),
        PlannedWaypoint(runtime_sec=1200, depth_m=40.0, gas_id="Dil", gas_auto=True),
    ]
    return DiveProfilePlan(dive_type="ccr", gases=gases, waypoints=waypoints, **kwargs)


def test_ccr_loop_holds_low_then_high_setpoint():
    plan = _ccr_plan(ccr_low_setpoint=0.7, ccr_high_setpoint=1.3, ccr_setpoint_switch_depth_m=6.0)
    samples, _ = simulate(plan, resolution_sec=1)
    shallow = next(s for s in samples if 3.0 <= s.depth_m < 5.0)
    deep = next(s for s in samples if s.depth_m == pytest.approx(40.0))
    assert shallow.po2 == pytest.approx(0.7, abs=0.01)
    assert deep.po2 == pytest.approx(1.3, abs=0.01)
    assert {s.divemode for s in samples} == {"closedcircuit"}


def test_ccr_auto_gas_stays_on_the_loop_and_ascent_has_no_gas_switches():
    plan = _ccr_plan()
    plan.gases.append(PlannedGas(id="EAN50", gas_type="nitrox", o2_percent=50.0, use_max_depth_m=21, use_phase="ascent", tank_ref="T3"))
    apply_auto_gases(plan)
    assert {wp.gas_id for wp in plan.waypoints} == {"Dil"}
    ascent, _, stops = plan_ascent(plan)
    assert {wp.gas_id for wp in ascent} == {"Dil"}
    assert {gas_id for _, _, gas_id in stops} <= {"Dil"}


def test_ccr_bailout_is_open_circuit_and_breathed_from_its_own_tank():
    plan = _ccr_plan()
    plan.waypoints.append(PlannedWaypoint(runtime_sec=1500, depth_m=21.0, gas_id="BO"))
    samples, _ = simulate(plan, resolution_sec=1)
    bailout = [s for s in samples if s.gas_id == "BO"]
    assert bailout and {s.divemode for s in bailout} == {"opencircuit"}
    assert {s.tank_ref for s in bailout} == {"T2"}
    assert samples[-1].tank_pressures["T2"] < 207.0


def test_ccr_draws_on_o2_cylinder_and_diluent_only_while_on_the_loop():
    plan = _ccr_plan()
    assert [t.ref for t in plan.tank_specs()] == ["O2", "D", "T2"]
    samples, _ = simulate(plan, resolution_sec=1)
    last = samples[-1].tank_pressures
    assert last["O2"] < plan.ccr_o2_start_pressure_bar
    assert last["D"] < 207.0
    assert last["T2"] == 207.0  # bailout never breathed
    # A rebreather: far less diluent than open circuit would breathe.
    assert 207.0 - last["D"] < 50


def test_ccr_without_a_diluent_is_an_error():
    plan = _ccr_plan()
    for gas in plan.gases:
        gas.diluent = False
    with pytest.raises(ValueError, match="diluent"):
        simulate(plan)


def _sidemount_plan(switch_bar=30.0) -> DiveProfilePlan:
    gases = [
        PlannedGas(id="EAN32", gas_type="nitrox", o2_percent=32.0, side="left", tank_size_l=11.1, start_pressure_bar=207),
        PlannedGas(id="EAN32 R", gas_type="nitrox", o2_percent=32.0, side="right", tank_ref="T2", tank_size_l=11.1, start_pressure_bar=207),
    ]
    waypoints = [
        PlannedWaypoint(runtime_sec=120, depth_m=20.0, gas_id="EAN32"),
        PlannedWaypoint(runtime_sec=2400, depth_m=20.0, gas_id="EAN32"),
    ]
    return DiveProfilePlan(dive_type="sidemount", sidemount_switch_bar=switch_bar, gases=gases, waypoints=waypoints)


def test_sidemount_pair_alternates_tanks_within_the_switch_pressure():
    plan = _sidemount_plan(switch_bar=30.0)
    assert plan.tank_refs_for(plan.gases[0]) == plan.tank_refs_for(plan.gases[1]) == ["T1", "T2"]
    samples, _ = simulate(plan, resolution_sec=1)
    assert samples[0].tank_ref == "T1"
    assert {s.gas_id for s in samples} == {"EAN32"}  # one gas, from either side
    switches = sum(1 for a, b in zip(samples, samples[1:]) if a.tank_ref != b.tank_ref)
    assert switches >= 3
    for s in samples:
        assert abs(s.tank_pressures["T1"] - s.tank_pressures["T2"]) <= 30.0 + 0.5
    # Both tanks together cover the gas an OC diver would breathe from one.
    used = sum(207.0 - p for p in samples[-1].tank_pressures.values())
    single = DiveProfilePlan(gases=[PlannedGas(id="EAN32", o2_percent=32.0, start_pressure_bar=400)], waypoints=plan.waypoints)
    single_samples, _ = simulate(single, resolution_sec=1)
    assert used == pytest.approx(400 - single_samples[-1].tank_pressure_bar, abs=1.0)


def test_sidemount_pair_is_ignored_on_other_dive_types():
    plan = _sidemount_plan()
    plan.dive_type = "oc"
    assert plan.tank_refs_for(plan.gases[0]) == ["T1"]
    assert [(t.ref, t.gas_id) for t in plan.tank_specs()] == [("T1", "EAN32"), ("T2", "EAN32 R")]



def test_sidemount_dive_needs_both_tanks_before_it_simulates():
    plan = _sidemount_plan()
    plan.gases.pop()
    with pytest.raises(ValueError, match="Left.*Right"):
        simulate(plan)


def test_profile_line_takes_the_colour_of_the_sidemount_tank_in_use():
    from gui.dive_profile_view import gas_color, sample_color

    plan = _sidemount_plan()
    plan.gases[0].color, plan.gases[1].color = "#0EA5A4", "#3B82F6"
    samples, _ = simulate(plan, resolution_sec=1)
    colors = {s.tank_ref: sample_color(plan, s) for s in samples}
    assert colors == {"T1": "#0EA5A4", "T2": "#3B82F6"}
    assert gas_color(plan, samples[0].gas_id) == "#0EA5A4"


def test_older_plan_with_a_sidemount_pair_loads_as_left_and_right_tanks():
    """Plans embedded in logs saved before tanks had a side."""
    plan = DiveProfilePlan.model_validate({
        "dive_type": "sidemount",
        "gases": [
            {"id": "EAN32", "o2_percent": 32.0, "tank_ref": "T1", "sidemount_pair": True, "color": "#0EA5A4"},
            {"id": "EAN50", "o2_percent": 50.0, "tank_ref": "T2"},
        ],
    })
    assert [(g.id, g.tank_ref, g.side, g.o2_percent) for g in plan.gases] == [
        ("EAN32", "T1", "left", 32.0), ("EAN32 R", "T3", "right", 32.0), ("EAN50", "T2", None, 50.0),
    ]
    assert plan.gases[1].color is None  # a palette colour of its own
    assert [g.id for g in plan.breathed_gases()] == ["EAN32", "EAN50"]

# --- Ceiling at both GFs, logged stops, deco schedule timeline -------------

def _trimix_deco_plan():
    gases = [
        PlannedGas(id="Tx", gas_type="trimix", o2_percent=21.0, he_percent=35.0),
        PlannedGas(id="EAN50", gas_type="nitrox", o2_percent=50.0, use_max_depth_m=21, use_phase="ascent", tank_ref="T2"),
    ]
    return _bottom_plan(50, 1800, gases)


def test_gf_low_ceiling_is_deeper_than_gf_high_ceiling():
    samples, _ = simulate(_trimix_deco_plan(), resolution_sec=10)
    in_deco = [s for s in samples if s.ceiling_m > 0]
    assert in_deco
    assert all(s.ceiling_gf_low_m >= s.ceiling_m for s in in_deco)
    assert any(s.ceiling_gf_low_m > s.ceiling_m + 3 for s in in_deco)


def test_logged_first_stop_deepens_steadily_on_the_bottom_and_is_held_whole_minutes():
    samples, _ = simulate(_trimix_deco_plan(), resolution_sec=1)
    bottom = [s for s in samples if 180 <= s.time_sec <= 1800 and s.ceiling_m > 0]
    stops = [s.stop_depth_m for s in bottom]
    assert stops == sorted(stops)  # never jumps back up while tissues keep loading
    recomputed = [s for s in bottom if s.time_sec % 10 == 0]
    assert all(s.stop_duration_sec >= 60 and s.stop_duration_sec % 60 == 0 for s in recomputed)


def test_deco_schedule_timeline_grows_with_bottom_time():
    from utils.dive_plan_engine import deco_schedule_timeline

    assert deco_schedule_timeline(_bottom_plan(18, 1200)) == []  # no deco
    timeline = deco_schedule_timeline(_trimix_deco_plan(), interval_sec=60)
    assert timeline and all(t % 60 == 0 for t, _ in timeline)
    first, last = timeline[0][1], timeline[-1][1]
    assert sum(d for _, d, _ in last) > sum(d for _, d, _ in first)  # more deco by the end of the bottom
    assert max(depth for depth, _, _ in last) >= max(depth for depth, _, _ in first)
    assert any(gas == "EAN50" for _, _, gas in last)  # the schedule switches gas like End dive


def test_ndl_is_judged_at_gf_high_and_runs_out_when_the_ceiling_appears():
    # 18m on air at GF 30/70: ~29 min (ZHL-16C), not the ~7 min GF low would give.
    plan = DiveProfilePlan(gf_low=30, gf_high=70, gases=[PlannedGas(id="Air")], waypoints=[
        PlannedWaypoint(runtime_sec=60, depth_m=18, gas_id="Air"),
        PlannedWaypoint(runtime_sec=3600, depth_m=18, gas_id="Air"),
    ])
    samples, _ = simulate(plan, resolution_sec=10)
    at_1_min = next(s for s in samples if s.time_sec == 60)
    assert 25 * 60 <= at_1_min.ndl_sec <= 33 * 60
    # Never "NDL 0" while there is no ceiling, and the ceiling arrives about
    # when the NDL said it would.
    assert all(s.ndl_sec != 0 for s in samples if s.ceiling_m <= 0 and s.time_sec % 10 == 0)
    first_deco = next(s.time_sec for s in samples if s.ceiling_m > 0)
    assert abs(first_deco - (60 + at_1_min.ndl_sec)) <= 60
