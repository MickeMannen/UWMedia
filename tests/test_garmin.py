import pytest
from datetime import datetime
from pathlib import Path
from parsers.base import BaseParser
from parsers.garmin import GarminParser
from models.dive import Waypoint, Dive, TankData


class TestGarmin:

    def test_load(self):
        # file = Path("/Users/mikael/development/UWMedia/test_data/fit/488 Phuket, Camera Bay.fit")
        file = Path("/Users/mikael/DivingMedia/20260524_Sipadan/logs/494 Sipadan, Whitetip Avenue.fit")
        file = Path("/Users/mikael/DivingMedia/20260524_Sipadan/logs/493 Mabul Island, Ray Point.fit")
        file = Path("/Users/mikael/DivingMedia/20260524_Sipadan/logs/494_ebcf9f47-771b-4cbf-bca4-e890544fcb6e.fit")
        file = Path("/Users/mikael/DivingMedia/20260524_Sipadan/logs/494_63776789-32ad-4c9c-becf-68909bd060c8.fit")
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
