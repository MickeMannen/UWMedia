"""Overlay Generator page - PySide6 port of uwmedia/app.py's
_build_hud_page_fields/_build_hud_page_section and friends (was "HUD",
renamed alongside its own Toga layout rework - see ui_rework.md and
pyside6_rework.md Phase 2).

Same porting posture as Color (Phase 1): business logic (brand/computer/
page cascade resolution, CLI arg building, the N-sequential-invocations
batch loop) ported close to verbatim; only the widget-facing edges change.
Settings persist through the SAME utils.app_settings keys the Toga app's
own PERSISTED_TEXT_FIELDS/PERSISTED_SELECTION_FIELDS/PERSISTED_SWITCH_
FIELDS already use for this page's fields (hudpage_source_input/
hudpage_output_input/hudpage_logs_input/hudpage_filename_format_input/
hudpage_filename_format_select/no_overwrite_switch) - same reasoning as
Color's own docstring: this page reads/writes the exact same settings.json
the Toga app does. hudpage_selected_overlays is deliberately NOT
persisted, matching the Toga app's own documented choice.

Deliberately deferred, matching Color's own Phase 1 scope call: the
custom-filename-pattern escape hatch (this page's Output-filename dropdown
offers only the 2 real RENDER_LOG_FORMAT_PRESETS, no "Custom…" entry).

Process-tree kill on Abort reuses the exact same pkill-based fix Phase 1
found live-testing Color's own Start/Abort (see that phase's writeup in
pyside6_rework.md) - applied here from the start rather than deferred and
rediscovered.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from utils.app_settings import get_fields, set_field
from utils.layouts import list_templates, resolve_template_state

from uwmedia.pages.overlay_generator_page_ui import Ui_OverlayGeneratorPage

LAYOUT_CUSTOM = "Custom…"
HUD_LOCATION_MARGIN = 24.0
RENDER_LOG_FORMAT_PRESETS = [
    ("source_filename_hudname", "{filename}_{hud}"),
    ("source_datetaken_hudname", "{datetaken:%Y%m%d_%H%M%S}_{hud}"),
]


def _prettify(key: str) -> str:
    return key.replace("_", " ").title()


class OverlayGeneratorPage(QtWidgets.QWidget, Ui_OverlayGeneratorPage):
    def __init__(self):
        super().__init__()
        self.setupUi(self)

        self.hud_templates = list_templates()
        self.selected_overlays = []  # not persisted across restarts - matches the Toga app
        self._brand_choices = {}
        self._computer_choices = {}
        self._page_choices = {}

        self._filename_format_by_label = dict(RENDER_LOG_FORMAT_PRESETS)
        self.filename_format_combo.addItems(list(self._filename_format_by_label.keys()))

        self.process = None
        self.abort_requested = False
        self._run_queue = []
        self._run_total = 0
        self._run_index = 0

        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)

        self._restore_fields()
        self._wire_signals()

        self._brand_choices = {_prettify(key): key for key in sorted(self.hud_templates)}
        self.brand_combo.addItems(list(self._brand_choices.keys()) + [LAYOUT_CUSTOM])
        self._refresh_row_visibility()
        if self.brand_combo.currentText() != LAYOUT_CUSTOM:
            self._refresh_computer_choices()

    # ------------------------------------------------------------------
    # Persistence - see this module's own docstring.
    # ------------------------------------------------------------------

    def _restore_fields(self):
        fields = get_fields()
        self.source_input.setText(fields.get("hudpage_source_input", ""))
        self.output_input.setText(fields.get("hudpage_output_input", ""))
        self.logs_input.setText(fields.get("hudpage_logs_input", ""))
        self.skip_existing_checkbox.setChecked(fields.get("no_overwrite_switch", False))
        fmt_label = fields.get("hudpage_filename_format_select")
        if fmt_label and fmt_label in self._filename_format_by_label:
            self.filename_format_combo.setCurrentText(fmt_label)
        else:
            self.filename_format_combo.setCurrentText("source_datetaken_hudname")

    def _wire_signals(self):
        self.source_input.textChanged.connect(lambda text: set_field("hudpage_source_input", text))
        self.output_input.textChanged.connect(lambda text: set_field("hudpage_output_input", text))
        self.logs_input.textChanged.connect(lambda text: set_field("hudpage_logs_input", text))
        self.skip_existing_checkbox.toggled.connect(lambda checked: set_field("no_overwrite_switch", checked))
        self.filename_format_combo.currentTextChanged.connect(
            lambda text: set_field("hudpage_filename_format_select", text)
        )

        self.source_file_button.clicked.connect(lambda: self._browse_file(self.source_input))
        self.source_folder_button.clicked.connect(lambda: self._browse_folder(self.source_input))
        self.output_file_button.clicked.connect(lambda: self._browse_file(self.output_input))
        self.output_folder_button.clicked.connect(lambda: self._browse_folder(self.output_input))
        self.logs_browse_button.clicked.connect(lambda: self._browse_folder(self.logs_input))
        self.custom_path_file_button.clicked.connect(lambda: self._browse_file(self.custom_path_input))
        self.custom_path_folder_button.clicked.connect(lambda: self._browse_folder(self.custom_path_input))

        self.brand_combo.currentTextChanged.connect(self._on_brand_change)
        self.computer_combo.currentTextChanged.connect(self._on_computer_change)
        self.add_button.clicked.connect(self._on_add)
        self.remove_button.clicked.connect(self._on_remove)
        self.start_button.clicked.connect(self._on_start)

    def _browse_file(self, target_input):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select file")
        if path:
            target_input.setText(path)

    def _browse_folder(self, target_input):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select folder")
        if path:
            target_input.setText(path)

    # ------------------------------------------------------------------
    # Brand -> computer -> page cascade - ported from
    # _refresh_hudpage_selector_rows/on_hudpage_brand_change/
    # _refresh_hudpage_computer_choices/on_hudpage_computer_change/
    # _refresh_hudpage_page_choices. Row show/hide uses QFormLayout's
    # labelForField (same technique Phase 1's AddHudDialog already uses)
    # instead of Toga's own add/remove-from-a-plain-Box approach.
    # ------------------------------------------------------------------

    def _current_brand(self):
        return self._brand_choices.get(self.brand_combo.currentText())

    def _current_computer(self):
        brand = self._current_brand()
        return self._computer_choices.get(self.computer_combo.currentText()) if brand else None

    def _refresh_row_visibility(self):
        is_custom = self.brand_combo.currentText() == LAYOUT_CUSTOM
        for w in (self.custom_path_label, self.custom_path_input,
                  self.custom_path_file_button, self.custom_path_folder_button):
            w.setVisible(is_custom)
        brand = self._current_brand()
        computers = self.hud_templates.get(brand, {}) if brand else {}
        show_computer = (not is_custom) and len(computers) > 1
        self.computer_label.setVisible(show_computer)
        self.computer_combo.setVisible(show_computer)
        self.page_label.setVisible(not is_custom)
        self.page_combo.setVisible(not is_custom)

    def _refresh_computer_choices(self):
        brand = self._current_brand()
        computers = self.hud_templates.get(brand, {}) if brand else {}
        self._computer_choices = {_prettify(key): key for key in sorted(computers)}
        self.computer_combo.blockSignals(True)
        self.computer_combo.clear()
        self.computer_combo.addItems(list(self._computer_choices.keys()))
        self.computer_combo.blockSignals(False)
        self._refresh_page_choices()

    def _refresh_page_choices(self):
        brand = self._current_brand()
        computer = self._current_computer()
        manifest = self.hud_templates.get(brand, {}).get(computer) if brand and computer else None
        pages = manifest["pages"] if manifest else []
        self._page_choices = {page["name"]: page["id"] for page in pages}
        self.page_combo.clear()
        self.page_combo.addItems(list(self._page_choices.keys()))

    def _on_brand_change(self, text):
        self._refresh_row_visibility()
        if text != LAYOUT_CUSTOM:
            self._refresh_computer_choices()

    def _on_computer_change(self, _text):
        self._refresh_page_choices()

    # ------------------------------------------------------------------
    # Overlay list - ported from _compose_hud_layout_path/on_add_overlay/
    # on_remove_overlay/_refresh_hudpage_overlay_table.
    # ------------------------------------------------------------------

    def _compose_hud_layout_path(self, brand, computer, page):
        # anchor="CENTER"/multiplier=1.0 hardcoded - the Toga original
        # always passes "Medium"/"CENTER" here too (render-video-log sizes
        # its own canvas from the skin's natural dimensions regardless;
        # CENTER is the one anchor whose margin math is exactly (0.0, 0.0),
        # see the Toga _compose_hud_layout_path's own comment) - no size/
        # location picker UI ever existed for this page.
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

    def _on_add(self):
        if self.brand_combo.currentText() == LAYOUT_CUSTOM:
            path_str = self.custom_path_input.text().strip()
            if not path_str:
                return
            layout_path = Path(path_str)
            label = layout_path.stem
        else:
            brand = self._current_brand()
            computer = self._current_computer()
            page = self._page_choices.get(self.page_combo.currentText())
            if not (brand and computer and page):
                return
            layout_path = self._compose_hud_layout_path(brand, computer, page)
            if layout_path is None:
                return
            label = layout_path.stem.replace("_", " ")
        self.selected_overlays.append({"label": label, "layout_path": layout_path})
        self._refresh_overlay_list()

    def _refresh_overlay_list(self):
        self.overlay_list.clear()
        for overlay in self.selected_overlays:
            self.overlay_list.addItem(overlay["label"])

    def _on_remove(self):
        row = self.overlay_list.currentRow()
        if row < 0:
            return
        del self.selected_overlays[row]
        self._refresh_overlay_list()

    # ------------------------------------------------------------------
    # Start/Progress - ported from build_hud_args/on_run_hud. N sequential
    # CLI invocations (one per selected overlay, not combined into one
    # render) via a small QProcess-driven queue, since QProcess is
    # event-driven rather than awaitable the way asyncio's subprocess is -
    # _run_next_overlay/_on_overlay_finished is the state machine standing
    # in for on_run_hud's own `for overlay in overlays: await ...` loop.
    # Continues to the next overlay even if one fails (matches the Toga
    # app's own batch semantics - only an explicit Abort stops the loop).
    # ------------------------------------------------------------------

    def _build_hud_args(self, layout_path):
        args = []
        source = self.source_input.text().strip()
        output = self.output_input.text().strip()
        if source:
            args.append(source)
        if output:
            args.append(output)
        if self.logs_input.text().strip():
            args += ["--logs", self.logs_input.text().strip()]
        args += ["--layout", str(layout_path)]
        args.append("--render-video-log")
        if self.skip_existing_checkbox.isChecked():
            args.append("--no-overwrite")
        pattern = self._filename_format_by_label.get(self.filename_format_combo.currentText())
        if pattern:
            args += ["--render-log-filename-format", pattern]
        return args

    def _build_command(self, args):
        exe = Path(sys.executable)
        if "python" in exe.name.lower():
            return [sys.executable, "-m", "uwmedia", *args]
        return [sys.executable, *args]

    def _on_start(self):
        if self.process is not None:
            self.abort_requested = True
            self.status_label.setText("Aborting…")
            self._kill_process_tree()
            return

        overlays = self.selected_overlays
        source = self.source_input.text().strip()
        logs = self.logs_input.text().strip()
        if not overlays or not source or not logs:
            self.status_label.setText(
                "Nothing to run: select a source folder, a dive logs folder, and at least one overlay first."
            )
            return

        self.abort_requested = False
        self._run_queue = list(overlays)
        self._run_total = len(overlays)
        self._run_index = 0
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(True)
        self.start_button.setText("Abort")
        self._run_next_overlay()

    def _run_next_overlay(self):
        if self.abort_requested or not self._run_queue:
            self._finish_batch()
            return
        overlay = self._run_queue.pop(0)
        self._run_index += 1
        self.overlay_progress_label.setText(f"Overlay {self._run_index} of {self._run_total}: {overlay['label']}")
        self.status_label.setText("Starting…")
        args = self._build_hud_args(overlay["layout_path"])
        cmd = self._build_command(args)

        self.process = QtCore.QProcess(self)
        self.process.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._on_process_output)
        self.process.finished.connect(self._on_overlay_finished)
        self.process.start(cmd[0], cmd[1:])

    def _on_process_output(self):
        if self.process is None:
            return
        text = bytes(self.process.readAllStandardOutput()).decode(errors="replace").strip()
        if text:
            self.status_label.setText(text.splitlines()[-1])

    def _on_overlay_finished(self, _exit_code, _exit_status):
        self.process = None
        self._run_next_overlay()

    def _finish_batch(self):
        self.status_label.setText("Aborted" if self.abort_requested else "Done")
        self.overlay_progress_label.setText("")
        self.progress_bar.setVisible(False)
        self.start_button.setText("Start")
        self.process = None

    def _kill_process_tree(self):
        # See color_page.py's own docstring/pyside6_rework.md Phase 1 -
        # plain QProcess.kill() leaves ffmpeg (cli_main.py's own child)
        # running orphaned.
        if self.process is None:
            return
        pid = self.process.processId()
        if pid:
            try:
                subprocess.run(["pkill", "-9", "-P", str(pid)], capture_output=True)
            except Exception:
                pass
        self.process.kill()
        # self._run_queue is cleared implicitly by abort_requested short-
        # circuiting _run_next_overlay once _on_overlay_finished fires for
        # this (now-killed) process - no separate queue-clear needed here.
