import pytest
from datetime import datetime
from pathlib import Path
from parsers.base import BaseParser
from parsers.garmin import GarminParser
from models.dive import Waypoint, Dive, TankData


class TestGarmin:

    def test_load(self):
        file = Path(__file__).parent.parent / "test_data" / "release_test" / "fit" / "488 Phuket, Camera Bay.fit"
        dives = GarminParser().parse(file_path=file)

        assert len(dives) > 0
        dive = dives[0]
        assert dive.start_time is not None
        assert len(dive.waypoints) > 0
        assert dive.device is not None
        
        # Check first waypoint
        wp = dive.waypoints[0]
        assert wp.depth >= 0
        assert wp.temp != 0
        
        # Verify tanks
        # We expect 2 tanks as per user report and debug output
        assert len(wp.tanks) == 2
        print(f"Found {len(wp.tanks)} tanks: {list(wp.tanks.keys())}")
