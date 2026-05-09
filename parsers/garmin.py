from garmin_fit_sdk import Decoder, Stream
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict
from pathlib import Path
from parsers.base import BaseParser
from models.dive import Dive, Waypoint, TankData

FIT_EPOCH_S = 631065600

def remove_offset(dt: datetime) -> datetime:
    if dt is None:
        return None
    return dt.replace(tzinfo=None)

def is_offset_aware(dt: datetime) -> bool:
    return dt.tzinfo is not None and dt.tzinfo.utcoffset(dt) is not None

def timezone_from_pair(local_dt: datetime, utc_dt: datetime) -> timezone:
    # Remove tzinfo for calculation if they are aware to get naive delta
    l = remove_offset(local_dt)
    u = remove_offset(utc_dt)
    offset = l - u
    # Round to nearest minute to handle potential small discrepancies
    minutes = round(offset.total_seconds() / 60)
    return timezone(timedelta(minutes=minutes))

class GarminParser(BaseParser):
    def parse(self, file_path: Path) -> List[Dive]:
        """Entry point for the parser, utilizing the extended parse_garmin logic."""
        return self.parse_garmin(file_path)

    def parse_garmin(self, filename: Path) -> List[Dive]:
        """
        Extended logic for decoding Garmin FIT files with detailed dive telemetry.
        """
        stream = Stream.from_file(str(filename))
        decoder = Decoder(stream)
        messages, errors = decoder.read()
        
        if errors:
            print(f"Warning: Errors decoding FIT file {filename}: {errors}")

        # Meta data collection
        dive_meta = {
            "device": None,
            "manufactor": None,
            "start_latitude": None,
            "start_longitude": None,
            "end_latitude": None,
            "end_longitude": None,
            "timezone": None
        }

        id_messages = messages.get("file_id_mesgs", [])
        if id_messages:
            dive_meta["device"] = id_messages[0].get("garmin_product")
            dive_meta["manufactor"] = id_messages[0].get("manufacturer")

        # Time synchronization logic
        def _get_timedata():
            s_data = messages.get("session_mesgs", [])
            a_data = messages.get("activity_mesgs", [])

            if not a_data:
                # Fallback to session data if activity missing
                if s_data:
                    start_time_utc = s_data[0].get("start_time")
                    # Note: SDK usually converts these if requested, 
                    # but here we follow user's manual logic approach if needed.
                    # If SDK already converted to datetime, we use it.
                    if isinstance(start_time_utc, int):
                        start_time_utc = datetime.fromtimestamp(start_time_utc + FIT_EPOCH_S, tz=timezone.utc)
                    
                    start_time_local_epoch = s_data[0].get("local_timestamp")
                    if start_time_local_epoch:
                        start_time_local = datetime.fromtimestamp(start_time_local_epoch + FIT_EPOCH_S, tz=timezone.utc)
                        tz = timezone_from_pair(start_time_local, start_time_utc)
                    else:
                        tz = timezone.utc
                    
                    duration = s_data[0].get("total_elapsed_time", 0)
                    end_time_utc = start_time_utc + timedelta(seconds=duration)
                    return start_time_utc, end_time_utc, duration, tz
                raise SystemError("Failed to find timing data in FIT file")

            start_time_utc = a_data[0].get("timestamp")
            if isinstance(start_time_utc, int):
                start_time_utc = datetime.fromtimestamp(start_time_utc + FIT_EPOCH_S, tz=timezone.utc)
            
            start_time_local_epoch = a_data[0].get("local_timestamp")
            if start_time_local_epoch:
                start_time_local = datetime.fromtimestamp(start_time_local_epoch + FIT_EPOCH_S, tz=timezone.utc)
                tz = timezone_from_pair(start_time_local, start_time_utc)
            else:
                tz = timezone.utc
            
            duration = a_data[0].get("total_timer_time", 0)
            end_time_utc = start_time_utc + timedelta(seconds=duration)
            
            return start_time_utc, end_time_utc, duration, tz

        try:
            start_time_utc, end_time_utc, duration, tz = _get_timedata()
        except SystemError as e:
            print(f"Error: {e}")
            return []

        # Convert to local times for the model storage as per requirement
        start_time_local = remove_offset(start_time_utc.astimezone(tz))
        end_time_local = remove_offset(end_time_utc.astimezone(tz))
        dive_meta["timezone"] = str(tz)

        # GPS Coordinates
        s_data = messages.get("session_mesgs", [])
        if s_data:
            def semicircle_to_degree(sc):
                if sc is None: return None
                return float(sc) * (180.0 / 2**31)

            dive_meta["start_latitude"] = semicircle_to_degree(s_data[0].get("start_position_lat"))
            dive_meta["start_longitude"] = semicircle_to_degree(s_data[0].get("start_position_long"))
            dive_meta["end_latitude"] = semicircle_to_degree(s_data[0].get("end_position_lat"))
            dive_meta["end_longitude"] = semicircle_to_degree(s_data[0].get("end_position_long"))

        # Sensors (e.g. Tank Transmitters)
        device_sensors = messages.get("device_info_mesgs", []) # 147 is device_info
        sensor_data = {}
        for device in device_sensors:
            s_id = device.get("serial_number")
            name = device.get("product_name") or device.get("nickname")
            if s_id:
                sensor_data[s_id] = {"sensor_id": s_id, "name": name}

        # Gas Mixes
        gas_dict = {}
        gas_messages = messages.get("dive_gas_mesgs", [])
        for gas in gas_messages:
            idx = gas.get("message_index")
            if idx is not None:
                gas_dict[idx] = {
                    "he": gas.get("helium_content", 0),
                    "o2": gas.get("oxygen_content", 21),
                    "mode": gas.get("mode", "open_circuit"),
                    "status": gas.get("status") == "enabled"
                }

        # Tank Updates
        tank_messages_dict = {}
        tank_messages = messages.get("tank_update_mesgs", [])
        for t_msg in tank_messages:
            ts = t_msg.get("timestamp")
            if isinstance(ts, int):
                ts = datetime.fromtimestamp(ts + FIT_EPOCH_S, tz=timezone.utc)
            
            # Map to local time
            ts_local = remove_offset(ts.astimezone(tz))
            
            sensor_id = t_msg.get("sensor")
            tank_name = sensor_data.get(sensor_id, {}).get("name") if sensor_id else None
            
            gas_idx = t_msg.get("gas_type_index") # Field 3 usually
            gas_info = gas_dict.get(gas_idx, {"he": 0, "o2": 21, "mode": "open_circuit", "status": True})
            
            tank_data = TankData(
                pressure_bar=float(t_msg.get("pressure", 0.0)),
                o2_percent=float(gas_info["o2"]),
                he_percent=float(gas_info["he"]),
                name=tank_name,
                mode=gas_info["mode"],
                enabled=gas_info["status"]
            )
            
            if ts_local not in tank_messages_dict:
                tank_messages_dict[ts_local] = {}
            tank_messages_dict[ts_local][str(gas_idx or "default")] = tank_data

        # Process Waypoints (Records)
        waypoints = []
        record_messages = messages.get("record_mesgs", [])
        for record in record_messages:
            ts = record.get("timestamp")
            if ts is None: continue
            if isinstance(ts, int):
                ts = datetime.fromtimestamp(ts + FIT_EPOCH_S, tz=timezone.utc)
            
            ts_local = remove_offset(ts.astimezone(tz))
            
            # Map tanks for this waypoint
            # Find nearest tank update or use last seen (simplified for now)
            current_tanks = tank_messages_dict.get(ts_local, {})
            if not current_tanks and waypoints:
                current_tanks = waypoints[-1].tanks

            wp = Waypoint(
                timestamp=ts_local,
                depth=float(record.get("depth", 0.0)),
                temp=float(record.get("temperature", 0.0)),
                time_since_start=int((ts_local - start_time_local).total_seconds()),
                deco_stop_depth=float(record.get("next_stop_depth", 0.0)),
                next_stop_depth=float(record.get("next_stop_depth", 0.0)),
                next_stop_time=int(record.get("next_stop_time", 0)),
                tts=int(record.get("time_to_surface", 0)),
                ndl=int(record.get("ndl_time", 0)),
                air_remaining=int(record.get("air_time_remaining", 0)),
                ascent_rate=float(record.get("ascent_rate", 0.0)),
                n2=float(record.get("n2_load", 0.0)),
                pressure_sac=float(record.get("pressure_sac", 0.0)),
                volume_sac=float(record.get("volume_sac", 0.0)),
                rmv=float(record.get("rmv", 0.0)),
                heart_rate=int(record.get("heart_rate", 0)),
                cns=int(record.get("cns_load", 0)),
                po2=float(record.get("po2", 1.2)),
                tanks=current_tanks
            )
            waypoints.append(wp)

        if not waypoints:
            return []

        dive = Dive(
            start_time=start_time_local,
            end_time=end_time_local,
            waypoints=waypoints,
            **dive_meta
        )
        
        return [dive]
