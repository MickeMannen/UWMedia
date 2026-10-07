"""Log Viewer page backend. QObject exposed to uwmedia/qml/LogViewerPage.qml
as the "logViewerBackend" context property.

The page's layout follows DiveSync's Convert page (dive_sync repo,
desktop/qml/ConvertPage.qml + desktop/controllers/convert.py), without its
save/send parts: Open files / Open folder add dives to one working list,
Remove / Clear take them off again (the files on disk are never touched),
and the selected dive is shown as a grid of fields, a tanks table, a depth
profile, the channels the log holds, its events and - unlike DiveSync - the
full sample table with a filter, which is what an overlay is drawn from.

The one thing that writes a file is "Adjust time" for a Garmin FIT dive
(a dive computer whose clock was wrong): a Save As dialog writes a copy
with the corrected start time and time zone (parsers/fit_time.py), which
is then added to the list; the original is left as it was.

Logs are read through parsers.registry (every format UWMedia reads, .xml/.csv
told apart by content). Every dive of every file is listed, including
several exports of one dive - unlike the media pages' DiveManager, which
keeps only the richest. Reading runs on a worker thread so a folder of FIT
files doesn't freeze the window; the result comes back through a queued
signal. The folder the dialogs open in is remembered in settings.json's
"fields" (key LAST_FOLDER_FIELD).
"""
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import Property, QObject, QStandardPaths, Signal, Slot

from models.dive import Dive
from parsers.fit_time import adjust_fit_time, fit_activity_time
from parsers.registry import LOG_FILE_FILTER, is_log_file, parse_log_file
from utils.app_settings import get_fields, set_field
from utils.config import get_config

LAST_FOLDER_FIELD = "log_viewer_folder"

TABLE_COLUMNS = ["time", "depth", "temp", "ndl", "tts", "gas", "tanks"]
TABLE_HEADERS = ["Time", "Depth (m)", "Temp (°C)", "NDL (s)", "TTS (s)", "Gas", "Tanks"]

# The chart draws at most this many points; a 1 s FIT log of an hour's dive
# has ~3600, which only slows the Canvas down without showing more.
MAX_CHART_POINTS = 1500
MAX_EVENT_LINES = 60

FORMAT_NAMES = {
    "uddf": "UDDF",
    "fit": "Garmin FIT",
    "subsurface_xml": "Subsurface",
    "subsurface_csv": "Subsurface CSV",
    "shearwater_xml": "Shearwater Cloud",
    "shearwater_csv": "Shearwater Cloud CSV",
}

# (Waypoint attribute, label) of the channels listed under the profile as
# "also logged" when any sample of the dive has them.
CHANNEL_LABELS = [
    ("temp", "temperature"),
    ("ndl", "NDL"),
    ("tts", "TTS"),
    ("ceiling", "ceiling"),
    ("deco_stop_depth", "deco stop"),
    ("next_stop_depth", "next stop"),
    ("cns", "CNS"),
    ("po2", "ppO₂"),
    ("po2_1", "ppO₂ cells"),
    ("n2_tissue_load", "N₂ tissue load"),
    ("ascent_rate", "ascent rate"),
    ("air_remaining", "gas time remaining"),
    ("pressure_sac", "SAC"),
    ("rmv", "RMV"),
    ("heart_rate", "heart rate"),
    ("gf", "GF"),
    ("battery", "battery"),
]

# Garmin logs a dismissal after nearly every alert; it says nothing new.
IGNORED_ALERTS = ("alert_dismissed",)


def _num(value: Optional[float], unit: str = "", digits: int = 1) -> str:
    if value is None:
        return ""
    text = f"{value:.{digits}f}"
    return f"{text} {unit}" if unit else text


def _minutes(seconds: Optional[int]) -> str:
    if seconds is None:
        return ""
    return f"{seconds // 60}:{seconds % 60:02d} min"


def _clock(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


def mix_name(o2: float, he: float) -> str:
    o2, he = round(o2), round(he)
    if he:
        return f"Tx {o2}/{he}"
    if o2 == 21:
        return "Air"
    return f"Nx{o2}" if o2 > 21 else f"{o2}% O₂"


def _avg_depth(dive: Dive) -> Optional[float]:
    """Time-weighted mean depth over the samples that have one."""
    points = [(wp.time_since_start, wp.depth) for wp in dive.waypoints if wp.depth is not None]
    if len(points) < 2:
        return points[0][1] if points else None
    area = 0.0
    for (t0, d0), (t1, d1) in zip(points, points[1:]):
        area += (t1 - t0) * (d0 + d1) / 2
    span = points[-1][0] - points[0][0]
    return area / span if span > 0 else None


def _device(dive: Dive) -> str:
    device = dive.device or ""
    maker = dive.manufactor or ""
    if maker and device.lower().startswith(maker.lower()):
        maker = ""
    return " ".join(p for p in (maker, device) if p)


def dive_row(dive: Dive) -> Dict[str, Any]:
    """One line of the page's dive list."""
    return {
        "date": f"{dive.start_time:%Y-%m-%d}",
        "time": f"{dive.start_time:%H:%M}",
        "max_depth": _num(dive.max_depth, "m"),
        "duration": _minutes(dive.duration),
        "file": dive.log_filename or "",
        "device": _device(dive),
    }


def _sensor_label(key: str, reverse_map: Dict[str, str]) -> str:
    serial = reverse_map.get(key)
    return f"{key} ({serial})" if serial and serial != key else key


def _tanks(dive: Dive, reverse_map: Dict[str, str]) -> List[Dict[str, Any]]:
    seen: Dict[str, Dict[str, Any]] = {}
    for wp in dive.waypoints:
        for key, tank in wp.tanks.items():
            entry = seen.get(key)
            if entry is None:
                serial = reverse_map.get(key, "")
                entry = seen[key] = {
                    "index": len(seen) + 1,
                    "key": key,
                    "name": tank.name or "",
                    "serial": serial if serial != key else "",
                    "mix": mix_name(tank.o2_percent, tank.he_percent),
                    "start": None,
                    "end": None,
                }
            if tank.pressure_bar:
                if entry["start"] is None:
                    entry["start"] = tank.pressure_bar
                entry["end"] = tank.pressure_bar
    tanks = list(seen.values())
    for t in tanks:
        t["start_pressure"] = _num(t.pop("start"), "bar", 0)
        t["end_pressure"] = _num(t.pop("end"), "bar", 0)
    return tanks


def _events(dive: Dive) -> List[str]:
    events: List[str] = []
    previous_gas = None
    for wp in dive.waypoints:
        at = _clock(wp.time_since_start)
        for alert in wp.dive_alerts:
            if alert.startswith(IGNORED_ALERTS):
                continue
            events.append(f"{at}  {alert.replace('_', ' ')}")
        if wp.tanks:
            gas = wp.gasmix
            if previous_gas is not None and gas != previous_gas:
                events.append(f"{at}  gas change: {previous_gas} → {gas}")
            previous_gas = gas
    if len(events) > MAX_EVENT_LINES:
        more = len(events) - MAX_EVENT_LINES
        events = events[:MAX_EVENT_LINES] + [f"... and {more} more"]
    return events


def _chart_samples(dive: Dive) -> List[Dict[str, float]]:
    points = [wp for wp in dive.waypoints if wp.depth is not None]
    step = max(1, -(-len(points) // MAX_CHART_POINTS))
    picked = points[::step]
    if points and picked[-1] is not points[-1]:
        picked.append(points[-1])
    return [
        {"time": wp.time_since_start, "depth": wp.depth, "ceiling": wp.ceiling or 0.0}
        for wp in picked
    ]


def dive_details(dive: Dive, reverse_map: Dict[str, str]) -> Dict[str, Any]:
    """Everything the right-hand pane shows for one dive; every value is a
    display string ("" when the log doesn't have it - the page hides those)."""
    temps = [wp.temp for wp in dive.waypoints if wp.temp is not None]
    present = [label for attr, label in CHANNEL_LABELS
               if any(getattr(wp, attr) is not None for wp in dive.waypoints)]
    if any(wp.tanks for wp in dive.waypoints):
        present.insert(0, "tank pressure")
    if any(wp.dive_alerts for wp in dive.waypoints):
        present.append("dive alerts")
    gps = dive.start_latitude is not None and dive.start_longitude is not None
    exit_gps = dive.end_latitude is not None and dive.end_longitude is not None
    samples = _chart_samples(dive)
    return {
        "title": f"{dive.start_time:%Y-%m-%d %H:%M}" + (f" — {_device(dive)}" if _device(dive) else ""),
        "file": dive.log_filename or "",
        "path": dive.log_path or "",
        "format": FORMAT_NAMES.get(dive.log_format or "", dive.log_format or ""),
        "start": f"{dive.start_time:%Y-%m-%d %H:%M:%S}",
        "end": f"{dive.end_time:%Y-%m-%d %H:%M:%S}",
        "timezone": dive.timezone or "",
        "duration": _minutes(dive.duration),
        "max_depth": _num(dive.max_depth, "m"),
        "avg_depth": _num(_avg_depth(dive), "m"),
        "temp_min": _num(min(temps), "°C") if temps else "",
        "temp_max": _num(max(temps), "°C") if temps else "",
        "device": _device(dive),
        "lat": _num(dive.start_latitude, "", 6) if gps else "",
        "lng": _num(dive.start_longitude, "", 6) if gps else "",
        "exit_lat": _num(dive.end_latitude, "", 6) if exit_gps else "",
        "exit_lng": _num(dive.end_longitude, "", 6) if exit_gps else "",
        "tanks": _tanks(dive, reverse_map),
        "samples": samples,
        "has_ceiling": any(s["ceiling"] > 0 for s in samples),
        "sample_count": len(dive.waypoints),
        "channels": present,
        "events": _events(dive),
    }


def _format_tank_reading(key, tank, reverse_map) -> str:
    text = f"{_sensor_label(key, reverse_map)}: {tank.pressure_bar:.0f} bar"
    if tank.he_percent:
        text += f" ({tank.o2_percent:.0f}/{tank.he_percent:.0f})"
    elif abs(tank.o2_percent - 21.0) > 0.5:
        text += f" (Nx{tank.o2_percent:.0f})"
    return text


def sample_rows(dive: Dive, reverse_map: Dict[str, str]) -> List[Dict[str, str]]:
    rows = []
    for wp in dive.waypoints:
        rows.append(
            {
                "time": wp.timestamp.strftime("%H:%M:%S"),
                "depth": f"{wp.depth:.1f}" if wp.depth is not None else "",
                "temp": f"{wp.temp:.1f}" if wp.temp is not None else "",
                "ndl": str(wp.ndl) if wp.ndl is not None else "",
                "tts": str(wp.tts) if wp.tts is not None else "",
                "gas": wp.gasmix if wp.tanks else "",
                "tanks": "; ".join(_format_tank_reading(k, t, reverse_map) for k, t in wp.tanks.items()),
            }
        )
    return rows


def read_logs(paths: List[Path]) -> Tuple[List[Dive], List[str]]:
    """Parse every path; returns the dives and one warning per file that
    could not be read or held no dives."""
    dives: List[Dive] = []
    warnings: List[str] = []
    for path in paths:
        try:
            found = parse_log_file(path)
        except Exception as e:
            warnings.append(f"{path.name}: could not be read ({e})")
            continue
        if found is None:
            warnings.append(f"{path.name}: not a dive log UWMedia reads")
        elif not found:
            warnings.append(f"{path.name}: no dives in the file")
        else:
            for dive in found:
                if not dive.log_path:
                    dive.log_path = str(path)
                if not dive.log_filename:
                    dive.log_filename = path.name
            dives.extend(found)
    return dives, warnings


def log_files_in(folder: Path) -> List[Path]:
    return sorted(
        (f for f in folder.iterdir() if f.is_file() and not f.name.startswith(".") and is_log_file(f)),
        key=lambda f: f.name.lower(),
    )


START_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M")


def parse_local_start(text: str) -> datetime:
    """'2026-03-05 14:23[:07]' as a naive local datetime; ValueError otherwise."""
    text = " ".join(text.split())
    for fmt in START_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    raise ValueError(text)


def parse_utc_offset(text: str) -> int:
    """'+07:00', '-5:30', '+7', 'UTC+08:00' or '0' as minutes east of UTC;
    ValueError otherwise (or outside UTC-12:00..UTC+14:00)."""
    match = re.fullmatch(r"(?:UTC|GMT)?\s*([+-]?)(\d{1,2})(?::?(\d{2}))?", text.strip(), re.IGNORECASE)
    if not match:
        raise ValueError(text)
    sign, hours, minutes = match.groups()
    total = int(hours) * 60 + int(minutes or 0)
    if sign == "-":
        total = -total
    if not -12 * 60 <= total <= 14 * 60 or int(minutes or 0) >= 60:
        raise ValueError(text)
    return total


def format_utc_offset(minutes: int) -> str:
    sign = "-" if minutes < 0 else "+"
    return f"{sign}{abs(minutes) // 60:02}:{abs(minutes) % 60:02}"


def adjusted_name(path: Path) -> Path:
    """Where Save As starts: 'Dive 12.fit' -> 'Dive 12 (adjusted).fit'."""
    return path.with_name(f"{path.stem} (adjusted){path.suffix}")


def _dive_key(dive: Dive):
    return (dive.log_path, dive.start_time)


class LogViewerBackend(QObject):
    divesChanged = Signal()
    selectionChanged = Signal()
    tableChanged = Signal()
    messageChanged = Signal()
    busyChanged = Signal()
    _readDone = Signal(object)

    def __init__(self, background: bool = True):
        super().__init__()
        # Tests read synchronously (background=False); the app uses a thread.
        self._background = background
        self._dives: List[Dive] = []
        self._rows: List[Dict[str, Any]] = []
        self._current = -1
        self._selected: Dict[str, Any] = {}
        self._all_rows: List[Dict[str, str]] = []
        self._filter_text = ""
        self._files: List[str] = []
        self._warnings: List[str] = []
        self._message = ""
        self._busy = False
        self._readDone.connect(self._apply_read)

    # -- list --------------------------------------------------------------

    @Property("QVariantList", notify=divesChanged)
    def dives(self):
        return self._rows

    @Property(int, notify=divesChanged)
    def diveCount(self) -> int:
        return len(self._dives)

    @Property("QVariantList", notify=divesChanged)
    def files(self):
        return self._files

    @Property("QVariantList", notify=divesChanged)
    def warnings(self):
        return self._warnings

    @Property(str, notify=messageChanged)
    def message(self) -> str:
        return self._message

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    def _set_message(self, text: str) -> None:
        self._message = text
        self.messageChanged.emit()

    def _set_busy(self, value: bool) -> None:
        self._busy = value
        self.busyChanged.emit()

    # -- opening -----------------------------------------------------------

    def _dialog_folder(self) -> str:
        folder = get_fields().get(LAST_FOLDER_FIELD) or ""
        if folder and Path(folder).is_dir():
            return folder
        return QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)

    def _remember_folder(self, folder: Path) -> None:
        set_field(LAST_FOLDER_FIELD, str(folder))

    @Slot()
    def openFiles(self):
        from PySide6.QtWidgets import QFileDialog

        paths, _ = QFileDialog.getOpenFileNames(None, "Open dive logs", self._dialog_folder(), LOG_FILE_FILTER)
        if paths:
            self.addFiles(paths)

    @Slot()
    def openFolder(self):
        from PySide6.QtWidgets import QFileDialog

        path = QFileDialog.getExistingDirectory(None, "Open a folder of dive logs", self._dialog_folder())
        if path:
            self.addFolder(path)

    @Slot(str)
    def addFolder(self, folder: str) -> None:
        directory = Path(folder)
        self._remember_folder(directory)
        files = log_files_in(directory)
        if not files:
            self._set_message(f"No dive logs in {directory.name}.")
            return
        self._read([str(f) for f in files])

    @Slot("QVariantList")
    def addFiles(self, paths) -> None:
        paths = [str(p) for p in paths]
        if paths:
            self._remember_folder(Path(paths[0]).parent)
            self._read(paths)

    def _read(self, paths: List[str]) -> None:
        if self._busy:
            return
        files = [Path(p) for p in paths]
        self._set_busy(True)
        self._set_message(f"Reading {len(files)} file{'s' if len(files) != 1 else ''}...")
        if not self._background:
            self._apply_read(read_logs(files))
            return
        threading.Thread(
            target=lambda: self._readDone.emit(read_logs(files)), daemon=True
        ).start()

    def _row_of(self, dive: Dive) -> int:
        # By identity, never list.index(): pydantic's == walks the waypoints,
        # whose private _dive points back at the dive, so comparing two
        # copies of one dive (same dive in two files) recurses without end.
        return next(i for i, d in enumerate(self._dives) if d is dive)

    def _refresh_rows(self) -> None:
        self._rows = [dive_row(d) for d in self._dives]
        self._files = sorted({d.log_filename for d in self._dives if d.log_filename}, key=str.lower)

    def _apply_read(self, outcome) -> None:
        dives, warnings = outcome
        known = {_dive_key(d) for d in self._dives}
        current = self._dives[self._current] if self._current >= 0 else None
        added = [d for d in dives if _dive_key(d) not in known]
        skipped = len(dives) - len(added)
        self._dives = sorted(self._dives + added, key=lambda d: d.start_time)
        self._refresh_rows()
        self._warnings = self._warnings + warnings
        self.divesChanged.emit()

        if current is not None:
            self._set_current(self._row_of(current))
        elif added:
            self._set_current(min(self._row_of(d) for d in added))

        parts = [f"Added {len(added)} dive{'s' if len(added) != 1 else ''}"]
        if skipped:
            parts.append(f"{skipped} already in the list")
        self._set_busy(False)
        self._set_message(", ".join(parts) + ".")

    # -- selection ---------------------------------------------------------

    @Property(int, notify=selectionChanged)
    def currentRow(self) -> int:
        return self._current

    @Property("QVariantMap", notify=selectionChanged)
    def selected(self):
        return self._selected

    @Slot(int)
    def select(self, row: int) -> None:
        if 0 <= row < len(self._dives) and row != self._current:
            self._set_current(row)

    def _set_current(self, row: int) -> None:
        self._current = row
        if row < 0:
            self._selected = {}
            self._all_rows = []
        else:
            reverse_map = {name: serial for serial, name in get_config().get_tank_mapping().items()}
            dive = self._dives[row]
            self._selected = dive_details(dive, reverse_map)
            self._all_rows = sample_rows(dive, reverse_map)
        self._filter_text = ""
        self.selectionChanged.emit()
        self.tableChanged.emit()

    @Slot()
    def removeSelected(self) -> None:
        """Takes the selected dive off the list; the file is not touched."""
        row = self._current
        if not 0 <= row < len(self._dives):
            return
        del self._dives[row]
        self._refresh_rows()
        self.divesChanged.emit()
        self._set_current(min(row, len(self._dives) - 1))
        self._set_message("Removed 1 dive from the list.")

    @Slot()
    def clear(self) -> None:
        self._dives = []
        self._rows = []
        self._files = []
        self._warnings = []
        self.divesChanged.emit()
        self._set_current(-1)
        self._set_message("")

    # -- adjust time (Garmin FIT) -------------------------------------------

    def _selected_dive(self) -> Optional[Dive]:
        return self._dives[self._current] if 0 <= self._current < len(self._dives) else None

    @Property(bool, notify=selectionChanged)
    def canAdjustTime(self) -> bool:
        dive = self._selected_dive()
        return bool(dive and dive.log_format == "fit" and dive.log_path and Path(dive.log_path).is_file())

    @Property(str, notify=selectionChanged)
    def adjustStartText(self) -> str:
        """The selected dive's start as the dialog shows it."""
        dive = self._selected_dive()
        return dive.start_time.strftime("%Y-%m-%d %H:%M:%S") if dive else ""

    @Property(str, notify=selectionChanged)
    def adjustOffsetText(self) -> str:
        """The selected FIT dive's UTC offset as the dialog shows it."""
        if not self.canAdjustTime:
            return ""
        try:
            _, offset = fit_activity_time(Path(self._selected_dive().log_path))
        except (OSError, ValueError):
            return ""
        return format_utc_offset(offset or 0)

    def _dialog_save(self, suggested: Path) -> str:
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(None, "Save the adjusted log", str(suggested), "Garmin FIT (*.fit)")
        return path

    @Slot(str, str, result=str)
    def adjustTime(self, start_text: str, offset_text: str) -> str:
        """The Adjust time dialog's OK: asks where to save, writes the copy
        and adds it to the list. Returns an error for the dialog, or ""."""
        if not self.canAdjustTime:
            return "Only Garmin FIT logs can be adjusted"
        try:
            local_start = parse_local_start(start_text)
        except ValueError:
            return "Enter the start as YYYY-MM-DD HH:MM:SS (the dive site's local time)"
        try:
            offset = parse_utc_offset(offset_text)
        except ValueError:
            return "Enter the time zone as a UTC offset, e.g. +07:00 or -05:30"
        source = Path(self._selected_dive().log_path)
        target = self._dialog_save(adjusted_name(source))
        if not target:
            return ""  # cancelled: nothing written
        target = Path(target)
        if target.suffix.lower() != ".fit":
            target = target.with_name(target.name + ".fit")
        if target.resolve() == source.resolve():
            return "Save the adjusted log under a new name; the original is kept as it is"
        try:
            adjust_fit_time(source, target, local_start, offset)
        except (OSError, ValueError) as e:
            return f"Could not save the adjusted log: {e}"
        self._remember_folder(target.parent)
        self._read([str(target)])
        return ""

    # -- sample table ------------------------------------------------------

    @Property(list, constant=True)
    def tableHeaders(self):
        return TABLE_HEADERS

    @Property(str, notify=tableChanged)
    def filterText(self):
        return self._filter_text

    @filterText.setter
    def filterText(self, value):
        if value == self._filter_text:
            return
        self._filter_text = value
        self.tableChanged.emit()

    @Property("QVariant", notify=tableChanged)
    def tableRows(self):
        text = (self._filter_text or "").lower()
        rows = self._all_rows
        if text:
            rows = [row for row in rows if any(text in str(v).lower() for v in row.values())]
        return [[row[key] for key in TABLE_COLUMNS] for row in rows]
