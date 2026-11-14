"""The Suunto app's per-dive JSON export (EON Steel / EON Steel Black / EON
Core, Nautic, D5, Ocean): one dive per file.

    {"DeviceLog": {"Header": {...}, "Samples": [{...}, ...]}}

The tree is the device's own log, in SI units:

- Header: DateTime (ISO 8601 with the time zone), ActivityType (51 is
  scuba; the app exports every sport the same way), Device.Name, Duration
  and DiveTime (s), Diving.Gases[] (Oxygen / Helium fractions, TankSize
  m3, Start/EndPressure Pa) and Diving.Algorithm. The Ocean and the Nautic
  write no Diving block at all, so no gas mixes.
- Samples are sparse records, each with TimeISO8601 and some of: Depth (m),
  Temperature (Kelvin), NoDecTime and TimeToSurface (s), Ceiling (m),
  GasTime (s), Ventilation (m3/s at the surface), Cylinders[] with
  GasNumber, Pressure (Pa) and Pressure2 (a second transmitter on the same
  gas: sidemount), and events. A value carries forward to the next record
  that has the key again.
- Events: Events[] (EON / D5) or DiveEvents (Ocean / Nautic, an object or
  a list), each {Notify|Warning|Alarm|State: {Type, Active}} or
  {GasSwitch: {GasNumber}}.

Quirks handled: gas numbers are 1-based list positions on the EON / D5 and
an explicit 0-based GasNumber on the Ocean / Nautic; records are not always
in time order and can share a second (sorted, the first kept); records
after DiveTime are surface readings (dropped); NoDecTime -1 and
TimeToSurface 0 mean "no value", NoDecTime 6000 is the 100-minute display
cap; Ceiling 0 means no ceiling; the Nautic's Device.Name is its internal
name "Vaasa".

No stop time is logged: NDL, TTS and the ceiling are the computer's own,
the stop time and the GF99 come from the deco pass (parsers/deco_pass.py).
RtGradientFactors.gf99 is not read: its values (up to 12 575 on a deco
ascent) are not a GF99 in percent.
"""
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from models.dive import Dive, TankData, Waypoint
from parsers.base import BaseParser
from parsers.deco_pass import apply_deco_and_gas, deco_gas

SCUBA_ACTIVITY = 51
PA_PER_BAR = 100000.0
KELVIN = 273.15
NDL_ABSENT = -1
EVENT_KINDS = ("Notify", "Warning", "Alarm", "State")

# Device.Name as the app writes it -> the model name the templates use.
INTERNAL_NAMES = {"vaasa": "Nautic", "porvoo": "Ocean"}

# Gradient factors in force when the log names none (manuals: Nautic
# medium 40/85, p.42; EON Bühlmann 16 GF 30/70, EON Core p.18). A Fused
# RGBM 2 dive gets the deco engine's own default.
DEFAULT_GF = {"nautic": (0.40, 0.85)}
BUHLMANN_DEFAULT_GF = (0.30, 0.70)

# Suunto event types -> the dive_alerts names the HUD rules already know
# (hud_rules.json "alert"), keyed by the type with only letters and digits.
ALERTS = {
    "ceilingbroken": "deco_ceiling_broken",
    "po2high": "po2_crit_high",
    "po2low": "po2_crit_low",
    "ascentspeed": "ascent_critical",
    "safetystopbroken": "safety_stop_broken",
    "cns80": "cns_warning",
    "cns100": "cns_critical",
    "otu250": "otu_warning",
    "otu300": "otu_critical",
}


def is_suunto_json(head: str) -> bool:
    """Whether the start of a .json file is a Suunto app dive export."""
    return '"DeviceLog"' in head


def _key(text) -> str:
    return "".join(c for c in str(text or "").lower() if c.isalnum())


def _num(value) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_time(text) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None


def read_device_log(path: Path) -> Dict[str, Any]:
    with open(path, encoding="utf-8-sig") as f:
        data = json.load(f)
    log = data.get("DeviceLog", data) if isinstance(data, dict) else {}
    return log if isinstance(log, dict) else {}


def device_name(log: Dict[str, Any]) -> Optional[str]:
    header = log.get("Header") or {}
    device = header.get("Device") or log.get("Device") or {}
    name = str(device.get("Name") or "").strip()
    return INTERNAL_NAMES.get(name.lower(), name) or None


@dataclass
class SuuntoGas:
    number: int
    o2_percent: float
    he_percent: float
    tank_size_l: Optional[float] = None
    start_pressure_bar: Optional[float] = None


def read_gases(log: Dict[str, Any]) -> Dict[int, SuuntoGas]:
    """The header's gases by the number the samples use for them."""
    gases: Dict[int, SuuntoGas] = {}
    listed = ((log.get("Header") or {}).get("Diving") or {}).get("Gases") or []
    for position, gas in enumerate(listed, start=1):
        if not isinstance(gas, dict):
            continue
        number = gas.get("GasNumber")
        number = int(number) if _num(number) is not None else position
        o2 = _num(gas.get("Oxygen"))
        size = _num(gas.get("TankSize"))
        start = _num(gas.get("StartPressure")) or _num(gas.get("TankFillPressure"))
        gases[number] = SuuntoGas(
            number=number,
            o2_percent=round(o2 * 100.0, 1) if o2 is not None else 21.0,
            he_percent=round((_num(gas.get("Helium")) or 0.0) * 100.0, 1),
            tank_size_l=round(size * 1000.0, 1) if size else None,
            start_pressure_bar=round(start / PA_PER_BAR, 1) if start else None,
        )
    return gases


@dataclass
class _Record:
    seconds: float
    values: Dict[str, Any]
    events: List[Tuple[str, str, bool]] = field(default_factory=list)
    gas_switch: Optional[int] = None


def _event_items(raw) -> Iterable[Dict[str, Any]]:
    if isinstance(raw, dict):
        return [raw]
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def sample_records(log: Dict[str, Any], start: datetime) -> List[_Record]:
    """The samples as records in time order, seconds from the header's
    start; records after DiveTime (surface readings) are left out."""
    header = log.get("Header") or {}
    limit = _num(header.get("DiveTime"))
    records = []
    for sample in log.get("Samples") or []:
        if not isinstance(sample, dict):
            continue
        when = parse_time(sample.get("TimeISO8601"))
        if when is None:
            continue
        seconds = (when - start).total_seconds()
        if seconds < 0 or (limit is not None and seconds > limit):
            continue
        record = _Record(seconds, sample)
        for item in [*_event_items(sample.get("Events")), *_event_items(sample.get("DiveEvents"))]:
            for kind, body in item.items():
                if kind == "GasSwitch" and isinstance(body, dict) and _num(body.get("GasNumber")) is not None:
                    record.gas_switch = int(body["GasNumber"])
                elif kind in EVENT_KINDS and isinstance(body, dict):
                    record.events.append((kind, str(body.get("Type") or ""), body.get("Active", True) is not False))
        records.append(record)
    records.sort(key=lambda r: r.seconds)  # stable: same-time records keep their file order
    return records


def _alerts(events: List[Tuple[str, str, bool]]) -> List[str]:
    """dive_alerts for the events that switched on: the shared alert name
    where one means the same, and "suunto:<Type>" for every one."""
    alerts = []
    for kind, kind_type, active in events:
        if not active or kind == "State" or not kind_type:
            continue
        shared = ALERTS.get(_key(kind_type))
        if shared and shared not in alerts:
            alerts.append(shared)
        alerts.append(f"suunto:{kind_type}")
    return alerts


def _file_gf(log: Dict[str, Any], device: Optional[str]) -> Optional[Tuple[float, float]]:
    algorithm = _key(((log.get("Header") or {}).get("Diving") or {}).get("Algorithm"))
    for model, gf in DEFAULT_GF.items():
        if model in _key(device):
            return gf
    if "buhlmann" in algorithm or "bhlmann" in algorithm:
        return BUHLMANN_DEFAULT_GF
    return None


class SuuntoJSONParser(BaseParser):
    def parse(self, file_path: Path) -> List[Dive]:
        file_path = Path(file_path)
        try:
            log = read_device_log(file_path)
        except (OSError, ValueError) as e:
            print(f"Error parsing Suunto export {file_path}: {e}")
            return []
        header = log.get("Header") or {}
        if header.get("ActivityType") != SCUBA_ACTIVITY:
            print(f"Skipping {file_path.name}: not a scuba dive (Suunto activity {header.get('ActivityType')})")
            return []
        start = parse_time(header.get("DateTime"))
        if start is None:
            return []

        gases = read_gases(log)
        device = device_name(log)
        start_local = start.replace(tzinfo=None)
        waypoints, logged_ceilings = self._waypoints(sample_records(log, start), gases, start_local)
        if not waypoints:
            return []

        mixes = {(g.o2_percent, g.he_percent) for g in gases.values()} or {(21.0, 0.0)}
        apply_deco_and_gas(
            waypoints,
            [deco_gas(f"{o2:g}/{he:g}", o2, he) for o2, he in sorted(mixes)],
            _file_gf(log, device),
        )
        for wp, ceiling in zip(waypoints, logged_ceilings):
            if ceiling is not None:
                wp.ceiling = ceiling

        end_time = waypoints[-1].timestamp
        return [Dive(
            start_time=start_local,
            end_time=end_time,
            waypoints=waypoints,
            device=device,
            manufactor="Suunto",
            timezone=str(start.tzinfo) if start.tzinfo else None,
            duration_seconds=int((end_time - start_local).total_seconds()),
            log_filename=file_path.name,
            log_path=str(file_path),
        )]

    @staticmethod
    def _waypoints(records: List[_Record], gases: Dict[int, SuuntoGas], start: datetime):
        """One waypoint per record with a depth, each value carried forward
        from the last record that had it; events between two waypoints go
        on the later one. Returns the waypoints and the ceiling each one's
        log gave (None where none was logged yet)."""
        waypoints: List[Waypoint] = []
        logged_ceilings: List[Optional[float]] = []
        state: Dict[str, Any] = {}
        pressures: Dict[Tuple[int, str], float] = {}
        tank_names: Dict[Tuple[int, str], str] = {}
        current_gas = min(gases) if gases else None
        pending_alerts: List[str] = []
        max_depth, last_second = 0.0, -1

        for record in records:
            values = record.values
            if record.gas_switch is not None:
                current_gas = record.gas_switch
            for alert in _alerts(record.events):
                if alert not in pending_alerts:
                    pending_alerts.append(alert)

            temp = _num(values.get("Temperature"))
            if temp is not None:
                state["temp"] = round(temp - KELVIN, 2) if temp > 100 else temp
            ndl = _num(values.get("NoDecTime"))
            if ndl is not None:
                state["ndl"] = None if ndl <= NDL_ABSENT else int(ndl)
            tts = _num(values.get("TimeToSurface"))
            if tts is not None:
                state["tts"] = int(tts) if tts > 0 else None
            ceiling = _num(values.get("Ceiling"))
            if ceiling is not None:
                state["ceiling"] = max(0.0, ceiling)
            gas_time, ventilation = values.get("GasTime"), values.get("Ventilation")
            for cylinder in values.get("Cylinders") or []:
                if not isinstance(cylinder, dict) or _num(cylinder.get("GasNumber")) is None:
                    continue
                number = int(cylinder["GasNumber"])
                for slot in ("Pressure", "Pressure2", "Pressure3"):
                    pa = _num(cylinder.get(slot))
                    if pa is not None and pa > 0:
                        pressures[(number, slot)] = round(pa / PA_PER_BAR, 1)
                        tank_names.setdefault((number, slot), f"T{len(tank_names) + 1}")
                if number == current_gas:
                    gas_time = cylinder.get("GasTime", gas_time)
                    ventilation = cylinder.get("Ventilation", ventilation)
            if "GasTime" in values or values.get("Cylinders"):
                seconds_left = _num(gas_time)
                state["air_remaining"] = int(seconds_left) if seconds_left is not None and seconds_left > 0 else None
            if "Ventilation" in values or values.get("Cylinders"):
                m3_per_s = _num(ventilation)
                state["rmv"] = round(m3_per_s * 60000.0, 1) if m3_per_s else None

            depth = _num(values.get("Depth"))
            second = int(round(record.seconds))
            if depth is None or second <= last_second:
                continue
            last_second = second
            depth = max(0.0, depth)
            max_depth = max(max_depth, depth)

            gas = gases.get(current_gas) if current_gas is not None else None
            tanks = {}
            for (number, slot), name in sorted(tank_names.items(), key=lambda item: item[1]):
                mix = gases.get(number)
                tanks[name] = TankData(
                    pressure_bar=pressures[(number, slot)],
                    o2_percent=mix.o2_percent if mix else 21.0,
                    he_percent=mix.he_percent if mix else 0.0,
                )
            logged_ceilings.append(state.get("ceiling"))
            waypoints.append(Waypoint(
                timestamp=start + timedelta(seconds=second),
                depth=depth,
                max_depth=max_depth,
                temp=state.get("temp"),
                ndl=state.get("ndl"),
                tts=state.get("tts"),
                deco_stop_depth=state.get("ceiling"),
                air_remaining=state.get("air_remaining"),
                rmv=state.get("rmv"),
                gas_o2_percent=gas.o2_percent if gas else None,
                gas_he_percent=gas.he_percent if gas else None,
                time_since_start=second,
                dive_time=second,
                tanks=tanks,
                dive_alerts=pending_alerts,
            ))
            pending_alerts = []
        return waypoints, logged_ceilings
