"""The Suunto app's JSON dive export (parsers/suunto.py): units, the sparse
records, events, the EON / D5 and Ocean / Nautic shapes, detection in
parsers/registry.py and the Dive Profile Builder import. The files are
written by the tests (real exports carry serial numbers and GPS); the real
D5 / Ocean samples in test_data/ are read where present."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from conftest import TEST_DATA
from parsers.registry import SUUNTO_JSON, detect_log_format, parse_log_file
from parsers.suunto import SuuntoJSONParser
from utils.dive_plan_import import logged_plan_parts

SAMPLES = TEST_DATA / "dive_computers" / "suunto" / "suunto_json_samples"
START = datetime(2026, 5, 2, 10, 0, 0, tzinfo=timezone(timedelta(hours=7)))


def _at(seconds: float) -> str:
    return (START + timedelta(seconds=seconds)).isoformat(timespec="milliseconds")


def _write(tmp_path, header, samples, name="dive.json"):
    path = tmp_path / name
    header = {"ActivityType": 51, "DateTime": START.isoformat(timespec="milliseconds"), **header}
    path.write_text(json.dumps({"DeviceLog": {"Header": header, "Samples": samples}}))
    return path


def _eon(tmp_path):
    """An EON Core-shaped log: a gas list (1-based), 10 s records with the
    values at the top level, a deco stop and a switch to the second gas."""
    header = {
        "Device": {"Name": "EON Core", "SerialNumber": "0000000000"},
        "Duration": 90,
        "Diving": {
            "Algorithm": "Suunto Fused2 RGBM",
            "Gases": [
                {"State": "Primary", "Oxygen": 0.32, "Helium": 0, "TankSize": 0.012, "StartPressure": 20000000},
                {"State": "Primary", "Oxygen": 0.5, "Helium": 0, "TankSize": 0.0057},
            ],
        },
    }
    samples = [
        {"TimeISO8601": _at(0), "Events": [{"State": {"Type": "Dive Active", "Active": True}}, {"GasSwitch": {"GasNumber": 1}}]},
        {"TimeISO8601": _at(10), "Depth": 10.0, "Temperature": 293.15, "NoDecTime": 6000, "TimeToSurface": 60,
         "Ceiling": 0, "GasTime": 3000, "Ventilation": 0.0002,
         "Cylinders": [{"GasNumber": 1, "Pressure": 19500000}]},
        # out of order, and a second record in the same second
        {"TimeISO8601": _at(30), "Depth": 30.0, "NoDecTime": 0, "TimeToSurface": 600, "Ceiling": 6.0,
         "Cylinders": [{"GasNumber": 1, "Pressure": 18000000}]},
        {"TimeISO8601": _at(20), "Depth": 20.0, "NoDecTime": 300, "TimeToSurface": 120},
        {"TimeISO8601": _at(30.4), "Depth": 31.0},
        {"TimeISO8601": _at(35), "Events": [{"Warning": {"Type": "Ceiling Broken", "Active": True}},
                                             {"Notify": {"Type": "Deco Window", "Active": False}}]},
        {"TimeISO8601": _at(40), "Events": [{"GasSwitch": {"GasNumber": 2}}]},
        {"TimeISO8601": _at(50), "Depth": 6.0, "NoDecTime": -1, "Ceiling": 3.0},
        {"TimeISO8601": _at(90), "Depth": 0.5, "NoDecTime": 6000, "TimeToSurface": 0, "Ceiling": 0},
    ]
    return _write(tmp_path, header, samples, "eon.json")


def _nautic(tmp_path):
    """A Nautic-shaped log: internal device name, no Diving block, 0-based
    cylinder numbers with values inside them, sidemount Pressure2,
    DiveEvents as an object, and a surface reading after DiveTime."""
    header = {"Device": {"Name": "Vaasa"}, "DiveTime": 60, "Duration": 200}
    samples = [
        {"TimeISO8601": _at(0), "DiveEvents": {"GasSwitch": {"GasNumber": 0}}},
        {"TimeISO8601": _at(5), "Depth": 5.0, "NoDecTime": 6000, "TimeToSurface": 30,
         "Cylinders": [{"GasNumber": 0, "Pressure": 20000000, "Pressure2": 19000000, "GasTime": 1200, "Ventilation": 0.00025},
                       {"GasNumber": 1, "Pressure": None, "GasTime": 0, "Ventilation": 0}]},
        {"TimeISO8601": _at(10), "Temperature": 300.15},
        {"TimeISO8601": _at(20), "Depth": 18.0, "DiveEvents": [{"Alarm": {"Type": "PO2 High", "Active": True}}]},
        {"TimeISO8601": _at(60), "Depth": 1.0,
         "Cylinders": [{"GasNumber": 0, "Pressure": 15000000, "Pressure2": 14000000, "GasTime": 900, "Ventilation": 0.0002}]},
        {"TimeISO8601": _at(150), "Depth": 0.0, "Cylinders": [{"GasNumber": 0, "Pressure": 14062}]},
    ]
    return _write(tmp_path, header, samples, "nautic.json")


def test_detect_suunto_json_only(tmp_path):
    assert detect_log_format(_eon(tmp_path)) == SUUNTO_JSON
    other = tmp_path / "settings.json"
    other.write_text(json.dumps({"units": "metric"}))
    assert detect_log_format(other) is None
    assert parse_log_file(other) is None


def test_eon_units_and_values(tmp_path):
    dive = parse_log_file(_eon(tmp_path))[0]
    assert dive.log_format == SUUNTO_JSON
    assert dive.device == "EON Core"
    assert dive.manufactor == "Suunto"
    assert dive.start_time == START.replace(tzinfo=None)
    assert dive.timezone == "UTC+07:00"
    assert [wp.time_since_start for wp in dive.waypoints] == [10, 20, 30, 50, 90]

    first = dive.waypoints[0]
    assert first.temp == pytest.approx(20.0)
    assert first.ndl == 6000
    assert first.tts == 60
    assert first.ceiling == 0.0
    assert first.air_remaining == 3000
    assert first.rmv == pytest.approx(12.0)
    assert first.tanks["T1"].pressure_bar == pytest.approx(195.0)
    assert first.tanks["T1"].o2_percent == 32.0
    assert first.gasmix == "Nx32"

    deco = dive.waypoints[2]
    assert deco.depth == 30.0  # the 30.4 s record falls in the same second: the first one is kept
    assert deco.ndl == 0
    assert deco.ceiling == 6.0
    assert deco.deco_stop_depth == 6.0
    assert deco.next_stop_depth == 6.0  # the logged ceiling is the stop, not rounded up to the next 3 m
    assert deco.temp == pytest.approx(20.0)  # carried forward
    assert deco.tanks["T1"].pressure_bar == pytest.approx(180.0)


def test_eon_events_and_gas_switch(tmp_path):
    wps = parse_log_file(_eon(tmp_path))[0].waypoints
    at_6m = wps[3]
    assert at_6m.dive_alerts == ["deco_ceiling_broken", "suunto:Ceiling Broken"]
    assert at_6m.gas_o2_percent == 50.0
    assert at_6m.gasmix == "Nx50"
    assert at_6m.ndl is None  # -1: no value
    assert wps[-1].tts > 0  # 0 is no value: the deco pass fills it
    assert all(not wp.dive_alerts for wp in wps[:3])


def test_nautic_shape(tmp_path):
    dive = parse_log_file(_nautic(tmp_path))[0]
    assert dive.device == "Nautic"
    wps = dive.waypoints
    assert [wp.time_since_start for wp in wps] == [5, 20, 60]  # the 150 s surface reading is after DiveTime
    assert {name: tank.pressure_bar for name, tank in wps[0].tanks.items()} == {"T1": 200.0, "T2": 190.0}
    assert wps[0].air_remaining == 1200
    assert wps[0].rmv == pytest.approx(15.0)
    assert wps[0].gas_o2_percent is None  # no gas list: the mix is unknown
    assert wps[1].temp == pytest.approx(27.0)
    assert wps[1].dive_alerts == ["po2_crit_high", "suunto:PO2 High"]
    assert wps[-1].secondary_tank_pressure == pytest.approx(140.0)


def test_not_a_dive_and_empty(tmp_path):
    run = _write(tmp_path, {"ActivityType": 3}, [{"TimeISO8601": _at(0), "Speed": 3.1}], "run.json")
    assert detect_log_format(run) == SUUNTO_JSON
    assert parse_log_file(run) == []
    assert SuuntoJSONParser().parse(_write(tmp_path, {}, [], "empty.json")) == []


def test_builder_import(tmp_path):
    path = _eon(tmp_path)
    dive = parse_log_file(path)[0]
    parts = logged_plan_parts(path, dive)
    assert [(g.name, g.tank_ref, g.tank_size_l, g.start_pressure_bar) for g in parts.gases] == [
        ("EAN32", "T1", 12.0, 200.0), ("EAN50", "T2", 5.7, None),
    ]
    assert parts.switches == [(0, "EAN32"), (40, "EAN50")]
    assert parts.water_temp_c == pytest.approx(20.0)


@pytest.mark.requires_media
@pytest.mark.parametrize("name, device, max_depth", [
    ("d5-deco-max-depth.json", "Suunto D5", 44.79),
    ("suunto-ocean-2026.json", "Ocean", 19.0),
])
def test_real_samples(name, device, max_depth):
    path = SAMPLES / name
    if not path.exists():
        pytest.skip(f"{path} not on hand")
    dive = parse_log_file(path)[0]
    assert dive.device == device
    assert dive.max_depth == pytest.approx(max_depth, abs=0.01)
