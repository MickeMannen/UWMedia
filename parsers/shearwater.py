from lxml import etree
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from pathlib import Path
from parsers.base import BaseParser
from models.dive import Dive, Waypoint, TankData

class ShearwaterParser(BaseParser):
    def update_timezone(self, file_path: Path, offset_minutes: int):
        """Adds <timezone> tag to <dive> elements if missing."""
        tree = etree.parse(str(file_path))
        root = tree.getroot()
        modified = False
        
        for dive in root.xpath("//*[local-name()='dive']"):
            if not dive.xpath("*[local-name()='timezone']"):
                qname = etree.QName(dive.tag)
                ns = qname.namespace
                if ns:
                    tz_elem = etree.SubElement(dive, "{%s}timezone" % ns)
                else:
                    tz_elem = etree.SubElement(dive, "timezone")
                tz_elem.text = str(offset_minutes)
                modified = True
        
        if modified:
            tree.write(str(file_path), pretty_print=True, xml_declaration=True, encoding="utf-8")
            print(f"Updated timezone in UDDF: {file_path.name}")

    def parse(self, file_path: Path) -> List[Dive]:
        try:
            tree = etree.parse(str(file_path))
        except Exception as e:
            print(f"Error parsing XML file {file_path}: {e}")
            return []
            
        root = tree.getroot()
        dives = []

        # 1. Global metadata (optional, can be overridden by dive-specific data)
        # Try to find device name
        device_name = root.xpath("string(.//*[local-name()='divecomputer']/*[local-name()='name'])")
        manufacturer = root.xpath("string(.//*[local-name()='generator']/*[local-name()='manufacturer']/*[local-name()='name'])")

        # 2. Gas definitions
        gas_mixes = {}
        for mix in root.xpath(".//*[local-name()='mix']"):
            mix_id = mix.get("id")
            name = mix.xpath("string(*[local-name()='name'])") or mix_id
            
            o2_str = mix.xpath("string(*[local-name()='o2'])")
            o2 = float(o2_str) * 100 if o2_str else 21.0
            
            he_str = mix.xpath("string(*[local-name()='he'])")
            he = float(he_str) * 100 if he_str else 0.0
            
            gas_mixes[mix_id] = {
                "name": name,
                "o2": o2,
                "he": he
            }

        # 3. UDDF structure: <uddf> <logbook> <dive>
        for dive_elem in root.xpath("//*[local-name()='dive']"):
            # Extract start time
            start_time = None
            
            # Try <datetime> tag
            dt_str = dive_elem.xpath("string(.//*[local-name()='datetime'])")
            if dt_str:
                try:
                    dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
                    start_time = dt.replace(tzinfo=None)
                except ValueError:
                    pass
            
            if not start_time:
                # Try legacy year/month/day/hour/minute
                year = dive_elem.xpath("string(.//*[local-name()='year'])")
                month = dive_elem.xpath("string(.//*[local-name()='month'])")
                day = dive_elem.xpath("string(.//*[local-name()='day'])")
                hour = dive_elem.xpath("string(.//*[local-name()='hour'])")
                minute = dive_elem.xpath("string(.//*[local-name()='minute'])")
                
                if all([year, month, day, hour, minute]):
                    try:
                        start_time = datetime(int(year), int(month), int(day), int(hour), int(minute))
                    except (ValueError, TypeError):
                        pass
            
            if not start_time:
                continue
            
            tz_offset_str = dive_elem.xpath("string(*[local-name()='timezone'])")
            
            waypoints = []
            current_max_depth = 0.0
            active_mix_id = None
            
            # 4. Process waypoints
            for sample in dive_elem.xpath(".//*[local-name()='waypoint']"):
                seconds_str = sample.xpath("string(*[local-name()='divetime'])")
                if not seconds_str:
                    continue
                    
                try:
                    seconds = int(float(seconds_str))
                except (ValueError, TypeError):
                    continue
                    
                timestamp = start_time + timedelta(seconds=seconds)
                
                # Depth
                depth_str = sample.xpath("string(*[local-name()='depth'])")
                depth = float(depth_str) if depth_str else 0.0
                if depth > current_max_depth:
                    current_max_depth = depth
                
                # Temperature (Kelvin to Celsius)
                temp_str = sample.xpath("string(*[local-name()='temperature'])")
                temp = 0.0
                if temp_str:
                    try:
                        temp = float(temp_str)
                        if temp > 150: # UDDF specifies Kelvin
                            temp -= 273.15
                    except (ValueError, TypeError):
                        pass

                # NDL (nodecotime)
                ndl_str = sample.xpath("string(*[local-name()='nodecotime'])")
                ndl = int(float(ndl_str)) if ndl_str else None

                # CNS
                cns_str = sample.xpath("string(*[local-name()='cns'])")
                cns = int(float(cns_str)) if cns_str else None

                # PO2
                po2_str = sample.xpath("string(*[local-name()='calculatedpo2'])")
                po2 = float(po2_str) if po2_str else None

                # Dive Mode
                divemode = sample.xpath("string(*[local-name()='divemode']/@type)") or \
                           sample.xpath("string(*[local-name()='divemode'])")

                # GF
                gf_str = sample.xpath("string(*[local-name()='gradientfactor'])")
                gf = float(gf_str) if gf_str else None

                # Battery
                batt_str = sample.xpath("string(*[local-name()='batterychargecondition'])")
                battery = float(batt_str) if batt_str else None

                # Gas Switch
                mix_ref = sample.xpath("string(*[local-name()='switchmix']/@ref)")
                if mix_ref:
                    active_mix_id = mix_ref

                # Tank data
                tanks = {}
                pressure_str = sample.xpath("string(*[local-name()='tankpressure'])")
                if pressure_str:
                    try:
                        pressure_pa = float(pressure_str)
                        pressure_bar = pressure_pa / 100000.0 if pressure_pa > 5000 else pressure_pa
                        
                        # Get gas info from active mix
                        gas_info = gas_mixes.get(active_mix_id, {"o2": 21.0, "he": 0.0, "name": "AIR"})
                        
                        tanks["1"] = TankData(
                            pressure_bar=pressure_bar,
                            o2_percent=gas_info["o2"],
                            he_percent=gas_info["he"],
                            name=gas_info["name"]
                        )
                    except (ValueError, TypeError):
                        pass
                
                waypoints.append(Waypoint(
                    timestamp=timestamp,
                    depth=depth,
                    max_depth=current_max_depth,
                    temp=temp,
                    ndl=ndl,
                    cns=cns,
                    po2=po2,
                    divemode=divemode,
                    gf=gf,
                    battery=battery,
                    time_since_start=seconds,
                    dive_time=seconds,
                    tanks=tanks
                ))
            
            if waypoints:
                end_time = waypoints[-1].timestamp
                dives.append(Dive(
                    start_time=start_time,
                    end_time=end_time,
                    waypoints=waypoints,
                    device=device_name if device_name else None,
                    manufactor=manufacturer if manufacturer else None,
                    timezone=tz_offset_str if tz_offset_str else None,
                    log_filename=file_path.name,
                    log_path=str(file_path)
                ))
        
        return dives
