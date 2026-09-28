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
no_overwrite_switch, plus hudpage_log_file_input/hudpage_log_file_mode for
the Log file switch) - hudpage_selected_overlays is deliberately NOT
persisted, matching the Toga app's own documented choice (unchanged
here).

Deliberately deferred, matching every other first-pass page's own
convention: the custom-filename-pattern escape hatch (Output-filename
dropdown offers only the 2 real RENDER_LOG_FORMAT_PRESETS). The custom
LAYOUT PATH escape hatch (brand cascade's "Custom..." entry) is NOT
deferred - it's part of this page's main cascade and is ported in full.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Property, QObject, QProcess, Signal, Slot

from utils.app_settings import get_fields, set_field
from utils.display_paths import contract_home_path
from utils.resource_paths import app_temp_dir
from utils.run_timing import RunTiming
from utils.layouts import list_templates, page_display_name, resolve_template_state, load_layout_file, strip_variant_markers, variant_display_name

LAYOUT_CUSTOM = "Custom…"
# The CLI's machine-readable progress lines (cli_main.py's batch loop and
# render loops; the same protocol convertion_backend.py reads):
#   UWMEDIA_PROGRESS <done>/<total> <start|done|skipped|error> <file>
#   UWMEDIA_PROGRESS_ACTIVE <file>           a file's render has begun
#   UWMEDIA_FFMPEG_PROGRESS <pct>            frames written for the file being
#                                            rendered (ambiguous when several
#                                            files render in parallel)
PROGRESS_LINE_RE = re.compile(r"UWMEDIA_PROGRESS (\d+)/(\d+) (\S+) (.*)$")
PROGRESS_ACTIVE_RE = re.compile(r"UWMEDIA_PROGRESS_ACTIVE (.*)$")
FFMPEG_PROGRESS_RE = re.compile(r"UWMEDIA_FFMPEG_PROGRESS (\d+(?:\.\d+)?)")
# Output filename presets (2026-09-28, per the user): plain labels with an
# example instead of the old key-style names, which are still mapped from
# settings.json (LEGACY_RENDER_LOG_FORMAT_LABELS).
RENDER_LOG_FORMAT_PRESETS = [
    ("Original + overlay (GX010042_garmin_mk3i_main)", "{filename}_{hud}"),
    ("Date + time + overlay (20251101_121212_garmin_mk3i_main)", "{datetaken:%Y%m%d_%H%M%S}_{hud}"),
]
RENDER_LOG_FORMAT_DEFAULT = RENDER_LOG_FORMAT_PRESETS[1][0]
LEGACY_RENDER_LOG_FORMAT_LABELS = {
    "source_filename_hudname": RENDER_LOG_FORMAT_PRESETS[0][0],
    "source_datetaken_hudname": RENDER_LOG_FORMAT_PRESETS[1][0],
}
# "Overlay size" (2026-09-27, per the user): label -> (--overlay-size,
# --overlay-full-frame). 1080p is the template's own size in its 1920×1080
# design frame (what every render was until now), 4K twice that so it drops
# onto 4K footage 1:1; "Full frame" renders the whole frame with the overlay
# where the layout anchors it, so there is nothing to position in the editor.
OVERLAY_SIZE_CHOICES = [
    ("1080p (template size)", "1080p", False),
    ("4K (2×)", "4k", False),
    ("Full frame 1080p", "1080p", True),
    ("Full frame 4K", "4k", True),
]
OVERLAY_SIZE_DEFAULT = "4K (2×)"


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
        self._variant_choices = {}
        self._selected_brand_key = None
        self._selected_computer_key = None
        self._selected_page_id = None
        self._selected_variant = None
        self._is_custom = False

        self._source_text = ""
        self._output_text = ""
        self._logs_text = ""
        self._log_file_text = ""
        # The "Log directory / Log file" switch above the Dive logs field:
        # False renders each video/photo in Source against the logs FOLDER,
        # True renders the whole dive in one log FILE with no video (the
        # CLI's --render-log). One Start button serves both; the switch
        # decides which. The two paths are kept separately so flipping the
        # switch back shows the folder (or file) chosen before.
        self._log_file_mode = False
        self._log_mode = False  # what the RUNNING batch renders from - latched from _log_file_mode at Start
        self._custom_path_text = ""
        self._skip_existing = False
        self._hw_accel = True
        self._filename_format_by_label = dict(RENDER_LOG_FORMAT_PRESETS)
        self._filename_format = RENDER_LOG_FORMAT_DEFAULT
        self._overlay_size = OVERLAY_SIZE_DEFAULT

        self.process = None
        self.abort_requested = False
        self._run_queue = []
        self._run_total = 0
        self._run_index = 0
        self._status_text = "No batch running"
        self._overlay_progress_text = ""
        # Progress of the overlay run in flight (one CLI invocation renders
        # every file in Source for one overlay) - see _handle_output_line.
        self._failed_runs = []     # (overlay label, last CLI line) of runs that exited non-zero
        self._files_total = 0      # files the CLI found in Source (0 until it says)
        self._files_done = 0       # files finished in this run
        self._current_file = ""    # file the CLI last started
        self._file_pct = 0.0       # its frames written, 0-100 (single-file runs only)
        # Elapsed / estimated-remaining line under the bars (utils/run_timing.py);
        # extrapolates from the whole batch (totalProgress), not the overlay in flight.
        self.timing = RunTiming(lambda: self.totalProgress, self)
        self.timing.changed.connect(self.runStateChanged.emit)

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
        self._log_file_text = fields.get("hudpage_log_file_input", "") or ""
        self._log_file_mode = bool(fields.get("hudpage_log_file_mode", False))
        self._skip_existing = fields.get("no_overwrite_switch", False)
        self._hw_accel = fields.get("hw_accel_switch", True)
        fmt_label = fields.get("hudpage_filename_format_select")
        fmt_label = LEGACY_RENDER_LOG_FORMAT_LABELS.get(fmt_label, fmt_label)
        if fmt_label and fmt_label in self._filename_format_by_label:
            self._filename_format = fmt_label
        size_label = fields.get("hudpage_overlay_size")
        if size_label in {label for label, _, _ in OVERLAY_SIZE_CHOICES}:
            self._overlay_size = size_label

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

    @Property(list, constant=True)
    def overlaySizeList(self):
        return [label for label, _, _ in OVERLAY_SIZE_CHOICES]

    @Property(str, notify=fieldsChanged)
    def overlaySize(self):
        return self._overlay_size

    @overlaySize.setter
    def overlaySize(self, value):
        if value == self._overlay_size or value not in self.overlaySizeList:
            return
        self._overlay_size = value
        set_field("hudpage_overlay_size", value)
        self.fieldsChanged.emit()

    @Property(int, notify=fieldsChanged)
    def overlaySizeIndex(self):
        return self.overlaySizeList.index(self._overlay_size)

    def _overlay_size_args(self):
        """CLI arguments for the chosen Overlay size (both render modes)."""
        _label, size, full_frame = next(c for c in OVERLAY_SIZE_CHOICES if c[0] == self._overlay_size)
        args = [] if size == "1080p" else ["--overlay-size", size]
        if full_frame:
            args.append("--overlay-full-frame")
        return args

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

    @Property(bool, notify=fieldsChanged)
    def logFileMode(self):
        """True when the Dive logs field holds a single log FILE to render
        the whole dive for with no video (Start then runs the CLI's
        --render-log); False when it holds the dive logs FOLDER that each
        video/photo in Source is matched against."""
        return self._log_file_mode

    @logFileMode.setter
    def logFileMode(self, value):
        value = bool(value)
        if value == self._log_file_mode:
            return
        self._log_file_mode = value
        set_field("hudpage_log_file_mode", value)
        self.fieldsChanged.emit()

    @Property(str, notify=fieldsChanged)
    def logFileText(self):
        """A single dive log to render overlays for without any video - the
        whole dive, start to end, as one overlay video per selected overlay
        (the CLI's --render-log). Shown in the Dive logs field while
        logFileMode is on."""
        return self._log_file_text

    @logFileText.setter
    def logFileText(self, value):
        if value == self._log_file_text:
            return
        self._log_file_text = value
        set_field("hudpage_log_file_input", value)
        self.fieldsChanged.emit()

    @Slot()
    def browseLogFile(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            None, "Select dive log", "", "Dive logs (*.uddf *.fit *.ssrf *.xml);;All files (*)"
        )
        if path:
            self.logFileText = path

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

    # The combos bind currentIndex to these: a cascade change re-emits the
    # list models, and an unbound ComboBox then falls back to entry 0
    # ("Garmin") while the backend still holds e.g. Generic (bug seen
    # 2026-09-27 after adding a Generic overlay).
    @Property(int, notify=cascadeChanged)
    def brandIndex(self):
        if self._is_custom:
            return len(self._brand_choices)
        keys = list(self._brand_choices.values())
        return keys.index(self._selected_brand_key) if self._selected_brand_key in keys else 0

    @Property(int, notify=cascadeChanged)
    def computerIndex(self):
        keys = list(self._computer_choices.values())
        return keys.index(self._selected_computer_key) if self._selected_computer_key in keys else 0

    @Property(int, notify=cascadeChanged)
    def pageIndex(self):
        keys = list(self._page_choices.values())
        return keys.index(self._selected_page_id) if self._selected_page_id in keys else 0

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

    # Tank setup (the page's variant: no tank / single tank / sidemount /
    # multi-tank) - a choice here, not guessed from the logs.
    @Property(list, notify=cascadeChanged)
    def variantList(self):
        return list(self._variant_choices.keys())

    @Property(bool, notify=cascadeChanged)
    def variantVisible(self):
        return (not self._is_custom) and bool(self._variant_choices)

    @Property(int, notify=cascadeChanged)
    def variantIndex(self):
        for i, v in enumerate(self._variant_choices.values()):
            if v == self._selected_variant:
                return i
        return 0

    @Slot(str)
    def onVariantSelected(self, variant_display):
        variant = self._variant_choices.get(variant_display)
        if variant is not None:
            self._selected_variant = variant
            self.cascadeChanged.emit()

    def _refresh_variant_choices(self):
        brand, computer, page = self._selected_brand_key, self._selected_computer_key, self._selected_page_id
        manifest = self.hud_templates.get(brand, {}).get(computer) if brand and computer else None
        entry = next((p for p in (manifest or {}).get("pages", []) if p["id"] == page), None)
        variants = (entry.get("variants") or []) if entry else []
        self._variant_choices = {variant_display_name(v): v for v in variants}
        if self._selected_variant not in variants:
            self._selected_variant = "single_tank" if "single_tank" in variants else (variants[0] if variants else None)

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
        self._refresh_variant_choices()

    @Slot(str)
    def onPageSelected(self, page_display_name):
        self._selected_page_id = self._page_choices.get(page_display_name)
        self._refresh_variant_choices()
        self.cascadeChanged.emit()

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
        variants = page_entry.get("variants") or []
        variant = self._selected_variant if self._selected_variant in variants else (variants[0] if variants else None)
        state_path = resolve_template_state(brand, computer, page, variant=variant)
        if state_path is None:
            return None

        layout = strip_variant_markers(load_layout_file(state_path))
        hud_skin = layout.setdefault("hud_skin", {})
        skin_path = hud_skin.get("path")
        if skin_path and not Path(skin_path).is_absolute():
            hud_skin["path"] = str((state_path.parent / skin_path).resolve())
        # The layout's own anchor/offsets stay: a template-sized render
        # neutralises them itself (cli_main.overlay_canvas) and a full-frame
        # render needs them to place the overlay as on the footage.

        name_parts = [brand]
        if len(self.hud_templates.get(brand, {})) > 1:
            name_parts.append(computer)
        name_parts.append(page)
        if variant:
            name_parts.append(variant)
        out_dir = app_temp_dir("uwmedia_qt_hud_")
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
        args += self._overlay_size_args()
        if self._hw_accel:
            args.append("--hw-accel")
        return args

    def _build_log_args(self, layout_path):
        """CLI arguments for one overlay rendered from the log file alone:
        `<output> --render-log <log> --layout <layout>` (the CLI names the
        file <log stem>_<layout>.mp4 and never overwrites)."""
        args = [self._output_text.strip(), "--render-log", self._log_file_text.strip(), "--layout", str(layout_path)]
        args += self._overlay_size_args()
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

    # -- the two progress bars (2026-09-27, per the user): the overlay run
    # in flight (its videos), and the whole batch (videos × overlays) -------

    @Property(bool, notify=runStateChanged)
    def progressKnown(self):
        """False until the CLI has said how many files Source holds - the
        bars are indeterminate until then."""
        return self._files_total > 0

    def _run_fraction(self):
        """0..1 of the current overlay run: files done, plus the file being
        rendered where its percentage is unambiguous (a single file, or the
        log-file mode's one render)."""
        if self._files_total <= 0:
            return 0.0
        done = float(self._files_done)
        if self._files_total == 1 and self._files_done == 0:
            done = self._file_pct / 100.0
        return max(0.0, min(1.0, done / self._files_total))

    @Property(float, notify=runStateChanged)
    def currentProgress(self):
        return self._run_fraction()

    @Property(str, notify=runStateChanged)
    def currentProgressText(self):
        if self.process is None or self._files_total <= 0:
            return ""
        if self._log_mode or self._files_total == 1:
            name = self._current_file or (Path(self._log_file_text.strip()).name if self._log_mode else "")
            return f"Rendering {name} - {self._file_pct:.0f} %".replace("  ", " ")
        text = f"Video {min(self._files_done + 1, self._files_total)} of {self._files_total}"
        if self._files_done >= self._files_total:
            text = f"All {self._files_total} videos done"
        elif self._current_file:
            text += f": {self._current_file}"
        return text

    @Property(float, notify=runStateChanged)
    def totalProgress(self):
        """0..1 over every render of the batch: files × overlays."""
        if self._run_total <= 0:
            return 0.0
        completed_runs = max(0, self._run_index - 1)
        return max(0.0, min(1.0, (completed_runs + self._run_fraction()) / self._run_total))

    @Property(str, notify=runStateChanged)
    def totalProgressText(self):
        if self.process is None or self._run_total <= 0 or self._files_total <= 0:
            return ""
        total = self._files_total * self._run_total
        done = max(0, self._run_index - 1) * self._files_total + min(self._files_done, self._files_total)
        unit = "render" if self._log_mode else "video render"
        return f"{done} of {total} {unit}s ({self._files_total} × {self._run_total} overlays)".replace("(1 × ", "(1 log × ")

    @Property(str, notify=runStateChanged)
    def timingText(self):
        return self.timing.text

    def _reset_run_progress(self):
        self._files_total = 1 if self._log_mode else 0
        self._files_done = 0
        self._current_file = ""
        self._file_pct = 0.0

    def _handle_output_line(self, line):
        """Feed one CLI stdout line into the progress state; True when it was
        a progress line (so it isn't shown as the status text)."""
        match = PROGRESS_LINE_RE.search(line)
        if match:
            done, total, status, filename = match.groups()
            self._files_total = int(total)
            self._files_done = int(done)
            if status == "start":
                self._current_file = ""
                if self._files_total == 0:
                    self._status_text = "No files found in the Source folder"
            self._file_pct = 0.0
            if status not in ("start",) and filename:
                self._status_text = f"{status.capitalize()}: {filename}"
            self.runStateChanged.emit()
            return True
        match = PROGRESS_ACTIVE_RE.search(line)
        if match:
            self._current_file = match.group(1).strip()
            self._file_pct = 0.0
            self.runStateChanged.emit()
            return True
        match = FFMPEG_PROGRESS_RE.search(line)
        if match:
            self._file_pct = max(0.0, min(100.0, float(match.group(1))))
            self.runStateChanged.emit()
            return True
        return False

    @Property(bool, notify=runStateChanged)
    def isRunning(self):
        return self.process is not None

    def _set_status(self, text):
        self._status_text = text
        self.runStateChanged.emit()

    @Slot()
    def onStartClicked(self):
        """Start (or abort) the batch. With the Log file switch off, every
        video/photo in Source is rendered against the dive logs folder; with
        it on, every selected overlay is rendered for the whole dive in the
        log file, start to end, with no video (e.g. a dive built in the Dive
        Profile Builder). _log_mode is latched here so flipping the switch
        mid-batch doesn't change what the remaining overlays render."""
        if self.process is not None:
            self.abort_requested = True
            self._set_status("Aborting…")
            self._kill_process_tree()
            return

        overlays = self.selected_overlays
        if self._log_file_mode:
            log_file = self._log_file_text.strip()
            output = self._output_text.strip()
            if not overlays or not log_file or not output:
                self._set_status("Nothing to run: select a log file, an output folder, and at least one overlay first.")
                return
            if not Path(log_file).is_file():
                self._set_status(f"Log file not found: {log_file}")
                return
        else:
            source = self._source_text.strip()
            logs = self._logs_text.strip()
            if not overlays or not source or not logs:
                self._set_status(
                    "Nothing to run: select a source folder, a dive logs folder, and at least one overlay first."
                )
                return

        self.abort_requested = False
        self._log_mode = self._log_file_mode
        self._failed_runs = []
        self._run_queue = list(overlays)
        self._run_total = len(overlays)
        self._run_index = 0
        self.timing.start()
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
        self._reset_run_progress()
        self.runStateChanged.emit()
        args = self._build_log_args(overlay["layout_path"]) if self._log_mode else self._build_hud_args(overlay["layout_path"])
        cmd = self._build_command(args)

        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._on_process_output)
        self.process.finished.connect(self._on_overlay_finished)
        self.process.start(cmd[0], cmd[1:])

    def _on_process_output(self):
        if self.process is None:
            return
        text = bytes(self.process.readAllStandardOutput()).decode(errors="replace")
        status = None
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if not self._handle_output_line(line):
                status = line
        if status is not None:
            self._set_status(status)

    def _on_overlay_finished(self, exit_code, _exit_status):
        # A run that exits non-zero (e.g. the CLI refusing the layout) used
        # to vanish behind the next overlay's "Starting…" - remember it for
        # the final status instead (2026-09-27: three overlays added, only
        # two ran, nothing said why).
        if exit_code != 0 and not self.abort_requested:
            self._failed_runs.append((self._overlay_progress_text.split(": ", 1)[-1], self._status_text))
        self.process = None
        self._run_next_overlay()

    def _finish_batch(self):
        self._status_text = "Aborted" if self.abort_requested else "Done"
        if self._failed_runs and not self.abort_requested:
            failed = "; ".join(f"{label} ({reason})" for label, reason in self._failed_runs)
            self._status_text = f"Done - {len(self._failed_runs)} of {self._run_total} overlays failed: {failed}"
        self._overlay_progress_text = ""
        self.process = None
        self._files_total = 0
        self.timing.stop(ok=not self.abort_requested and not self._failed_runs)
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
