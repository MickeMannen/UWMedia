"""
The Convertion page backend's run handling (uwmedia/backends/convertion_backend.py):
Start launching the CLI with the arguments the form builds, the CLI's output
moving the status line, finish and abort, and the form edges the main tests
leave out (a cancelled picker, the hardware switch kept as is, the command of
a packaged app). QProcess is replaced by a stand-in, so nothing is rendered.
"""
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QProcess

import uwmedia.backends.convertion_backend as convertion_backend
from uwmedia.backends.convertion_backend import ConvertionBackend
from utils.app_settings import get_fields


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
    ProcessChannelMode = QProcess.ProcessChannelMode
    ExitStatus = QProcess.ExitStatus

    def __init__(self, parent=None):
        self.readyReadStandardOutput = FakeSignal()
        self.finished = FakeSignal()
        self.mode = None
        self.program = None
        self.arguments = None
        self.killed = False
        self.pid = 4321
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
    monkeypatch.setattr(convertion_backend, "QProcess", make)
    return started


@pytest.fixture
def pkill(monkeypatch):
    calls = []
    monkeypatch.setattr(convertion_backend.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    return calls


@pytest.fixture
def ready(settings_file, tmp_path):
    """A source, a destination and one resolution - enough to start."""
    backend = ConvertionBackend()
    backend._source_text = str(tmp_path / "clip.mp4")
    backend._dest_text = str(tmp_path / "out")
    backend.setChecked("480p", True)
    return backend


def test_hardware_switch_is_read_from_settings_and_unchanged_value_is_not_saved(settings_file):
    backend = ConvertionBackend()
    assert backend.hwAccel is True  # default
    backend.hwAccel = True  # same value: nothing written
    assert not settings_file.exists()
    backend.hwAccel = False
    assert ConvertionBackend().hwAccel is False


def test_cancelled_source_picker_changes_nothing(settings_file, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: ""))
    backend = ConvertionBackend()
    backend.browseSource()
    backend.browseDest()
    assert backend.sourceText == "" and backend.destText == ""
    assert "convertion_source_dialog_dir" not in get_fields()


def test_preview_without_destination_lists_bare_file_names(settings_file, tmp_path):
    backend = ConvertionBackend()
    backend._source_text = str(tmp_path / "dive.mp4")
    backend.setChecked("720p", True)
    assert backend.outputPreviewText == "dive 720p.mp4"


def test_packaged_app_runs_itself_without_python_m(settings_file, monkeypatch, tmp_path):
    app = str(tmp_path / "UWMedia")
    monkeypatch.setattr(sys, "executable", app)
    assert ConvertionBackend()._build_command(["a", "b"]) == [app, "a", "b"]


def test_start_runs_the_cli_with_the_form_arguments(ready, processes, tmp_path):
    ready.onStartClicked()
    assert ready.isRunning and ready.statusText == "Starting…"
    (process,) = processes
    assert process.mode == QProcess.ProcessChannelMode.MergedChannels
    assert process.program == sys.executable
    assert process.arguments == ["-m", "uwmedia", str(tmp_path / "clip.mp4"), str(tmp_path / "out"),
                                 "--convert", "480p", "--hw-accel"]
    assert ready.progressFractionText == ""  # running, but no count yet
    assert isinstance(ready.timingText, str)


def test_cli_output_drives_status_and_progress(ready, processes):
    ready.onStartClicked()
    process = processes[0]
    process.say("UWMEDIA_PROGRESS 0/1 start -\n")
    assert ready.statusText == "Processing 0 of 1…" and ready.progressKnown
    # an ordinary line becomes the status; a line split across reads waits for its end
    process.say("Scaling to 480p\nUWMEDIA_PROGRESS 0/1 converting cl")
    assert ready.statusText == "Scaling to 480p"
    process.say("ip 480p.mp4\n\n")
    assert ready.statusText == "Processing: clip 480p.mp4"
    process.say("UWMEDIA_FFMPEG_PROGRESS 40\n")
    assert ready.progressFraction == pytest.approx(0.4)
    assert ready.progressFractionText == "0/1 · 40%"
    # the last line arrives without a newline and is read when the process ends
    process.say("UWMEDIA_PROGRESS 1/1 done clip 480p.mp4")
    assert ready.progressFraction == pytest.approx(0.4)
    process.exit(0)
    assert ready.progressFraction == 1.0
    assert ready.statusText == "Finished (exit code 0)"
    assert not ready.isRunning


def test_failed_run_reports_the_exit_code(ready, processes):
    ready.onStartClicked()
    processes[0].say("Error: unsupported codec\n")
    processes[0].exit(1)
    assert ready.statusText == "Failed (exit code 1)"
    assert not ready.isRunning


def test_output_after_the_process_is_gone_is_ignored(ready, processes):
    ready.onStartClicked()
    process = processes[0]
    process.exit(0)
    process.say("late line\n")
    assert ready.statusText == "Finished (exit code 0)"


def test_second_click_aborts_and_kills_the_process_tree(ready, processes, pkill):
    ready.onStartClicked()
    ready.onStartClicked()
    process = processes[0]
    assert ready.statusText == "Aborting…"
    assert process.killed
    assert pkill == [["pkill", "-9", "-P", "4321"]]
    assert len(processes) == 1  # no second run started
    process.exit(9, QProcess.ExitStatus.CrashExit)
    assert ready.statusText == "Failed - processing stopped (signal 9)"
    assert not ready.isRunning


def test_abort_without_pid_or_pkill_still_kills(ready, processes, monkeypatch):
    def no_pkill(*a, **k):
        raise FileNotFoundError("pkill")  # e.g. Windows

    monkeypatch.setattr(convertion_backend.subprocess, "run", no_pkill)
    ready.onStartClicked()
    ready.onStartClicked()
    assert processes[0].killed
    processes[0].killed = False
    processes[0].pid = 0
    ready.onStartClicked()
    assert processes[0].killed


def test_kill_with_no_process_does_nothing(settings_file, pkill):
    backend = ConvertionBackend()
    backend._kill_process_tree()
    assert pkill == []


def test_a_new_start_resets_the_previous_progress(ready, processes):
    ready.onStartClicked()
    processes[0].say("UWMEDIA_PROGRESS 1/1 done a.mp4\n")
    processes[0].exit(0)
    assert ready.progressKnown
    ready.onStartClicked()
    assert not ready.progressKnown and ready.progressFraction == 0.0
    assert len(processes) == 2


def test_missing_destination_or_resolution_starts_nothing(settings_file, processes, tmp_path):
    backend = ConvertionBackend()
    backend._source_text = str(tmp_path / "clip.mp4")
    backend.setChecked("480p", True)
    backend.onStartClicked()  # no destination
    assert backend.statusText.startswith("Nothing to run")
    backend._dest_text = str(Path(tmp_path))
    backend.setChecked("480p", False)
    backend.onStartClicked()  # no resolution
    assert backend.statusText.startswith("Nothing to run")
    assert processes == []
