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
    path = Path("test_data/ssrf/494.ssrf")
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

def test_parse_495_ssrf():
    parser = SubsurfaceParser()
    path = Path("test_data/ssrf/495.ssrf")
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
