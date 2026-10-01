"""Shearwater Cloud's own "Export as XML" / "Export as CSV" dive files
(Perdix, Petrel, Teric, ...): one dive per file, a dive-level header and
one record per sample (every 2 s on a Perdix 2).

Both exports carry the same fields under different names, so each is read
into rows keyed by the CSV column name (XML_TAGS maps the XML's tags onto
those) and one builder turns rows into Waypoints. Differences handled:

- XML <currentTime> is milliseconds, the CSV's "Time (sec)" seconds.
- The XML says encoding="utf-16" but the file is plain ASCII/UTF-8
  (confirmed against a real Shearwater Cloud Desktop export) - lxml
  refuses that as-is, so the declaration is dropped before parsing.
- The CSV is two tables back to back (dive header + its one row, then
  the sample header + samples) and its header repeats "Computer Firmware
  Version".
- The XML header has no product name (<product> is a number), so the
  device comes from the export's file name "Perdix 2[A5419AC1]#451 ...".
- "Start Date" is written in the exporting PC's locale; the file name's
  own "2025-10-19 11-42-39" picks between day/month readings.

Units: tank pressure is always PSI and SAC PSI/min (SAC confirmed: the
same dive's UDDF gives 1.13 bar/min where this logs 16.48); depth and
temperature follow the "Imperial Units" flag. NDL, TTS and first stop
time are minutes, NDL 99 meaning "99 or more".
"""
import csv
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from lxml import etree

from models.dive import Dive, TankData, Waypoint
from parsers.base import BaseParser
from parsers.deco_pass import apply_deco_and_gas, deco_gas, parse_gf

PSI_TO_BAR = 0.0689476
FT_TO_M = 0.3048
TANK_COLUMNS = [f"Tank {n} pressure (PSI)" for n in range(1, 5)]

# XML tag -> CSV column name, for both the header and the sample records.
XML_TAGS = {
    # header
    "number": "Dive Number",
    "gfMin": "GF Minimum",
    "gfMax": "GF Maximum",
    "imperialUnits": "Imperial Units",
    "startDate": "Start Date",
    "endDate": "End Date",
    "computerSerial": "Computer Serial Number",
    "maxDepth": "Max Depth",
    # samples
    "currentDepth": "Depth",
    "firstStopDepth": "First Stop Depth",
    "ttsMins": "Time To Surface (min)",
    "averagePPO2": "Average PPO2",
    "fractionO2": "Fraction O2",
    "fractionHe": "Fraction He",
    "firstStopTime": "First Stop Time",
    "currentNdl": "Current NDL",
    "currentCircuitSetting": "Current Circuit Mode",
    "waterTemp": "Water Temp",
    "batteryVoltage": "Battery Voltage",
    "tank0pressurePSI": TANK_COLUMNS[0],
    "tank1pressurePSI": TANK_COLUMNS[1],
    "tank2pressurePSI": TANK_COLUMNS[2],
    "tank3pressurePSI": TANK_COLUMNS[3],
    "gasTime": "Gas Time Remaining",
    "sac": "SAC Rate (2 minute avg)",
}

_DATE_FORMATS = [
    "%m/%d/%Y %I:%M:%S %p",
    "%d/%m/%Y %I:%M:%S %p",
    "%m/%d/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
    "%d.%m.%Y %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
]
_FILENAME_DATE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2}) (\d{1,2})-(\d{1,2})-(\d{1,2})")
_FILENAME_DEVICE = re.compile(r"^(.+?)\s*\[")


def _num(value) -> Optional[float]:
    """A float, or None for the exports' blank/"N/A"/"AI is off"/"Not Diving"."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_true(value) -> bool:
    return str(value).strip().lower() == "true"


def read_xml_root(path: Path):
    """The export's root element, despite its wrong encoding declaration."""
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = raw.decode("utf-16")
    else:
        text = raw.decode("utf-8-sig", errors="replace")
    text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text, count=1)
    return etree.fromstring(text.encode("utf-8"), etree.XMLParser(huge_tree=True))


def _xml_tables(path: Path):
    root = read_xml_root(path)
    log = root.find("diveLog")
    if log is None:
        return {}, []
    header = {XML_TAGS.get(child.tag, child.tag): (child.text or "") for child in log if child.tag != "diveLogRecords"}
    rows = []
    for record in log.iter("diveLogRecord"):
        row = {XML_TAGS.get(child.tag, child.tag): (child.text or "") for child in record}
        ms = _num(row.get("currentTime"))
        row["Time (sec)"] = ms / 1000.0 if ms is not None else None
        rows.append(row)
    return header, rows


def _csv_tables(path: Path):
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
        lines = list(csv.reader(f))
    if len(lines) < 2:
        return {}, []
    # setdefault: the first of a repeated column name wins.
    header: Dict[str, str] = {}
    for name, value in zip(lines[0], lines[1]):
        header.setdefault(name, value)
    rows = []
    if len(lines) > 2:
        columns = lines[2]
        for values in lines[3:]:
            if not values:
                continue
            row: Dict[str, str] = {}
            for name, value in zip(columns, values):
                row.setdefault(name, value)
            row["Time (sec)"] = _num(row.get("Time (sec)"))
            rows.append(row)
    return header, rows


def _start_time(header: Dict[str, str], path: Path) -> Optional[datetime]:
    text = (header.get("Start Date") or "").strip()
    candidates = []
    for fmt in _DATE_FORMATS:
        try:
            candidates.append(datetime.strptime(text, fmt))
        except ValueError:
            pass
    match = _FILENAME_DATE.search(path.stem)
    from_name = datetime(*(int(g) for g in match.groups())) if match else None
    if from_name is not None:
        for candidate in candidates:
            if candidate.date() == from_name.date():
                return candidate
    if candidates:
        return candidates[0]
    return from_name


def _divemode(value) -> Optional[str]:
    """XML "OC/BO"/"CC/BO"-style text or the CSV's numeric mode. Only open
    circuit (XML "OC/BO", CSV 1) is confirmed against a real export."""
    text = str(value or "").strip().upper()
    if not text:
        return None
    if text.startswith(("CC", "SC")):
        return "closedcircuit"
    if "OC" in text or text == "1":
        return "opencircuit"
    if text == "0":
        return "closedcircuit"
    return None


class ShearwaterParser(BaseParser):
    def parse(self, file_path: Path) -> List[Dive]:
        file_path = Path(file_path)
        try:
            header, rows = read_tables(file_path)
        except Exception as e:
            print(f"Error parsing Shearwater export {file_path}: {e}")
            return []

        start_time = _start_time(header, file_path)
        if start_time is None or not rows:
            return []

        imperial = _is_true(header.get("Imperial Units"))
        depth_scale = FT_TO_M if imperial else 1.0

        def to_c(value):
            temp = _num(value)
            if temp is None:
                return None
            return (temp - 32.0) * 5.0 / 9.0 if imperial else temp

        waypoints: List[Waypoint] = []
        gases: Dict[tuple, str] = {}
        current_max_depth = 0.0
        last_seconds = -1
        for row in rows:
            seconds_f = row.get("Time (sec)")
            if seconds_f is None:
                continue
            seconds = int(round(seconds_f))
            if seconds <= last_seconds:
                continue
            last_seconds = seconds

            depth = (_num(row.get("Depth")) or 0.0) * depth_scale
            current_max_depth = max(current_max_depth, depth)

            o2 = (_num(row.get("Fraction O2")) or 0.21) * 100.0
            he = (_num(row.get("Fraction He")) or 0.0) * 100.0
            gases.setdefault((round(o2, 1), round(he, 1)), f"{o2:g}/{he:g}")

            stop_depth = (_num(row.get("First Stop Depth")) or 0.0) * depth_scale
            stop_min = _num(row.get("First Stop Time"))
            ndl_min = _num(row.get("Current NDL"))
            # NDL 0 with no stop is the computer at the surface/not diving
            # yet, not "in deco".
            ndl = int(ndl_min * 60) if ndl_min is not None and (ndl_min > 0 or stop_depth > 0) else None
            tts_min = _num(row.get("Time To Surface (min)"))
            gas_time = _num(row.get("Gas Time Remaining"))
            sac_psi = _num(row.get("SAC Rate (2 minute avg)"))

            tanks = {}
            for n, column in enumerate(TANK_COLUMNS, start=1):
                psi = _num(row.get(column))
                if psi is not None and psi > 0:
                    tanks[f"T{n}"] = TankData(pressure_bar=psi * PSI_TO_BAR, o2_percent=o2, he_percent=he)

            po2 = _num(row.get("Average PPO2"))
            waypoints.append(Waypoint(
                timestamp=start_time + timedelta(seconds=seconds),
                depth=depth,
                max_depth=current_max_depth,
                temp=to_c(row.get("Water Temp")),
                ndl=ndl,
                tts=int(tts_min * 60) if tts_min is not None else None,
                deco_stop_depth=stop_depth,
                next_stop_time=int(stop_min * 60) if stop_min is not None and stop_depth > 0 else 0,
                po2=round(po2, 2) if po2 is not None else None,
                divemode=_divemode(row.get("Current Circuit Mode")),
                battery=_num(row.get("Battery Voltage")),
                air_remaining=int(gas_time * 60) if gas_time is not None else None,
                pressure_sac=round(sac_psi * PSI_TO_BAR, 2) if sac_psi is not None and sac_psi > 0 else None,
                time_since_start=seconds,
                dive_time=seconds,
                tanks=tanks,
            ))

        if not waypoints:
            return []

        deco_gases = [deco_gas(name, o2, he) for (o2, he), name in gases.items()]
        apply_deco_and_gas(waypoints, deco_gases, parse_gf(header.get("GF Minimum"), header.get("GF Maximum")))

        device_match = _FILENAME_DEVICE.match(file_path.stem)
        device = (header.get("Product") or "").strip() or (device_match.group(1) if device_match else None)
        end_time = waypoints[-1].timestamp
        return [Dive(
            start_time=start_time,
            end_time=end_time,
            waypoints=waypoints,
            device=device,
            manufactor="Shearwater Research, Inc",
            duration_seconds=int((end_time - start_time).total_seconds()),
            log_filename=file_path.name,
            log_path=str(file_path),
        )]


def read_tables(path: Path):
    """(header, sample rows) of either export, keyed by CSV column name;
    each row's "Time (sec)" is a float of seconds, everything else as in
    the file (so in its own units - see the module docstring)."""
    path = Path(path)
    return _csv_tables(path) if path.suffix.lower() == ".csv" else _xml_tables(path)
