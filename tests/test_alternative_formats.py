"""Shearwater Cloud XML/CSV and Subsurface CSV exports (parsers/shearwater.py,
parsers/subsurface_csv.py), the content sniffing in parsers/registry.py and
DiveManager keeping one copy of a dive exported several ways."""
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from conftest import LOGS_DIR
from models.dive import Dive, Waypoint
from models.manager import DiveManager
from parsers.registry import (
    SHEARWATER_CSV,
    SHEARWATER_XML,
    SUBSURFACE_CSV,
    SUBSURFACE_XML,
    detect_log_format,
    parse_log_file,
)
from parsers.uddf import UDDFParser

ALT = LOGS_DIR / "alternative_formats"
PERDIX_451 = "Perdix 2[A5419AC1]#451 2025-10-19 11-42-39"
PERDIX_451_UDDF = LOGS_DIR / "uddf/Perdix 2 451 2025-10-19 11-42-39.uddf"


@pytest.mark.parametrize("name, expected", [
    (f"{PERDIX_451}.xml", SHEARWATER_XML),
    (f"{PERDIX_451}.csv", SHEARWATER_CSV),
    (f"{PERDIX_451}.zxu", None),
    ("subsurfac_496.csv", SUBSURFACE_CSV),
    ("subsurfac_496.ssrf", SUBSURFACE_XML),
])
@pytest.mark.requires_media
def test_detect_real_exports(name, expected):
    assert detect_log_format(ALT / name) == expected


def test_detect_other_csv_and_xml(tmp_path):
    other = tmp_path / "budget.csv"
    other.write_text("a,b,c\n1,2,3\n")
    assert detect_log_format(other) is None
    assert parse_log_file(other) is None
    subsurface = tmp_path / "dive.xml"
    subsurface.write_text("<divelog program='subsurface' version='3'><dives/></divelog>")
    assert detect_log_format(subsurface) == SUBSURFACE_XML


@pytest.mark.requires_media
@pytest.mark.parametrize("suffix", [".xml", ".csv"])
def test_shearwater_export_matches_same_dives_uddf(suffix):
    dive = parse_log_file(ALT / f"{PERDIX_451}{suffix}")[0]
    ref = UDDFParser().parse(PERDIX_451_UDDF)[0]
    assert dive.log_format == (SHEARWATER_XML if suffix == ".xml" else SHEARWATER_CSV)
    assert dive.start_time == datetime(2025, 10, 19, 11, 42, 39)
    assert dive.device == "Perdix 2"
    assert dive.max_depth == pytest.approx(12.9, abs=0.01)
    for t in (30, 600, 1200, 2600):
        wp = dive.get_waypoint_at(dive.start_time + timedelta(seconds=t))
        want = ref.get_waypoint_at(ref.start_time + timedelta(seconds=t))
        assert wp.time_since_start == want.time_since_start
        assert wp.depth == pytest.approx(want.depth, abs=0.01)
        assert wp.temp == pytest.approx(want.temp, abs=0.01)
        assert wp.ndl == want.ndl == 5940
        assert wp.po2 == pytest.approx(want.po2, abs=0.01)
        assert wp.divemode == "opencircuit"
        assert wp.tanks["T1"].pressure_bar == pytest.approx(want.tanks["T1"].pressure_bar, abs=0.5)
        assert wp.gasmix == "AIR"
    # Logged SAC is PSI/min: 16.48 at 20 min, the UDDF's own computed 1.13 bar/min.
    wp = dive.get_waypoint_at(dive.start_time + timedelta(seconds=1200))
    assert wp.pressure_sac == pytest.approx(1.13, abs=0.03)
    assert wp.tts == 240 and wp.air_remaining == 45 * 60


def test_shearwater_csv_imperial_units(tmp_path):
    path = tmp_path / "Teric[ABC]#1 2025-01-02 10-00-00.csv"
    path.write_text(
        "Dive Number,GF Minimum,GF Maximum,Imperial Units,Start Date,Product\n"
        "1,30,70,True,1/2/2025 10:00:00 AM,Teric\n"
        "Time (sec),Depth,First Stop Depth,Time To Surface (min),Current NDL,Water Temp,Fraction O2,Fraction He,Tank 1 pressure (PSI)\n"
        "0,0,0,0,0,68,0.32,0,3000\n"
        "10,33,0,1,50,50,0.32,0,AI is off\n"
    )
    dive = parse_log_file(path)[0]
    assert dive.start_time == datetime(2025, 1, 2, 10, 0, 0)
    assert dive.device == "Teric"
    wp = dive.waypoints[1]
    assert wp.depth == pytest.approx(33 * 0.3048)
    assert wp.temp == pytest.approx(10.0)
    assert wp.ndl == 50 * 60
    assert wp.tanks == {}
    assert dive.waypoints[0].ndl is None  # NDL 0 with no stop = not diving yet
    assert dive.waypoints[0].tanks["T1"].pressure_bar == pytest.approx(206.8, abs=0.1)
    assert dive.waypoints[0].gasmix == "Nx32"


def test_shearwater_start_date_in_day_month_locale(tmp_path):
    path = tmp_path / "Perdix 2[X]#7 2025-10-03 09-15-00.csv"
    path.write_text(
        "Dive Number,Start Date\n7,03/10/2025 09:15:00\n"
        "Time (sec),Depth\n0,0\n10,5\n"
    )
    assert parse_log_file(path)[0].start_time == datetime(2025, 10, 3, 9, 15, 0)


@pytest.mark.requires_media
def test_subsurface_csv_real_export():
    dives = parse_log_file(ALT / "subsurfac_496.csv")
    assert len(dives) == 1
    dive = dives[0]
    ssrf = parse_log_file(ALT / "subsurfac_496.ssrf")[0]
    assert dive.start_time == ssrf.start_time == datetime(2026, 5, 26, 11, 1, 27)
    # The trailing spurious "0:01" sample is dropped like the ssrf's.
    assert len(dive.waypoints) == len(ssrf.waypoints)
    assert dive.end_time == ssrf.end_time
    assert dive.max_depth == pytest.approx(ssrf.max_depth)
    # Temperature is only on the samples where it changed - carried forward.
    assert all(wp.temp is not None for wp in dive.waypoints)
    assert [wp.temp for wp in dive.waypoints] == [wp.temp for wp in ssrf.waypoints]
    assert dive.waypoints[-1].tts is not None  # deco recompute ran


def test_subsurface_csv_groups_dives_and_converts_units(tmp_path):
    path = tmp_path / "two.csv"
    path.write_text(
        '"dive number","date","time","sample time (min)","sample depth (ft)","sample temperature (F)","sample pressure (psi)","sample heartrate"\n'
        '"1","2026-01-01","09:00:00","0:10","10","50","3000","80"\n'
        '"1","2026-01-01","09:00:00","0:20","20",,,\n'
        '"2","2026-01-01","11:00:00","0:10","5",,,\n'
    )
    first, second = parse_log_file(path)
    assert first.waypoints[1].depth == pytest.approx(20 * 0.3048)
    assert first.waypoints[1].temp == pytest.approx(10.0)
    assert first.waypoints[1].tanks["1"].pressure_bar == pytest.approx(206.8, abs=0.1)
    assert first.waypoints[0].heart_rate == 80
    assert second.start_time == datetime(2026, 1, 1, 11, 0, 0)


def _dive(start, fmt, maker=None, samples=10):
    waypoints = [Waypoint(timestamp=start + timedelta(seconds=i), depth=1.0, time_since_start=i) for i in range(samples)]
    return Dive(
        start_time=start, end_time=waypoints[-1].timestamp, waypoints=waypoints,
        log_format=fmt, manufactor=maker, log_path=f"/logs/{fmt}-{samples}",
    )


def test_manager_keeps_richest_copy_of_a_dive():
    start = datetime(2025, 10, 19, 11, 42, 39)
    manager = DiveManager()
    manager.add_dives([_dive(start, "subsurface_csv", samples=50)])
    manager.add_dives([_dive(start + timedelta(seconds=8), "shearwater_csv", "Shearwater Research, Inc")])
    manager.add_dives([_dive(start, "subsurface_xml", "Shearwater")])
    (kept,) = manager.dives.values()
    assert kept.log_format == "shearwater_csv"
    # Equal rank: more samples wins.
    manager.add_dives([_dive(start, "uddf", "Shearwater Research, Inc", samples=5)])
    manager.add_dives([_dive(start, "shearwater_xml", "Shearwater Research, Inc", samples=20)])
    (kept,) = manager.dives.values()
    assert kept.log_format == "shearwater_xml"


def test_manager_merges_only_dives_from_different_log_files():
    start = datetime(2025, 10, 19, 11, 42, 39)
    manager = DiveManager()
    same_file = [_dive(start, "fit", samples=5), _dive(start, "fit", samples=6)]
    same_file[1].log_path = same_file[0].log_path
    in_memory = _dive(start + timedelta(hours=3), None)
    manager.add_dives(same_file + [in_memory, _dive(start + timedelta(hours=3, seconds=5), None, samples=4)])
    assert len(manager.dives) == 4


def test_manager_keeps_two_computers_on_one_dive():
    start = datetime(2025, 10, 19, 11, 42, 39)
    manager = DiveManager()
    manager.add_dives([_dive(start, "fit", "garmin"), _dive(start, "uddf", "Shearwater Research, Inc", samples=12)])
    manager.add_dives([_dive(start + timedelta(hours=2), "uddf", "Shearwater Research, Inc")])
    assert len(manager.dives) == 3


@pytest.mark.requires_media
def test_real_folder_of_one_dive_in_every_format():
    manager = DiveManager()
    for path in sorted(ALT.iterdir()):
        dives = parse_log_file(path)
        if dives:
            manager.add_dives(dives)
    manager.add_dives(parse_log_file(PERDIX_451_UDDF))
    kept = sorted(manager.dives.values(), key=lambda d: d.start_time)
    assert [d.log_format for d in kept] == [SHEARWATER_XML, SUBSURFACE_XML]
