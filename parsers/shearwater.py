from lxml import etree
from datetime import datetime, timedelta
from typing import List
from parsers.base import BaseParser
from models.dive import Dive, Waypoint, TankData

class ShearwaterParser(BaseParser):
    def parse(self, file_path: str) -> List[Dive]:
        tree = etree.parse(file_path)
        root = tree.getroot()
        dives = []
        
        # UDDF structure: <uddf> <logbook> <dive>
        for dive_elem in root.xpath("//dive"):
            # Extract start time
            # Usually in <informationafterdive> or <datetime>
            # For simplicity, let's assume a standard UDDF structure
            date_str = dive_elem.xpath("string(date/year)") + "-" + \
                       dive_elem.xpath("string(date/month)") + "-" + \
                       dive_elem.xpath("string(date/day)")
            time_str = dive_elem.xpath("string(time/hour)") + ":" + \
                       dive_elem.xpath("string(time/minute)")
            
            start_time = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            
            waypoints = []
            # Samples are usually in <samples> or <repetition>
            for sample in dive_elem.xpath(".//samples/waypoint"):
                seconds = int(sample.xpath("string(divetime)"))
                timestamp = start_time + timedelta(seconds=seconds)
                depth = float(sample.xpath("string(depth)"))
                temp = float(sample.xpath("string(temperature)"))
                
                # Tank data (simplified)
                tanks = {}
                pressure = sample.xpath("string(tankpressure)")
                if pressure:
                    tanks["1"] = TankData(pressure_bar=float(pressure))
                
                waypoints.append(Waypoint(
                    timestamp=timestamp,
                    depth=depth,
                    temp=temp,
                    time_since_start=seconds,
                    tanks=tanks
                ))
            
            if waypoints:
                end_time = waypoints[-1].timestamp
                dives.append(Dive(
                    start_time=start_time,
                    end_time=end_time,
                    waypoints=waypoints
                ))
        
        return dives
