"""Convertion page backend - qml_development.md Phase 3. QObject exposed to
uwmedia/qml/ConvertionPage.qml as the "convertionBackend" context
property.

Ported close to verbatim from uwmedia/pages/convertion_page.py
(the old Widgets page, kept as reference only) - simplest page so far, a
single ffmpeg invocation (resize to N target resolutions in one run, not
a batch loop) and no persistence (checked directly against
PERSISTED_TEXT_FIELDS/PERSISTED_SELECTION_FIELDS/PERSISTED_SWITCH_FIELDS
in uwmedia/app.py by that old page's own docstring - Source/Destination
genuinely aren't persisted in the Toga app either, so this backend adds
none, not an oversight).

Deliberately deferred, same reasoning as every other first-pass page:
--hw-accel/--debug (Advanced-page-adjacent, not ported yet).

_handle_progress_line restores UWMEDIA_FFMPEG_PROGRESS percentage display
- ported from uwmedia/app.py's own method of the same name
(qml_development.md's Toga-removal cutover flagged its absence here as an
undocumented Phase 3 simplification; see tests/test_progress_line.py,
which exercises it directly).
"""
import re
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Property, QObject, QProcess, Signal, Slot

from ffmpeg.ffmpeg_class import FfmpegClass
from utils.app_settings import get_fields, set_field
from utils.display_paths import contract_home_path

CONVERT_RESOLUTIONS = [
    ("1080p", 1920, 1080),
    ("720p", 1280, 720),
    ("480p", 854, 480),
    ("360p", 640, 360),
]
CONVERT_RESOLUTION_NAME_RE = re.compile(r"(?i)[ _](4k|2160p|1080p|720p|480p|360p)")

PROGRESS_LINE_RE = re.compile(r"UWMEDIA_PROGRESS (\d+)/(\d+) (\S+) (.*)$")
FFMPEG_PROGRESS_RE = re.compile(r"UWMEDIA_FFMPEG_PROGRESS (\d+(?:\.\d+)?)")


class ConvertionBackend(QObject):
    fieldsChanged = Signal()
    resolutionsChanged = Signal()
    outputPreviewChanged = Signal()
    runStateChanged = Signal()

    def __init__(self):
        super().__init__()

        self._source_text = ""
        self._dest_text = ""
        self._source_resolution_text = ""
        self._checked = {name: False for name, _w, _h in CONVERT_RESOLUTIONS}
        self._enabled = {name: True for name, _w, _h in CONVERT_RESOLUTIONS}
        self._hw_accel = get_fields().get("hw_accel_switch", True)

        self.process = None
        self._status_text = "No batch running"
        self._progress_total = 0
        self._progress_done = 0
        self._progress_current_target = None

        self._refresh_output_preview()

    # ------------------------------------------------------------------
    # Source/destination pickers, resolution auto-detection - ported
    # close to verbatim from on_choose_convert_source/
    # _refresh_convert_source_resolution/on_choose_convert_dest.
    # ------------------------------------------------------------------

    @Property(str, notify=fieldsChanged)
    def sourceText(self):
        return self._source_text

    @Property(str, notify=fieldsChanged)
    def destText(self):
        return self._dest_text

    @Property(str, notify=fieldsChanged)
    def sourceResolutionText(self):
        return self._source_resolution_text

    @Property(bool, notify=fieldsChanged)
    def hwAccel(self):
        # Same persisted "hw_accel_switch" key as ColorBackend's own
        # hwAccel/OverlayGeneratorBackend's own hwAccel - each page reads/
        # writes it independently now rather than one shared
        # AdvancedBackend property (moved per the user's request, since
        # it's specifically each page's own Start button that needs it
        # when building that run's CLI args).
        return self._hw_accel

    @hwAccel.setter
    def hwAccel(self, value):
        if value == self._hw_accel:
            return
        self._hw_accel = value
        set_field("hw_accel_switch", value)
        self.fieldsChanged.emit()

    @Slot()
    def browseSource(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(None, "Select video file to convert")
        if not path:
            return
        self._source_text = path
        self._refresh_source_resolution(Path(path))
        self.fieldsChanged.emit()
        self._refresh_output_preview()

    @Slot()
    def browseDest(self):
        from PySide6.QtWidgets import QFileDialog
        path = QFileDialog.getExistingDirectory(None, "Select destination folder")
        if path:
            self._dest_text = path
            self.fieldsChanged.emit()
            self._refresh_output_preview()

    @Slot(str, result=str)
    def contractPath(self, path):
        """Display-only /Users/<name>/... -> ~/... - see
        utils/display_paths.py and ColorBackend's own contractPath."""
        return contract_home_path(path)

    def _refresh_source_resolution(self, path: Path):
        source_height = None
        try:
            ff = FfmpegClass(hw_accel=False, debug=False)
            width, height = ff.get_video_dimensions(path)
            source_height = height
            label = f"{width}x{height}"
            for name, _w, h in CONVERT_RESOLUTIONS:
                if h <= height:
                    label = f"{width}x{height} (up to {name})"
                    break
            self._source_resolution_text = label
        except Exception as exc:
            self._source_resolution_text = f"Could not detect resolution: {exc}"

        for res_name, _w, h in CONVERT_RESOLUTIONS:
            allowed = source_height is None or h <= source_height
            self._enabled[res_name] = allowed
            if not allowed:
                self._checked[res_name] = False
        self.resolutionsChanged.emit()

    # ------------------------------------------------------------------
    # Resolution checkboxes
    # ------------------------------------------------------------------

    @Property(list, constant=True)
    def resolutionNames(self):
        return [name for name, _w, _h in CONVERT_RESOLUTIONS]

    # Exposed as lists (not per-name isChecked()/isEnabled() Slot calls)
    # deliberately - a QML property binding only re-evaluates on a real
    # NOTIFY signal from a Property it read; calling a Slot inside a
    # binding expression doesn't register as a dependency, so a
    # checked/enabled binding built on isChecked("1080p") would silently
    # never update after the first paint. indexOf() against a real
    # notify=resolutionsChanged property is the correct pattern.
    @Property(list, notify=resolutionsChanged)
    def checkedResolutions(self):
        return [name for name, value in self._checked.items() if value]

    @Property(list, notify=resolutionsChanged)
    def enabledResolutions(self):
        return [name for name, value in self._enabled.items() if value]

    @Slot(str, bool)
    def setChecked(self, name, value):
        if self._checked.get(name) == value:
            return
        self._checked[name] = value
        self.resolutionsChanged.emit()
        self._refresh_output_preview()

    def _selected_resolutions(self):
        return [name for name, checked in self._checked.items() if checked]

    # ------------------------------------------------------------------
    # Output filename preview - ported close to verbatim from
    # _convert_output_filename/_refresh_convert_output_preview.
    # ------------------------------------------------------------------

    def _convert_output_filename(self, source_path: Path, res_name: str) -> str:
        stem = source_path.stem
        if CONVERT_RESOLUTION_NAME_RE.search(stem):
            new_stem = CONVERT_RESOLUTION_NAME_RE.sub(f" {res_name}", stem)
        else:
            new_stem = f"{stem} {res_name}"
        return f"{new_stem}{source_path.suffix.lower()}"

    def _refresh_output_preview(self):
        source = self._source_text.strip()
        dest = self._dest_text.strip()
        selected = self._selected_resolutions()

        if not source or not selected:
            self._output_preview_text = "(select a source file and at least one output resolution)"
            self.outputPreviewChanged.emit()
            return

        source_path = Path(source)
        lines = []
        for res_name in selected:
            filename = self._convert_output_filename(source_path, res_name)
            lines.append(str(Path(dest) / filename) if dest else filename)
        self._output_preview_text = "\n".join(lines)
        self.outputPreviewChanged.emit()

    @Property(str, notify=outputPreviewChanged)
    def outputPreviewText(self):
        return getattr(self, "_output_preview_text", "")

    # ------------------------------------------------------------------
    # Start/Progress - ported close to verbatim from build_convert_args/
    # on_run's is_convert branch. Single QProcess invocation.
    # ------------------------------------------------------------------

    def _build_args(self):
        source = self._source_text.strip()
        dest = self._dest_text.strip()
        selected = self._selected_resolutions()
        if not source or not dest or not selected:
            return []
        args = [source, dest, "--convert", *selected]
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

    @Property(bool, notify=runStateChanged)
    def isRunning(self):
        return self.process is not None

    def _set_status(self, text):
        self._status_text = text
        self.runStateChanged.emit()

    @Slot()
    def onStartClicked(self):
        if self.process is not None:
            self._set_status("Aborting…")
            self._kill_process_tree()
            return

        args = self._build_args()
        if not args:
            self._set_status(
                "Nothing to run: select a source file, destination folder, and at least one output resolution first."
            )
            return

        cmd = self._build_command(args)
        self._progress_total = 0
        self._progress_done = 0
        self._progress_current_target = None
        self._set_status("Starting…")

        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._on_process_output)
        self.process.finished.connect(self._on_process_finished)
        self.process.start(cmd[0], cmd[1:])
        self.runStateChanged.emit()

    def _on_process_output(self):
        if self.process is None:
            return
        text = bytes(self.process.readAllStandardOutput()).decode(errors="replace").strip()
        if text:
            for line in text.splitlines():
                if not self._handle_progress_line(line):
                    self._set_status(line)

    def _handle_progress_line(self, line):
        """Ported from uwmedia/app.py's own _handle_progress_line. Convertion
        always runs one ffmpeg encode at a time (never a ThreadPoolExecutor
        batch), so a bare UWMEDIA_FFMPEG_PROGRESS percentage is never
        ambiguous - unlike Color's own "process" role, no total-in-(0,1)
        gating is needed here."""
        stripped = line.strip()
        match = PROGRESS_LINE_RE.search(stripped)
        if match:
            done, total, status, filename = match.groups()
            self._progress_done = int(done)
            self._progress_total = int(total)
            if status == "start":
                self._progress_current_target = None
                self._set_status(f"Processing 0 of {total}…")
            elif self._progress_done >= self._progress_total:
                self._progress_current_target = None
                self._set_status(f"Finished — last file: {filename}")
            else:
                self._progress_current_target = filename
                self._set_status(f"Processing: {filename}")
            return True

        ffmpeg_match = FFMPEG_PROGRESS_RE.search(stripped)
        if ffmpeg_match:
            pct = float(ffmpeg_match.group(1))
            if self._progress_current_target:
                self._set_status(f"Processing: {self._progress_current_target} — {pct:.0f}%")
            else:
                self._set_status(f"Rendering — {pct:.0f}%")
            return True

        return False

    def _on_process_finished(self, exit_code, _exit_status):
        self._set_status(
            f"Finished (exit code {exit_code})" if exit_code == 0 else f"Failed (exit code {exit_code})"
        )
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
