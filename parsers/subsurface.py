import math
from lxml import etree
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from pathlib import Path
from parsers.base import BaseParser
from models.dive import Dive, Waypoint, TankData
from utils.deco_engine import DiveDecompressor, GasDefinition
from utils.config import get_config

def parse_time_str(time_str: str) -> int:
    time_str = time_str.strip()
    is_minutes = False
    is_seconds = False
    
    if time_str.endswith("min"):
        is_minutes = True
        time_str = time_str[:-3].strip()
    elif time_str.endswith("s"):
        is_seconds = True
        time_str = time_str[:-1].strip()
        
    if ":" in time_str:
        parts = time_str.split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            
    try:
        val = float(time_str)
        if is_minutes:
            return int(val * 60)
        return int(val)
    except ValueError:
        return 0

def parse_depth_str(depth_str: str) -> float:
    depth_str = depth_str.strip()
    if depth_str.endswith("m"):
        return float(depth_str[:-1].strip())
    elif depth_str.endswith("ft"):
        return float(depth_str[:-2].strip()) * 0.3048
    try:
        return float(depth_str)
    except ValueError:
        return 0.0

def parse_temp_str(temp_str: str) -> float:
    temp_str = temp_str.strip()
    if temp_str.endswith("C"):
        return float(temp_str[:-1].strip())
    elif temp_str.endswith("F"):
        f_val = float(temp_str[:-1].strip())
        return (f_val - 32.0) * 5.0 / 9.0
    elif temp_str.endswith("K"):
        return float(temp_str[:-1].strip()) - 273.15
    try:
        return float(temp_str)
    except ValueError:
        return 0.0

def parse_pressure_str(pressure_str: str) -> float:
    pressure_str = pressure_str.strip()
    if pressure_str.endswith("bar"):
        return float(pressure_str[:-3].strip())
    elif pressure_str.endswith("psi"):
        return float(pressure_str[:-3].strip()) * 0.0689476
    try:
        return float(pressure_str)
    except ValueError:
        return 0.0

def parse_gas_percent(gas_str: Optional[str], default_val: float) -> float:
    if not gas_str:
        return default_val
    gas_str = gas_str.strip()
    if gas_str.endswith("%"):
        return float(gas_str[:-1].strip())
    try:
        val = float(gas_str)
        if val <= 1.0:
            return val * 100.0
        return val
    except ValueError:
        return default_val

class SubsurfaceParser(BaseParser):
    def parse(self, file_path: Path) -> List[Dive]:
        try:
            tree = etree.parse(str(file_path))
        except Exception as e:
            print(f"Error parsing XML file {file_path}: {e}")
            return []
            
        root = tree.getroot()
        dives = []

        # 1. Parse sites mapped by uuid
        sites_map = {}
        for site in root.xpath("//site"):
            uuid = site.get("uuid")
            name = site.get("name")
            gps = site.get("gps")
            lat, lon = None, None
            if gps:
                try:
                    parts = gps.strip().split()
                    if len(parts) == 2:
                        lat = float(parts[0])
                        lon = float(parts[1])
                except (ValueError, TypeError):
                    pass
            sites_map[uuid] = {"name": name, "lat": lat, "lon": lon}

        # 2. Iterate over all dive elements
        for dive_elem in root.xpath("//dive"):
            date_str = dive_elem.get("date")
            time_str = dive_elem.get("time")
            if not date_str or not time_str:
                continue
                
            try:
                start_time = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue

            duration_str = dive_elem.get("duration")
            duration_seconds = parse_time_str(duration_str) if duration_str else None

            # GPS coordinates from site
            divesiteid = dive_elem.get("divesiteid")
            lat, lon = None, None
            if divesiteid and divesiteid in sites_map:
                lat = sites_map[divesiteid]["lat"]
                lon = sites_map[divesiteid]["lon"]

            # Parse cylinders
            cylinders = []
            for idx, cyl in enumerate(dive_elem.xpath("cylinder")):
                size = cyl.get("size")
                workpressure = cyl.get("workpressure")
                desc = cyl.get("description")
                o2 = parse_gas_percent(cyl.get("o2"), 21.0)
                he = parse_gas_percent(cyl.get("he"), 0.0)
                start_str = cyl.get("start")
                end_str = cyl.get("end")
                cylinders.append({
                    "index": idx,
                    "size": size,
                    "workpressure": workpressure,
                    "description": desc,
                    "o2": o2,
                    "he": he,
                    "start_bar": parse_pressure_str(start_str) if start_str else None,
                    "end_bar": parse_pressure_str(end_str) if end_str else None,
                })

            # Check divecomputer elements
            divecomputer_elem = dive_elem.find("divecomputer")
            if divecomputer_elem is None:
                continue

            device = divecomputer_elem.get("model")
            manufacturer = None
            if device:
                if "Garmin" in device:
                    manufacturer = "Garmin"
                elif "Shearwater" in device:
                    manufacturer = "Shearwater"

            # Parse extradata
            extradata = {}
            for ed in divecomputer_elem.xpath("extradata"):
                k = ed.get("key")
                v = ed.get("value")
                if k:
                    extradata[k] = v

            # Resolve friendly tank names
            tank_keys = {}
            for idx in range(len(cylinders)):
                sensor_key = f"Sensor {idx+1}"
                sensor_id = extradata.get(sensor_key)
                if sensor_id:
                    tank_serial = sensor_id
                else:
                    cyl_desc = cylinders[idx]["description"]
                    tank_serial = cyl_desc if cyl_desc else str(idx+1)
                
                tank_keys[idx] = get_config().map_tank_name(tank_serial)

            # Get water temperature metadata
            water_temp_elem = divecomputer_elem.find("temperature")
            current_temp = None
            if water_temp_elem is not None:
                water_temp_str = water_temp_elem.get("water")
                if water_temp_str:
                    current_temp = parse_temp_str(water_temp_str)

            # Parse waypoints/samples
            waypoints = []
            current_max_depth = 0.0
            last_po2 = None
            current_active_tanks = {}
            # Tracks whether any *live* per-sample pressureN= reading was ever
            # seen for a cylinder - if not, its whole dive gets a start->end
            # linear-interpolation fallback below instead of a flat 0.0,
            # since real exports (confirmed against several real CCR/deco
            # Subsurface logs) commonly log only the dive-level start/end
            # summary, never a live per-sample value.
            live_pressure_seen = [False] * len(cylinders)

            # Initialize current_active_tanks with each cylinder's own
            # starting pressure where known, else 0.0
            for idx, cyl in enumerate(cylinders):
                tank_key = tank_keys.get(idx, str(idx+1))
                current_active_tanks[tank_key] = TankData(
                    pressure_bar=cyl["start_bar"] or 0.0,
                    o2_percent=cyl["o2"],
                    he_percent=cyl["he"],
                    name=cyl["description"] or f"Mix {idx+1}"
                )

            last_seconds = -1
            for sample in divecomputer_elem.xpath("sample"):
                time_val = sample.get("time")
                if not time_val:
                    continue
                
                seconds = parse_time_str(time_val)
                if seconds < last_seconds:
                    # Skip non-monotonic/spurious wrap-around samples at the end
                    continue
                last_seconds = seconds
                timestamp = start_time + timedelta(seconds=seconds)

                # Depth
                depth_val = sample.get("depth")
                depth = parse_depth_str(depth_val) if depth_val else 0.0
                if depth > current_max_depth:
                    current_max_depth = depth

                # Temperature
                temp_val = sample.get("temp")
                if temp_val:
                    current_temp = parse_temp_str(temp_val)

                # PO2
                po2_val = sample.get("po2")
                if po2_val:
                    try:
                        last_po2 = round(float(po2_val.replace("bar", "").strip()), 2)
                    except ValueError:
                        pass
                po2 = last_po2

                # TTS / NDL
                tts_val = sample.get("tts")
                tts = parse_time_str(tts_val) if tts_val else None
                ndl_val = sample.get("ndl")
                ndl = parse_time_str(ndl_val) if ndl_val else None

                # Deco stop - prefer the file's own logged stopdepth/stoptime
                # (same reasoning as the UDDF <decostop> fix: a real
                # device/software's own tuned algorithm beats our generic
                # Buhlmann recompute) over the post-pass recompute below.
                stopdepth_val = sample.get("stopdepth")
                logged_deco_stop_depth = parse_depth_str(stopdepth_val) if stopdepth_val else None
                stoptime_val = sample.get("stoptime")
                logged_next_stop_time = parse_time_str(stoptime_val) if stoptime_val else None

                # Update cylinder pressures
                for idx, cyl in enumerate(cylinders):
                    p_attr = f"pressure{idx}"
                    p_val = sample.get(p_attr)
                    if p_val is not None:
                        live_pressure_seen[idx] = True
                        p_bar = parse_pressure_str(p_val)
                        tank_key = tank_keys.get(idx, str(idx+1))
                        current_active_tanks[tank_key] = TankData(
                            pressure_bar=p_bar,
                            o2_percent=cyl["o2"],
                            he_percent=cyl["he"],
                            name=cyl["description"] or f"Mix {idx+1}"
                        )

                # Extended Garmin fields if present
                gf_val = sample.get("gf")
                gf = float(gf_val) if gf_val else None
                battery_val = sample.get("battery")
                battery = float(battery_val) if battery_val else None

                waypoints.append(Waypoint(
                    timestamp=timestamp,
                    depth=depth,
                    max_depth=current_max_depth,
                    temp=current_temp,
                    ndl=ndl,
                    tts=tts,
                    po2=po2,
                    gf=gf,
                    battery=battery,
                    time_since_start=seconds,
                    dive_time=seconds,
                    tanks=current_active_tanks.copy(),
                    deco_stop_depth=logged_deco_stop_depth,
                    next_stop_time=logged_next_stop_time,
                ))

            if waypoints:
                # --- Decompression Integration ---
                try:
                    deco_gases = []
                    for cyl in cylinders:
                        o2_frac = cyl["o2"] / 100.0
                        he_frac = cyl["he"] / 100.0
                        mod = ((1.4 / o2_frac) - 1.0) * 10.0
                        deco_gases.append(GasDefinition(
                            name=cyl["description"] or f"Mix {cyl['index']}",
                            f_o2=o2_frac,
                            f_he=he_frac,
                            mod_meters=max(0, mod)
                        ))
                    
                    if not deco_gases:
                        deco_gases.append(GasDefinition("AIR", 0.21, 0.0, 56.0))

                    decompressor = DiveDecompressor(simulation_interval=10)
                    wp_dicts = [wp.model_dump() for wp in waypoints]
                    for d in wp_dicts:
                        d['divetime'] = d['time_since_start']
                        d['datetime'] = d['timestamp']
                    
                    deco_results = decompressor.process_waypoints(wp_dicts, deco_gases)
                    
                    for wp in waypoints:
                        res = deco_results.get(wp.time_since_start)
                        if res:
                            wp.tts = res.tts_seconds
                            if wp.deco_stop_depth is None:
                                wp.deco_stop_depth = res.ceiling_meters
                            if wp.gf is None:
                                wp.gf = res.gf_current
                            if wp.po2 is None:
                                wp.po2 = round(res.po2, 2)
                            wp.cns = int(res.cns)

                            ceiling = wp.deco_stop_depth or 0.0
                            if ceiling > 0:
                                wp.next_stop_depth = math.ceil(ceiling / 3.0) * 3.0
                            else:
                                wp.next_stop_depth = 0.0
                            if wp.next_stop_time is None:
                                wp.next_stop_time = 0
                except Exception as e:
                    print(f"Warning: Decompression calculation failed for dive: {e}")

                # Cylinders with no live per-sample pressure reading anywhere
                # in the dive get a start->end linear interpolation over
                # elapsed time instead of a flat (wrong-looking) start value
                # for the whole dive - a real per-dive summary-only export
                # (confirmed against several real CCR/deco Subsurface logs)
                # has no better live signal to go on.
                total_seconds = waypoints[-1].time_since_start or 1
                for idx, cyl in enumerate(cylinders):
                    if live_pressure_seen[idx]:
                        continue
                    start_bar = cyl["start_bar"]
                    end_bar = cyl["end_bar"]
                    if start_bar is None or end_bar is None:
                        continue
                    tank_key = tank_keys.get(idx, str(idx + 1))
                    for wp in waypoints:
                        frac = min(1.0, max(0.0, wp.time_since_start / total_seconds))
                        interpolated = start_bar + (end_bar - start_bar) * frac
                        existing = wp.tanks.get(tank_key)
                        if existing is not None:
                            wp.tanks[tank_key] = existing.model_copy(update={"pressure_bar": interpolated})

                end_time = waypoints[-1].timestamp
                dives.append(Dive(
                    start_time=start_time,
                    end_time=end_time,
                    waypoints=waypoints,
                    device=device,
                    manufactor=manufacturer,
                    start_latitude=lat,
                    start_longitude=lon,
                    duration_seconds=duration_seconds or int((end_time - start_time).total_seconds()),
                    log_filename=file_path.name,
                    log_path=str(file_path)
                ))
        
        return dives
