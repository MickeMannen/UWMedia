"""
The Color page backend (uwmedia/backends/color_backend.py), the parts the
other Color tests leave out: form fields saved to and restored from settings,
the browse pickers (dialogs stubbed), the media count in the Progress card,
the preview of a photo or video matched against a folder of dive logs
(synthetic logs, fixture media), overlay edge cases, and the run - Start,
CLI output, finish and abort - with QProcess replaced by a stand-in, so
nothing is rendered.
"""
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

import pytest
from PySide6.QtCore import QProcess
from PySide6.QtGui import QImage

import uwmedia.backends.color_backend as cb
from conftest import DJI_CLIP, PHOTO
from utils.app_settings import get_fields, set_field
from uwmedia.backends.color_backend import (
    FILENAME_FORMAT_PRESETS,
    PREVIEW_WORKING_WIDTH,
    ColorBackend,
    ColorPreviewImageProvider,
)


class FakeSignal:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)

    def emit(self, *args):
        for slot in self.slots:
            slot(*args)


class FakeProcess:
    """Records how the backend starts it; the test feeds output and exit."""

    def __init__(self, parent=None):
        self.readyReadStandardOutput = FakeSignal()
        self.finished = FakeSignal()
        self.mode = None
        self.program = None
        self.arguments = None
        self.killed = False
        self.pid = 777
        self._output = b""

    def setProcessChannelMode(self, mode):
        self.mode = mode

    def start(self, program, arguments):
        self.program, self.arguments = program, list(arguments)

    def readAllStandardOutput(self):
        data, self._output = self._output, b""
        return data

    def processId(self):
        return self.pid

    def kill(self):
        self.killed = True

    # -- test side --
    def say(self, text):
        self._output += text.encode()
        self.readyReadStandardOutput.emit()

    def exit(self, code, status=QProcess.ExitStatus.NormalExit):
        self.finished.emit(code, status)


@pytest.fixture
def processes(monkeypatch):
    started = []

    def make(parent=None):
        process = FakeProcess(parent)
        started.append(process)
        return process

    make.ProcessChannelMode = QProcess.ProcessChannelMode
    make.ExitStatus = QProcess.ExitStatus
    monkeypatch.setattr(cb, "QProcess", make)
    return started


@pytest.fixture
def pkill(monkeypatch):
    calls = []
    monkeypatch.setattr(cb.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    return calls


@pytest.fixture
def color(isolated_template_roots, settings_file):
    return ColorBackend()


@pytest.fixture
def logs_folder(synthetic_logs, tmp_path):
    """The synthetic dives plus what a real logs folder also holds: a hidden
    file, a subfolder and a file that isn't a dive log."""
    folder = tmp_path / "logs"
    shutil.copytree(synthetic_logs, folder)
    (folder / ".DS_Store").write_text("x")
    (folder / "sub").mkdir()
    (folder / "broken.uddf").write_text("not xml at all")
    return folder


def _add_overlay(color):
    color.onAddHudBrandSelected("Shearwater")
    color.onAddHudComputerSelected("Perdix 2")
    assert color.confirmAddHud()
    return color.color_overlay_instances[-1]


# --- form fields --------------------------------------------------------------

def test_form_fields_are_saved_and_restored(color, tmp_path):
    color.outputText = str(tmp_path / "out")
    color.logsText = str(tmp_path / "no_logs_here")
    color.colorChecked = False
    color.hwAccel = False
    color.colorProfile = "vivid"
    color.filenameFormat = FILENAME_FORMAT_PRESETS[2][0]

    again = ColorBackend()
    assert again.outputText == str(tmp_path / "out")
    assert again.logsText == str(tmp_path / "no_logs_here")
    assert again.colorChecked is False and again.hwAccel is False
    assert again.colorProfile == "vivid" and "vivid" in again.colorProfileList
    assert again.filenameFormat == FILENAME_FORMAT_PRESETS[2][0]


def test_setting_a_field_to_its_current_value_saves_nothing(color, settings_file):
    color.sourceText = ""
    color.outputText = ""
    color.logsText = ""
    color.colorChecked = True
    color.hwAccel = True
    color.colorProfile = color.colorProfile
    color.filenameFormat = color.filenameFormat
    assert not settings_file.exists()


def test_profile_list_falls_back_to_default_when_profiles_cannot_load(isolated_template_roots, settings_file,
                                                                      monkeypatch):
    def broken():
        raise OSError("color.yaml unreadable")

    monkeypatch.setattr(cb, "load_merged_color_profiles", broken)
    set_field("color_profile", "vivid")  # no longer offered: ignored
    color = ColorBackend()
    assert color.colorProfileList == ["default"] and color.colorProfile == "default"


def test_pickers_fill_the_fields_and_remember_their_folder(color, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    folder = tmp_path / "picked"
    folder.mkdir()
    picked_file = folder / "frame.png"
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(picked_file), "")))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(folder)))
    color.browseSourceFile()
    assert color.sourceText == str(picked_file)
    color.browseOutputFile()
    assert color.outputText == str(picked_file)
    color.browseOutputFolder()
    assert color.outputText == str(folder)
    color.browseLogsFolder()
    assert color.logsText == str(folder)
    fields = get_fields()
    assert fields["color_output_dialog_dir"] == fields["color_logs_dialog_dir"] == str(folder)


def test_cancelled_pickers_change_nothing(color, monkeypatch, settings_file):
    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: ""))
    for browse in (color.browseSourceFile, color.browseSourceFolder, color.browseOutputFile,
                   color.browseOutputFolder, color.browseLogsFolder):
        browse()
    assert (color.sourceText, color.outputText, color.logsText) == ("", "", "")
    assert not settings_file.exists()


def test_contract_path_shortens_the_home_folder(color):
    assert color.contractPath(str(Path.home()) + "/Pictures") == "~/Pictures"


# --- media count ------------------------------------------------------------------

def test_source_count_counts_videos_and_photos(color, tmp_path):
    assert color.sourceCountText == ""
    media = tmp_path / "media"
    media.mkdir()
    color._source_text = str(media)
    assert color.sourceCountText == "No media files found"
    for name in ("a.MP4", "b.mov", "c.jpg", ".hidden.mp4"):
        (media / name).write_bytes(b"")
    (media / "sub").mkdir()
    assert color.sourceCountText == "2 videos, 1 photo found"
    color._source_text = str(media / "a.MP4")
    assert color.sourceCountText == "1 video found"
    color._source_text = str(media / "c.jpg")
    assert color.sourceCountText == "1 photo found"
    color._source_text = str(tmp_path / "missing")
    assert color.sourceCountText == ""


# --- preview and dive matching --------------------------------------------------

def test_photo_preview_is_matched_to_its_dive(color, logs_folder, monkeypatch, capsys):
    real_parse = cb.parse_log_file

    def parse(path, *a):
        if path.name == "broken.uddf":
            raise ValueError("bad header")
        return real_parse(path, *a)

    monkeypatch.setattr(cb, "parse_log_file", parse)
    color.sourceText = str(PHOTO)
    assert color.preview_frame is not None and color.preview_frame.shape[1] == PREVIEW_WORKING_WIDTH
    assert not color.scrubEnabled and color.scrubTimeText == "Photo"
    assert color.preview_current_dive is None  # no logs yet
    revision = color.previewImageSource

    color.logsText = str(logs_folder)
    assert "Error parsing broken.uddf: bad header" in capsys.readouterr().out
    assert color.preview_current_dive is not None
    assert color.preview_current_waypoint is not None
    assert color.preview_current_waypoint.timestamp >= color.preview_creation_date
    assert color.previewImageSource != revision

    _add_overlay(color)
    image = color.render_current_frame()
    assert isinstance(image, QImage) and image.width() == PREVIEW_WORKING_WIDTH
    provider = ColorPreviewImageProvider(color)
    assert provider.requestImage("frame", None, None).width() == PREVIEW_WORKING_WIDTH


def test_video_preview_scrubs_through_the_clip(color):
    color.sourceText = str(DJI_CLIP)
    assert color.scrubEnabled and color.scrubMinimum == 0 and color.scrubMaximum > 10
    assert color.scrubValue == 10 and color.scrubTimeText == "0:00:00"
    one_second = int(color.preview_video_fps) + 1
    color.onScrubChanged(one_second)
    assert color.scrubValue == one_second and color.scrubTimeText == "0:00:01"
    color.onScrubChanged(100000)  # past the end: frame unchanged
    assert color.scrubValue == one_second
    cap = color.preview_video_cap
    color.sourceText = str(PHOTO)  # the clip is let go
    assert color.preview_video_cap is None and cap is not None
    color.onScrubChanged(3)  # a photo has nothing to scrub
    assert color.scrubValue == 0


def test_unreadable_media_leaves_an_empty_preview(color, tmp_path):
    fake_video = tmp_path / "broken.mp4"
    fake_video.write_text("not a video")
    color.sourceText = str(fake_video)
    assert color.preview_frame is None
    fake_photo = tmp_path / "broken.jpg"
    fake_photo.write_text("not a photo")
    color.sourceText = str(fake_photo)
    assert color.preview_frame is None
    assert color.render_current_frame().width() == 1  # the 1x1 placeholder


def test_media_without_a_date_is_previewed_at_the_time_of_viewing(color, monkeypatch):
    def no_date(self, path):
        raise ValueError("no metadata")

    monkeypatch.setattr(cb.MetadataHandler, "get_local_creation_date", no_date)
    before = datetime.now()
    color.sourceText = str(PHOTO)
    assert color.preview_creation_date >= before
    color._sync_waypoint(5)
    assert color.preview_current_waypoint is None  # no dive matched


# --- overlays ---------------------------------------------------------------------

def test_overlay_placed_at_middle_left_is_centred_vertically(color):
    instance = color._resolve_new_color_overlay("shearwater", "perdix_2", "main", "Middle Left")
    assert instance["x"] == 0.0 and 0.0 < instance["y"] < 0.5


def test_add_overlay_reports_a_page_without_a_layout(color, monkeypatch):
    monkeypatch.setattr(cb, "resolve_template_state", lambda *a, **k: None)
    color.onAddHudBrandSelected("Shearwater")
    assert color.confirmAddHud() is False
    assert color.addHudError == "Could not resolve a layout for that choice."
    assert color.overlayLabels == []


def test_remove_overlay_clears_the_selection_and_ignores_bad_rows(color):
    instance = _add_overlay(color)
    color.color_selected_overlay_id = instance["id"]
    color.removeOverlayAtIndex(3)
    assert len(color.overlayLabels) == 1
    color.removeOverlayAtIndex(0)
    assert color.overlayLabels == [] and color.color_selected_overlay_id is None
    assert get_fields()["color_overlay_instances"] == []


def test_reload_templates_resets_the_add_overlay_picker(color):
    color.onAddHudBrandSelected("Shearwater")
    assert color.addHudComputerVisible
    color.onAddHudBrandSelected("Generic")
    color.reloadTemplates()
    assert color.addHudBrandList[color.addHudBrandIndex] == "Garmin"
    assert color.addHudError == ""
    color._selected_variant = "not_a_variant"
    assert color.addHudVariantIndex == 0


def test_overlay_with_a_missing_layout_is_skipped(color, tmp_path, capsys):
    gone = tmp_path / "gone.json"
    color.color_overlay_instances = [
        {"id": 0, "layout_path": gone, "label": "Gone", "x": 0.0, "y": 0.0, "scale": 1.0}]
    color.sourceText = str(PHOTO)
    assert color.render_current_frame().width() == PREVIEW_WORKING_WIDTH
    assert "Could not load overlay layout" in capsys.readouterr().out
    assert color._hit_test_overlay(10, 10) is None
    color._update_drag_box(color.color_overlay_instances[0])
    assert not color.dragBoxVisible


def test_overlay_draw_error_still_returns_the_frame(color, monkeypatch, capsys):
    color.sourceText = str(PHOTO)
    _add_overlay(color)

    def broken(*a, **k):
        raise RuntimeError("font missing")

    monkeypatch.setattr(cb, "draw_hud", broken)
    assert color.render_current_frame().width() == PREVIEW_WORKING_WIDTH
    assert "overlay render error" in capsys.readouterr().out


def test_drag_box_follows_a_move(color):
    instance = _add_overlay(color)
    assert not color.dragBoxVisible
    color.onPreviewDragged(1, 1)  # no drag in progress: nothing happens
    x0 = color.dragBoxX
    # press inside the overlay's box (seeded bottom-left), then drag right
    color.onPreviewPressed(20.0, cb.PREVIEW_DISPLAY_HEIGHT - 20.0)
    assert color.dragBoxVisible and color.dragBoxLabel == instance["label"]
    assert color.dragBoxW > 0 and color.dragBoxH > 0 and color.dragBoxY > 0
    color.onPreviewDragged(120.0, cb.PREVIEW_DISPLAY_HEIGHT - 20.0)
    assert color.dragBoxX > x0
    # the dragged overlay vanishing mid-drag is ignored
    saved = color.color_overlay_instances
    color.color_overlay_instances = []
    color.onPreviewDragged(200.0, 10.0)
    color.color_overlay_instances = saved
    color.onPreviewReleased()
    assert not color.dragBoxVisible
    assert get_fields()["color_overlay_instances"][0]["x"] > 0.0


def test_hit_test_without_a_preview_size_finds_nothing(color):
    color.preview_view_w = 0
    assert color._hit_test_overlay(5, 5) is None


# --- arguments ------------------------------------------------------------------

def test_arguments_carry_logs_overlays_and_switches(color, tmp_path):
    color.sourceText = str(tmp_path / "media")
    color.outputText = str(tmp_path / "out")
    color.logsText = str(tmp_path / "logs")
    _add_overlay(color)
    args = color._build_args()
    assert args[:4] == [str(tmp_path / "media"), str(tmp_path / "out"), "--logs", str(tmp_path / "logs")]
    assert args[4:6] == ["--color", "default"]
    overlays_file = Path(args[args.index("--overlays-file") + 1])
    saved = json.loads(overlays_file.read_text())
    assert len(saved) == 1 and saved[0]["scale"] == 1.0
    assert args[-2:] == ["--keep-filename", "--hw-accel"]


def test_packaged_app_runs_itself_without_python_m(color, monkeypatch, tmp_path):
    app = str(tmp_path / "UWMedia")
    monkeypatch.setattr(sys, "executable", app)
    assert color._build_command(["x"]) == [app, "x"]
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python3"))
    assert color._build_command(["x"])[1:] == ["-m", "uwmedia", "x"]


# --- the run ------------------------------------------------------------------

def _fill(color, tmp_path):
    color.sourceText = str(tmp_path / "media")
    color.outputText = str(tmp_path / "out")


def test_start_needs_source_and_output(color, processes, tmp_path):
    color.onStartClicked()
    assert color.statusText.startswith("Nothing to run") and processes == []
    color.sourceText = str(tmp_path / "media")
    color.onStartClicked()
    assert processes == [] and not color.isRunning


def test_start_runs_the_cli_and_its_output_moves_the_bars(color, processes, tmp_path):
    _fill(color, tmp_path)
    color._drag_box["visible"] = True  # a drag left over from before Start
    color.onStartClicked()
    assert color.isRunning and color.statusText == "Starting…"
    assert not color.dragBoxVisible
    (process,) = processes
    assert process.mode == QProcess.ProcessChannelMode.MergedChannels
    assert process.program == sys.executable and str(tmp_path / "out") in process.arguments

    process.say("UWMEDIA_PROGRESS 0/2 start -\nStarting parallel batch...\n\n")
    assert color.statusText == "Starting — 0 of 2 files…"
    assert (color.progressFilesDone, color.progressFilesTotal) == (0, 2)
    assert not color.progressCurrentDeterminate
    process.say("UWMEDIA_PROGRESS_ACTIVE a.mp4\nUWMEDIA_FFMPEG_PROGRESS 50 a.mp4\n")
    assert color.activeFilesCount == 1
    assert color.progressCurrentDeterminate
    assert color._batch_fraction() == pytest.approx(0.25)
    process.say("UWMEDIA_PROGRESS 1/2 done a.mp4\n")
    assert color.progressOverallFraction == 0.5
    assert color.statusText == "Processing: a.mp4"
    assert isinstance(color.timingText, str)
    process.say("UWMEDIA_PROGRESS 2/2 done b.mp4")  # no newline: read on exit
    process.exit(0)
    assert color.statusText == "Finished (exit code 0)"
    assert color.progressOverallFraction == 1.0
    assert not color.isRunning


def test_whole_files_drive_the_estimate_without_labelled_progress(color):
    color._progress_total, color._progress_done = 4, 1
    assert color._batch_fraction() == 0.25


def test_unknown_lines_are_not_progress(color):
    assert color._handle_progress_line("Generating LUT for vivid") is False


def test_output_after_the_process_is_gone_is_ignored(color, processes, tmp_path):
    _fill(color, tmp_path)
    color.onStartClicked()
    process = processes[0]
    process.exit(2)
    assert color.statusText == "Failed (exit code 2)"
    process.say("UWMEDIA_PROGRESS 0/9 start -\n")
    assert color.progressFilesTotal == 0


def test_second_click_aborts_and_kills_the_process_tree(color, processes, pkill, tmp_path):
    _fill(color, tmp_path)
    color.onStartClicked()
    color.onStartClicked()
    process = processes[0]
    assert process.killed and pkill == [["pkill", "-9", "-P", "777"]]
    assert color.isRunning  # cleared once the killed process has exited
    process.exit(9, QProcess.ExitStatus.CrashExit)
    assert color.statusText == "Failed - processing stopped (signal 9)"
    assert not color.isRunning


def test_abort_without_pkill_or_pid_still_kills(color, processes, monkeypatch, tmp_path):
    _fill(color, tmp_path)
    def no_pkill(*a, **k):
        raise FileNotFoundError("pkill")  # e.g. Windows

    monkeypatch.setattr(cb.subprocess, "run", no_pkill)
    color.onStartClicked()
    color.onStartClicked()
    assert processes[0].killed
    processes[0].killed = False
    processes[0].pid = 0
    color._kill_process_tree()
    assert processes[0].killed
    color.process = None
    color._kill_process_tree()  # nothing running: no error


def test_unreadable_file_after_a_video_resets_the_slider(color, tmp_path):
    color.sourceText = str(DJI_CLIP)
    assert color.scrubEnabled
    broken = tmp_path / "broken.mp4"
    broken.write_text("not a video")
    color.sourceText = str(broken)
    assert not color.scrubEnabled and color.scrubMaximum == 0 and color.scrubTimeText == "--"
