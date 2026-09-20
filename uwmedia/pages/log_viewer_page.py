"""Log Viewer page - PySide6 port of uwmedia/app.py's
_build_log_viewer_fields/_build_log_viewer_section and friends, see
pyside6_rework.md Phase 6.

Built entirely in Python, no .ui file - same shape as Phase 5's Tag
Editor (left file list + right detail cards), reused directly rather
than re-derived from scratch.

Reused verbatim: UDDFParser/GarminParser/SubsurfaceParser (parsers.*),
get_config (utils.config) - all zero-Toga-dependency engine code.
parse_dive_log_file itself lives in uwmedia/app.py (not a shared utils
module) - duplicated here verbatim, same "small pure helper, no state"
posture as color_page.py's own load_color_profiles duplication.

Read-only page - no settings persistence, matching uwmedia/app.py's own
PERSISTED_TEXT_FIELDS/PERSISTED_SELECTION_FIELDS/PERSISTED_SWITCH_FIELDS
(none of this page's fields are listed there either).

Single-file parse runs directly on the UI thread rather than via
asyncio.to_thread (the Toga original's approach) - parsing one dive log
file is fast enough in practice that a QThread worker would be pure
overhead for this first pass; unlike Tag Editor's own batch loop over
many files, there's no per-item progress to keep the UI responsive for.
"""
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from parsers.garmin import GarminParser
from parsers.subsurface import SubsurfaceParser
from parsers.uddf import UDDFParser
from utils.config import get_config

LOG_VIEWER_EXTENSIONS = {".fit", ".uddf", ".ssrf", ".xml"}


def parse_dive_log_file(path: Path):
    suffix = path.suffix.lower()
    if suffix == ".uddf":
        return UDDFParser().parse(path)
    if suffix == ".fit":
        return GarminParser().parse(path)
    if suffix in (".ssrf", ".xml"):
        return SubsurfaceParser().parse(path)
    raise ValueError(f"Unsupported log file type: {suffix}")


class LogViewerPage(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.log_viewer_files = []
        self.log_viewer_dives = []
        self.log_viewer_dive_map = {}
        self.log_viewer_all_rows = []

        self._build_ui()
        self._wire_signals()

    # ------------------------------------------------------------------
    # Layout - ported from _build_log_viewer_section.
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QtWidgets.QHBoxLayout(self)

        left = QtWidgets.QVBoxLayout()
        left_widget = QtWidgets.QWidget()
        left_widget.setLayout(left)
        left_widget.setFixedWidth(260)
        self.select_dir_button = QtWidgets.QPushButton("Select Log Directory")
        left.addWidget(self.select_dir_button)
        self.log_viewer_dir_label = QtWidgets.QLabel("No directory selected")
        self.log_viewer_dir_label.setWordWrap(True)
        left.addWidget(self.log_viewer_dir_label)
        self.log_viewer_file_list = QtWidgets.QListWidget()
        left.addWidget(self.log_viewer_file_list, stretch=1)
        root.addWidget(left_widget)

        right = QtWidgets.QVBoxLayout()

        selected_group = QtWidgets.QGroupBox("Selected file")
        file_header = QtWidgets.QHBoxLayout(selected_group)
        self.log_viewer_file_name_label = QtWidgets.QLabel("None")
        self.log_viewer_file_name_label.setStyleSheet("font-weight: bold;")
        file_header.addWidget(self.log_viewer_file_name_label)
        file_header.addStretch(1)
        file_header.addWidget(QtWidgets.QLabel("Dive:"))
        self.log_viewer_dive_select = QtWidgets.QComboBox()
        self.log_viewer_dive_select.setFixedWidth(280)
        file_header.addWidget(self.log_viewer_dive_select)
        right.addWidget(selected_group)

        summary_group = QtWidgets.QGroupBox("Dive summary")
        summary_layout = QtWidgets.QVBoxLayout(summary_group)
        self.log_viewer_summary_label = QtWidgets.QPlainTextEdit()
        self.log_viewer_summary_label.setReadOnly(True)
        self.log_viewer_summary_label.setFixedHeight(140)
        summary_layout.addWidget(self.log_viewer_summary_label)
        right.addWidget(summary_group)

        sensors_group = QtWidgets.QGroupBox("Tank sensors found")
        sensors_layout = QtWidgets.QVBoxLayout(sensors_group)
        self.log_viewer_sensors_label = QtWidgets.QPlainTextEdit()
        self.log_viewer_sensors_label.setReadOnly(True)
        self.log_viewer_sensors_label.setFixedHeight(50)
        sensors_layout.addWidget(self.log_viewer_sensors_label)
        sensors_hint = QtWidgets.QLabel(
            "Use these serial numbers in Advanced → Sensor names to map them to friendly names."
        )
        sensors_hint.setWordWrap(True)
        sensors_hint.setStyleSheet("color: gray; font-size: 10px;")
        sensors_layout.addWidget(sensors_hint)
        right.addWidget(sensors_group)

        filter_row = QtWidgets.QHBoxLayout()
        filter_row.addWidget(QtWidgets.QLabel("Filter:"))
        self.log_viewer_filter_input = QtWidgets.QLineEdit()
        self.log_viewer_filter_input.setPlaceholderText("Type to filter waypoints...")
        filter_row.addWidget(self.log_viewer_filter_input)
        right.addLayout(filter_row)

        self.log_viewer_table = QtWidgets.QTableWidget(0, 7)
        self.log_viewer_table.setHorizontalHeaderLabels(
            ["Time", "Depth (m)", "Temp (°C)", "NDL (s)", "TTS (s)", "Gas", "Tanks"]
        )
        self.log_viewer_table.horizontalHeader().setStretchLastSection(True)
        self.log_viewer_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        right.addWidget(self.log_viewer_table, stretch=1)

        self.log_viewer_status_label = QtWidgets.QLabel("")
        right.addWidget(self.log_viewer_status_label)

        root.addLayout(right, stretch=1)

    def _wire_signals(self):
        self.select_dir_button.clicked.connect(self._on_select_dir)
        self.log_viewer_file_list.itemSelectionChanged.connect(self._on_file_select)
        self.log_viewer_dive_select.currentTextChanged.connect(self._on_dive_change)
        self.log_viewer_filter_input.textChanged.connect(self._on_filter)

    # ------------------------------------------------------------------
    # Log Viewer - ported from the same-named Toga methods.
    # ------------------------------------------------------------------

    def _on_select_dir(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select dive log directory")
        if not path:
            return
        directory = Path(path)
        self.log_viewer_dir_label.setText(str(directory))

        files = sorted(
            (f for f in directory.iterdir() if f.is_file() and f.suffix.lower() in LOG_VIEWER_EXTENSIONS),
            key=lambda f: f.name.lower(),
        )
        self.log_viewer_files = files
        self.log_viewer_file_list.clear()
        for f in files:
            item = QtWidgets.QListWidgetItem(f.name)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, str(f))
            self.log_viewer_file_list.addItem(item)
        self._log_viewer_clear()
        if files:
            self.log_viewer_file_list.setCurrentRow(0)

    def _on_file_select(self):
        items = self.log_viewer_file_list.selectedItems()
        if not items:
            return
        path = items[0].data(QtCore.Qt.ItemDataRole.UserRole)
        self._display_log_viewer_file(Path(path))

    def _display_log_viewer_file(self, file_path):
        self.log_viewer_file_name_label.setText(file_path.name)
        self.log_viewer_status_label.setText("Loading...")
        try:
            dives = parse_dive_log_file(file_path)
        except Exception as e:
            self._log_viewer_clear()
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to parse {file_path.name}: {e}")
            return

        self.log_viewer_dives = dives
        if not dives:
            self._log_viewer_clear()
            self.log_viewer_status_label.setText("No dives found in this file.")
            return

        labels = [
            f"Dive {i + 1}: {dive.start_time:%Y-%m-%d %H:%M} ({len(dive.waypoints)} pts)"
            for i, dive in enumerate(dives)
        ]
        self.log_viewer_dive_map = dict(zip(labels, dives))
        self.log_viewer_dive_select.blockSignals(True)
        self.log_viewer_dive_select.clear()
        self.log_viewer_dive_select.addItems(labels)
        self.log_viewer_dive_select.setCurrentIndex(0)
        self.log_viewer_dive_select.blockSignals(False)
        self._log_viewer_show_dive(dives[0])

    def _on_dive_change(self, label):
        dive = self.log_viewer_dive_map.get(label)
        if dive is not None:
            self._log_viewer_show_dive(dive)

    def _log_viewer_sensor_label(self, key, reverse_map):
        serial = reverse_map.get(key)
        return f"{key} ({serial})" if serial and serial != key else key

    def _format_tank_reading(self, key, tank, reverse_map):
        text = f"{self._log_viewer_sensor_label(key, reverse_map)}: {tank.pressure_bar:.0f} bar"
        if tank.he_percent:
            text += f" ({tank.o2_percent:.0f}/{tank.he_percent:.0f})"
        elif abs(tank.o2_percent - 21.0) > 0.5:
            text += f" (Nx{tank.o2_percent:.0f})"
        return text

    def _log_viewer_show_dive(self, dive):
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
        self.log_viewer_summary_label.setPlainText("\n".join(lines))

        reverse_map = {name: serial for serial, name in get_config().get_tank_mapping().items()}
        sensors = sorted({key for wp in dive.waypoints for key in wp.tanks.keys()})
        sensor_labels = [self._log_viewer_sensor_label(key, reverse_map) for key in sensors]
        self.log_viewer_sensors_label.setPlainText(
            ", ".join(sensor_labels) if sensor_labels else "No tank sensor data in this dive."
        )

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
                    "gas": wp.gasmix,
                    "tanks": tanks_text,
                }
            )
        self.log_viewer_all_rows = rows
        self._populate_table(rows)
        self.log_viewer_filter_input.blockSignals(True)
        self.log_viewer_filter_input.clear()
        self.log_viewer_filter_input.blockSignals(False)
        self.log_viewer_status_label.setText(f"{len(rows)} waypoints")

    def _populate_table(self, rows):
        columns = ["time", "depth", "temp", "ndl", "tts", "gas", "tanks"]
        self.log_viewer_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, key in enumerate(columns):
                self.log_viewer_table.setItem(i, j, QtWidgets.QTableWidgetItem(row[key]))

    def _on_filter(self, text):
        text = (text or "").lower()
        if not text:
            self._populate_table(self.log_viewer_all_rows)
            return
        self._populate_table(
            [row for row in self.log_viewer_all_rows if any(text in str(v).lower() for v in row.values())]
        )

    def _log_viewer_clear(self):
        self.log_viewer_dives = []
        self.log_viewer_dive_map = {}
        self.log_viewer_dive_select.blockSignals(True)
        self.log_viewer_dive_select.clear()
        self.log_viewer_dive_select.blockSignals(False)
        self.log_viewer_file_name_label.setText("None")
        self.log_viewer_summary_label.setPlainText("")
        self.log_viewer_sensors_label.setPlainText("")
        self.log_viewer_all_rows = []
        self._populate_table([])
        self.log_viewer_status_label.setText("")
