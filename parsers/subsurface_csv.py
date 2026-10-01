"""Subsurface's "Export > CSV dive profile" file: one row per sample,
every dive of the export in the same table, keyed by dive number/date/
time:

    "dive number","date","time","sample time (min)","sample depth (m)",
    "sample temperature (C)","sample pressure (bar)","sample heartrate"

Units are in the column names ("(m)"/"(ft)", "(C)"/"(F)", "(bar)"/
"(psi)"). Temperature and pressure are only filled in on the samples
where they changed, so the last value carries forward. There is no gas
or cylinder information: the gas is taken as air in one tank, and NDL/
TTS/ceiling come from the deco recompute. A real export ends with a
spurious "0:01" sample after the last one, skipped like
parsers/subsurface.py skips its wrap-around samples.
"""
import csv
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from models.dive import Dive, TankData, Waypoint
from parsers.base import BaseParser
from parsers.deco_pass import apply_deco_and_gas, deco_gas
from parsers.subsurface import parse_time_str

PSI_TO_BAR = 0.0689476
FT_TO_M = 0.3048


def _column(columns: List[str], prefix: str) -> Tuple[Optional[str], str]:
    """The column starting with `prefix` and the unit in its brackets."""
    for name in columns:
        if name.lower().startswith(prefix):
            unit = name[name.find("(") + 1:name.find(")")].strip().lower() if "(" in name else ""
            return name, unit
    return None, ""


def _num(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def is_subsurface_profile_header(first_line: str) -> bool:
    line = first_line.lower()
    return "sample time" in line and "sample depth" in line


class SubsurfaceCSVParser(BaseParser):
    def parse(self, file_path: Path) -> List[Dive]:
        file_path = Path(file_path)
        try:
            with open(file_path, newline="", encoding="utf-8-sig", errors="replace") as f:
                reader = csv.DictReader(f)
                columns = list(reader.fieldnames or [])
                rows = list(reader)
        except Exception as e:
            print(f"Error parsing Subsurface CSV {file_path}: {e}")
            return []

        time_col, _ = _column(columns, "sample time")
        depth_col, depth_unit = _column(columns, "sample depth")
        temp_col, temp_unit = _column(columns, "sample temperature")
        pressure_col, pressure_unit = _column(columns, "sample pressure")
        hr_col, _ = _column(columns, "sample heartrate")
        if not time_col or not depth_col:
            return []

        # Group samples by dive, keeping the file's dive order.
        groups: Dict[tuple, List[dict]] = {}
        for row in rows:
            key = (row.get("dive number", ""), row.get("date", ""), row.get("time", ""))
            groups.setdefault(key, []).append(row)

        dives = []
        for (number, date_str, time_str), samples in groups.items():
            try:
                start_time = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue

            waypoints: List[Waypoint] = []
            current_max_depth = 0.0
            current_temp = None
            current_pressure = None
            last_seconds = -1
            for row in samples:
                if not row.get(time_col):
                    continue
                seconds = parse_time_str(row[time_col])
                if seconds <= last_seconds:
                    continue
                last_seconds = seconds

                depth = max(0.0, _num(row.get(depth_col)) or 0.0)
                if depth_unit == "ft":
                    depth *= FT_TO_M
                current_max_depth = max(current_max_depth, depth)

                temp = _num(row.get(temp_col)) if temp_col else None
                if temp is not None:
                    current_temp = (temp - 32.0) * 5.0 / 9.0 if temp_unit == "f" else temp
                pressure = _num(row.get(pressure_col)) if pressure_col else None
                if pressure is not None and pressure > 0:
                    current_pressure = pressure * PSI_TO_BAR if pressure_unit == "psi" else pressure
                heart_rate = _num(row.get(hr_col)) if hr_col else None

                waypoints.append(Waypoint(
                    timestamp=start_time + timedelta(seconds=seconds),
                    depth=depth,
                    max_depth=current_max_depth,
                    temp=current_temp,
                    heart_rate=int(heart_rate) if heart_rate is not None else None,
                    time_since_start=seconds,
                    dive_time=seconds,
                    tanks={"1": TankData(pressure_bar=current_pressure)} if current_pressure is not None else {},
                ))

            if not waypoints:
                continue
            apply_deco_and_gas(waypoints, [deco_gas("AIR", 21.0, 0.0)])
            end_time = waypoints[-1].timestamp
            dives.append(Dive(
                start_time=start_time,
                end_time=end_time,
                waypoints=waypoints,
                duration_seconds=int((end_time - start_time).total_seconds()),
                log_filename=file_path.name,
                log_path=str(file_path),
            ))
        return dives
