import pytest

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
