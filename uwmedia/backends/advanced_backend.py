"""Advanced page backend - qml_development.md Phase 9. QObject exposed to
uwmedia/qml/AdvancedPage.qml as the "advancedBackend" context
property.

Ported close to verbatim from uwmedia/pages/advanced_page.py
(the old Widgets page, kept as reference only) - user_layouts_dir/
user_templates_dir (utils.layouts), user_color_yaml_path
(utils.color_profiles), get_config/user_config_yaml_path (utils.config),
get_ffmpeg_path/get_exiftool_path/is_valid_ffmpeg/is_valid_exiftool
(utils.tool_paths), update_settings/add_unique/set_field/get_fields
(utils.app_settings), GarminParser - all reused unchanged.

debug_switch/summary_switch ARE persisted (checked directly against
PERSISTED_SWITCH_FIELDS in uwmedia/app.py, unlike every page ported in
earlier phases) - same utils.app_settings keys the Toga app already
uses. The folder/tool-path overrides are their own top-level
settings.json keys via update_settings(), not part of that per-field
list - ported as such, unchanged.

hw_accel_switch's own toggle used to live here too, but moved to a
per-page Switch on Color/Overlay Generator/Convertion instead (the user's
own request - each has its own hwAccel Property/setter on its own
backend, same persisted "hw_accel_switch" key, reused verbatim rather
than kept centralized here, since it's specifically each of those pages'
Start button that needs to read it when building CLI args).

CLAUDE.md flags settings.json/color.yaml (Application Support) as
needing the user's go-ahead before a live test touches them - this page
IS the "change those files" page by design, so unlike every other
phase's own settings.json writes (Color's overlay instances, an ordinary
per-field key), live-testing this page's switches/folder-overrides/tank-
names/filename-formats was deliberately not done without asking first
(see qml_development.md's own Phase 9 write-up for how that was resolved).

Known, deliberate limitation of this first pass, unchanged from the old
Widgets page's own docstring: a folder-override change here doesn't
live-refresh any other already-built page's dropdowns (independent
QObject backends, no shared reference) - only affects this page's own
display and anything constructed after the change.
"""
from pathlib import Path

from PySide6.QtCore import Property, QObject, Signal, Slot

from parsers.garmin import GarminParser
from utils.app_settings import add_unique, get_fields, set_field, update_settings
from utils.color_profiles import user_color_yaml_path
from utils.config import get_config, user_config_yaml_path
from utils.layouts import user_layouts_dir, user_templates_dir
from utils.tool_paths import get_exiftool_path, get_ffmpeg_path, is_valid_exiftool, is_valid_ffmpeg


class AdvancedBackend(QObject):
    switchesChanged = Signal()
    locationsChanged = Signal()
    toolsChanged = Signal()
    statusChanged = Signal()
    filenameFormatFieldChanged = Signal()
    tankNamesChanged = Signal()

    def __init__(self):
        super().__init__()

        fields = get_fields()
        self._debug = fields.get("debug_switch", False)
        self._summary = fields.get("summary_switch", False)

        self._new_filename_format_text = ""
        self._status_text = ""

        self._tank_row_state = dict(get_config().get_tank_mapping())
        self._new_serial_text = ""
        self._tank_status_text = ""
        self._tank_window_visible = False

    # ------------------------------------------------------------------
    # Flags - persisted, matching PERSISTED_SWITCH_FIELDS keys exactly.
    # ------------------------------------------------------------------

    @Property(bool, notify=switchesChanged)
    def debug(self):
        return self._debug

    @debug.setter
    def debug(self, value):
        self._debug = value
        set_field("debug_switch", value)
        self.switchesChanged.emit()

    @Property(bool, notify=switchesChanged)
    def summary(self):
        return self._summary

    @summary.setter
    def summary(self, value):
        self._summary = value
        set_field("summary_switch", value)
        self.switchesChanged.emit()

    # ------------------------------------------------------------------
    # Locations / tool paths - ported close to verbatim from
    # _refresh_location_inputs/on_choose_*_dir/on_reset_*_dir/
    # _refresh_tool_paths/on_choose_*_path/on_reset_*_path.
    # ------------------------------------------------------------------

    @Property(str, notify=locationsChanged)
    def layoutsDirText(self):
        return str(user_layouts_dir())

    @Property(str, notify=locationsChanged)
    def templatesDirText(self):
        return str(user_templates_dir())

    @Property(str, notify=locationsChanged)
    def colorDirText(self):
        return str(user_color_yaml_path().parent)

    @Property(str, notify=locationsChanged)
    def tankNamesPathText(self):
        return str(user_config_yaml_path())

    @Property(str, notify=toolsChanged)
    def ffmpegPathText(self):
        path = get_ffmpeg_path()
        return str(path) if path else "Not found"

    @Property(str, notify=toolsChanged)
    def exiftoolPathText(self):
        path = get_exiftool_path()
        return str(path) if path else "Not found"

    @Slot(str)
    def choosePath(self, kind):
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        if kind in ("layouts", "templates", "color"):
            title = {
                "layouts": "Select layouts folder",
                "templates": "Select templates folder",
                "color": "Select color profiles folder",
            }[kind]
            path = QFileDialog.getExistingDirectory(None, title)
            if not path:
                return
            update_settings(**{f"{kind if kind != 'color' else 'color_profiles'}_dir": path})
            self.locationsChanged.emit()
        elif kind == "ffmpeg":
            path, _ = QFileDialog.getOpenFileName(None, "Select ffmpeg executable")
            if not path:
                return
            if not is_valid_ffmpeg(path):
                QMessageBox.critical(
                    None, "Not a valid ffmpeg executable",
                    f"Running '{path} -version' didn't succeed, so this doesn't look like "
                    "a working ffmpeg executable. Please choose a different file.",
                )
                return
            update_settings(ffmpeg_path=path)
            self.toolsChanged.emit()
        elif kind == "exiftool":
            path, _ = QFileDialog.getOpenFileName(None, "Select exiftool executable")
            if not path:
                return
            if not is_valid_exiftool(path):
                QMessageBox.critical(
                    None, "Not a valid exiftool executable",
                    f"Running '{path} -ver' didn't succeed, so this doesn't look like "
                    "a working exiftool executable. Please choose a different file.",
                )
                return
            update_settings(exiftool_path=path)
            self.toolsChanged.emit()

    @Slot(str)
    def resetPath(self, kind):
        if kind == "layouts":
            update_settings(layouts_dir=None)
            self.locationsChanged.emit()
        elif kind == "templates":
            update_settings(templates_dir=None)
            self.locationsChanged.emit()
        elif kind == "color":
            update_settings(color_profiles_dir=None)
            self.locationsChanged.emit()
        elif kind == "ffmpeg":
            update_settings(ffmpeg_path=None)
            self.toolsChanged.emit()
        elif kind == "exiftool":
            update_settings(exiftool_path=None)
            self.toolsChanged.emit()

    # ------------------------------------------------------------------
    # Custom filename formats - ported close to verbatim from
    # on_add_filename_format.
    # ------------------------------------------------------------------

    @Property(str, notify=filenameFormatFieldChanged)
    def newFilenameFormatText(self):
        return self._new_filename_format_text

    @newFilenameFormatText.setter
    def newFilenameFormatText(self, value):
        self._new_filename_format_text = value
        self.filenameFormatFieldChanged.emit()

    @Slot()
    def addFilenameFormat(self):
        pattern = self._new_filename_format_text.strip()
        if not pattern:
            return
        add_unique("filename_formats", pattern)
        self._new_filename_format_text = ""
        self.filenameFormatFieldChanged.emit()

    # ------------------------------------------------------------------
    # Tank Sensor Names window - ported close to verbatim from
    # TankSensorNamesWindow (_rebuild_rows/_on_remove/_on_scan/
    # _on_add_manual/_on_save), as backend state a QML Window binds to.
    # ------------------------------------------------------------------

    @Slot()
    def openTankNamesWindow(self):
        self._tank_row_state = dict(get_config().get_tank_mapping())
        self._tank_status_text = ""
        self._tank_window_visible = True
        self.tankNamesChanged.emit()

    @Slot()
    def closeTankNamesWindow(self):
        self._tank_window_visible = False
        self.tankNamesChanged.emit()

    @Property(bool, notify=tankNamesChanged)
    def tankWindowVisible(self):
        return self._tank_window_visible

    @Property("QVariant", notify=tankNamesChanged)
    def tankRows(self):
        return [{"serial": s, "name": self._tank_row_state[s]} for s in sorted(self._tank_row_state.keys())]

    @Property(str, notify=tankNamesChanged)
    def tankStatusText(self):
        return self._tank_status_text

    @Property(str, notify=tankNamesChanged)
    def newSerialText(self):
        return self._new_serial_text

    @newSerialText.setter
    def newSerialText(self, value):
        self._new_serial_text = value
        self.tankNamesChanged.emit()

    @Slot(str, str)
    def setTankName(self, serial, name):
        if serial in self._tank_row_state:
            self._tank_row_state[serial] = name

    @Slot(str)
    def removeTankRow(self, serial):
        self._tank_row_state.pop(serial, None)
        self.tankNamesChanged.emit()

    @Slot()
    def addManualSerial(self):
        serial = self._new_serial_text.strip()
        if not serial or serial in self._tank_row_state:
            return
        self._tank_row_state[serial] = f"Tank {serial}"
        self._new_serial_text = ""
        self.tankNamesChanged.emit()

    @Slot()
    def scanLogsFolder(self):
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        path = QFileDialog.getExistingDirectory(None, "Select folder with Garmin .fit logs")
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
            QMessageBox.critical(None, "Error", f"Failed to scan folder: {e}")
            return
        new_serials = [s for s in found if s not in self._tank_row_state]
        for serial in new_serials:
            self._tank_row_state[serial] = f"Tank {serial}"
        self._tank_status_text = (
            f"Found {len(found)} sensor(s) in .fit files, added {len(new_serials)} new."
            if found else "No tank sensors found in that folder."
        )
        self.tankNamesChanged.emit()

    @Slot()
    def saveTankNames(self):
        from PySide6.QtWidgets import QMessageBox

        config = get_config()
        for serial in list(config.get_tank_mapping().keys()):
            if serial not in self._tank_row_state:
                config.remove_tank(serial)
        for serial, name in self._tank_row_state.items():
            config.set_tank_name(serial, name.strip() or f"Tank {serial}")
        self._tank_window_visible = False
        self.tankNamesChanged.emit()
        self.locationsChanged.emit()
        QMessageBox.information(None, "Saved", f"Sensor names saved to:\n{user_config_yaml_path()}")
