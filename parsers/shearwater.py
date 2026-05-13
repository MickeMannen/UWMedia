from lxml import etree
from datetime import datetime, timedelta
from typing import List
from pathlib import Path
from parsers.base import BaseParser
from models.dive import Dive, Waypoint, TankData

class ShearwaterParser(BaseParser):
    def update_timezone(self, file_path: Path, offset_minutes: int):
        """Adds <timezone> tag to <dive> elements if missing."""
        tree = etree.parse(str(file_path))
        root = tree.getroot()
        modified = False
        
        for dive in root.xpath("//dive"):
            if not dive.xpath("timezone"):
                tz_elem = etree.SubElement(dive, "timezone")
                tz_elem.text = str(offset_minutes)
                modified = True
        
        if modified:
            tree.write(str(file_path), pretty_print=True, xml_declaration=True, encoding="utf-8")
            print(f"Updated timezone in UDDF: {file_path.name}")

    def parse(self, file_path: Path) -> List[Dive]:
        tree = etree.parse(str(file_path))
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
            
            # Read timezone offset if available
            tz_offset_str = dive_elem.xpath("string(timezone)")
            
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
                    waypoints=waypoints,
                    timezone=tz_offset_str if tz_offset_str else None
                ))
        
        return dives
