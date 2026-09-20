"""Convertion page - PySide6 port of uwmedia/app.py's
_build_convert_fields/_build_convertion_section and friends (see
pyside6_rework.md Phase 3).

Simpler than Color/Overlay Generator: a single ffmpeg invocation (resize
to N target resolutions in one run, not a batch loop), and - checked
directly against PERSISTED_TEXT_FIELDS/PERSISTED_SELECTION_FIELDS/
PERSISTED_SWITCH_FIELDS in uwmedia/app.py - Source/Destination aren't
persisted across restarts in the Toga app either, so this page adds none
(not an oversight - the Toga original genuinely doesn't persist these).

Deliberately deferred, same reasoning as Color/Overlay Generator's own
Phase 1/2 scope calls: --hw-accel/--debug (Advanced-page-adjacent, that
page isn't ported yet) - FfmpegClass(hw_accel=False, debug=False) is
hardcoded for the resolution-detection probe, and build_convert_args
never appends either flag.
"""
import re
import subprocess
import sys
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from ffmpeg.ffmpeg_class import FfmpegClass

from uwmedia.pages.convertion_page_ui import Ui_ConvertionPage

# Order matches cli_main.py's --convert choices/resolutions dict, highest
# first. Height disables any target that would upscale the source.
CONVERT_RESOLUTIONS = [
    ("1080p", 1920, 1080),
    ("720p", 1280, 720),
    ("480p", 854, 480),
    ("360p", 640, 360),
]
CONVERT_RESOLUTION_NAME_RE = re.compile(r"(?i)[ _](4k|2160p|1080p|720p|480p|360p)")


class ConvertionPage(QtWidgets.QWidget, Ui_ConvertionPage):
    def __init__(self):
        super().__init__()
        self.setupUi(self)

        self.resolution_checkboxes = {
            "1080p": self.checkbox_1080p,
            "720p": self.checkbox_720p,
            "480p": self.checkbox_480p,
            "360p": self.checkbox_360p,
        }
        self.process = None

        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)

        self._wire_signals()
        self._refresh_output_preview()

    def _wire_signals(self):
        self.source_browse_button.clicked.connect(self._on_choose_source)
        self.dest_browse_button.clicked.connect(self._on_choose_dest)
        for checkbox in self.resolution_checkboxes.values():
            checkbox.toggled.connect(self._refresh_output_preview)
        self.start_button.clicked.connect(self._on_start)

    # ------------------------------------------------------------------
    # Source/destination pickers, resolution auto-detection - ported from
    # on_choose_convert_source/_refresh_convert_source_resolution/
    # on_choose_convert_dest.
    # ------------------------------------------------------------------

    def _on_choose_source(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select video file to convert")
        if not path:
            return
        self.source_input.setText(path)
        self._refresh_source_resolution(Path(path))
        self._refresh_output_preview()

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
            self.source_resolution_label.setText(label)
        except Exception as exc:
            self.source_resolution_label.setText(f"Could not detect resolution: {exc}")

        for res_name, _w, h in CONVERT_RESOLUTIONS:
            checkbox = self.resolution_checkboxes[res_name]
            allowed = source_height is None or h <= source_height
            checkbox.setEnabled(allowed)
            if not allowed:
                checkbox.setChecked(False)

    def _on_choose_dest(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select destination folder")
        if path:
            self.dest_input.setText(path)
            self._refresh_output_preview()

    def _convert_output_filename(self, source_path: Path, res_name: str) -> str:
        stem = source_path.stem
        if CONVERT_RESOLUTION_NAME_RE.search(stem):
            new_stem = CONVERT_RESOLUTION_NAME_RE.sub(f" {res_name}", stem)
        else:
            new_stem = f"{stem} {res_name}"
        return f"{new_stem}{source_path.suffix.lower()}"

    def _selected_resolutions(self):
        return [name for name, checkbox in self.resolution_checkboxes.items() if checkbox.isChecked()]

    def _refresh_output_preview(self):
        source = self.source_input.text().strip()
        dest = self.dest_input.text().strip()
        selected = self._selected_resolutions()

        if not source or not selected:
            self.output_preview.setPlainText("(select a source file and at least one output resolution)")
            return

        source_path = Path(source)
        lines = []
        for res_name in selected:
            filename = self._convert_output_filename(source_path, res_name)
            lines.append(str(Path(dest) / filename) if dest else filename)
        self.output_preview.setPlainText("\n".join(lines))

    # ------------------------------------------------------------------
    # Start/Progress - ported from build_convert_args/on_run's is_convert
    # branch. Single QProcess invocation (not a batch loop, unlike Overlay
    # Generator) - reuses the same pkill-based process-tree-kill fix Phase
    # 1 found live-testing Color's own Start/Abort.
    # ------------------------------------------------------------------

    def _build_args(self):
        source = self.source_input.text().strip()
        dest = self.dest_input.text().strip()
        selected = self._selected_resolutions()
        if not source or not dest or not selected:
            return []
        return [source, dest, "--convert", *selected]

    def _build_command(self, args):
        exe = Path(sys.executable)
        if "python" in exe.name.lower():
            return [sys.executable, "-m", "uwmedia", *args]
        return [sys.executable, *args]

    def _on_start(self):
        if self.process is not None:
            self.status_label.setText("Aborting…")
            self._kill_process_tree()
            return

        args = self._build_args()
        if not args:
            self.status_label.setText(
                "Nothing to run: select a source file, destination folder, and at least one output resolution first."
            )
            return

        cmd = self._build_command(args)
        self.status_label.setText("Starting…")
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(True)
        self.start_button.setText("Abort")

        self.process = QtCore.QProcess(self)
        self.process.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._on_process_output)
        self.process.finished.connect(self._on_process_finished)
        self.process.start(cmd[0], cmd[1:])

    def _on_process_output(self):
        if self.process is None:
            return
        text = bytes(self.process.readAllStandardOutput()).decode(errors="replace").strip()
        if text:
            self.status_label.setText(text.splitlines()[-1])

    def _on_process_finished(self, exit_code, _exit_status):
        self.status_label.setText(f"Finished (exit code {exit_code})" if exit_code == 0 else f"Failed (exit code {exit_code})")
        self.progress_bar.setVisible(False)
        self.start_button.setText("Start")
        self.process = None

    def _kill_process_tree(self):
        # See color_page.py's own docstring/pyside6_rework.md Phase 1.
        if self.process is None:
            return
        pid = self.process.processId()
        if pid:
            try:
                subprocess.run(["pkill", "-9", "-P", str(pid)], capture_output=True)
            except Exception:
                pass
        self.process.kill()
