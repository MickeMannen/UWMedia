"""
The app's entry points: uwmedia/__main__.py (CLI run vs. GUI launch, and the
Windows hidden-console relaunch) and uwmedia/app.py's main() (prunes old
working folders, loads main.qml, exits with the event loop's code, or -1
when main.qml doesn't load). The CLI, the GUI and the Windows calls are
stubbed in process; app.main() runs in a child process off screen (one
QApplication per process) and quits itself straight away.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import uwmedia.__main__ as entry
from conftest import REPO_ROOT


# ------------------------------------------------------------ main() routing

@pytest.fixture
def calls(monkeypatch):
    seen = []
    import cli_main
    import uwmedia.app

    monkeypatch.setattr(entry, "_restore_console_stdio", lambda: seen.append("stdio"))
    monkeypatch.setattr(entry, "_ignore_sigpipe", lambda: seen.append("sigpipe"))
    monkeypatch.setattr(cli_main, "main", lambda: seen.append("cli"))
    monkeypatch.setattr(uwmedia.app, "main", lambda: seen.append("gui"))
    return seen


def test_arguments_run_the_cli(calls, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["uwmedia", "in.mp4", "out", "--color"])
    monkeypatch.setattr(entry, "_should_relaunch_for_gui", lambda: pytest.fail("no GUI for a CLI run"))
    entry.main()
    assert calls == ["stdio", "sigpipe", "cli"]


def test_no_arguments_start_the_gui(calls, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["uwmedia"])
    monkeypatch.setattr(entry, "_should_relaunch_for_gui", lambda: False)
    entry.main()
    assert calls == ["gui"]


def test_gui_relaunched_without_console_returns(calls, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["uwmedia"])
    monkeypatch.setattr(entry, "_should_relaunch_for_gui", lambda: True)
    monkeypatch.setattr(entry, "_relaunch_gui_without_console_window", lambda: True)
    entry.main()
    assert calls == []


def test_gui_runs_here_when_the_relaunch_fails(calls, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["uwmedia"])
    monkeypatch.setattr(entry, "_should_relaunch_for_gui", lambda: True)
    monkeypatch.setattr(entry, "_relaunch_gui_without_console_window", lambda: False)
    entry.main()
    assert calls == ["gui"]


# ------------------------------------------------ Windows console relaunch

def test_no_relaunch_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(entry, "_windows_console_is_ours_alone", lambda: pytest.fail("not on Windows"))
    assert entry._should_relaunch_for_gui() is False


def test_no_relaunch_from_the_relaunched_copy(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv(entry._RELAUNCHED_ENV, "1")
    monkeypatch.setattr(entry, "_windows_console_is_ours_alone", lambda: True)
    assert entry._should_relaunch_for_gui() is False


@pytest.mark.parametrize("alone, expected", [(True, True), (False, False)])
def test_relaunch_only_with_a_console_of_our_own(monkeypatch, alone, expected):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv(entry._RELAUNCHED_ENV, raising=False)
    monkeypatch.setattr(entry, "_windows_console_is_ours_alone", lambda: alone)
    assert entry._should_relaunch_for_gui() is expected


def test_no_relaunch_when_the_console_check_fails(monkeypatch):
    def broken():
        raise OSError("no console API")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv(entry._RELAUNCHED_ENV, raising=False)
    monkeypatch.setattr(entry, "_windows_console_is_ours_alone", broken)
    assert entry._should_relaunch_for_gui() is False


@pytest.mark.parametrize("process_count, expected", [(1, True), (2, False)])
def test_console_is_ours_alone(monkeypatch, process_count, expected):
    import ctypes

    class Kernel32:
        def GetConsoleProcessList(self, pids, size):
            assert size == 2
            return process_count

    class WinDLL:
        kernel32 = Kernel32()

    monkeypatch.setattr(ctypes, "windll", WinDLL(), raising=False)
    assert entry._windows_console_is_ours_alone() is expected


@pytest.fixture
def popen(monkeypatch):
    seen = []

    def fake_popen(cmd, env, creationflags):
        seen.append({"cmd": cmd, "env": env, "flags": creationflags})

    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    return seen


@pytest.mark.parametrize("executable, module_args", [
    (os.path.join("C:", "Python", "python.exe"), ["-m", "uwmedia"]),   # source checkout
    (os.path.join("C:", "Programs", "uwmedia", "UWMedia.exe"), []),    # packaged app
])
def test_relaunch_starts_a_hidden_copy(popen, monkeypatch, executable, module_args):
    monkeypatch.setattr(sys, "executable", executable)
    monkeypatch.delenv(entry._RELAUNCHED_ENV, raising=False)
    assert entry._relaunch_gui_without_console_window() is True
    assert len(popen) == 1
    assert popen[0]["cmd"] == [executable, *module_args]
    assert popen[0]["env"][entry._RELAUNCHED_ENV] == "1"
    assert popen[0]["flags"] == subprocess.CREATE_NO_WINDOW
    assert entry._RELAUNCHED_ENV not in os.environ  # only the child's env


def test_relaunch_failure_returns_false(monkeypatch):
    def failing(*a, **k):
        raise OSError("cannot start")
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(subprocess, "Popen", failing)
    assert entry._relaunch_gui_without_console_window() is False


def test_restore_console_stdio_survives_a_stream_without_reconfigure(monkeypatch):
    class Plain:
        pass
    plain = Plain()
    monkeypatch.setattr(sys, "__stdout__", plain)
    monkeypatch.setattr(sys, "stdout", plain)
    monkeypatch.setattr(sys, "__stderr__", None)  # leave pytest's stderr capture alone
    entry._restore_console_stdio()  # no reconfigure(): ignored, not raised
    assert sys.stdout is plain


def test_python_m_uwmedia_runs_the_cli():
    result = subprocess.run([sys.executable, "-m", "uwmedia", "--help"], cwd=REPO_ROOT,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "usage:" in result.stdout
    assert "--logs" in result.stdout


# ---------------------------------------------------------- uwmedia.app.main

CHILD = r"""
import sys
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
import uwmedia.app as app_mod

class QuittingApp(QApplication):
    def exec(self):
        def report_and_quit():
            print("WINDOWS", len(self.topLevelWindows()), flush=True)
            self.exit(7)
        QTimer.singleShot(300, report_and_quit)
        return super().exec()

app_mod.QApplication = QuittingApp
if len(sys.argv) > 1:
    app_mod.QML_MAIN = Path(sys.argv[1])
try:
    app_mod.main()
except SystemExit as e:
    print("EXIT", e.code, flush=True)
"""


def _run_app(*args):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    return subprocess.run([sys.executable, "-c", CHILD, *map(str, args)], cwd=REPO_ROOT, env=env,
                          capture_output=True, text=True, timeout=120)


def test_app_main_loads_the_window_prunes_old_temp_and_exits_with_the_loop_code():
    import utils.resource_paths as rp

    temp_base = rp._cache_base() / rp.TEMP_DIR_NAME
    old, fresh = temp_base / "uwmedia_old", temp_base / "uwmedia_fresh"
    old.mkdir(parents=True)
    fresh.mkdir()
    two_days_ago = time.time() - 2 * 24 * 3600
    os.utime(old, (two_days_ago, two_days_ago))

    result = _run_app()
    out = result.stdout + result.stderr
    assert "EXIT 7" in result.stdout, out
    windows = [line for line in result.stdout.splitlines() if line.startswith("WINDOWS ")]
    assert windows and int(windows[0].split()[1]) >= 1, out
    assert not old.exists()
    assert fresh.exists()


def test_app_main_exits_with_minus_one_when_main_qml_fails(tmp_path):
    broken = tmp_path / "broken.qml"
    broken.write_text("import QtQuick\nItem {\n")
    result = _run_app(broken)
    out = result.stdout + result.stderr
    assert "EXIT -1" in result.stdout, out
    assert "WINDOWS" not in result.stdout
