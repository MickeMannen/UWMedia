"""The Dive Profile Builder on a rebreather dive (conftest.synthetic_ccr_plan):
the setpoint switching at two depths, the logs it writes - setpoint in
force, three O2 cells, the O2 cylinder's own mix, a Descent's setpoint and
circuit alerts with no record PO2 - read back by UWMedia's own parsers, the
setpoints imported again, and plans saved with the old single switch depth.
Logs are written into tmp_path; nothing is copied from real dives."""
from datetime import datetime

import pytest

from conftest import synthetic_ccr_plan
from models.dive_plan import DiveProfilePlan
from parsers.fit_writer import write_fit
from parsers.registry import parse_log_file
from parsers.subsurface_writer import write_subsurface
from parsers.uddf_writer import write_uddf
from utils.dive_plan_engine import simulate
from utils.dive_plan_import import plan_from_log

START = datetime(2026, 3, 1, 9, 0)


def _setpoint_at(samples, t):
    return next(s for s in samples if s.time_sec >= t).setpoint


def test_setpoint_switches_at_two_depths():
    """Low until 8 m on the way down, high from there - also when the ascent
    passes 8 m again - and low once above 2 m."""
    plan = synthetic_ccr_plan(START)
    samples, _ = simulate(plan, resolution_sec=1)
    descent_8m = next(s for s in samples if s.depth_m > 8.0)
    assert _setpoint_at(samples, descent_8m.time_sec - 2) == 0.7 and descent_8m.setpoint == 1.3
    assert _setpoint_at(samples, 2400) == 1.3  # back on the loop at 6 m: still high
    assert next(s for s in samples if s.time_sec > 2400 and s.depth_m < 2.0).setpoint == 0.7
    assert all(s.setpoint is None and not s.cells for s in samples if s.divemode == "opencircuit")
    loop = next(s for s in samples if s.time_sec == 1000)
    assert len(loop.cells) == 3 and all(abs(c - loop.po2) <= 0.02 * loop.po2 + 0.005 for c in loop.cells)


def test_old_single_switch_depth_becomes_the_high_depth():
    plan = DiveProfilePlan(dive_type="ccr", ccr_setpoint_switch_depth_m=9.0)
    assert (plan.ccr_high_setpoint_depth_m, plan.ccr_low_setpoint_depth_m) == (9.0, 3.0)
    assert DiveProfilePlan(computer="Shearwater Petrel").computer == "Shearwater Petrel 3"
    assert DiveProfilePlan(computer="Shearwater Peregrine").computer == "Shearwater Peregrine TX"


@pytest.mark.parametrize("suffix, writer", [(".uddf", write_uddf), (".ssrf", write_subsurface)])
def test_uddf_and_subsurface_ccr_logs_read_back(tmp_path, suffix, writer):
    plan = synthetic_ccr_plan(START)
    samples, _ = simulate(plan, resolution_sec=2)
    path = tmp_path / f"ccr{suffix}"
    writer(plan, samples, path)
    dive, = parse_log_file(path)
    assert dive.is_ccr
    by_t = {w.time_since_start: w for w in dive.waypoints}
    deep, bailout, stop = by_t[1000], by_t[1700], by_t[2400]
    assert (deep.circuit, deep.setpoint, deep.gasmix) == ("CC", 1.3, "18/45")
    assert deep.po2_1 is not None and abs(deep.po2_1 - 1.3) < 0.03
    assert (bailout.circuit, bailout.setpoint, bailout.gasmix) == ("BO", None, "Nx50")
    assert bailout.po2_1 is not None  # the loop's last readings stay up (Petrel 3 Technical manual p.37)
    assert (bailout.diluent_o2_percent, bailout.diluent_he_percent) == (18.0, 45.0)
    assert (stop.circuit, stop.setpoint) == ("CC", 1.3)
    assert dive.waypoints[0].tanks["O2"].o2_percent == 100.0


def test_a_ccr_fit_is_like_a_descents(tmp_path):
    """No record po2; the setpoint comes from the switch alerts and
    dive_settings, the circuit from the gas modes, as on a real Descent."""
    plan = synthetic_ccr_plan(START, computer="Garmin Descent X50i")
    samples, _ = simulate(plan, resolution_sec=2)
    path = tmp_path / "ccr.fit"
    write_fit(plan, samples, path)
    dive, = parse_log_file(path)
    by_t = {w.time_since_start: w for w in dive.waypoints}
    alerts = [a for w in dive.waypoints for a in w.dive_alerts]
    assert alerts == ["setpoint_switch_auto_high", "switched_to_open_circuit", "switched_to_closed_circuit", "setpoint_switch_auto_low"]
    assert (by_t[1000].circuit, by_t[1000].setpoint, by_t[1000].po2) == ("CC", 1.3, 1.3)
    assert (by_t[1700].circuit, by_t[1700].gasmix) == ("BO", "Nx50")
    assert by_t[10].setpoint == 0.7


@pytest.mark.parametrize("suffix, writer", [(".uddf", write_uddf), (".ssrf", write_subsurface)])
def test_setpoints_and_switch_depths_import_again(tmp_path, suffix, writer):
    plan = synthetic_ccr_plan(START)
    plan.ccr_low_setpoint, plan.ccr_high_setpoint = 0.6, 1.2
    plan.ccr_high_setpoint_depth_m, plan.ccr_low_setpoint_depth_m = 10.0, 3.0
    samples, _ = simulate(plan, resolution_sec=1)
    path = tmp_path / f"ccr{suffix}"
    writer(plan, samples, path)
    dive, = parse_log_file(path)
    imported = plan_from_log(path, dive)  # from the log's samples (the embedded plan is another path)
    assert (imported.ccr_low_setpoint, imported.ccr_high_setpoint) == (0.6, 1.2)
    assert (imported.ccr_high_setpoint_depth_m, imported.ccr_low_setpoint_depth_m) == (10.0, 3.0)
