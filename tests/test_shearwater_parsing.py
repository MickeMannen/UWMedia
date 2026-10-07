"""ShearwaterParser (parsers/shearwater.py) on small synthetic Shearwater
Cloud XML and CSV exports: the wrong utf-16 declaration and a real UTF-16
file, start dates in several locales against the file name's date, units
(PSI, imperial), NDL/TTS/stop minutes, circuit modes, repeated/missing
samples and files that hold no dive. Values and serials are invented."""
from datetime import datetime

import pytest

from parsers.shearwater import ShearwaterParser, _divemode, read_tables

NAME = "Perdix 2[00000000]#7 2026-02-03 10-20-30"


def _record(ms, depth, **extra):
    fields = {"currentTime": ms, "currentDepth": depth, "fractionO2": "0.32", "fractionHe": "0", **extra}
    return "<diveLogRecord>" + "".join(f"<{k}>{v}</{k}>" for k, v in fields.items()) + "</diveLogRecord>"


def _xml(records, start="2/3/2026 10:20:30 AM", imperial="false", gf=("40", "85")):
    return f"""<?xml version="1.0" encoding="utf-16"?>
<dive version="3">
  <diveLog>
    <number>7</number><gfMin>{gf[0]}</gfMin><gfMax>{gf[1]}</gfMax>
    <imperialUnits>{imperial}</imperialUnits><startDate>{start}</startDate>
    <computerSerial>00000000</computerSerial><product>11</product><emptyTag />
    <diveLogRecords>{records}</diveLogRecords>
  </diveLog>
</dive>
"""


def _write(tmp_path, text, name=f"{NAME}.xml", encoding="utf-8"):
    path = tmp_path / name
    path.write_bytes(text.encode(encoding))
    return path


def _parse(path):
    return ShearwaterParser().parse(path)


def test_xml_export_values(tmp_path):
    records = (
        _record(0, 0, currentNdl=0, waterTemp=29, tank0pressurePSI=3000, tank1pressurePSI="AI is off",
                currentCircuitSetting="OC/BO", sac="Not Diving", gasTime="N/A", averagePPO2="0.32")
        + _record(60000, 18.5, currentNdl=25, ttsMins=2, waterTemp=27, tank0pressurePSI=2900,
                  sac="16.0", gasTime=40, averagePPO2="0.9123", batteryVoltage="1.52")
        + _record(120000, 21, firstStopDepth=6, firstStopTime=2, currentNdl=0, ttsMins=5)
        + _record(180000, 0, currentNdl=99))
    dive = _parse(_write(tmp_path, _xml(records)))[0]
    assert dive.start_time == datetime(2026, 2, 3, 10, 20, 30)
    assert dive.end_time == datetime(2026, 2, 3, 10, 23, 30)
    assert dive.duration_seconds == 180
    assert dive.device == "Perdix 2"  # from the file name: <product> is a number
    assert dive.manufactor == "Shearwater Research, Inc"
    assert dive.max_depth == 21.0

    w0, w1, w2, w3 = dive.waypoints
    assert [wp.time_since_start for wp in dive.waypoints] == [0, 60, 120, 180]
    assert w0.ndl is None  # NDL 0 and no stop: not diving yet
    assert w0.tanks["T1"].pressure_bar == pytest.approx(3000 * 0.0689476)
    assert set(w0.tanks) == {"T1"}
    assert (w0.tanks["T1"].o2_percent, w0.tanks["T1"].he_percent) == pytest.approx((32.0, 0.0))
    assert w0.divemode == "opencircuit"
    assert w0.air_remaining is None

    assert (w1.depth, w1.temp, w1.ndl, w1.tts) == (18.5, 27.0, 25 * 60, 120)
    assert w1.po2 == 0.91
    assert w1.battery == 1.52
    assert w1.air_remaining == 40 * 60
    assert w1.pressure_sac == pytest.approx(16.0 * 0.0689476, abs=0.01)
    assert (w1.deco_stop_depth, w1.next_stop_time) == (0.0, 0)

    assert (w2.deco_stop_depth, w2.next_stop_time, w2.next_stop_depth) == (6.0, 120, 6.0)
    assert w2.ndl == 0  # in deco
    assert w2.tts == 300
    assert w3.ndl == 99 * 60


def test_xml_imperial_units(tmp_path):
    records = (_record(0, 0, waterTemp=86) + _record(10000, 66, firstStopDepth=20, firstStopTime=1, waterTemp=77)
               + _record(20000, 0))
    w0, w1, _ = _parse(_write(tmp_path, _xml(records, imperial="True")))[0].waypoints
    assert w0.temp == pytest.approx(30.0)
    assert w1.depth == pytest.approx(66 * 0.3048)
    assert w1.temp == pytest.approx(25.0)
    assert w1.deco_stop_depth == pytest.approx(20 * 0.3048)
    assert w1.next_stop_time == 60


def test_xml_really_in_utf16(tmp_path):
    records = _record(0, 0) + _record(10000, 5) + _record(20000, 0)
    path = _write(tmp_path, _xml(records), encoding="utf-16")
    assert path.read_bytes()[:2] in (b"\xff\xfe", b"\xfe\xff")
    dive = _parse(path)[0]
    assert dive.max_depth == 5.0
    assert dive.start_time == datetime(2026, 2, 3, 10, 20, 30)


def test_xml_skips_repeated_and_timeless_records(tmp_path):
    records = (_record(0, 0) + _record(10000, 5) + _record(10400, 9)  # rounds to 10 s again
               + "<diveLogRecord><currentDepth>12</currentDepth></diveLogRecord>"
               + _record(5000, 15)  # goes back in time
               + _record(20000, 3))
    dive = _parse(_write(tmp_path, _xml(records)))[0]
    assert [(wp.time_since_start, wp.depth) for wp in dive.waypoints] == [(0, 0.0), (10, 5.0), (20, 3.0)]


def test_xml_without_a_dive_log_or_samples(tmp_path):
    assert _parse(_write(tmp_path, "<dive version='3'><other /></dive>")) == []
    assert read_tables(_write(tmp_path, "<dive version='3'></dive>", name="b.xml")) == ({}, [])
    assert _parse(_write(tmp_path, _xml(""), name="c.xml")) == []
    # Records but none with a time.
    assert _parse(_write(tmp_path, _xml("<diveLogRecord><currentDepth>3</currentDepth></diveLogRecord>"),
                         name="d.xml")) == []


def test_broken_xml_returns_no_dives(tmp_path):
    assert _parse(_write(tmp_path, "<dive><diveLog>")) == []


@pytest.mark.parametrize("start, file_name, expected", [
    # Month/day and day/month both parse: the file name's date picks.
    ("03/02/2026 10:20:30", NAME, datetime(2026, 2, 3, 10, 20, 30)),
    ("02/03/2026 10:20:30", NAME, datetime(2026, 2, 3, 10, 20, 30)),
    ("03.02.2026 10:20:30", NAME, datetime(2026, 2, 3, 10, 20, 30)),
    ("2026-02-03T10:20:30", NAME, datetime(2026, 2, 3, 10, 20, 30)),
    # No date in the file name: the first reading (month first) wins.
    ("03/02/2026 10:20:30", "export", datetime(2026, 3, 2, 10, 20, 30)),
    # The file name disagrees with every reading: still the first one.
    ("05/06/2026 10:20:30", NAME, datetime(2026, 5, 6, 10, 20, 30)),
    # No readable start date: the file name's own date and time.
    ("", NAME, datetime(2026, 2, 3, 10, 20, 30)),
    ("yesterday", NAME, datetime(2026, 2, 3, 10, 20, 30)),
])
def test_start_date_against_the_file_name(tmp_path, start, file_name, expected):
    path = tmp_path / f"{file_name}.csv"
    path.write_text(f"Dive Number,Start Date\n7,{start}\nTime (sec),Depth\n0,0\n10,5\n")
    assert _parse(path)[0].start_time == expected


def test_no_start_date_anywhere_gives_no_dive(tmp_path):
    path = tmp_path / "export.csv"
    path.write_text("Dive Number,Start Date\n7,\nTime (sec),Depth\n0,0\n10,5\n")
    assert _parse(path) == []


def test_device_from_the_header_product(tmp_path):
    path = tmp_path / "export 2026-02-03 10-20-30.csv"
    path.write_text("Product,Start Date\nPetrel 3,2026-02-03 10:20:30\nTime (sec),Depth\n0,0\n10,5\n")
    assert _parse(path)[0].device == "Petrel 3"
    nameless = tmp_path / "export 2026-02-03 10-20-31.csv"
    nameless.write_text("Start Date\n2026-02-03 10:20:31\nTime (sec),Depth\n0,0\n10,5\n")
    assert _parse(nameless)[0].device is None


def test_csv_repeated_header_column_blank_rows_and_gas(tmp_path):
    path = tmp_path / f"{NAME}.csv"
    path.write_text(
        "Computer Firmware Version,Start Date,Computer Firmware Version,GF Minimum,GF Maximum\n"
        "64,2026-02-03 10:20:30,99,40,85\n"
        "Time (sec),Depth,Fraction O2,Fraction He,Current Circuit Mode,Tank 2 pressure (PSI),Average PPO2\n"
        "0,0,0.18,0.45,1,2000,0.18\n"
        "\n"
        "10,30,0.18,0.45,0,1900,1.2\n"
        "20,0,,,,0,\n"
    )
    header, rows = read_tables(path)
    assert header["Computer Firmware Version"] == "64"  # the first of a repeated name
    assert [row["Time (sec)"] for row in rows] == [0.0, 10.0, 20.0]
    w0, w1, w2 = _parse(path)[0].waypoints
    assert w0.divemode == "opencircuit" and w1.divemode == "closedcircuit" and w2.divemode is None
    assert set(w0.tanks) == {"T2"}
    assert (w0.tanks["T2"].o2_percent, w0.tanks["T2"].he_percent) == pytest.approx((18.0, 45.0))
    assert w2.tanks == {}  # 0 PSI: no reading
    assert w2.po2 is not None  # recomputed where the export left it blank


@pytest.mark.parametrize("content", ["", "Dive Number,Start Date\n"])
def test_csv_without_samples(tmp_path, content):
    path = tmp_path / f"{NAME}.csv"
    path.write_text(content)
    assert _parse(path) == []


def test_csv_with_a_header_but_no_sample_table(tmp_path):
    path = tmp_path / f"{NAME}.csv"
    path.write_text("Dive Number,Start Date\n7,2026-02-03 10:20:30\n")
    assert read_tables(path) == ({"Dive Number": "7", "Start Date": "2026-02-03 10:20:30"}, [])
    assert _parse(path) == []


@pytest.mark.parametrize("value, mode", [
    ("OC/BO", "opencircuit"),
    ("oc/bo", "opencircuit"),
    ("CC/BO", "closedcircuit"),
    ("SC/BO", "closedcircuit"),
    ("1", "opencircuit"),
    ("0", "closedcircuit"),
    ("", None),
    (None, None),
    ("2", None),
    ("Gauge", None),
])
def test_divemode(value, mode):
    assert _divemode(value) == mode
