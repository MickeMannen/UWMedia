"""SubsurfaceParser (parsers/subsurface.py) on small synthetic Subsurface XML
files, and its unit helpers: time/depth/temperature/pressure/gas strings in
every unit Subsurface writes, sites and GPS, cylinders and their pressures
(live, start/end interpolation, sensor names), the file's GFs, logged deco
stops, several dives per file and malformed or missing fields. All values
are invented and written to tmp_path."""
from datetime import datetime

import pytest

from parsers.subsurface import (
    SubsurfaceParser,
    parse_depth_str,
    parse_gas_percent,
    parse_pressure_str,
    parse_temp_str,
    parse_time_str,
)


@pytest.mark.parametrize("text, seconds", [
    ("45:20 min", 45 * 60 + 20),
    ("1:02:03", 3723),
    ("1.5 min", 90),
    ("30 s", 30),
    ("42", 42),
    (" 7.9 ", 7),
    ("soon", 0),
    ("1:2:3:4", 0),  # neither mm:ss nor h:mm:ss
])
def test_parse_time_str(text, seconds):
    assert parse_time_str(text) == seconds


@pytest.mark.parametrize("text, metres", [
    ("12.5 m", 12.5),
    ("33 ft", 33 * 0.3048),
    ("7", 7.0),
    ("deep", 0.0),
])
def test_parse_depth_str(text, metres):
    assert parse_depth_str(text) == pytest.approx(metres)


@pytest.mark.parametrize("text, celsius", [
    ("28.5 C", 28.5),
    ("50 F", 10.0),
    ("300.15 K", 27.0),
    ("21", 21.0),
    ("cold", 0.0),
])
def test_parse_temp_str(text, celsius):
    assert parse_temp_str(text) == pytest.approx(celsius)


@pytest.mark.parametrize("text, bar", [
    ("200.0 bar", 200.0),
    ("3000 psi", 3000 * 0.0689476),
    ("150", 150.0),
    ("full", 0.0),
])
def test_parse_pressure_str(text, bar):
    assert parse_pressure_str(text) == pytest.approx(bar)


@pytest.mark.parametrize("text, default, percent", [
    ("32.0%", 21.0, 32.0),
    ("0.32", 21.0, 32.0),
    ("50", 21.0, 50.0),
    (None, 21.0, 21.0),
    ("", 0.0, 0.0),
    ("rich", 21.0, 21.0),
])
def test_parse_gas_percent(text, default, percent):
    assert parse_gas_percent(text, default) == pytest.approx(percent)


def _ssrf(dives, sites=""):
    return f"""<divelog program='subsurface' version='3'>
<divesites>{sites}</divesites>
<dives>{dives}</dives>
</divelog>
"""


def _parse(tmp_path, text, name="dive.ssrf"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return SubsurfaceParser().parse(path)


def _square(depth="10.0 m", minutes=3, attrs=""):
    """Samples every minute: down, `minutes` at depth, up."""
    rows = [f"<sample time='0:00 min' depth='0.0 m' {attrs}/>"]
    rows += [f"<sample time='{m}:00 min' depth='{depth}' />" for m in range(1, minutes + 1)]
    rows.append(f"<sample time='{minutes + 1}:00 min' depth='0.0 m' />")
    return "".join(rows)


def test_dive_metadata_site_and_duration(tmp_path):
    sites = ("<site uuid='aa01' name='Test Reef' gps='12.345600 98.765400' />"
             "<site uuid='aa02' name='No GPS' />")
    dives = _parse(tmp_path, _ssrf(
        f"<dive number='1' divesiteid='aa01' date='2026-01-01' time='09:30:00' duration='5:00 min'>"
        f"<divecomputer model='Shearwater Perdix 2' deviceid='0000000'>{_square()}</divecomputer></dive>"
        f"<dive number='2' divesiteid='aa02' date='2026-01-01' time='13:00:00'>"
        f"<divecomputer model='Garmin Descent Mk3i'>{_square('20.0 m', 4)}</divecomputer></dive>"
        f"<dive number='3' divesiteid='unknown' date='2026-01-02' time='08:00:00'>"
        f"<divecomputer model='Other'>{_square()}</divecomputer></dive>", sites))
    first, second, third = dives
    assert first.start_time == datetime(2026, 1, 1, 9, 30)
    assert first.end_time == datetime(2026, 1, 1, 9, 34)
    assert first.duration_seconds == 300  # the dive's own duration attribute
    assert (first.start_latitude, first.start_longitude) == (12.3456, 98.7654)
    assert (first.device, first.manufactor) == ("Shearwater Perdix 2", "Shearwater")
    assert first.max_depth == 10.0

    assert second.duration_seconds == 300  # from the samples when not given
    assert (second.start_latitude, second.start_longitude) == (None, None)
    assert (second.device, second.manufactor) == ("Garmin Descent Mk3i", "Garmin")
    assert second.max_depth == 20.0

    assert third.manufactor is None and third.start_latitude is None


@pytest.mark.parametrize("gps", ["north east", "1.0", "1.0 2.0 3.0"])
def test_unreadable_site_gps_is_ignored(tmp_path, gps):
    dive = _parse(tmp_path, _ssrf(
        f"<dive divesiteid='s1' date='2026-01-01' time='10:00:00'><divecomputer>{_square()}</divecomputer></dive>",
        f"<site uuid='s1' name='Somewhere' gps='{gps}' />"))[0]
    assert (dive.start_latitude, dive.start_longitude) == (None, None)


@pytest.mark.parametrize("attrs", [
    "time='10:00:00'",                      # no date
    "date='2026-01-01'",                    # no time
    "date='01/02/2026' time='10:00:00'",    # wrong date format
    "date='2026-01-01' time='25:00:00'",    # impossible time
])
def test_dives_without_a_usable_start_are_skipped(tmp_path, attrs):
    dives = _parse(tmp_path, _ssrf(
        f"<dive {attrs}><divecomputer>{_square()}</divecomputer></dive>"
        f"<dive date='2026-01-03' time='07:00:00'><divecomputer>{_square('8.0 m')}</divecomputer></dive>"))
    assert len(dives) == 1
    assert dives[0].start_time == datetime(2026, 1, 3, 7, 0)
    assert dives[0].max_depth == 8.0


def test_dives_without_a_dive_computer_or_samples_are_skipped(tmp_path):
    dives = _parse(tmp_path, _ssrf(
        "<dive date='2026-01-01' time='10:00:00'><cylinder o2='32.0%' /></dive>"
        "<dive date='2026-01-01' time='11:00:00'><divecomputer model='X' /></dive>"))
    assert dives == []


def test_samples_units_temperature_and_po2(tmp_path):
    samples = ("<sample time='0:00 min' depth='0 ft' temp='77.0 F' po2='1.25 bar' />"
               "<sample time='1:00 min' depth='66 ft' />"
               "<sample time='2:00 min' depth='66 ft' temp='299.15 K' po2='n/a' />"
               "<sample depth='99 m' />"  # no time: skipped
               "<sample time='3:00 min' depth='0 ft' />")
    dive = _parse(tmp_path, _ssrf(
        "<dive date='2026-01-01' time='10:00:00'><divecomputer model='X'>"
        f"<temperature water='29.0 C' />{samples}</divecomputer></dive>"))[0]
    wps = dive.waypoints
    assert [wp.time_since_start for wp in wps] == [0, 60, 120, 180]
    assert wps[1].depth == pytest.approx(66 * 0.3048)
    assert dive.max_depth == pytest.approx(66 * 0.3048)
    assert [wp.temp for wp in wps] == pytest.approx([25.0, 25.0, 26.0, 26.0])
    assert [wp.po2 for wp in wps] == [1.25, 1.25, 1.25, 1.25]  # a bad value keeps the last


def test_water_temperature_from_the_dive_computer_header(tmp_path):
    dive = _parse(tmp_path, _ssrf(
        "<dive date='2026-01-01' time='10:00:00'><divecomputer><temperature water='27.5 C' />"
        f"{_square()}</divecomputer></dive>"))[0]
    assert all(wp.temp == 27.5 for wp in dive.waypoints)


def test_non_monotonic_trailing_sample_is_dropped(tmp_path):
    samples = _square() + "<sample time='0:01 min' depth='0.0 m' />"
    dive = _parse(tmp_path, _ssrf(
        f"<dive date='2026-01-01' time='10:00:00'><divecomputer>{samples}</divecomputer></dive>"))[0]
    assert dive.waypoints[-1].time_since_start == 240
    assert dive.end_time == datetime(2026, 1, 1, 10, 4)


def test_ndl_tts_gf_battery_and_no_invented_stop(tmp_path):
    samples = ("<sample time='0:00 min' depth='0.0 m' />"
               "<sample time='1:00 min' depth='15.0 m' ndl='20:00 min' tts='1:30 min' gf='35.5' battery='3.9' />"
               "<sample time='2:00 min' depth='0.0 m' />")
    wp = _parse(tmp_path, _ssrf(
        f"<dive date='2026-01-01' time='10:00:00'><divecomputer>{samples}</divecomputer></dive>"))[0].waypoints[1]
    assert (wp.ndl, wp.tts, wp.gf, wp.battery) == (1200, 90, 35.5, 3.9)
    assert (wp.deco_stop_depth, wp.next_stop_time, wp.next_stop_depth) == (0.0, 0, 0.0)


def test_cylinders_live_pressures_and_sensor_names(tmp_path):
    samples = ("<sample time='0:00 min' depth='0.0 m' pressure0='3000 psi' pressure1='200.0 bar' />"
               "<sample time='1:00 min' depth='30.0 m' pressure0='2900 psi' />"
               "<sample time='2:00 min' depth='0.0 m' pressure1='190.0 bar' />")
    dive = _parse(tmp_path, _ssrf(
        "<dive date='2026-01-01' time='10:00:00'>"
        "<cylinder size='11.1 l' o2='32.0%' description='AL80' start='3000 psi' />"
        "<cylinder size='12.0 l' o2='0.18' he='0.45' />"
        "<cylinder o2='50.0%' start='200.0 bar' />"
        "<divecomputer model='X'><extradata key='Sensor 1' value='0000001' />"
        f"{samples}</divecomputer></dive>"))[0]
    w0, w1, w2 = dive.waypoints
    # Tank keys: the sensor id for cylinder 1, the description otherwise, else the 1-based index.
    assert set(w0.tanks) == {"0000001", "2", "3"}
    t1 = w1.tanks["0000001"]
    assert t1.pressure_bar == pytest.approx(2900 * 0.0689476)
    assert (t1.o2_percent, t1.he_percent, t1.name) == (32.0, 0.0, "AL80")
    t2 = w2.tanks["2"]
    assert t2.pressure_bar == 190.0
    assert (t2.o2_percent, t2.he_percent, t2.name) == (18.0, 45.0, "Mix 2")
    assert w1.tanks["2"].pressure_bar == 200.0  # carried forward
    # Only a start pressure and no live readings: stays at the start value.
    assert [wp.tanks["3"].pressure_bar for wp in dive.waypoints] == [200.0] * 3


def test_cylinder_description_is_the_tank_key_without_a_sensor(tmp_path):
    dive = _parse(tmp_path, _ssrf(
        "<dive date='2026-01-01' time='10:00:00'><cylinder description='Left' start='200 bar' end='100 bar' />"
        f"<divecomputer>{_square(minutes=1)}</divecomputer></dive>"))[0]
    assert [wp.tanks["Left"].pressure_bar for wp in dive.waypoints] == pytest.approx([200.0, 150.0, 100.0])


def _tts_at_bottom(tmp_path, deco_model, name):
    extradata = f"<extradata key='Deco model' value='{deco_model}' />" if deco_model is not None else ""
    dive = _parse(tmp_path, _ssrf(
        "<dive date='2026-01-01' time='10:00:00'><cylinder o2='21.0%' />"
        f"<divecomputer>{extradata}{_square('40.0 m', 25)}</divecomputer></dive>"), name=name)[0]
    return dive.waypoints[25].tts


def test_the_files_own_gradient_factors_drive_the_recompute(tmp_path):
    default = _tts_at_bottom(tmp_path, None, "default.ssrf")
    assert default > 0
    assert _tts_at_bottom(tmp_path, "Buhlmann ZHL-16C GF 30/70", "same.ssrf") == default
    assert _tts_at_bottom(tmp_path, "GF 100/100", "lenient.ssrf") < default
    assert _tts_at_bottom(tmp_path, "GF 20 / 50", "strict.ssrf") > default
    assert _tts_at_bottom(tmp_path, "GF 85/40", "bad.ssrf") == default  # low > high: ignored
    assert _tts_at_bottom(tmp_path, "VPM-B +3", "vpm.ssrf") == default


def test_no_cylinders_recomputes_on_air(tmp_path):
    dive = _parse(tmp_path, _ssrf(
        f"<dive date='2026-01-01' time='10:00:00'><divecomputer>{_square('20.0 m')}</divecomputer></dive>"))[0]
    wp = dive.waypoints[2]
    assert wp.tts is not None and wp.ceiling is not None
    assert wp.po2 == pytest.approx(0.21 * 3.01, abs=0.02)
    assert wp.tanks == {}


def test_a_failed_recompute_still_returns_the_dive(tmp_path):
    # An O2 of 0% can't give a MOD - the recompute is skipped, the samples stay.
    dive = _parse(tmp_path, _ssrf(
        "<dive date='2026-01-01' time='10:00:00'><cylinder o2='0' start='200 bar' end='150 bar' />"
        f"<divecomputer>{_square()}</divecomputer></dive>"))[0]
    assert dive.max_depth == 10.0
    assert all(wp.ceiling is None for wp in dive.waypoints)
    assert dive.waypoints[-1].tanks["1"].pressure_bar == pytest.approx(150.0)


@pytest.mark.parametrize("helper, text, fallback", [
    (parse_time_str, "ab:cd min", 0),
    (parse_depth_str, "abc m", 0.0),
    (parse_depth_str, "x ft", 0.0),
    (parse_temp_str, "x C", 0.0),
    (parse_pressure_str, "x bar", 0.0),
    (parse_gas_percent, "x%", None),
])
def test_unreadable_values_with_a_unit_fall_back(helper, text, fallback):
    if helper is parse_gas_percent:
        assert parse_gas_percent(text, 21.0) == 21.0
    else:
        assert helper(text) == fallback


def test_an_unreadable_gf_or_battery_is_empty_not_fatal(tmp_path):
    dives = _parse(tmp_path, _ssrf(
        "<dive date='2026-01-01' time='10:00:00'><divecomputer model='X'>"
        "<sample time='0:00 min' depth='0.0 m' />"
        "<sample time='1:00 min' depth='10.0 m' gf='n/a' battery='low' />"
        "<sample time='2:00 min' depth='0.0 m' /></divecomputer></dive>"))
    wp = dives[0].waypoints[1]
    assert (wp.depth, wp.battery) == (10.0, None)
    assert wp.gf == pytest.approx(0.7)  # empty, so the recompute fills it in
