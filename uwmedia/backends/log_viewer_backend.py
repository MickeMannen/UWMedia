"""Log Viewer page backend - qml_development.md Phase 6. QObject exposed to
uwmedia/qml/LogViewerPage.qml as the "logViewerBackend" context
property.

Ported close to verbatim from uwmedia/pages/log_viewer_page.py
(the old Widgets page, kept as reference only) - reuses UDDFParser/
GarminParser/SubsurfaceParser (parsers.*) and get_config (utils.config)
unchanged; parse_dive_log_file is duplicated here verbatim, same posture
the old Widgets page's own docstring already documents (a small pure
helper, no shared-module home).

Read-only page, no settings persistence - matches the old Widgets page's
own docstring (checked directly against PERSISTED_TEXT_FIELDS/
PERSISTED_SELECTION_FIELDS/PERSISTED_SWITCH_FIELDS in uwmedia/app.py:
none of this page's fields are persisted in the Toga app either).

Single-file parse runs directly (no QThread/asyncio) - same first-pass
simplification the old Widgets page's own docstring already documents,
unchanged here.
"""
from pathlib import Path

from PySide6.QtCore import Property, QObject, Signal, Slot

from parsers.garmin import GarminParser
from parsers.subsurface import SubsurfaceParser
from parsers.uddf import UDDFParser
from utils.config import get_config

LOG_VIEWER_EXTENSIONS = {".fit", ".uddf", ".ssrf", ".xml"}

TABLE_COLUMNS = ["time", "depth", "temp", "ndl", "tts", "gas", "tanks"]
TABLE_HEADERS = ["Time", "Depth (m)", "Temp (°C)", "NDL (s)", "TTS (s)", "Gas", "Tanks"]


def parse_dive_log_file(path: Path):
    suffix = path.suffix.lower()
    if suffix == ".uddf":
        return UDDFParser().parse(path)
    if suffix == ".fit":
        return GarminParser().parse(path)
    if suffix in (".ssrf", ".xml"):
        return SubsurfaceParser().parse(path)
    raise ValueError(f"Unsupported log file type: {suffix}")


class LogViewerBackend(QObject):
    filesChanged = Signal()
    selectionChanged = Signal()
    diveChanged = Signal()
    tableChanged = Signal()
    statusChanged = Signal()

    def __init__(self):
        super().__init__()

        self.log_viewer_files = []
        self.log_viewer_dives = []
        self.log_viewer_dive_map = {}
        self.log_viewer_all_rows = []

        self._dir_label = "No directory selected"
        self._file_name = "None"
        self._dive_labels = []
        self._current_dive_label = ""
        self._summary_text = ""
        self._sensors_text = ""
        self._filter_text = ""
        self._status_text = ""

    # ------------------------------------------------------------------
    # Directory/file list - ported close to verbatim from
    # _on_select_dir/_on_file_select.
    # ------------------------------------------------------------------

    @Property(str, notify=filesChanged)
    def dirLabel(self):
        return self._dir_label

    @Property(list, notify=filesChanged)
    def fileNames(self):
        return [f.name for f in self.log_viewer_files]

    @Property(list, constant=True)
    def tableHeaders(self):
        return TABLE_HEADERS

    @Slot()
    def selectDirectory(self):
        from PySide6.QtWidgets import QFileDialog

        path = QFileDialog.getExistingDirectory(None, "Select dive log directory")
        if not path:
            return
        directory = Path(path)
        self._dir_label = str(directory)

        self.log_viewer_files = sorted(
            (f for f in directory.iterdir() if f.is_file() and f.suffix.lower() in LOG_VIEWER_EXTENSIONS),
            key=lambda f: f.name.lower(),
        )
        self._clear()
        self.filesChanged.emit()
        if self.log_viewer_files:
            self.selectFileAtIndex(0)

    @Slot(int)
    def selectFileAtIndex(self, index):
        if index < 0 or index >= len(self.log_viewer_files):
            return
        self._display_file(self.log_viewer_files[index])

    def _display_file(self, file_path: Path):
        self._file_name = file_path.name
        self._status_text = "Loading..."
        self.selectionChanged.emit()
        self.statusChanged.emit()
        try:
            dives = parse_dive_log_file(file_path)
        except Exception as e:
            self._clear()
            self._status_text = f"Failed to parse {file_path.name}: {e}"
            self.statusChanged.emit()
            return

        self.log_viewer_dives = dives
        if not dives:
            self._clear()
            self._status_text = "No dives found in this file."
            self.statusChanged.emit()
            return

        labels = [
            f"Dive {i + 1}: {dive.start_time:%Y-%m-%d %H:%M} ({len(dive.waypoints)} pts)"
            for i, dive in enumerate(dives)
        ]
        self.log_viewer_dive_map = dict(zip(labels, dives))
        self._dive_labels = labels
        self._current_dive_label = labels[0]
        self.diveChanged.emit()
        self._show_dive(dives[0])

    @Property(str, notify=selectionChanged)
    def selectedFileName(self):
        return self._file_name

    # ------------------------------------------------------------------
    # Dive selector
    # ------------------------------------------------------------------

    @Property(list, notify=diveChanged)
    def diveLabels(self):
        return self._dive_labels

    @Property(str, notify=diveChanged)
    def currentDiveLabel(self):
        return self._current_dive_label

    @Slot(str)
    def selectDive(self, label):
        dive = self.log_viewer_dive_map.get(label)
        if dive is not None:
            self._current_dive_label = label
            self._show_dive(dive)

    # ------------------------------------------------------------------
    # Dive summary/sensors/table - ported close to verbatim from
    # _log_viewer_show_dive/_log_viewer_sensor_label/_format_tank_reading.
    # ------------------------------------------------------------------

    def _sensor_label(self, key, reverse_map):
        serial = reverse_map.get(key)
        return f"{key} ({serial})" if serial and serial != key else key

    def _format_tank_reading(self, key, tank, reverse_map):
        text = f"{self._sensor_label(key, reverse_map)}: {tank.pressure_bar:.0f} bar"
        if tank.he_percent:
            text += f" ({tank.o2_percent:.0f}/{tank.he_percent:.0f})"
        elif abs(tank.o2_percent - 21.0) > 0.5:
            text += f" (Nx{tank.o2_percent:.0f})"
        return text

    def _show_dive(self, dive):
        lines = [
            f"Device: {dive.device or 'Unknown'} ({dive.manufactor or 'Unknown'})",
            f"Start: {dive.start_time:%Y-%m-%d %H:%M:%S}",
            f"End: {dive.end_time:%Y-%m-%d %H:%M:%S}",
            f"Duration: {dive.duration // 60}m {dive.duration % 60}s",
            f"Max depth: {dive.max_depth:.1f} m",
            f"Waypoints: {len(dive.waypoints)}",
        ]
        if dive.start_latitude is not None and dive.start_longitude is not None:
            lines.append(f"Start GPS: {dive.start_latitude:.5f}, {dive.start_longitude:.5f}")
        if dive.timezone:
            lines.append(f"Timezone: {dive.timezone}")
        self._summary_text = "\n".join(lines)

        reverse_map = {name: serial for serial, name in get_config().get_tank_mapping().items()}
        sensors = sorted({key for wp in dive.waypoints for key in wp.tanks.keys()})
        sensor_labels = [self._sensor_label(key, reverse_map) for key in sensors]
        self._sensors_text = ", ".join(sensor_labels) if sensor_labels else "No tank sensor data in this dive."

        rows = []
        for wp in dive.waypoints:
            tanks_text = "; ".join(
                self._format_tank_reading(key, tank, reverse_map) for key, tank in wp.tanks.items()
            )
            rows.append(
                {
                    "time": wp.timestamp.strftime("%H:%M:%S"),
                    "depth": f"{wp.depth:.1f}" if wp.depth is not None else "",
                    "temp": f"{wp.temp:.1f}" if wp.temp is not None else "",
                    "ndl": str(wp.ndl) if wp.ndl is not None else "",
                    "tts": str(wp.tts) if wp.tts is not None else "",
                    "gas": wp.gasmix or "",
                    "tanks": tanks_text,
                }
            )
        self.log_viewer_all_rows = rows
        self._filter_text = ""
        self._status_text = f"{len(rows)} waypoints"
        self.tableChanged.emit()
        self.statusChanged.emit()

    @Property(str, notify=tableChanged)
    def summaryText(self):
        return self._summary_text

    @Property(str, notify=tableChanged)
    def sensorsText(self):
        return self._sensors_text

    @Property(str, notify=statusChanged)
    def statusText(self):
        return self._status_text

    # ------------------------------------------------------------------
    # Waypoint table + live filter - ported close to verbatim from
    # _populate_table/_on_filter.
    # ------------------------------------------------------------------

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
        rows = self.log_viewer_all_rows
        if text:
            rows = [row for row in rows if any(text in str(v).lower() for v in row.values())]
        return [[row[key] for key in TABLE_COLUMNS] for row in rows]

    def _clear(self):
        self.log_viewer_dives = []
        self.log_viewer_dive_map = {}
        self._dive_labels = []
        self._current_dive_label = ""
        self.diveChanged.emit()
        self._file_name = "None"
        self.selectionChanged.emit()
        self._summary_text = ""
        self._sensors_text = ""
        self.log_viewer_all_rows = []
        self._filter_text = ""
        self.tableChanged.emit()
        self._status_text = ""
        self.statusChanged.emit()
