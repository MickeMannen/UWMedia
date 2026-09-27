import pytest
from pathlib import Path

from models.dive_plan import DiveProfilePlan, PlannedGas, PlannedWaypoint
from parsers.uddf import UDDFParser
from parsers.uddf_writer import write_uddf
from utils.dive_plan_engine import simulate


def _deco_plan() -> DiveProfilePlan:
    gases = [
        PlannedGas(id="Bottom", gas_type="trimix", o2_percent=21.0, he_percent=30.0, tank_ref="T1"),
        PlannedGas(id="Deco50", gas_type="nitrox", o2_percent=50.0, tank_ref="T2"),
    ]
    waypoints = [
        PlannedWaypoint(runtime_sec=120, depth_m=40.0, gas_id="Bottom"),
        PlannedWaypoint(runtime_sec=1200, depth_m=40.0, gas_id="Bottom"),
        PlannedWaypoint(runtime_sec=1400, depth_m=21.0, gas_id="Deco50"),
        PlannedWaypoint(runtime_sec=1700, depth_m=0.0, gas_id="Deco50"),
    ]
    return DiveProfilePlan(name="Round-trip test", gf_low=30, gf_high=70, waypoints=waypoints, gases=gases)


def test_round_trip_write_and_parse(tmp_path):
    plan = _deco_plan()
    samples, warnings = simulate(plan, resolution_sec=1)
    assert samples

    out_path = tmp_path / "synthetic.uddf"
    write_uddf(plan, samples, out_path)
    assert out_path.exists()

    dives = UDDFParser().parse(out_path)
    assert len(dives) == 1
    dive = dives[0]
    assert dive.device == "Perdix 2"

    waypoints = dive.waypoints
    assert len(waypoints) == len(samples)

    # Depth/time round-trip exactly.
    assert waypoints[0].time_since_start == samples[0].time_sec
    assert waypoints[-1].depth == pytest.approx(samples[-1].depth_m, abs=0.1)

    # Some waypoint at the 40m bottom phase should show a populated NDL or
    # be past it into deco - either way ndl/deco_stop_depth shouldn't both
    # be silently empty for the whole dive.
    assert any(wp.ndl is not None for wp in waypoints) or any(
        (wp.deco_stop_depth or 0) > 0 for wp in waypoints
    )

    # The deco phase should round-trip a logged mandatory stop.
    deco_waypoints = [wp for wp in waypoints if (wp.deco_stop_depth or 0) > 0]
    assert deco_waypoints, "expected at least one waypoint with a logged decostop"

    # Gas switch to the 50% deco gas should be visible via tank pressure
    # keyed by its own tank ref once it comes into use.
    assert any("T2" in wp.tanks for wp in waypoints)

    # NDL-before-deco sanity: nodecotime present somewhere before the switch.
    pre_switch = [wp for wp in waypoints if wp.time_since_start < 1400]
    assert any(wp.ndl is not None for wp in pre_switch)


def test_write_uddf_requires_samples(tmp_path):
    with pytest.raises(ValueError):
        write_uddf(_deco_plan(), [], tmp_path / "empty.uddf")


def test_uddf_writes_tank_volume(tmp_path):
    from models.dive_plan import DiveProfilePlan, PlannedGas, PlannedWaypoint
    from parsers.uddf_writer import write_uddf
    from utils.dive_plan_engine import simulate

    plan = DiveProfilePlan(
        gases=[PlannedGas(id="Air", tank_size_l=12.0, start_pressure_bar=232.0)],
        waypoints=[PlannedWaypoint(runtime_sec=120, depth_m=10, gas_id="Air"),
                   PlannedWaypoint(runtime_sec=600, depth_m=0, gas_id="Air")],
    )
    samples, _ = simulate(plan, resolution_sec=10)
    out = tmp_path / "t.uddf"
    write_uddf(plan, samples, out)
    text = out.read_text()
    assert "<tankvolume>0.012</tankvolume>" in text
    assert "<tankpressurebegin>23200000</tankpressurebegin>" in text


def test_older_builder_uddf_without_tts_ends_deco_where_the_file_does():
    # test_data/logs/DecoTest_2.uddf was saved before the builder logged TTS or
    # kept NDL after the last stop: the sample after the final <decostop> has
    # neither. The file logs its own stops, so that means "no stop" - not a
    # ceiling of our own making that kept the DECO box and a 9-minute TTS on
    # screen down to the surface. The recompute runs with the file's GF 40/85.
    import io
    import contextlib
    from parsers.uddf import UDDFParser
    from utils.hud_rules_engine import resolve_state

    with contextlib.redirect_stdout(io.StringIO()):
        dive = UDDFParser().parse(Path("test_data/logs/DecoTest_2.uddf"))[0]
    at = {wp.time_since_start: wp for wp in dive.waypoints}
    assert resolve_state("Garmin", "x50i", at[3815], dive.waypoints) == "deco"
    assert at[3815].next_stop_depth == 3.0
    for t in (3816, 3830, 3850):
        assert resolve_state("Garmin", "x50i", at[t], dive.waypoints) == "normal", t
        assert at[t].deco_stop_depth == 0.0 and at[t].next_stop_depth == 0.0
        assert at[t].tts is not None and at[t].tts < 60


def test_shearwater_uddf_gets_sac_and_gtr_computed_from_its_pressures():
    import io
    import contextlib
    from parsers.uddf import UDDFParser

    with contextlib.redirect_stdout(io.StringIO()):
        dive = UDDFParser().parse(Path("test_data/logs/submersion_dives/issue_71_perdix_single_tank.uddf"))[0]
    at = {wp.time_since_start: wp for wp in dive.waypoints}
    assert at[30].pressure_sac is None                      # "wait" while data is collected
    assert 0.5 < at[600].pressure_sac < 3.0                 # a plausible bar/min at the surface
    assert at[600].air_remaining is not None and 0 < at[600].air_remaining < 60 * 60
