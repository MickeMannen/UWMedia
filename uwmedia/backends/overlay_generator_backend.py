"""Overlay Generator page backend - qml_development.md Phase 2. QObject
exposed to uwmedia/qml/OverlayGeneratorPage.qml as the
"overlayGeneratorBackend" context property.

Ported close to verbatim from uwmedia/pages/overlay_generator_page.py
(the old Widgets page, kept as reference only, unused by this shell - see
qml_development.md's Phase 0 write-up) - same posture as Color's own backend:
business logic unchanged, only the widget-facing edges change (Property/
Signal/Slot instead of direct widget access, QML ListView instead of
QListWidget, a real QProcess-driven N-sequential-invocations state
machine unchanged from the original).

Settings persist through the SAME utils.app_settings keys the Toga app
and the old Widgets page already use (hudpage_source_input/
hudpage_output_input/hudpage_logs_input/hudpage_filename_format_select/
no_overwrite_switch) - hudpage_selected_overlays is deliberately NOT
persisted, matching the Toga app's own documented choice (unchanged
here).

Deliberately deferred, matching every other first-pass page's own
convention: the custom-filename-pattern escape hatch (Output-filename
dropdown offers only the 2 real RENDER_LOG_FORMAT_PRESETS). The custom
LAYOUT PATH escape hatch (brand cascade's "Custom..." entry) is NOT
deferred - it's part of this page's main cascade and is ported in full.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import Property, QObject, QProcess, Signal, Slot

from utils.app_settings import get_fields, set_field
from utils.display_paths import contract_home_path
from utils.layouts import list_templates, page_display_name, resolve_template_state

LAYOUT_CUSTOM = "Custom…"
RENDER_LOG_FORMAT_PRESETS = [
    ("source_filename_hudname", "{filename}_{hud}"),
    ("source_datetaken_hudname", "{datetaken:%Y%m%d_%H%M%S}_{hud}"),
]


def _prettify(key: str) -> str:
    return key.replace("_", " ").title()


class OverlayGeneratorBackend(QObject):
    fieldsChanged = Signal()
    cascadeChanged = Signal()
    overlaysChanged = Signal()
    runStateChanged = Signal()

    def __init__(self):
        super().__init__()

        self.hud_templates = list_templates()
        self.selected_overlays = []  # not persisted - matches the Toga app

        self._brand_choices = {_prettify(k): k for k in sorted(self.hud_templates)}
        self._computer_choices = {}
        self._page_choices = {}
        self._selected_brand_key = None
        self._selected_computer_key = None
        self._selected_page_id = None
        self._is_custom = False

        self._source_text = ""
        self._output_text = ""
        self._logs_text = ""
        self._custom_path_text = ""
        self._skip_existing = False
        self._hw_accel = True
        self._filename_format_by_label = dict(RENDER_LOG_FORMAT_PRESETS)
        self._filename_format = "source_datetaken_hudname"

        self.process = None
        self.abort_requested = False
        self._run_queue = []
        self._run_total = 0
        self._run_index = 0
        self._status_text = "No batch running"
        self._overlay_progress_text = ""

        self._restore_fields()
        if self._brand_choices:
            self._select_brand(next(iter(self._brand_choices.keys())))

    # ------------------------------------------------------------------
    # Persistence - see this module's own docstring.
    # ------------------------------------------------------------------

    def _restore_fields(self):
        fields = get_fields()
        self._source_text = fields.get("hudpage_source_input", "") or ""
        self._output_text = fields.get("hudpage_output_input", "") or ""
        self._logs_text = fields.get("hudpage_logs_input", "") or ""
        self._skip_existing = fields.get("no_overwrite_switch", False)
        self._hw_accel = fields.get("hw_accel_switch", True)
        fmt_label = fields.get("hudpage_filename_format_select")
        if fmt_label and fmt_label in self._filename_format_by_label:
            self._filename_format = fmt_label

    @Property(str, notify=fieldsChanged)
    def sourceText(self):
        return self._source_text

    @sourceText.setter
    def sourceText(self, value):
        if value == self._source_text:
            return
        self._source_text = value
        set_field("hudpage_source_input", value)
        self.fieldsChanged.emit()

    @Property(str, notify=fieldsChanged)
    def outputText(self):
        return self._output_text

    @outputText.setter
    def outputText(self, value):
        if value == self._output_text:
            return
        self._output_text = value
        set_field("hudpage_output_input", value)
        self.fieldsChanged.emit()

    @Property(str, notify=fieldsChanged)
    def logsText(self):
        return self._logs_text

    @logsText.setter
    def logsText(self, value):
        if value == self._logs_text:
            return
        self._logs_text = value
        set_field("hudpage_logs_input", value)
        self.fieldsChanged.emit()

    @Property(str, notify=fieldsChanged)
    def customPathText(self):
        return self._custom_path_text

    @customPathText.setter
    def customPathText(self, value):
        if value == self._custom_path_text:
            return
        self._custom_path_text = value
        self.fieldsChanged.emit()

    @Property(bool, notify=fieldsChanged)
    def skipExisting(self):
        return self._skip_existing

    @skipExisting.setter
    def skipExisting(self, value):
        if value == self._skip_existing:
            return
        self._skip_existing = value
        set_field("no_overwrite_switch", value)
        self.fieldsChanged.emit()

    @Property(bool, notify=fieldsChanged)
    def hwAccel(self):
        # Same persisted "hw_accel_switch" key as ColorBackend's own
        # hwAccel/ConvertionBackend's own hwAccel - each page reads/writes
        # it independently now rather than one shared AdvancedBackend
        # property (moved per the user's request, since it's specifically
        # each page's own Start button that needs it when building that
        # run's CLI args).
        return self._hw_accel

    @hwAccel.setter
    def hwAccel(self, value):
        if value == self._hw_accel:
            return
        self._hw_accel = value
        set_field("hw_accel_switch", value)
        self.fieldsChanged.emit()

    @Property(list, constant=True)
    def filenameFormatList(self):
        return list(self._filename_format_by_label.keys())

    @Property(str, notify=fieldsChanged)
    def filenameFormat(self):
        return self._filename_format

    @filenameFormat.setter
    def filenameFormat(self, value):
        if value == self._filename_format:
            return
        self._filename_format = value
        set_field("hudpage_filename_format_select", value)
        self.fieldsChanged.emit()

    # ------------------------------------------------------------------
    # File/folder browse - real native dialogs.
    # ------------------------------------------------------------------

    @Slot()
    def browseSourceFile(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(None, "Select file")
        if path:
            self.sourceText = path

    @Slot()
    def browseSourceFolder(self):
        from PySide6.QtWidgets import QFileDialog
        path = QFileDialog.getExistingDirectory(None, "Select folder")
        if path:
            self.sourceText = path

    @Slot()
    def browseOutputFile(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(None, "Select file")
        if path:
            self.outputText = path

    @Slot()
    def browseOutputFolder(self):
        from PySide6.QtWidgets import QFileDialog
        path = QFileDialog.getExistingDirectory(None, "Select folder")
        if path:
            self.outputText = path

    @Slot()
    def browseLogsFolder(self):
        from PySide6.QtWidgets import QFileDialog
        path = QFileDialog.getExistingDirectory(None, "Select folder")
        if path:
            self.logsText = path

    @Slot()
    def browseCustomPathFile(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(None, "Select file")
        if path:
            self.customPathText = path

    @Slot()
    def browseCustomPathFolder(self):
        from PySide6.QtWidgets import QFileDialog
        path = QFileDialog.getExistingDirectory(None, "Select folder")
        if path:
            self.customPathText = path

    @Slot(str, result=str)
    def contractPath(self, path):
        """Display-only /Users/<name>/... -> ~/... - see
        utils/display_paths.py and ColorBackend's own contractPath."""
        return contract_home_path(path)

    # ------------------------------------------------------------------
    # Brand -> computer -> page cascade - ported close to verbatim from
    # _refresh_hudpage_selector_rows/on_hudpage_brand_change/
    # _refresh_hudpage_computer_choices/on_hudpage_computer_change/
    # _refresh_hudpage_page_choices.
    # ------------------------------------------------------------------

    @Property(list, notify=cascadeChanged)
    def brandList(self):
        return list(self._brand_choices.keys()) + [LAYOUT_CUSTOM]

    @Slot()
    def reloadTemplates(self):
        """Re-read the template tree - wired (app.py) to the Overlay
        Designer's templatesChanged. Keeps the current brand/computer/page
        when they still exist, else falls back to the first brand."""
        self.hud_templates = list_templates()
        self._brand_choices = {_prettify(k): k for k in sorted(self.hud_templates)}
        if self._is_custom:
            self.cascadeChanged.emit()
            return
        brand, computer, page = self._selected_brand_key, self._selected_computer_key, self._selected_page_id
        if brand in self.hud_templates:
            self._refresh_computer_choices()
            if computer in self.hud_templates.get(brand, {}):
                self._selected_computer_key = computer
                self._refresh_page_choices()
                if page in self._page_choices.values():
                    self._selected_page_id = page
        elif self._brand_choices:
            self._select_brand(next(iter(self._brand_choices.keys())))
        self.cascadeChanged.emit()

    @Property(bool, notify=cascadeChanged)
    def isCustom(self):
        return self._is_custom

    @Property(list, notify=cascadeChanged)
    def computerList(self):
        return list(self._computer_choices.keys())

    @Property(bool, notify=cascadeChanged)
    def computerVisible(self):
        brand = self._selected_brand_key
        computers = self.hud_templates.get(brand, {}) if brand else {}
        return (not self._is_custom) and len(computers) > 1

    @Property(list, notify=cascadeChanged)
    def pageList(self):
        return list(self._page_choices.keys())

    def _select_brand(self, brand_display_name):
        self._is_custom = brand_display_name == LAYOUT_CUSTOM
        self._selected_brand_key = self._brand_choices.get(brand_display_name)
        if not self._is_custom:
            self._refresh_computer_choices()
        self.cascadeChanged.emit()

    @Slot(str)
    def onBrandSelected(self, brand_display_name):
        self._select_brand(brand_display_name)

    def _refresh_computer_choices(self):
        brand = self._selected_brand_key
        computers = self.hud_templates.get(brand, {}) if brand else {}
        self._computer_choices = {_prettify(k): k for k in sorted(computers)}
        self._selected_computer_key = next(iter(self._computer_choices.values()), None)
        self._refresh_page_choices()

    @Slot(str)
    def onComputerSelected(self, computer_display_name):
        self._selected_computer_key = self._computer_choices.get(computer_display_name)
        self._refresh_page_choices()
        self.cascadeChanged.emit()

    def _refresh_page_choices(self):
        brand, computer = self._selected_brand_key, self._selected_computer_key
        manifest = self.hud_templates.get(brand, {}).get(computer) if brand and computer else None
        pages = manifest["pages"] if manifest else []
        self._page_choices = {page_display_name(page): page["id"] for page in pages}
        self._selected_page_id = next(iter(self._page_choices.values()), None)

    @Slot(str)
    def onPageSelected(self, page_display_name):
        self._selected_page_id = self._page_choices.get(page_display_name)

    # ------------------------------------------------------------------
    # Overlay list - ported close to verbatim from
    # _compose_hud_layout_path/on_add_overlay/on_remove_overlay/
    # _refresh_hudpage_overlay_table.
    # ------------------------------------------------------------------

    def _compose_hud_layout_path(self, brand, computer, page):
        manifest = self.hud_templates.get(brand, {}).get(computer)
        page_entry = next((p for p in (manifest or {}).get("pages", []) if p["id"] == page), None)
        if page_entry is None:
            return None
        variant = page_entry["variants"][0] if page_entry.get("variants") else None
        state_path = resolve_template_state(brand, computer, page, variant=variant)
        if state_path is None:
            return None

        with open(state_path) as f:
            layout = json.load(f)
        hud_skin = layout.setdefault("hud_skin", {})
        skin_path = hud_skin.get("path")
        if skin_path and not Path(skin_path).is_absolute():
            hud_skin["path"] = str((state_path.parent / skin_path).resolve())
        hud_skin["anchor"] = "CENTER"
        hud_skin["ref_offset_x"] = 0.0
        hud_skin["ref_offset_y"] = 0.0

        name_parts = [brand]
        if len(self.hud_templates.get(brand, {})) > 1:
            name_parts.append(computer)
        name_parts.append(page)
        out_dir = Path(tempfile.mkdtemp(prefix="uwmedia_qt_hud_"))
        out_path = out_dir / f"{'_'.join(name_parts)}.json"
        with open(out_path, "w") as f:
            json.dump(layout, f, indent=2)
        return out_path

    @Property(list, notify=overlaysChanged)
    def overlayLabels(self):
        return [o["label"] for o in self.selected_overlays]

    @Slot()
    def addOverlay(self):
        if self._is_custom:
            path_str = self._custom_path_text.strip()
            if not path_str:
                return
            layout_path = Path(path_str)
            label = layout_path.stem
        else:
            brand, computer, page = self._selected_brand_key, self._selected_computer_key, self._selected_page_id
            if not (brand and computer and page):
                return
            layout_path = self._compose_hud_layout_path(brand, computer, page)
            if layout_path is None:
                return
            label = layout_path.stem.replace("_", " ")
        self.selected_overlays.append({"label": label, "layout_path": layout_path})
        self.overlaysChanged.emit()

    @Slot(int)
    def removeOverlayAtIndex(self, row):
        if row < 0 or row >= len(self.selected_overlays):
            return
        del self.selected_overlays[row]
        self.overlaysChanged.emit()

    # ------------------------------------------------------------------
    # Start/Progress - ported close to verbatim from build_hud_args/
    # on_run_hud. N sequential CLI invocations (one per selected overlay).
    # ------------------------------------------------------------------

    def _build_hud_args(self, layout_path):
        args = []
        source = self._source_text.strip()
        output = self._output_text.strip()
        if source:
            args.append(source)
        if output:
            args.append(output)
        if self._logs_text.strip():
            args += ["--logs", self._logs_text.strip()]
        args += ["--layout", str(layout_path)]
        args.append("--render-video-log")
        if self._skip_existing:
            args.append("--no-overwrite")
        pattern = self._filename_format_by_label.get(self._filename_format)
        if pattern:
            args += ["--render-log-filename-format", pattern]
        if self._hw_accel:
            args.append("--hw-accel")
        return args

    def _build_command(self, args):
        exe = Path(sys.executable)
        if "python" in exe.name.lower():
            return [sys.executable, "-m", "uwmedia", *args]
        return [sys.executable, *args]

    @Property(str, notify=runStateChanged)
    def statusText(self):
        return self._status_text

    @Property(str, notify=runStateChanged)
    def overlayProgressText(self):
        return self._overlay_progress_text

    @Property(bool, notify=runStateChanged)
    def isRunning(self):
        return self.process is not None

    def _set_status(self, text):
        self._status_text = text
        self.runStateChanged.emit()

    @Slot()
    def onStartClicked(self):
        if self.process is not None:
            self.abort_requested = True
            self._set_status("Aborting…")
            self._kill_process_tree()
            return

        overlays = self.selected_overlays
        source = self._source_text.strip()
        logs = self._logs_text.strip()
        if not overlays or not source or not logs:
            self._set_status(
                "Nothing to run: select a source folder, a dive logs folder, and at least one overlay first."
            )
            return

        self.abort_requested = False
        self._run_queue = list(overlays)
        self._run_total = len(overlays)
        self._run_index = 0
        self.runStateChanged.emit()
        self._run_next_overlay()

    def _run_next_overlay(self):
        if self.abort_requested or not self._run_queue:
            self._finish_batch()
            return
        overlay = self._run_queue.pop(0)
        self._run_index += 1
        self._overlay_progress_text = f"Overlay {self._run_index} of {self._run_total}: {overlay['label']}"
        self._status_text = "Starting…"
        self.runStateChanged.emit()
        args = self._build_hud_args(overlay["layout_path"])
        cmd = self._build_command(args)

        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._on_process_output)
        self.process.finished.connect(self._on_overlay_finished)
        self.process.start(cmd[0], cmd[1:])

    def _on_process_output(self):
        if self.process is None:
            return
        text = bytes(self.process.readAllStandardOutput()).decode(errors="replace").strip()
        if text:
            self._set_status(text.splitlines()[-1])

    def _on_overlay_finished(self, _exit_code, _exit_status):
        self.process = None
        self._run_next_overlay()

    def _finish_batch(self):
        self._status_text = "Aborted" if self.abort_requested else "Done"
        self._overlay_progress_text = ""
        self.process = None
        self.runStateChanged.emit()

    def _kill_process_tree(self):
        if self.process is None:
            return
        pid = self.process.processId()
        if pid:
            try:
                subprocess.run(["pkill", "-9", "-P", str(pid)], capture_output=True)
            except Exception:
                pass
        self.process.kill()
