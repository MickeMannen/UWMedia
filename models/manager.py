from datetime import datetime, timedelta
from typing import Dict, Tuple, List, Optional
from models.dive import Dive

# The same dive exported in several formats (a folder holding a dive's
# UDDF, Shearwater CSV and Subsurface CSV) is kept once, from the format
# carrying the most: higher wins, then more samples. Keys are
# parsers.registry format keys; a dive with none ranks lowest.
LOG_FORMAT_RANK = {
    "fit": 5,
    "uddf": 5,
    "shearwater_xml": 5,
    "shearwater_csv": 4,
    "subsurface_xml": 3,
    "subsurface_csv": 1,
}
SAME_DIVE_START_TOLERANCE = timedelta(seconds=60)


def _maker(dive: Dive) -> str:
    return ((dive.manufactor or "").split() or [""])[0].strip(",").lower()


def _richness(dive: Dive) -> Tuple[int, int]:
    return LOG_FORMAT_RANK.get(dive.log_format or "", 0), len(dive.waypoints)


class DiveManager:
    def __init__(self):
        # Key: (start_time, end_time)
        self.dives: Dict[Tuple[datetime, datetime], Dive] = {}

    def _same_dive_key(self, dive: Dive) -> Optional[Tuple[datetime, datetime]]:
        """The key of a dive already held that is `dive` in another format:
        both read from log files (log_format set), different files, starts
        within SAME_DIVE_START_TOLERANCE and not from a different maker's
        computer (two computers worn on one dive stay two dives)."""
        if not dive.log_format:
            return None
        maker = _maker(dive)
        for key, held in self.dives.items():
            if not held.log_format or held.log_path == dive.log_path:
                continue
            if abs(held.start_time - dive.start_time) > SAME_DIVE_START_TOLERANCE:
                continue
            held_maker = _maker(held)
            if maker and held_maker and maker != held_maker:
                continue
            return key
        return None

    def add_dives(self, dives: List[Dive]):
        for dive in dives:
            key = self._same_dive_key(dive)
            if key is not None:
                if _richness(dive) < _richness(self.dives[key]):
                    continue
                del self.dives[key]
            self.dives[(dive.start_time, dive.end_time)] = dive

    def find_dive_for_timestamp(self, timestamp: datetime) -> Optional[Dive]:
        # Expand search by 30 minutes before as per requirements
        for (start, end), dive in self.dives.items():
            if start - timedelta(minutes=30) <= timestamp <= end:
                return dive
        return None

    def print_dives(self):
        for (start, end), dive in self.dives.items():
            print(f"{start} - {end}")
