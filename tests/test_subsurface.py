import pytest
from pathlib import Path
from parsers.subsurface import SubsurfaceParser
from models.dive import Dive, Waypoint, TankData

def test_missing_file():
    parser = SubsurfaceParser()
    dives = parser.parse(Path("non_existent_file.ssrf"))
    assert dives == []

def test_parse_494_ssrf():
    parser = SubsurfaceParser()
    path = Path("test_data/logs/ssrf/494.ssrf")
    dives = parser.parse(path)
    
    assert len(dives) == 1
    dive = dives[0]
    
    assert dive.start_time.year == 2026
    assert dive.start_time.month == 5
    assert dive.start_time.day == 26
    assert dive.start_time.hour == 6
    assert dive.start_time.minute == 49
    assert dive.start_time.second == 24
    
    assert len(dive.waypoints) > 0
    # First sample: <sample time='0:01 min' depth='1.233 m' temp='30.0 C' po2='0.7 bar' />
    first_wp = dive.waypoints[0]
    assert first_wp.time_since_start == 1
    assert first_wp.depth == 1.233
    assert first_wp.temp == 30.0
    assert first_wp.po2 == 0.7
    
    # Check max depth matches metadata or correct calculation
    assert dive.max_depth > 20.0
    
    # Check device/manufacturer
    assert dive.device == "Garmin Descent Mk2(i)/Mk3(i)(S)/G1/G2/X50i"
    assert dive.manufactor == "Garmin"
    
    # Check coordinates from site id mapping
    assert dive.start_latitude == 4.119861
    assert dive.start_longitude == 118.633856

    # Verify tanks are loaded and mapped using Sensor ID d5461f8c
    # Sample at 0:09 has pressure0='192.98 bar'
    wp_9s = next(wp for wp in dive.waypoints if wp.time_since_start == 9)
    # The serial Sensor 1 is 'd5461f8c'
    # Without config mapping, it should be key 'd5461f8c'
    assert "d5461f8c" in wp_9s.tanks
    assert wp_9s.tanks["d5461f8c"].pressure_bar == 192.98

    # gf is populated (native sample value here) rather than the deco-engine's
    # computed current-GF being written into the Garmin-only n2_tissue_load field
    # they used to share under the old "n2" name - see rework_hud.md Phase 2 item 12
    assert wp_9s.gf is not None
    assert wp_9s.n2_tissue_load is None

_DECO_AND_SUMMARY_PRESSURE_XML = """<divelog program='subsurface' version='3'>
<dives>
<dive number='1' date='2026-01-01' time='10:00:00' duration='10:00 min'>
  <cylinder size='11.0 l' description='Back gas (air)' start='200.0 bar' end='120.0 bar' />
  <divecomputer model='Test Computer'>
  <sample time='0:00 min' depth='0.0 m' />
  <sample time='5:00 min' depth='30.0 m' stopdepth='6.0 m' stoptime='2:00 min' />
  <sample time='10:00 min' depth='0.0 m' />
  </divecomputer>
</dive>
</dives>
</divelog>
"""

def test_deco_stop_prefers_logged_value_over_recompute(tmp_path):
    # A real device/software's own logged stopdepth/stoptime is more
    # authoritative than our generic Buhlmann recompute (same reasoning as
    # the UDDF <decostop> fix) - the sample that logs one explicitly must
    # keep exactly that value.
    path = tmp_path / "deco.ssrf.xml"
    path.write_text(_DECO_AND_SUMMARY_PRESSURE_XML)

    parser = SubsurfaceParser()
    dives = parser.parse(path)
    assert len(dives) == 1

    wp = next(wp for wp in dives[0].waypoints if wp.time_since_start == 300)
    assert wp.deco_stop_depth == 6.0
    assert wp.next_stop_time == 120

def test_cylinder_pressure_interpolates_when_no_live_samples(tmp_path):
    # Several real CCR/deco Subsurface exports only carry a dive-level
    # start=/end= cylinder summary, never a live per-sample pressureN=
    # reading - confirmed against real submersion_dives/*.ssrf.xml files.
    # Interpolating start->end over elapsed time beats a flat (visibly wrong)
    # 0.0 or a flat start value for the whole dive.
    path = tmp_path / "pressure.ssrf.xml"
    path.write_text(_DECO_AND_SUMMARY_PRESSURE_XML)

    parser = SubsurfaceParser()
    dives = parser.parse(path)
    waypoints = dives[0].waypoints

    tank_key = next(iter(waypoints[0].tanks))
    assert waypoints[0].tanks[tank_key].pressure_bar == pytest.approx(200.0)
    assert waypoints[-1].tanks[tank_key].pressure_bar == pytest.approx(120.0)
    mid = next(wp for wp in waypoints if wp.time_since_start == 300)
    assert mid.tanks[tank_key].pressure_bar == pytest.approx(160.0)

def test_parse_495_ssrf():
    parser = SubsurfaceParser()
    path = Path("test_data/logs/ssrf/495.ssrf")
    dives = parser.parse(path)
    
    assert len(dives) == 1
    dive = dives[0]
    
    assert dive.start_time.year == 2026
    assert dive.start_time.month == 5
    assert dive.start_time.day == 26
    assert dive.start_time.hour == 8
    assert dive.start_time.minute == 56
    assert dive.start_time.second == 37
    
    assert len(dive.waypoints) > 0
    assert dive.start_latitude == 4.104267
    assert dive.start_longitude == 118.631528
