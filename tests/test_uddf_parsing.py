"""UDDFParser (parsers/uddf.py) on small synthetic UDDF files: start times
(ISO with/without offset, the legacy year/month/day fields), the <timezone>
tag and update_timezone(), several dives per file, units (Kelvin, Pa),
gases and tank pressures, the file's own GFs, NDL/deco stops and logged
values against the Buhlmann recompute, and malformed or missing fields.
Every file is written to tmp_path with invented values (no real logs)."""
from datetime import datetime

import pytest

from parsers.uddf import UDDFParser

NS = "http://www.streit.cc/uddf/3.2/"

AIR_MIX = '<mix id="air"><name>Air</name><o2>0.21</o2><he>0.0</he></mix>'
TX_MIX = '<mix id="tx"><name>Tx 18/45</name><o2>0.18</o2><he>0.45</he></mix>'


def _uddf(dives, mixes=AIR_MIX, extra="", ns=NS):
    xmlns = f' xmlns="{ns}"' if ns else ""
    return f"""<?xml version="1.0" encoding="utf-8"?>
<uddf{xmlns} version="3.2.3">
  <generator><name>Test</name><manufacturer id="m"><name>Acme Diving</name></manufacturer></generator>
  <diver><owner id="o"><equipment><divecomputer id="dc"><name>Acme One</name><serialnumber>0000000</serialnumber></divecomputer></equipment></owner></diver>
  <gasdefinitions>{mixes}</gasdefinitions>
  {extra}
  <profiledata><repetitiongroup id="rg">{dives}</repetitiongroup></profiledata>
</uddf>
"""


def _dive(waypoints, when="<datetime>2026-01-01T10:00:00</datetime>", tz=""):
    return f"""<dive id="d"><informationbeforedive>{when}</informationbeforedive>{tz}
<samples>{waypoints}</samples></dive>"""


def _wp(t, depth, extra=""):
    return f"<waypoint><divetime>{t}</divetime><depth>{depth}</depth>{extra}</waypoint>"


def _square(depth, minutes, extra_first='<switchmix ref="air"/>'):
    """A square profile sampled every minute: down, `minutes` at depth, up."""
    wps = [_wp(0, 0, extra_first)]
    wps += [_wp(60 * m, depth) for m in range(1, minutes + 1)]
    wps.append(_wp(60 * minutes + 60, 0))
    return "".join(wps)


def _parse(tmp_path, text, name="dive.uddf"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return UDDFParser().parse(path)


def test_header_metadata_and_basic_samples(tmp_path):
    dives = _parse(tmp_path, _uddf(_dive(_square(12.0, 3))))
    assert len(dives) == 1
    dive = dives[0]
    assert dive.device == "Acme One"
    assert dive.manufactor == "Acme Diving"
    assert dive.timezone is None
    assert dive.log_filename == "dive.uddf"
    assert dive.start_time == datetime(2026, 1, 1, 10, 0, 0)
    assert dive.end_time == datetime(2026, 1, 1, 10, 4, 0)
    assert [wp.time_since_start for wp in dive.waypoints] == [0, 60, 120, 180, 240]
    assert [wp.max_depth for wp in dive.waypoints] == [0.0, 12.0, 12.0, 12.0, 12.0]
    assert dive.max_depth == 12.0


@pytest.mark.parametrize("stamp", [
    "2026-03-04T05:06:07Z",
    "2026-03-04T05:06:07+08:00",
    "2026-03-04T05:06:07-05:30",
    "2026-03-04T05:06:07",
])
def test_datetime_keeps_the_logged_wall_clock_time(tmp_path, stamp):
    dive = _parse(tmp_path, _uddf(_dive(_square(5, 1), when=f"<datetime>{stamp}</datetime>")))[0]
    assert dive.start_time == datetime(2026, 3, 4, 5, 6, 7)
    assert dive.start_time.tzinfo is None


def test_legacy_date_fields_are_used_when_datetime_is_missing_or_bad(tmp_path):
    legacy = "<date><year>2025</year><month>7</month><day>9</day></date><time><hour>14</hour><minute>30</minute></time>"
    dives = _parse(tmp_path, _uddf(
        _dive(_square(5, 1), when=legacy)
        + _dive(_square(5, 1), when=f"<datetime>not a date</datetime>{legacy}")
    ))
    assert [d.start_time for d in dives] == [datetime(2025, 7, 9, 14, 30)] * 2


@pytest.mark.parametrize("when", [
    "",  # no start time at all
    "<datetime>garbage</datetime>",  # bad datetime, no legacy fields
    "<year>2025</year><month>13</month><day>1</day><hour>1</hour><minute>1</minute>",  # impossible date
    "<year>2025</year><month>1</month><day>1</day><hour>1</hour>",  # incomplete
])
def test_dive_without_a_usable_start_time_is_skipped(tmp_path, when):
    dives = _parse(tmp_path, _uddf(
        _dive(_square(5, 1), when=when) + _dive(_square(7, 1), when="<datetime>2026-02-02T08:00:00</datetime>")
    ))
    assert len(dives) == 1
    assert dives[0].start_time == datetime(2026, 2, 2, 8, 0)
    assert dives[0].max_depth == 7.0


def test_several_dives_per_file_and_dives_without_samples(tmp_path):
    dives = _parse(tmp_path, _uddf(
        _dive(_square(10, 2), when="<datetime>2026-01-01T09:00:00</datetime>")
        + _dive("", when="<datetime>2026-01-01T11:00:00</datetime>")  # no samples: dropped
        + _dive(_square(20, 3), when="<datetime>2026-01-01T14:00:00</datetime>", tz="<timezone>-300</timezone>")
    ))
    assert [d.start_time.hour for d in dives] == [9, 14]
    assert [d.max_depth for d in dives] == [10.0, 20.0]
    assert [d.timezone for d in dives] == [None, "-300"]
    assert dives[1].end_time == datetime(2026, 1, 1, 14, 4)


def test_update_timezone_adds_the_tag_once(tmp_path):
    path = tmp_path / "tz.uddf"
    path.write_text(_uddf(_dive(_square(5, 1)) + _dive(_square(6, 1), tz="<timezone>60</timezone>")), encoding="utf-8")
    parser = UDDFParser()
    parser.update_timezone(path, 480)
    first, second = parser.parse(path)
    assert first.timezone == "480"
    assert second.timezone == "60"  # an existing tag is left alone
    # Still the same file otherwise.
    assert first.start_time == datetime(2026, 1, 1, 10, 0)
    assert first.max_depth == 5.0

    written = path.read_bytes()
    parser.update_timezone(path, -120)  # nothing missing now: file untouched
    assert path.read_bytes() == written
    assert parser.parse(path)[0].timezone == "480"


def test_update_timezone_without_a_namespace(tmp_path):
    path = tmp_path / "plain.uddf"
    path.write_text(_uddf(_dive(_square(5, 1)), ns=None), encoding="utf-8")
    UDDFParser().update_timezone(path, -330)
    assert b"<timezone>-330</timezone>" in path.read_bytes()
    assert UDDFParser().parse(path)[0].timezone == "-330"


def test_temperature_kelvin_and_celsius(tmp_path):
    wps = (_wp(0, 0, "<temperature>301.15</temperature>")
           + _wp(60, 5, "<temperature>24.5</temperature>")
           + _wp(120, 5, "<temperature>warm</temperature>")
           + _wp(180, 0))
    temps = [wp.temp for wp in _parse(tmp_path, _uddf(_dive(wps)))[0].waypoints]
    assert temps == pytest.approx([28.0, 24.5, 0.0, 0.0])


def test_bad_or_missing_divetime_samples_are_skipped(tmp_path):
    wps = (_wp(0, 0) + "<waypoint><depth>99</depth></waypoint>"
           + _wp("soon", 98) + _wp("60.7", 6) + _wp(120, 0))
    dive = _parse(tmp_path, _uddf(_dive(wps)))[0]
    assert [wp.time_since_start for wp in dive.waypoints] == [0, 60, 120]
    assert dive.max_depth == 6.0


def test_logged_per_sample_values_are_read(tmp_path):
    extra = ("<nodecotime>1200</nodecotime><tts>90</tts><gradientfactor>42.5</gradientfactor>"
             "<batterychargecondition>87</batterychargecondition><calculatedpo2>1.234</calculatedpo2>")
    wps = _wp(0, 0, '<switchmix ref="air"/>') + _wp(60, 15, extra) + _wp(120, 15) + _wp(180, 0)
    wp = _parse(tmp_path, _uddf(_dive(wps)))[0].waypoints[1]
    assert wp.ndl == 1200
    assert wp.tts == 90
    assert wp.gf == 42.5
    assert wp.battery == 87.0
    assert wp.po2 == 1.23
    # The file's NDL says no stop is owed - the recompute doesn't invent one.
    assert wp.deco_stop_depth == 0.0
    assert wp.next_stop_time == 0
    assert wp.next_stop_depth == 0.0


def test_logged_cns_wins_over_the_recompute(tmp_path):
    wps = _wp(0, 0, "<cns>37</cns>") + _wp(60, 5, "<cns>38</cns>") + _wp(120, 0, "<cns>38</cns>")
    dive = _parse(tmp_path, _uddf(_dive(wps)))[0]
    assert [wp.cns for wp in dive.waypoints] == [37, 38, 38]


def test_po2_persists_and_a_bad_value_keeps_the_last_one(tmp_path):
    wps = (_wp(0, 0, "<calculatedpo2>1.3</calculatedpo2>") + _wp(60, 10)
           + _wp(120, 10, "<calculatedpo2>n/a</calculatedpo2>") + _wp(180, 10, "<calculatedpo2>0.7</calculatedpo2>"))
    po2 = [wp.po2 for wp in _parse(tmp_path, _uddf(_dive(wps)))[0].waypoints]
    assert po2 == [1.3, 1.3, 1.3, 0.7]


def test_divemode_as_text(tmp_path):
    wps = _wp(0, 0, "<divemode>opencircuit</divemode>") + _wp(60, 5) + _wp(120, 0)
    assert [wp.divemode for wp in _parse(tmp_path, _uddf(_dive(wps)))[0].waypoints] == ["opencircuit"] * 3


def test_decostop_with_bad_attributes_falls_back_to_the_recompute(tmp_path):
    bad_stop = '<decostop kind="mandatory" decodepth="deep" duration="long"/>'
    wps = _wp(0, 0, '<switchmix ref="air"/>') + _wp(60, 18, bad_stop) + _wp(120, 18) + _wp(180, 0)
    wp = _parse(tmp_path, _uddf(_dive(wps)))[0].waypoints[1]
    assert wp.deco_stop_depth == wp.ceiling  # from the recompute
    assert wp.next_stop_time == 0


def test_a_file_that_logs_stops_gets_direct_ascent_tts_where_it_logs_none(tmp_path):
    stop = '<decostop kind="mandatory" decodepth="3" duration="60"/>'
    wps = _wp(0, 0, '<switchmix ref="air"/>') + _wp(60, 9, stop) + _wp(120, 9) + _wp(180, 0)
    w0, w1, w2, _ = _parse(tmp_path, _uddf(_dive(wps)))[0].waypoints
    assert (w1.deco_stop_depth, w1.next_stop_time, w1.next_stop_depth) == (3.0, 60, 3.0)
    assert (w2.deco_stop_depth, w2.next_stop_time) == (0.0, 0)
    assert w2.tts == 60  # 9 m at 9 m/min, no stop


def test_tank_pressures_pascal_bar_bad_and_unreferenced(tmp_path):
    wps = (_wp(0, 0, '<switchmix ref="tx"/><tankpressure ref="T1">20000000</tankpressure>'
                     '<tankpressure ref="T2">199.5</tankpressure><tankpressure ref="T3">AI off</tankpressure>')
           + _wp(60, 30, "<tankpressure>18000000</tankpressure>") + _wp(120, 0))
    dive = _parse(tmp_path, _uddf(_dive(wps), mixes=AIR_MIX + TX_MIX))[0]
    first = dive.waypoints[0].tanks
    assert set(first) == {"T1", "T2"}  # the unreadable T3 is dropped
    assert first["T1"].pressure_bar == pytest.approx(200.0)
    assert first["T2"].pressure_bar == pytest.approx(199.5)
    assert (first["T1"].o2_percent, first["T1"].he_percent, first["T1"].name) == (18.0, 45.0, "Tx 18/45")
    second = dive.waypoints[1].tanks
    assert set(second) == {"1"}  # no ref: keyed by position
    assert second["1"].pressure_bar == pytest.approx(180.0)
    assert dive.waypoints[2].tanks == {}


def test_tank_gas_defaults_to_air_before_any_switch(tmp_path):
    wps = _wp(0, 0, '<tankpressure ref="T1">200</tankpressure>') + _wp(60, 5) + _wp(120, 0)
    tank = _parse(tmp_path, _uddf(_dive(wps)))[0].waypoints[0].tanks["T1"]
    assert (tank.o2_percent, tank.he_percent, tank.name) == (21.0, 0.0, "AIR")


def test_mix_defaults_name_and_fractions(tmp_path):
    mixes = '<mix id="m1"></mix><mix id="m2"><o2>0.32</o2></mix>'
    wps = (_wp(0, 0, '<switchmix ref="m1"/><tankpressure ref="T1">200</tankpressure>')
           + _wp(60, 5, '<switchmix ref="m2"/><tankpressure ref="T1">190</tankpressure>') + _wp(120, 0))
    w0, w1, _ = _parse(tmp_path, _uddf(_dive(wps), mixes=mixes))[0].waypoints
    assert (w0.tanks["T1"].name, w0.tanks["T1"].o2_percent, w0.tanks["T1"].he_percent) == ("m1", 21.0, 0.0)
    assert (w1.tanks["T1"].name, w1.tanks["T1"].o2_percent) == ("m2", 32.0)


def test_no_gas_definitions_recomputes_on_air(tmp_path):
    dive = _parse(tmp_path, _uddf(_dive(_square(20, 3, extra_first="")), mixes=""))[0]
    wp = dive.waypoints[2]
    assert wp.ceiling is not None and wp.tts is not None
    assert wp.po2 == pytest.approx(0.21 * 3.01, abs=0.02)


def test_a_failed_recompute_still_returns_the_dive(tmp_path):
    # An O2 fraction of 0 can't give a MOD - the recompute is skipped, the samples stay.
    mixes = '<mix id="bad"><name>Bad</name><o2>0</o2></mix>'
    dive = _parse(tmp_path, _uddf(_dive(_square(10, 2, extra_first='<switchmix ref="bad"/>')), mixes=mixes))[0]
    assert dive.max_depth == 10.0
    assert all(wp.ceiling is None and wp.tts is None for wp in dive.waypoints)


DECO_DIVE = _square(40.0, 25)


def _tts_at_bottom(tmp_path, extra, name):
    dive = _parse(tmp_path, _uddf(_dive(DECO_DIVE), extra=extra), name=name)[0]
    return dive.waypoints[25].tts


def _gf(low, high):
    return (f"<decomodel><buehlmann id='b'><gradientfactorlow>{low}</gradientfactorlow>"
            f"<gradientfactorhigh>{high}</gradientfactorhigh></buehlmann></decomodel>")


def test_the_files_own_gradient_factors_drive_the_recompute(tmp_path):
    default = _tts_at_bottom(tmp_path, "", "default.uddf")
    assert default > 0
    assert _tts_at_bottom(tmp_path, _gf(30, 70), "same.uddf") == default  # 30/70 is the default
    assert _tts_at_bottom(tmp_path, _gf(100, 100), "lenient.uddf") < default
    assert _tts_at_bottom(tmp_path, _gf(20, 50), "strict.uddf") > default


@pytest.mark.parametrize("low, high", [("abc", "70"), ("80", "40"), ("0", "70"), ("30", "120")])
def test_unusable_gradient_factors_fall_back_to_the_default(tmp_path, low, high):
    default = _tts_at_bottom(tmp_path, "", "default.uddf")
    assert _tts_at_bottom(tmp_path, _gf(low, high), "bad.uddf") == default


def test_not_xml_returns_no_dives(tmp_path):
    assert _parse(tmp_path, "<uddf><unclosed>") == []


def test_an_unreadable_number_is_skipped_not_fatal(tmp_path):
    """One bad value in a sample costs that value (or, for depth, that sample),
    not the whole log - as for temperature and tank pressure."""
    wps = (_wp(0, 0, '<switchmix ref="air"/>') + _wp(60, 10, "<nodecotime>x</nodecotime><cns>x</cns>")
           + _wp(120, "deep") + _wp(180, 10, "<tts>?</tts><gradientfactor>n/a</gradientfactor>"
                                            "<batterychargecondition>low</batterychargecondition>")
           + _wp(240, 0))
    dive = _parse(tmp_path, _uddf(_dive(wps)))[0]
    assert [wp.time_since_start for wp in dive.waypoints] == [0, 60, 180, 240]
    assert dive.waypoints[1].depth == 10.0
    assert dive.waypoints[2].battery is None
