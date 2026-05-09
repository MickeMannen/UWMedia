import fitparse
from datetime import datetime, timezone
from typing import List
from parsers.base import BaseParser
from models.dive import Dive, Waypoint, TankData

class GarminParser(BaseParser):
    def parse(self, file_path: str) -> List[Dive]:
        fitfile = fitparse.FitFile(file_path)
        waypoints = []
        start_time = None
        
        # Garmin FIT data is a stream of messages
        for record in fitfile.get_messages("record"):
            data = record.get_values()
            
            timestamp = data.get("timestamp")
            if not timestamp:
                continue
            
            if start_time is None:
                start_time = timestamp
            
            depth = data.get("depth", 0.0)
            temp = data.get("temperature", 0.0)
            
            # Garmin uses meters for depth and Celsius for temp usually
            # But let's check field names
            # time_since_start can be calculated
            seconds_since_start = int((timestamp - start_time).total_seconds())
            
            # Tank pressure might be in 'tank_pressure' field
            tanks = {}
            pressure = data.get("tank_pressure")
            if pressure is not None:
                tanks["1"] = TankData(pressure_bar=pressure)
                
            waypoints.append(Waypoint(
                timestamp=timestamp,
                depth=depth,
                temp=temp,
                time_since_start=seconds_since_start,
                tanks=tanks
            ))
            
        if not waypoints:
            return []
            
        end_time = waypoints[-1].timestamp
        return [Dive(
            start_time=start_time,
            end_time=end_time,
            waypoints=waypoints
        )]
