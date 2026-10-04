"""
Dive Profile Builder log writers - UDDF (parsers/uddf_writer.py), Garmin
FIT (parsers/fit_writer.py) and Subsurface XML (parsers/subsurface_writer.py)
- round-tripped through UWMedia's own parsers for each dive type.
"""
from datetime import datetime

import pytest

from models.dive_plan import DiveProfilePlan, PlannedGas, PlannedWaypoint
from parsers.fit_writer import write_fit
from parsers.garmin import GarminParser
from parsers.subsurface import SubsurfaceParser
from parsers.subsurface_writer import write_subsurface
from parsers.uddf import UDDFParser
from parsers.uddf_writer import write_uddf
from utils.dive_plan_engine import simulate

START = datetime(2026, 9, 20, 10, 15, 0)
WRITERS = {
    "uddf": (write_uddf, UDDFParser),
    "fit": (write_fit, GarminParser),
    "ssrf": (write_subsurface, SubsurfaceParser),
}


def _waypoints(gas_id):
    return [
        PlannedWaypoint(runtime_sec=120, depth_m=30.0, gas_id=gas_id),
        PlannedWaypoint(runtime_sec=1500, depth_m=30.0, gas_id=gas_id),
        PlannedWaypoint(runtime_sec=1800, depth_m=5.0, gas_id=gas_id),
        PlannedWaypoint(runtime_sec=2100, depth_m=0.0, gas_id=gas_id),
    ]


def _plan(dive_type):
    if dive_type == "ccr":
        gases = [
            PlannedGas(id="Dil", gas_type="trimix", o2_percent=21.0, he_percent=35.0, diluent=True, tank_size_l=3, tank_ref="D"),
            PlannedGas(id="BO", gas_type="nitrox", o2_percent=32.0, tank_ref="T2"),
        ]
    elif dive_type == "sidemount":
        gases = [
            PlannedGas(id="EAN32", gas_type="nitrox", o2_percent=32.0, side="left", start_pressure_bar=232),
            PlannedGas(id="EAN32 R", gas_type="nitrox", o2_percent=32.0, side="right", tank_ref="T2", start_pressure_bar=232),
        ]
    else:
        gases = [PlannedGas(id="EAN32", gas_type="nitrox", o2_percent=32.0, start_pressure_bar=232)]
    return DiveProfilePlan(
        dive_type=dive_type, gases=gases, waypoints=_waypoints(gases[0].id),
        start_time=START, computer="Garmin Descent Mk3i", computer_serial="3486870757",
    )


def _round_trip(plan, fmt, tmp_path):
    samples, _ = simulate(plan, resolution_sec=1)
    writer, parser = WRITERS[fmt]
    path = tmp_path / f"dive.{fmt}"
    writer(plan, samples, path)
    dives = parser().parse(path)
    assert len(dives) == 1
    return samples, dives[0]


@pytest.mark.parametrize("fmt", WRITERS)
@pytest.mark.parametrize("dive_type", ["oc", "sidemount", "ccr"])
def test_round_trip_profile_start_and_tanks(fmt, dive_type, tmp_path):
    plan = _plan(dive_type)
    samples, dive = _round_trip(plan, fmt, tmp_path)

    assert dive.start_time == START
    assert len(dive.waypoints) == len(samples)
    assert max(wp.depth for wp in dive.waypoints) == pytest.approx(30.0, abs=0.01)
    assert dive.waypoints[-1].time_since_start == samples[-1].time_sec

    # Every tank comes back, in tank_specs order, with the simulated pressures.
    mid, parsed_mid = samples[len(samples) // 2], dive.waypoints[len(samples) // 2]
    expected = [mid.tank_pressures[t.ref] for t in plan.tank_specs()]
    assert [t.pressure_bar for t in parsed_mid.tanks.values()] == pytest.approx(expected, abs=0.1)
    if fmt != "fit":  # FIT only knows tanks by transmitter serial
        assert list(parsed_mid.tanks) == [t.ref for t in plan.tank_specs()]
    assert parsed_mid.po2 == pytest.approx(mid.po2, abs=0.01)


@pytest.mark.parametrize("fmt, device, manufacturer", [
    ("uddf", "Descent Mk3i", "Garmin"),
    ("fit", "descent_mk3i", "garmin"),
    ("ssrf", "Garmin Descent Mk3i", "Garmin"),
])
def test_round_trip_names_the_chosen_computer(fmt, device, manufacturer, tmp_path):
    _, dive = _round_trip(_plan("oc"), fmt, tmp_path)
    assert (dive.device, dive.manufactor) == (device, manufacturer)


def test_x50i_fit_round_trips_its_unmapped_product_id(tmp_path):
    plan = _plan("oc")
    plan.computer = "Garmin Descent X50i"
    _, dive = _round_trip(plan, "fit", tmp_path)
    assert dive.device == "descent_x50i"


@pytest.mark.parametrize("fmt", ["uddf", "ssrf"])
def test_shearwater_computer_in_xml_formats(fmt, tmp_path):
    plan = _plan("oc")
    plan.computer = "Shearwater Petrel"
    _, dive = _round_trip(plan, fmt, tmp_path)
    assert "Petrel" in dive.device and dive.manufactor == "Shearwater"


def test_fit_refuses_a_non_garmin_computer(tmp_path):
    plan = _plan("oc")
    plan.computer = "Shearwater Perdix 2"
    samples, _ = simulate(plan, resolution_sec=10)
    with pytest.raises(ValueError, match="Garmin"):
        write_fit(plan, samples, tmp_path / "dive.fit")


def test_uddf_marks_ccr_loop_and_setpoint(tmp_path):
    plan = _plan("ccr")
    samples, dive = _round_trip(plan, "uddf", tmp_path)
    assert {wp.divemode for wp in dive.waypoints} == {"closedcircuit"}
    text = (tmp_path / "dive.uddf").read_text()
    assert "<setpo2 setby=\"computer\">1.3</setpo2>" in text


def test_subsurface_marks_ccr_cylinders_and_dctype(tmp_path):
    _round_trip(_plan("ccr"), "ssrf", tmp_path)
    text = (tmp_path / "dive.ssrf").read_text()
    assert "dctype=\"CCR\"" in text
    assert "use=\"oxygen\"" in text and "use=\"diluent\"" in text


def test_subsurface_logs_sidemount_tank_switches_as_gaschanges(tmp_path):
    samples, _ = _round_trip(_plan("sidemount"), "ssrf", tmp_path)
    switches = 1 + sum(1 for a, b in zip(samples, samples[1:]) if a.tank_ref != b.tank_ref)
    assert (tmp_path / "dive.ssrf").read_text().count("name=\"gaschange\"") == switches


@pytest.mark.parametrize("writer", [w for w, _ in WRITERS.values()])
def test_writers_require_samples(writer, tmp_path):
    with pytest.raises(ValueError):
        writer(_plan("oc"), [], tmp_path / "empty")


@pytest.mark.parametrize("fmt", WRITERS)
def test_parsers_recompute_a_ceiling_for_deco_dives(fmt, tmp_path):
    plan = _plan("oc")
    plan.waypoints = [
        PlannedWaypoint(runtime_sec=180, depth_m=45.0, gas_id="EAN32"),
        PlannedWaypoint(runtime_sec=1500, depth_m=45.0, gas_id="EAN32"),
        PlannedWaypoint(runtime_sec=2400, depth_m=0.0, gas_id="EAN32"),
    ]
    plan.gases[0].o2_percent = 21.0
    _, dive = _round_trip(plan, fmt, tmp_path)
    assert any((wp.ceiling or 0) > 0 for wp in dive.waypoints)
    assert any((wp.next_stop_depth or 0) > 0 for wp in dive.waypoints)


def test_uddf_logged_ndl_means_no_deco_stop_yet(tmp_path):
    # The parser's own recompute (other GFs) mustn't invent a stop while the
    # file still logs an NDL - that flipped the HUD to DECO too early.
    plan = _plan("oc")
    samples, dive = _round_trip(plan, "uddf", tmp_path)
    for s, wp in zip(samples, dive.waypoints):
        if s.ndl_sec:
            assert not wp.deco_stop_depth
        if s.ceiling_m > 0 and s.depth_m > 0:
            assert s.stop_depth_m > 0  # recomputed the moment deco starts


# --- after deco clears the log says so: no stop, NDL 99+, TTS a direct ascent --

def _deco_plan_that_clears_on_the_way_up():
    from utils.dive_plan_engine import plan_ascent

    plan = DiveProfilePlan(
        gf_low=40, gf_high=85, computer="Garmin Descent X50i", start_time=START,
        gases=[PlannedGas(id="Air", gas_type="air", o2_percent=21.0)],
        waypoints=[PlannedWaypoint(runtime_sec=180, depth_m=45.0, gas_id="Air"),
                   PlannedWaypoint(runtime_sec=1500, depth_m=45.0, gas_id="Air")],
    )
    ascent, deco_needed, stops = plan_ascent(plan)
    assert deco_needed and stops
    plan.waypoints.extend(ascent)
    return plan


@pytest.mark.parametrize("fmt", WRITERS)
def test_after_the_last_deco_stop_the_log_reads_as_no_deco_with_a_short_tts(fmt, tmp_path):
    from utils.hud_rules_engine import resolve_state

    plan = _deco_plan_that_clears_on_the_way_up()
    samples, dive = _round_trip(plan, fmt, tmp_path)
    cleared = next(s.time_sec for s in samples if s.time_sec > 1500 and s.ceiling_m <= 0
                   and samples[samples.index(s) - 1].ceiling_m > 0)
    at = {wp.time_since_start: wp for wp in dive.waypoints}
    before, after = at[cleared - 1], at[cleared + 5]
    assert resolve_state("Garmin", "x50i", before, dive.waypoints) == "deco"
    assert resolve_state("Garmin", "x50i", after, dive.waypoints) == "normal"
    assert not after.deco_stop_depth and not after.next_stop_depth
    # TTS is the direct ascent from here (about 9 m/min), not the stops already done
    assert after.tts is not None and after.tts <= after.depth / 9.0 * 60 + 15
    # the sample's own TTS survives the round trip (Garmin FIT keeps it in the record)
    logged = next(s for s in samples if s.time_sec == cleared + 5)
    assert after.tts == logged.tts_sec
    if fmt != "fit":
        assert after.ndl == 99 * 60  # unbounded NDL logged as the 99+ cap


def test_no_deco_tts_includes_the_safety_stop_until_deco_has_been_done():
    from utils.dive_plan_engine import _no_deco_tts

    plan = DiveProfilePlan(default_ascent_rate=9.0)
    assert _no_deco_tts(plan, 18.0, 18.0, had_deco=False) == 120 + 180
    assert _no_deco_tts(plan, 18.0, 18.0, had_deco=True) == 120
    assert _no_deco_tts(plan, 9.0, 10.0, had_deco=False) == 60  # never past 11 m: no safety stop
    assert _no_deco_tts(plan, 3.0, 30.0, had_deco=False) == 20  # at the stop: only the ascent is known
    assert _no_deco_tts(plan, 0.0, 30.0, had_deco=False) == 0
