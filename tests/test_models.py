import pytest
from datetime import datetime
from models.dive import Waypoint, Dive, TankData

def test_waypoint_model():
    wp = Waypoint(
        timestamp=datetime.now(),
        depth=10.5,
        temp=24.0,
        time_since_start=60,
        tanks={"1": TankData(pressure_bar=200, o2_percent=21.0)}
    )
    assert wp.depth == 10.5
    assert wp.tanks["1"].pressure_bar == 200

def test_dive_duration():
    start = datetime(2023, 10, 1, 10, 0, 0)
    end = datetime(2023, 10, 1, 11, 0, 0)
    dive = Dive(start_time=start, end_time=end, waypoints=[])
    assert dive.duration == 3600
