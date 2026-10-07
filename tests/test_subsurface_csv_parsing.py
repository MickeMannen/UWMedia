"""SubsurfaceCSVParser (parsers/subsurface_csv.py) on small synthetic
"CSV dive profile" exports: units from the column names, values carried
forward, several dives in one table, missing columns, bad rows and the
header sniffing helper. Values are invented and written to tmp_path."""
from datetime import datetime

import pytest

from parsers.subsurface_csv import SubsurfaceCSVParser, is_subsurface_profile_header

HEADER = ('"dive number","date","time","sample time (min)","sample depth (m)",'
          '"sample temperature (C)","sample pressure (bar)","sample heartrate"\n')


def _parse(tmp_path, text, name="profile.csv"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return SubsurfaceCSVParser().parse(path)


def test_metric_export_values_and_carry_forward(tmp_path):
    dive, = _parse(tmp_path, HEADER
                   + '"5","2026-04-05","08:15:00","0:00","0.0","28.0","210.0","70"\n'
                   + '"5","2026-04-05","08:15:00","1:00","12.4",,,\n'
                   + '"5","2026-04-05","08:15:00","2:00","18.0","27.0","190.5",""\n'
                   + '"5","2026-04-05","08:15:00","3:00","-0.2",,"0",\n'
                   + '"5","2026-04-05","08:15:00","0:01","0.0",,,\n')  # spurious trailing sample
    assert dive.start_time == datetime(2026, 4, 5, 8, 15)
    assert dive.end_time == datetime(2026, 4, 5, 8, 18)
    assert dive.duration_seconds == 180
    assert dive.log_filename == "profile.csv"
    wps = dive.waypoints
    assert [wp.time_since_start for wp in wps] == [0, 60, 120, 180]
    assert [wp.depth for wp in wps] == [0.0, 12.4, 18.0, 0.0]  # a negative depth reads as the surface
    assert [wp.max_depth for wp in wps] == [0.0, 12.4, 18.0, 18.0]
    assert [wp.temp for wp in wps] == [28.0, 28.0, 27.0, 27.0]
    assert [wp.tanks["1"].pressure_bar for wp in wps] == [210.0, 210.0, 190.5, 190.5]  # 0 = no reading
    assert [wp.heart_rate for wp in wps] == [70, None, None, None]
    assert wps[2].tts is not None and wps[2].ceiling is not None  # deco recompute ran


def test_minimal_columns_and_rows_without_a_time(tmp_path):
    dive, = _parse(tmp_path, '"dive number","date","time","sample time (min)","sample depth (ft)"\n'
                   '"1","2026-04-05","10:00:00","0:00","0"\n'
                   '"1","2026-04-05","10:00:00","","50"\n'
                   '"1","2026-04-05","10:00:00","0:30","33"\n')
    assert [wp.time_since_start for wp in dive.waypoints] == [0, 30]
    assert dive.max_depth == pytest.approx(33 * 0.3048)
    assert all(wp.temp is None and wp.heart_rate is None and wp.tanks == {} for wp in dive.waypoints)


def test_dives_with_bad_dates_or_no_samples_are_skipped(tmp_path):
    dives = _parse(tmp_path, HEADER
                   + '"1","05/04/2026","08:00:00","0:10","5",,,\n'
                   + '"2","2026-04-05","10:00:00","",,,,\n'
                   + '"3","2026-04-05","12:00:00","0:10","7",,,\n')
    assert [d.start_time for d in dives] == [datetime(2026, 4, 5, 12, 0)]


@pytest.mark.parametrize("header", [
    '"dive number","date","time","sample depth (m)"\n',
    '"dive number","date","time","sample time (min)"\n',
    "",
])
def test_without_time_or_depth_columns_there_is_no_dive(tmp_path, header):
    assert _parse(tmp_path, header + '"1","2026-04-05","08:00:00","5"\n') == []


def test_missing_file_returns_no_dives(tmp_path):
    assert SubsurfaceCSVParser().parse(tmp_path / "nowhere.csv") == []


@pytest.mark.parametrize("line, expected", [
    (HEADER, True),
    ('"Sample Time (min)","Sample Depth (ft)"', True),
    ('"sample time (min)","depth"', False),
    ("Dive Number,Start Date", False),
])
def test_is_subsurface_profile_header(line, expected):
    assert is_subsurface_profile_header(line) is expected
