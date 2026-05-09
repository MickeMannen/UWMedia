from datetime import datetime, timedelta
from typing import Dict, Tuple, List, Optional
from models.dive import Dive

class DiveManager:
    def __init__(self):
        # Key: (start_time, end_time)
        self.dives: Dict[Tuple[datetime, datetime], Dive] = {}

    def add_dives(self, dives: List[Dive]):
        for dive in dives:
            self.dives[(dive.start_time, dive.end_time)] = dive

    def find_dive_for_timestamp(self, timestamp: datetime) -> Optional[Dive]:
        # Expand search by 30 minutes before as per requirements
        for (start, end), dive in self.dives.items():
            if start - timedelta(minutes=30) <= timestamp <= end:
                return dive
        return None
