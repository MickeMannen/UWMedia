"""
The Overlay Generator page backend (uwmedia/backends/overlay_generator_backend.py):
form fields saved to and restored from settings, the browse pickers (dialogs
stubbed), the brand/computer/page cascade after a template reload, the
Custom layout entry, and the batch run - one CLI run per overlay, started,
fed output, finished, failed or aborted - with QProcess replaced by a
stand-in, so nothing is rendered.
"""
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QProcess

import uwmedia.backends.overlay_generator_backend as og
from utils.app_settings import get_fields, set_field
from uwmedia.backends.overlay_generator_backend import (
    LAYOUT_CUSTOM,
    RENDER_LOG_FORMAT_PRESETS,
    OverlayGeneratorBackend,
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
        self.pid = 555
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
    monkeypatch.setattr(og, "QProcess", make)
    return started


@pytest.fixture
def pkill(monkeypatch):
    calls = []
    monkeypatch.setattr(og.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    return calls


@pytest.fixture
def gen(isolated_template_roots, settings_file):
    return OverlayGeneratorBackend()


@pytest.fixture
def folder_batch(gen, tmp_path):
    """Source, logs and output folders plus two custom-layout overlays."""
    for name in ("media", "logs", "out"):
        (tmp_path / name).mkdir()
    gen.sourceText = str(tmp_path / "media")
    gen.logsText = str(tmp_path / "logs")
    gen.outputText = str(tmp_path / "out")
    gen.onBrandSelected(LAYOUT_CUSTOM)
    for name in ("first.json", "second.json"):
        gen.customPathText = str(tmp_path / name)
        gen.addOverlay()
    return gen


# --- form fields and persistence ---------------------------------------------

def test_form_fields_are_saved_and_restored(gen, tmp_path):
    gen.sourceText = str(tmp_path / "media")
    gen.outputText = str(tmp_path / "out")
    gen.logsText = str(tmp_path / "logs")
    gen.skipExisting = True
    gen.hwAccel = False
    gen.filenameFormat = RENDER_LOG_FORMAT_PRESETS[0][0]
    gen.logFileMode = True
    gen.logFileText = str(tmp_path / "dive.uddf")

    again = OverlayGeneratorBackend()
    assert (again.sourceText, again.outputText, again.logsText) == (
        str(tmp_path / "media"), str(tmp_path / "out"), str(tmp_path / "logs"))
    assert again.skipExisting is True and again.hwAccel is False
    assert again.filenameFormat == RENDER_LOG_FORMAT_PRESETS[0][0]
    assert again.filenameFormatList == [label for label, _ in RENDER_LOG_FORMAT_PRESETS]
    assert again.logFileMode is True and again.logFileText == str(tmp_path / "dive.uddf")


def test_setting_a_field_to_its_current_value_saves_nothing(gen, settings_file):
    gen.sourceText = ""
    gen.outputText = ""
    gen.logsText = ""
    gen.logFileText = ""
    gen.logFileMode = False
    gen.skipExisting = False
    gen.hwAccel = True
    gen.filenameFormat = gen.filenameFormat
    gen.overlaySize = gen.overlaySize
    gen.overlaySize = "8K"  # not a choice
    gen.customPathText = ""
    assert not settings_file.exists()
    assert gen.overlaySize == "4K (2×)"


def test_legacy_filename_format_label_is_mapped(isolated_template_roots, settings_file):
    set_field("hudpage_filename_format_select", "source_filename_hudname")
    assert OverlayGeneratorBackend().filenameFormat == RENDER_LOG_FORMAT_PRESETS[0][0]


def test_contract_path_shortens_the_home_folder(gen):
    assert gen.contractPath(str(Path.home()) + "/Movies") == "~/Movies"


# --- browse pickers ------------------------------------------------------------

def test_pickers_fill_the_fields_and_remember_their_folder(gen, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    folder = tmp_path / "picked"
    folder.mkdir()
    picked_file = folder / "thing.json"
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(picked_file), "")))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(folder)))

    gen.browseSourceFile()
    assert gen.sourceText == str(picked_file)
    gen.browseSourceFolder()
    assert gen.sourceText == str(folder)
    gen.browseOutputFile()
    assert gen.outputText == str(picked_file)
    gen.browseOutputFolder()
    assert gen.outputText == str(folder)
    gen.browseLogsFolder()
    assert gen.logsText == str(folder)
    gen.browseLogFile()
    assert gen.logFileText == str(picked_file)
    gen.browseCustomPathFile()
    assert gen.customPathText == str(picked_file)
    gen.browseCustomPathFolder()
    assert gen.customPathText == str(folder)
    fields = get_fields()
    for key in ("hudpage_source_dialog_dir", "hudpage_output_dialog_dir",
                "hudpage_logs_dialog_dir", "hudpage_custom_path_dialog_dir"):
        assert fields[key] == str(folder)


def test_cancelled_pickers_change_nothing(gen, monkeypatch, settings_file):
    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: ""))
    for browse in (gen.browseSourceFile, gen.browseSourceFolder, gen.browseOutputFile, gen.browseOutputFolder,
                   gen.browseLogsFolder, gen.browseLogFile, gen.browseCustomPathFile, gen.browseCustomPathFolder):
        browse()
    assert (gen.sourceText, gen.outputText, gen.logsText, gen.logFileText, gen.customPathText) == ("",) * 5
    assert not settings_file.exists()


# --- cascade -------------------------------------------------------------------

def test_reload_keeps_the_current_brand_computer_and_page(gen):
    gen.onBrandSelected("Shearwater")
    gen.onComputerSelected("Teric")
    page = gen.pageList[-1]
    gen.onPageSelected(page)
    gen.reloadTemplates()
    assert gen.brandList[gen.brandIndex] == "Shearwater"
    assert gen.computerList[gen.computerIndex] == "Teric"
    assert gen.pageList[gen.pageIndex] == page
    assert gen.computerVisible


def test_reload_falls_back_to_the_first_brand_when_the_current_one_is_gone(gen, monkeypatch):
    gen.onBrandSelected("Shearwater")
    full = og.list_templates()
    monkeypatch.setattr(og, "list_templates", lambda: {k: v for k, v in full.items() if k != "shearwater"})
    gen.reloadTemplates()
    assert "Shearwater" not in gen.brandList
    assert gen.brandList[gen.brandIndex] == "Garmin"
    assert gen.computerList and gen.pageList


def test_custom_entry_hides_the_cascade_and_survives_a_reload(gen):
    gen.onBrandSelected(LAYOUT_CUSTOM)
    assert gen.isCustom and not gen.computerVisible and not gen.variantVisible
    gen.reloadTemplates()
    assert gen.isCustom and gen.brandList[gen.brandIndex] == LAYOUT_CUSTOM


def test_unknown_variant_choice_is_ignored(gen):
    before = gen.variantIndex
    gen.onVariantSelected("Twelve tanks")
    assert gen.variantIndex == before


# --- overlay list ----------------------------------------------------------------

def test_custom_layout_is_added_by_its_file_name(gen, tmp_path):
    gen.onBrandSelected(LAYOUT_CUSTOM)
    gen.addOverlay()  # no path yet: nothing added
    assert gen.overlayLabels == []
    gen.customPathText = str(tmp_path / "my_hud.json")
    gen.addOverlay()
    assert gen.overlayLabels == ["my_hud"]
    assert gen.selected_overlays[0]["layout_path"] == tmp_path / "my_hud.json"


def test_nothing_is_added_without_a_resolvable_page(gen, monkeypatch):
    gen._selected_page_id = None
    gen.addOverlay()
    assert gen.overlayLabels == []
    gen._selected_page_id = "no_such_page"
    gen.addOverlay()
    assert gen.overlayLabels == []
    gen.onBrandSelected("Shearwater")
    monkeypatch.setattr(og, "resolve_template_state", lambda *a, **k: None)
    gen.addOverlay()
    assert gen.overlayLabels == []


def test_remove_overlay_ignores_rows_out_of_range(folder_batch):
    folder_batch.removeOverlayAtIndex(5)
    folder_batch.removeOverlayAtIndex(-1)
    assert folder_batch.overlayLabels == ["first", "second"]
    folder_batch.removeOverlayAtIndex(0)
    assert folder_batch.overlayLabels == ["second"]


# --- arguments --------------------------------------------------------------------

def test_hud_arguments_follow_the_form(gen, tmp_path):
    gen.sourceText = str(tmp_path / "media")
    gen.outputText = str(tmp_path / "out")
    gen.logsText = str(tmp_path / "logs")
    gen.skipExisting = True
    gen.filenameFormat = RENDER_LOG_FORMAT_PRESETS[0][0]
    layout = tmp_path / "hud.json"
    assert gen._build_hud_args(layout) == [
        str(tmp_path / "media"), str(tmp_path / "out"), "--logs", str(tmp_path / "logs"),
        "--layout", str(layout), "--render-video-log", "--no-overwrite",
        "--render-log-filename-format", "{filename}_{hud}", "--overlay-size", "4k", "--hw-accel",
    ]


def test_packaged_app_runs_itself_without_python_m(gen, monkeypatch, tmp_path):
    app = str(tmp_path / "UWMedia")
    monkeypatch.setattr(sys, "executable", app)
    assert gen._build_command(["x"]) == [app, "x"]


# --- the batch run -----------------------------------------------------------------

def test_start_runs_one_cli_per_overlay_in_turn(folder_batch, processes, tmp_path):
    folder_batch.onStartClicked()
    assert folder_batch.isRunning
    assert folder_batch.overlayProgressText == "Overlay 1 of 2: first"
    assert folder_batch.statusText == "Starting…"
    first = processes[0]
    assert first.mode == QProcess.ProcessChannelMode.MergedChannels
    assert first.program == sys.executable
    assert first.arguments[:4] == ["-m", "uwmedia", str(tmp_path / "media"), str(tmp_path / "out")]
    assert str(tmp_path / "first.json") in first.arguments

    first.say("UWMEDIA_PROGRESS 0/1 start -\nMatched dive at 10:00\n\n")
    assert folder_batch.statusText == "Matched dive at 10:00"
    first.say("UWMEDIA_PROGRESS_ACTIVE clip.mp4\nUWMEDIA_FFMPEG_PROGRESS 50\n")
    assert folder_batch.currentProgress == pytest.approx(0.5)
    assert folder_batch.totalProgress == pytest.approx(0.25)
    assert isinstance(folder_batch.timingText, str)
    first.say("UWMEDIA_PROGRESS 1/1 done clip.mp4")  # no newline: read on exit
    first.exit(0)

    assert len(processes) == 2
    assert folder_batch.overlayProgressText == "Overlay 2 of 2: second"
    second = processes[1]
    assert str(tmp_path / "second.json") in second.arguments
    second.exit(0)
    assert not folder_batch.isRunning
    assert folder_batch.statusText == "Done"
    assert folder_batch.overlayProgressText == ""
    assert not folder_batch.progressKnown


def test_empty_source_folder_is_reported(folder_batch, processes):
    folder_batch.onStartClicked()
    processes[0].say("UWMEDIA_PROGRESS 0/0 start -\n")
    assert folder_batch.statusText == "No files found in the Source folder"


def test_late_output_after_the_run_is_ignored(folder_batch, processes):
    folder_batch.onStartClicked()
    process = processes[0]
    folder_batch.process = None
    process.say("Something late\n")
    assert folder_batch.statusText == "Starting…"


def test_a_crashed_run_is_named_in_the_final_status(folder_batch, processes):
    folder_batch.onStartClicked()
    processes[0].exit(11, QProcess.ExitStatus.CrashExit)
    processes[1].exit(0)
    assert folder_batch.statusText == (
        "Done - 1 of 2 overlays failed: first (Failed - processing stopped (signal 11))")


def test_second_click_aborts_the_batch(folder_batch, processes, pkill):
    folder_batch.onStartClicked()
    folder_batch.onStartClicked()
    process = processes[0]
    assert folder_batch.statusText == "Aborting…"
    assert process.killed and pkill == [["pkill", "-9", "-P", "555"]]
    process.exit(9, QProcess.ExitStatus.CrashExit)
    assert len(processes) == 1  # the second overlay never starts
    assert folder_batch.statusText == "Aborted"
    assert not folder_batch.isRunning


def test_abort_without_pkill_or_pid_still_kills(folder_batch, processes, monkeypatch):
    def no_pkill(*a, **k):
        raise FileNotFoundError("pkill")  # e.g. Windows

    monkeypatch.setattr(og.subprocess, "run", no_pkill)
    folder_batch.onStartClicked()
    folder_batch.onStartClicked()
    assert processes[0].killed
    processes[0].killed = False
    processes[0].pid = 0
    folder_batch._kill_process_tree()
    assert processes[0].killed
    folder_batch.process = None
    folder_batch._kill_process_tree()  # nothing running: no error


def test_log_file_mode_renders_the_log_for_each_overlay(gen, processes, tmp_path):
    log = tmp_path / "dive.uddf"
    log.write_text("<uddf/>")
    gen.outputText = str(tmp_path / "out")
    gen.logFileText = str(log)
    gen.logFileMode = True
    gen.onBrandSelected(LAYOUT_CUSTOM)
    gen.customPathText = str(tmp_path / "hud.json")
    gen.addOverlay()
    gen.onStartClicked()
    (process,) = processes
    assert process.arguments[2:7] == [str(tmp_path / "out"), "--render-log", str(log),
                                      "--layout", str(tmp_path / "hud.json")]
    assert gen.currentProgressText == "Rendering dive.uddf - 0 %"
    gen.logFileMode = False  # flipping the switch mid-batch changes nothing
    assert gen._log_mode
    process.exit(0)
    assert gen.statusText == "Done"


def test_log_file_mode_needs_a_log_an_output_and_an_overlay(gen, processes, tmp_path):
    gen.logFileMode = True
    gen.onStartClicked()
    assert gen.statusText.startswith("Nothing to run: select a log file")
    assert processes == []
