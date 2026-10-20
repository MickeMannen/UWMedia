from garmin_fit_sdk import Decoder, Stream
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict
from pathlib import Path
from parsers.base import BaseParser
from models.dive import Dive, Waypoint, TankData
from utils.config import get_config
from utils.deco_engine import DiveDecompressor, GasDefinition

FIT_EPOCH_S = 631065600

# garmin_product codes not yet named in the installed garmin_fit_sdk's own
# profile (garmin_fit_sdk/profile.py's garmin_product enum) - the SDK decodes
# these as a raw int instead of a string, presumably because it predates the
# device's registration. Confirmed against real files (product 4518 is the
# "creator" device on every file in test_data/logs/fit/ numbered 455+, per
# user confirmation the diver switched to an x50i around then - two brief
# exceptions at 460/461 still show descent_mk3i, i.e. a temporary swap back).
_UNMAPPED_GARMIN_PRODUCTS = {
    4518: "descent_x50i",
}

# A Garmin rebreather's setpoint switches (dive_alert names) and which of
# dive_settings' two setpoints (ccr_low_setpoint / ccr_high_setpoint) each
# switches to. Confirmed against two Descent CCR dives: their records log no
# po2, the setpoint in force is what the computer shows (as DiveSync reads it).
SETPOINT_ALERTS = {
    "setpoint_switch_auto_low": "low", "setpoint_switch_manual_low": "low",
    "setpoint_switch_auto_high": "high", "setpoint_switch_manual_high": "high",
}
DILUENT_MODE = "closed_circuit_diluent"


def setpoint_timeline(switches, setpoints):
    """[(time, bar)] from the logged setpoint switches (time-sorted (time,
    "low"/"high") pairs) and dive_settings' {"low": bar, "high": bar}: each
    switch's setpoint from its time on, and before the first one the other
    setpoint (a dive that first switches to high was on low until then).
    No switch, or no value for the side switched to: nothing - none is
    invented."""
    out = []
    for when, side in switches:
        value = setpoints.get(side)
        if value is not None:
            out.append((when, float(value)))
    if out:
        first_side = switches[0][1]
        before = setpoints.get("high" if first_side == "low" else "low")
        if before is not None:
            out.insert(0, (None, float(before)))
    return out

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

def _add_ceilings(waypoints: List[Waypoint], gas_dict: Dict) -> None:
    """FIT logs the computer's own next stop but no ceiling, GF99 or SurfGF -
    recompute them with the same Buhlmann pass the UDDF/Subsurface parsers
    already run. On a rebreather's loop the setpoint through the diluent,
    otherwise every gas as open circuit."""
    gases = [
        GasDefinition(f"{g['o2']}/{g['he']}", g["o2"] / 100.0, g["he"] / 100.0, max(0.0, (1.4 / (g["o2"] / 100.0) - 1.0) * 10.0))
        for g in gas_dict.values() if g["status"] and g["o2"]
    ] or [GasDefinition("AIR", 0.21, 0.0, 56.0)]
    try:
        results = DiveDecompressor(simulation_interval=10).process_waypoints(
            [{"divetime": wp.time_since_start, "datetime": wp.timestamp, "depth": wp.depth or 0.0, "setpoint": wp.setpoint,
              "diluent_o2_percent": wp.diluent_o2_percent, "diluent_he_percent": wp.diluent_he_percent} for wp in waypoints],
            gases,
        )
    except Exception as e:
        print(f"Warning: Ceiling calculation failed for dive: {e}")
        return
    for wp in waypoints:
        res = results.get(wp.time_since_start)
        if res:
            wp.ceiling = res.ceiling_meters
            # FIT records no gradient factor: GF99 and SurfGF from the same pass
            if wp.gf is None:
                wp.gf = res.gf_current
            wp.surf_gf = res.surf_gf


class GarminParser(BaseParser):
    def get_unique_tank_serials(self, file_path: Path) -> List[str]:
        """Scans a FIT file and returns all unique tank sensor serial numbers."""
        stream = Stream.from_file(str(file_path))
        decoder = Decoder(stream)
        messages, _ = decoder.read()
        
        serials = set()
        tank_messages = messages.get("tank_update_mesgs", [])
        for t_msg in tank_messages:
            s_id = t_msg.get("sensor")
            if s_id is not None:
                serials.add(str(s_id))
        return list(serials)

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
            product = id_messages[0].get("garmin_product")
            manufacturer = id_messages[0].get("manufacturer")
            if isinstance(product, int) and product in _UNMAPPED_GARMIN_PRODUCTS:
                product = _UNMAPPED_GARMIN_PRODUCTS[product]
            dive_meta["device"] = str(product) if product is not None else None
            dive_meta["manufactor"] = str(manufacturer) if manufacturer is not None else None

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
            
            # The activity's local/UTC pair gives the zone; the dive starts at
            # the session's start_time where there is one - some files stamp
            # the activity at the dive's end (two older Descent CCR dives and a
            # Suunto Ocean); on the owner's own files the two are the same.
            session_start = s_data[0].get("start_time") if s_data else None
            if isinstance(session_start, int):
                session_start = datetime.fromtimestamp(session_start + FIT_EPOCH_S, tz=timezone.utc)
            if session_start is not None:
                start_time_utc = session_start

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
        device_sensors = messages.get("device_info_mesgs", [])
        sensor_data = {}
        for device in device_sensors:
            s_id = device.get("serial_number")
            # Custom Tank Names are usually in 'descriptor' or 'nickname'
            name = device.get("descriptor") or device.get("nickname") or device.get("product_name")
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

        # Which gas is breathed when: FIT doesn't link a tank pod to a gas
        # (tank_update carries only sensor and pressure). The computer logs a
        # dive_gas_switched event with the index of the gas in use, at the
        # start of the dive and at every switch; every tank reading takes the
        # gas active at its time, as the UDDF parser does with <switchmix>.
        gas_switches = []
        for ev in messages.get("event_mesgs", []):
            if ev.get("event") != "dive_gas_switched" or ev.get("data") not in gas_dict:
                continue
            ts = ev.get("timestamp")
            if ts is None:
                continue
            if isinstance(ts, int):
                ts = datetime.fromtimestamp(ts + FIT_EPOCH_S, tz=timezone.utc)
            gas_switches.append((remove_offset(ts.astimezone(tz)), ev["data"]))
        gas_switches.sort(key=lambda pair: pair[0])
        default_gas = 0 if 0 in gas_dict else min(gas_dict, default=None)
        # The start-of-dive switch names the first gas; a dive that logs none
        # (a Descent CCR dive whose first switch is the bailout 58 min in)
        # breathes the first listed gas until its first switch.
        starts_with_switch = bool(gas_switches) and \
            gas_switches[0][0] <= remove_offset(start_time_utc.astimezone(tz)) + timedelta(seconds=60)
        active_gas = gas_switches[0][1] if starts_with_switch else default_gas

        # Tank Updates
        tank_messages_dict = {}
        tanks_following_gas = set()  # tank keys whose readings don't name a gas of their own
        tank_messages = messages.get("tank_update_mesgs", [])
        for t_msg in tank_messages:
            ts = t_msg.get("timestamp")
            if isinstance(ts, int):
                ts = datetime.fromtimestamp(ts + FIT_EPOCH_S, tz=timezone.utc)
            
            # Map to local time
            ts_local = remove_offset(ts.astimezone(tz))
            
            sensor_id = t_msg.get("sensor")
            tank_serial = str(sensor_id) if sensor_id is not None else str(t_msg.get("gas_type_index", "default"))
            
            # Map serial to friendly name from config
            tank_key = get_config().map_tank_name(tank_serial)
            
            tank_name = sensor_data.get(sensor_id, {}).get("name") if sensor_id else None
            
            gas_idx = t_msg.get("gas_type_index")  # not in Garmin's profile; honoured when a file has it
            if gas_idx is None:
                tanks_following_gas.add(tank_key)
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
            tank_messages_dict[ts_local][tank_key] = tank_data

        # Dive-alert events (e.g. "approaching_first_deco_stop", "safety_stop_started") -
        # a more direct state signal than depth-band heuristics; see hud_rules_engine.resolve_state()
        alert_events = []
        for ev in messages.get("event_mesgs", []):
            if ev.get("event") != "dive_alert":
                continue
            alert = ev.get("dive_alert")
            ts = ev.get("timestamp")
            if alert is None or ts is None:
                continue
            if isinstance(ts, int):
                ts = datetime.fromtimestamp(ts + FIT_EPOCH_S, tz=timezone.utc)
            # Some dive_alert values are undecoded enum ints (unrecognized by the SDK's
            # profile) rather than the named string - normalize to str either way
            alert_events.append((remove_offset(ts.astimezone(tz)), str(alert)))
        alert_events.sort(key=lambda pair: pair[0])

        # A rebreather dive: the setpoint in force from the switch alerts
        settings = (messages.get("dive_settings_mesgs") or [{}])[0]
        setpoints = {"low": settings.get("ccr_low_setpoint"), "high": settings.get("ccr_high_setpoint")}
        setpoints_in_force = setpoint_timeline(
            [(when, SETPOINT_ALERTS[name]) for when, name in alert_events if name in SETPOINT_ALERTS], setpoints)
        setpoint_ptr = 0
        setpoint = setpoints_in_force[0][1] if setpoints_in_force and setpoints_in_force[0][0] is None else None
        rebreather = any(g["mode"] == DILUENT_MODE for g in gas_dict.values())
        # The diluent DilPO2 shows, also after a bailout: the one last breathed
        # on the loop, before that the first listed
        diluent = next((g for _, g in sorted(gas_dict.items()) if g["mode"] == DILUENT_MODE), None)

        # Process Waypoints (Records)
        waypoints = []
        current_active_tanks = {}
        record_messages = messages.get("record_mesgs", [])

        # Sort tank updates by time for efficient merging
        sorted_tank_times = sorted(tank_messages_dict.keys())
        
        # If the first record starts before the first tank update, 
        # pre-populate with the first available readings for all unique tanks
        initial_tanks = {}
        unique_tank_keys = set()
        for ts_key in sorted_tank_times:
            for t_key in tank_messages_dict[ts_key].keys():
                if t_key not in unique_tank_keys:
                    initial_tanks[t_key] = tank_messages_dict[ts_key][t_key]
                    unique_tank_keys.add(t_key)
        
        
        current_active_tanks = initial_tanks.copy()
        tank_ptr = 0
        alert_ptr = 0
        switch_ptr = 0
        current_max_depth = 0.0

        def with_active_gas(tanks: Dict[str, TankData]) -> Dict[str, TankData]:
            gas = gas_dict.get(active_gas)
            if gas is None:
                return tanks
            return {
                key: tank.model_copy(update={"o2_percent": float(gas["o2"]), "he_percent": float(gas["he"]),
                                             "mode": gas["mode"], "enabled": gas["status"]})
                if key in tanks_following_gas else tank
                for key, tank in tanks.items()
            }

        wp_tanks = with_active_gas(current_active_tanks)

        for record in record_messages:
            ts = record.get("timestamp")
            if ts is None: continue
            if isinstance(ts, int):
                ts = datetime.fromtimestamp(ts + FIT_EPOCH_S, tz=timezone.utc)
            
            ts_local = remove_offset(ts.astimezone(tz))
            
            # Catch up current_active_tanks and the breathed gas to the current waypoint time
            tanks_changed = False
            while tank_ptr < len(sorted_tank_times) and sorted_tank_times[tank_ptr] <= ts_local:
                updates = tank_messages_dict[sorted_tank_times[tank_ptr]]
                current_active_tanks.update(updates)
                tank_ptr += 1
                tanks_changed = True
            while switch_ptr < len(gas_switches) and gas_switches[switch_ptr][0] <= ts_local:
                if gas_switches[switch_ptr][1] != active_gas:
                    active_gas = gas_switches[switch_ptr][1]
                    tanks_changed = True
                switch_ptr += 1
            if tanks_changed:
                wp_tanks = with_active_gas(current_active_tanks)

            depth = float(record.get("depth", 0.0))
            if depth > current_max_depth:
                current_max_depth = depth

            # Catch up dive-alert events to the current waypoint time (same
            # sorted-pointer pattern as the tank-update merge above)
            wp_alerts = []
            while alert_ptr < len(alert_events) and alert_events[alert_ptr][0] <= ts_local:
                wp_alerts.append(alert_events[alert_ptr][1])
                alert_ptr += 1
            while setpoint_ptr < len(setpoints_in_force) and (setpoints_in_force[setpoint_ptr][0] is None
                                                               or setpoints_in_force[setpoint_ptr][0] <= ts_local):
                setpoint = setpoints_in_force[setpoint_ptr][1]
                setpoint_ptr += 1

            # The breathed gas says the circuit: a diluent is on the loop, any
            # other gas of a rebreather dive is bailout (open circuit).
            gas = gas_dict.get(active_gas)
            on_loop = rebreather and gas is not None and gas["mode"] == DILUENT_MODE
            divemode = ("closedcircuit" if on_loop else "opencircuit") if rebreather else None
            if on_loop:
                diluent = gas
            # PO2: the record's own, else the setpoint in force on the loop,
            # else the breathed gas at this depth (no made-up constant).
            po2 = record.get("po2")
            if po2 is None:
                if on_loop and setpoint is not None:
                    po2 = setpoint
                else:
                    f_o2 = (gas["o2"] if gas and gas["o2"] else 21) / 100.0
                    po2 = round((1.0 + depth / 10.0) * f_o2, 2)

            wp = Waypoint(
                timestamp=ts_local,
                depth=depth,
                max_depth=current_max_depth,
                temp=float(record.get("temperature", 0.0)),
                time_since_start=int((ts_local - start_time_local).total_seconds()),
                dive_time=int((ts_local - start_time_local).total_seconds()),
                deco_stop_depth=float(record.get("next_stop_depth", 0.0)),
                next_stop_depth=float(record.get("next_stop_depth", 0.0)),
                next_stop_time=int(record.get("next_stop_time", 0)),
                tts=int(record.get("time_to_surface", 0)),
                # A Descent leaves ndl_time out where it computes no NDL
                # (shallower than about 7.5 m: unbounded, None) and logs 0 in
                # deco. It read as 0 there, "00" on the overlay (2026-10-20).
                ndl=int(record["ndl_time"]) if record.get("ndl_time") is not None else None,
                air_remaining=int(record.get("air_time_remaining", 0)),
                # FIT logs it in m/s (positive = getting shallower); the HUD works in m/min.
                ascent_rate=float(record.get("ascent_rate", 0.0)) * 60.0,
                n2_tissue_load=float(record.get("n2_load", 0.0)),
                pressure_sac=float(record.get("pressure_sac", 0.0)),
                volume_sac=float(record.get("volume_sac", 0.0)),
                rmv=float(record.get("rmv", 0.0)),
                heart_rate=int(record.get("heart_rate", 0)),
                cns=int(record.get("cns_load", 0)),
                po2=float(po2),
                divemode=divemode,
                setpoint=setpoint if on_loop else None,
                gas_o2_percent=float(gas["o2"]) if rebreather and gas else None,
                gas_he_percent=float(gas["he"]) if rebreather and gas else None,
                diluent_o2_percent=float(diluent["o2"]) if rebreather and diluent else None,
                diluent_he_percent=float(diluent["he"]) if rebreather and diluent else None,
                tanks=dict(wp_tanks),
                dive_alerts=wp_alerts,
            )
            waypoints.append(wp)

        if not waypoints:
            return []
        _add_ceilings(waypoints, gas_dict)

        dive = Dive(
            start_time=start_time_local,
            end_time=end_time_local,
            waypoints=waypoints,
            log_filename=filename.name,
            log_path=str(filename),
            **dive_meta
        )
        
        return [dive]
