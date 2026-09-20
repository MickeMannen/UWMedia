"""Advanced page - PySide6 port of uwmedia/app.py's Advanced-related
fields/_build_advanced_section and friends, see pyside6_rework.md Phase 9.

Reused verbatim: user_layouts_dir/user_templates_dir (utils.layouts),
user_color_yaml_path (utils.color_profiles), get_config/
user_config_yaml_path (utils.config), get_ffmpeg_path/get_exiftool_path/
is_valid_ffmpeg/is_valid_exiftool (utils.tool_paths), update_settings/
add_unique/set_field/get_fields (utils.app_settings), GarminParser - all
zero-Toga-dependency engine code, nine phases in and still holding.

Built entirely in Python, no .ui file - the "Edit Tank Sensor Names…"
window's rows are rebuilt dynamically from whatever's in config.yaml (an
unbounded, runtime-determined list of serial->name rows, plus a
scan-a-folder action that can add more), the same "data-driven, no static
layout to gain from Designer XML" reasoning Phases 4/5/7/8 already used.

hw_accel_switch/debug_switch/summary_switch ARE persisted (checked
directly against PERSISTED_SWITCH_FIELDS in uwmedia/app.py - unlike every
page ported in Phases 3-8, which all checked negative) - wired through
utils.app_settings under the exact same keys the Toga app already uses.
The folder/tool-path overrides (layouts_dir/templates_dir/
color_profiles_dir/ffmpeg_path/exiftool_path) are NOT part of that
per-field persistence list - they're their own top-level settings.json
keys via update_settings(), read back by user_layouts_dir()/
get_ffmpeg_path()/etc. directly (see utils/tool_paths.py's own docstring)
- ported as such, not persisted a second way.

Known, deliberate limitation of this first pass: in the Toga original,
changing the Templates/Color-profiles folder override immediately live-
refreshes the brand/profile dropdowns on every other currently-open
section (HUD Designer, Overlay Generator, Color, Color Tuning), because
they're all methods on one shared `self`. This Qt port's pages are
independent QWidget instances with no reference to their siblings (see
pyside6_rework.md's own "independent state per page" posture) - so a
folder-override change here updates this page's own display and
everything *newly constructed* afterward, but any *already-built* sibling
page's dropdowns won't refresh until the app restarts. Same reasoning
applies to "Custom filename formats" - Add here writes to the same
settings.json list a future un-deferred Color-page "Custom…" option would
read, but neither Color's nor Overlay Generator's Qt port exposes that
choice yet (already flagged deferred in color_page.py's own docstring) -
not a new gap, just this page's own end of an already-known one.
"""
from pathlib import Path

from PySide6 import QtWidgets

from parsers.garmin import GarminParser
from utils.app_settings import add_unique, get_fields, set_field, update_settings
from utils.color_profiles import user_color_yaml_path
from utils.config import get_config, user_config_yaml_path
from utils.layouts import user_layouts_dir, user_templates_dir
from utils.tool_paths import get_exiftool_path, get_ffmpeg_path, is_valid_exiftool, is_valid_ffmpeg


def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w:
            w.deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


class TankSensorNamesWindow(QtWidgets.QWidget):
    """Ported from _show_tank_names_window - a separate top-level window
    that maps Garmin tank sensor serial numbers to friendly names, with a
    dynamically-rebuilt row per serial (add manually, scan a folder of
    .fit logs for more, remove one, save)."""

    def __init__(self, on_saved=None):
        super().__init__()
        self._on_saved = on_saved
        self.row_state = {}
        for serial, name in dict(get_config().get_tank_mapping()).items():
            entry = QtWidgets.QLineEdit(name)
            self.row_state[serial] = entry

        self.setWindowTitle("Tank Sensor Names")
        self.resize(560, 500)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(
            QtWidgets.QLabel('Map Garmin tank sensor serial numbers to friendly names (e.g. "Left", "Micke01").')
        )

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        rows_container = QtWidgets.QWidget()
        self.rows_layout = QtWidgets.QVBoxLayout(rows_container)
        scroll.setWidget(rows_container)
        layout.addWidget(scroll, stretch=1)

        manual_row = QtWidgets.QHBoxLayout()
        manual_row.addWidget(QtWidgets.QLabel("Add serial manually"))
        self.new_serial_input = QtWidgets.QLineEdit()
        self.new_serial_input.setPlaceholderText("Serial number")
        self.new_serial_input.setFixedWidth(140)
        manual_row.addWidget(self.new_serial_input)
        add_button = QtWidgets.QPushButton("Add")
        add_button.clicked.connect(self._on_add_manual)
        manual_row.addWidget(add_button)
        manual_row.addStretch(1)
        layout.addLayout(manual_row)

        self.status_label = QtWidgets.QLabel("")
        self.status_label.setStyleSheet("color: gray;")
        layout.addWidget(self.status_label)

        button_row = QtWidgets.QHBoxLayout()
        scan_button = QtWidgets.QPushButton("Scan Logs Folder…")
        scan_button.clicked.connect(self._on_scan)
        button_row.addWidget(scan_button)
        save_button = QtWidgets.QPushButton("Save")
        save_button.clicked.connect(self._on_save)
        button_row.addWidget(save_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self._rebuild_rows()

    def _rebuild_rows(self):
        _clear_layout(self.rows_layout)
        if not self.row_state:
            placeholder = QtWidgets.QLabel("No tank sensors yet - scan a logs folder or add one manually below.")
            placeholder.setStyleSheet("color: gray;")
            self.rows_layout.addWidget(placeholder)
            return
        for serial in sorted(self.row_state.keys()):
            row = QtWidgets.QHBoxLayout()
            serial_label = QtWidgets.QLabel(serial)
            serial_label.setFixedWidth(140)
            row.addWidget(serial_label)
            row.addWidget(self.row_state[serial], stretch=1)
            remove_button = QtWidgets.QPushButton("Remove")
            remove_button.clicked.connect(lambda checked=False, s=serial: self._on_remove(s))
            row.addWidget(remove_button)
            row_widget = QtWidgets.QWidget()
            row_widget.setLayout(row)
            self.rows_layout.addWidget(row_widget)

    def _on_remove(self, serial):
        del self.row_state[serial]
        self._rebuild_rows()

    def _on_scan(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select folder with Garmin .fit logs")
        if not path:
            return
        folder = Path(path)
        garmin = GarminParser()
        found = set()
        try:
            for file_path in folder.iterdir():
                if file_path.suffix.lower() == ".fit":
                    found.update(garmin.get_unique_tank_serials(file_path))
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to scan folder: {e}")
            return
        new_serials = [s for s in found if s not in self.row_state]
        for serial in new_serials:
            self.row_state[serial] = QtWidgets.QLineEdit(f"Tank {serial}")
        self._rebuild_rows()
        self.status_label.setText(
            f"Found {len(found)} sensor(s) in .fit files, added {len(new_serials)} new."
            if found
            else "No tank sensors found in that folder."
        )

    def _on_add_manual(self):
        serial = self.new_serial_input.text().strip()
        if not serial or serial in self.row_state:
            return
        self.row_state[serial] = QtWidgets.QLineEdit(f"Tank {serial}")
        self.new_serial_input.clear()
        self._rebuild_rows()

    def _on_save(self):
        config = get_config()
        for serial in list(config.get_tank_mapping().keys()):
            if serial not in self.row_state:
                config.remove_tank(serial)
        for serial, entry in self.row_state.items():
            config.set_tank_name(serial, entry.text().strip() or f"Tank {serial}")
        if self._on_saved:
            self._on_saved()
        self.close()
        QtWidgets.QMessageBox.information(
            None, "Saved", f"Sensor names saved to:\n{user_config_yaml_path()}"
        )


class AdvancedPage(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self._tank_names_window = None

        self._build_ui()
        self._wire_signals()
        self._restore_switches()
        self._refresh_location_inputs()
        self._refresh_tool_paths()

    # ------------------------------------------------------------------
    # Layout - ported from _build_advanced_section.
    # ------------------------------------------------------------------

    def _build_ui(self):
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        container = QtWidgets.QWidget()
        root = QtWidgets.QVBoxLayout(container)

        flags_group = QtWidgets.QGroupBox("Flags")
        flags_layout = QtWidgets.QVBoxLayout(flags_group)
        self.hw_accel_switch = QtWidgets.QCheckBox("Hardware acceleration")
        flags_layout.addWidget(self.hw_accel_switch)
        self.debug_switch = QtWidgets.QCheckBox("Debug output")
        flags_layout.addWidget(self.debug_switch)
        self.summary_switch = QtWidgets.QCheckBox("Show summary")
        flags_layout.addWidget(self.summary_switch)
        root.addWidget(flags_group)

        locations_group = QtWidgets.QGroupBox("Locations")
        locations_form = QtWidgets.QFormLayout(locations_group)
        self.layouts_dir_input = QtWidgets.QLineEdit()
        self.layouts_dir_input.setReadOnly(True)
        locations_form.addRow("Layouts folder", self._path_row(self.layouts_dir_input, "layouts"))
        self.templates_dir_input = QtWidgets.QLineEdit()
        self.templates_dir_input.setReadOnly(True)
        locations_form.addRow("Templates folder", self._path_row(self.templates_dir_input, "templates"))
        self.color_dir_input = QtWidgets.QLineEdit()
        self.color_dir_input.setReadOnly(True)
        locations_form.addRow("Color profiles folder", self._path_row(self.color_dir_input, "color"))
        root.addWidget(locations_group)

        sensors_group = QtWidgets.QGroupBox("Sensor names")
        sensors_layout = QtWidgets.QVBoxLayout(sensors_group)
        sensors_form = QtWidgets.QFormLayout()
        self.tank_names_path_input = QtWidgets.QLineEdit()
        self.tank_names_path_input.setReadOnly(True)
        sensors_form.addRow("Config file", self.tank_names_path_input)
        sensors_layout.addLayout(sensors_form)
        self.edit_tank_names_button = QtWidgets.QPushButton("Edit Tank Sensor Names…")
        sensors_layout.addWidget(self.edit_tank_names_button)
        root.addWidget(sensors_group)

        tools_group = QtWidgets.QGroupBox("External tools")
        tools_form = QtWidgets.QFormLayout(tools_group)
        self.ffmpeg_path_input = QtWidgets.QLineEdit()
        self.ffmpeg_path_input.setReadOnly(True)
        tools_form.addRow("ffmpeg path", self._path_row(self.ffmpeg_path_input, "ffmpeg"))
        self.exiftool_path_input = QtWidgets.QLineEdit()
        self.exiftool_path_input.setReadOnly(True)
        tools_form.addRow("exiftool path", self._path_row(self.exiftool_path_input, "exiftool"))
        root.addWidget(tools_group)

        formats_group = QtWidgets.QGroupBox("Custom filename formats")
        formats_form = QtWidgets.QFormLayout(formats_group)
        new_format_row = QtWidgets.QHBoxLayout()
        self.new_filename_format_input = QtWidgets.QLineEdit()
        self.new_filename_format_input.setPlaceholderText('e.g. "%Y-%m-%d_%H-%M-%S"')
        new_format_row.addWidget(self.new_filename_format_input)
        self.add_filename_format_button = QtWidgets.QPushButton("Add")
        new_format_row.addWidget(self.add_filename_format_button)
        formats_form.addRow("New format", new_format_row)
        root.addWidget(formats_group)

        root.addStretch(1)
        scroll.setWidget(container)
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _path_row(self, line_edit, kind):
        row = QtWidgets.QHBoxLayout()
        row.addWidget(line_edit, stretch=1)
        change_button = QtWidgets.QPushButton("Change…")
        change_button.clicked.connect(lambda: self._on_choose_path(kind))
        row.addWidget(change_button)
        reset_button = QtWidgets.QPushButton("Reset")
        reset_button.clicked.connect(lambda: self._on_reset_path(kind))
        row.addWidget(reset_button)
        return row

    def _wire_signals(self):
        self.hw_accel_switch.toggled.connect(self._on_hw_accel_toggle)
        self.debug_switch.toggled.connect(self._on_debug_toggle)
        self.summary_switch.toggled.connect(self._on_summary_toggle)
        self.edit_tank_names_button.clicked.connect(self._on_edit_tank_names)
        self.add_filename_format_button.clicked.connect(self._on_add_filename_format)

    # ------------------------------------------------------------------
    # Flags - persisted, matching PERSISTED_SWITCH_FIELDS keys exactly.
    # ------------------------------------------------------------------

    def _restore_switches(self):
        fields = get_fields()
        self.hw_accel_switch.setChecked(fields.get("hw_accel_switch", True))
        self.debug_switch.setChecked(fields.get("debug_switch", False))
        self.summary_switch.setChecked(fields.get("summary_switch", False))

    def _on_hw_accel_toggle(self, checked):
        set_field("hw_accel_switch", checked)

    def _on_debug_toggle(self, checked):
        set_field("debug_switch", checked)

    def _on_summary_toggle(self, checked):
        set_field("summary_switch", checked)

    # ------------------------------------------------------------------
    # Locations / tool paths - ported from _refresh_location_inputs/
    # on_choose_*_dir/on_reset_*_dir/_refresh_tool_paths/
    # on_choose_*_path/on_reset_*_path.
    # ------------------------------------------------------------------

    def _refresh_location_inputs(self):
        self.layouts_dir_input.setText(str(user_layouts_dir()))
        self.templates_dir_input.setText(str(user_templates_dir()))
        self.color_dir_input.setText(str(user_color_yaml_path().parent))
        self.tank_names_path_input.setText(str(user_config_yaml_path()))

    def _refresh_tool_paths(self):
        ffmpeg_path = get_ffmpeg_path()
        exiftool_path = get_exiftool_path()
        self.ffmpeg_path_input.setText(str(ffmpeg_path) if ffmpeg_path else "Not found")
        self.exiftool_path_input.setText(str(exiftool_path) if exiftool_path else "Not found")

    def _on_choose_path(self, kind):
        if kind == "layouts":
            path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select layouts folder")
            if path:
                update_settings(layouts_dir=path)
                self._refresh_location_inputs()
        elif kind == "templates":
            path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select templates folder")
            if path:
                update_settings(templates_dir=path)
                self._refresh_location_inputs()
        elif kind == "color":
            path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select color profiles folder")
            if path:
                update_settings(color_profiles_dir=path)
                self._refresh_location_inputs()
        elif kind == "ffmpeg":
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select ffmpeg executable")
            if not path:
                return
            if not is_valid_ffmpeg(path):
                QtWidgets.QMessageBox.critical(
                    self,
                    "Not a valid ffmpeg executable",
                    f"Running '{path} -version' didn't succeed, so this doesn't look like "
                    "a working ffmpeg executable. Please choose a different file.",
                )
                return
            update_settings(ffmpeg_path=path)
            self._refresh_tool_paths()
        elif kind == "exiftool":
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select exiftool executable")
            if not path:
                return
            if not is_valid_exiftool(path):
                QtWidgets.QMessageBox.critical(
                    self,
                    "Not a valid exiftool executable",
                    f"Running '{path} -ver' didn't succeed, so this doesn't look like "
                    "a working exiftool executable. Please choose a different file.",
                )
                return
            update_settings(exiftool_path=path)
            self._refresh_tool_paths()

    def _on_reset_path(self, kind):
        if kind == "layouts":
            update_settings(layouts_dir=None)
            self._refresh_location_inputs()
        elif kind == "templates":
            update_settings(templates_dir=None)
            self._refresh_location_inputs()
        elif kind == "color":
            update_settings(color_profiles_dir=None)
            self._refresh_location_inputs()
        elif kind == "ffmpeg":
            update_settings(ffmpeg_path=None)
            self._refresh_tool_paths()
        elif kind == "exiftool":
            update_settings(exiftool_path=None)
            self._refresh_tool_paths()

    # ------------------------------------------------------------------
    # Sensor names / custom filename formats.
    # ------------------------------------------------------------------

    def _on_edit_tank_names(self):
        self._tank_names_window = TankSensorNamesWindow(on_saved=self._refresh_location_inputs)
        self._tank_names_window.show()

    def _on_add_filename_format(self):
        pattern = self.new_filename_format_input.text().strip()
        if not pattern:
            return
        add_unique("filename_formats", pattern)
        self.new_filename_format_input.clear()
