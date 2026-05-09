import pytest
from datetime import datetime
from pathlib import Path
from parsers.base import BaseParser
from parsers.garmin import GarminParser
from models.dive import Waypoint, Dive, TankData


class TestGarmin:

    def test_load(self):
        dive = GarminParser().parse(file_path=Path("/Users/mikael/development/UWMedia/test_data/fit/448 Tioman Island, Batu Jahat.fit"))

        pass
