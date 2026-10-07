"""utils/dependency_check.py beyond the host-system checks in
test_dependency_check.py: the order _find_tool searches in (bundled copy,
PATH, the ffmpeg folder for ffprobe, then the per-OS fallback folders,
including WinGet's package tree), _is_valid_executable on real child
processes, and check_dependencies' PATH handling, worker-process skip and
missing-tool report (stderr and the GUI dialog). Tool lookups are pointed at
empty files in tmp_path with a fake validator, so no real tool is needed."""
import os
import sys
import types
from pathlib import Path

import pytest

import utils.dependency_check as dc


@pytest.fixture
def isolated_search(tmp_path, monkeypatch):
    """No bundled folder, nothing on PATH, home in tmp_path, and a validator
    that accepts only files under tmp_path (so the real /opt/homebrew/bin or
    /usr/bin copies on the test machine are never picked). Returns the list
    of (cmd, timeout) the validator was asked about."""
    calls = []

    def valid(cmd, timeout=3):
        calls.append((cmd, timeout))
        return Path(cmd[0]).is_relative_to(tmp_path)

    monkeypatch.setattr(dc, "bundled_bin_dir", lambda start: None)
    monkeypatch.setattr(dc.shutil, "which", lambda name: None)
    monkeypatch.setattr(dc.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    monkeypatch.setattr(dc, "_is_valid_executable", valid)
    # Windows folders from the environment: empty ones in tmp_path, so a
    # Windows runner's real WinGet tree is never walked
    for name in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMDATA"):
        monkeypatch.setenv(name, str(tmp_path / name))
    return calls


def touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("")
    return path


# --- _is_valid_executable --------------------------------------------------------

def test_is_valid_executable_uses_exit_code():
    assert dc._is_valid_executable([sys.executable, "-c", "pass"]) is True
    assert dc._is_valid_executable([sys.executable, "-c", "raise SystemExit(3)"]) is False


def test_is_valid_executable_missing_or_hanging(tmp_path):
    assert dc._is_valid_executable([str(tmp_path / "no-such-tool"), "-version"]) is False
    # A tool that hangs is killed after the timeout and counts as broken
    assert dc._is_valid_executable([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.5) is False


# --- _find_tool search order -------------------------------------------------------

def test_bundled_copy_preferred(tmp_path, monkeypatch, isolated_search):
    bundled = touch(tmp_path / "bundle" / "exiftool")
    monkeypatch.setattr(dc, "bundled_bin_dir", lambda start: bundled.parent)
    monkeypatch.setattr(dc.shutil, "which", lambda name: str(touch(tmp_path / "path" / name)))

    assert dc._find_tool("exiftool", "Linux") == bundled
    # exiftool is asked for -ver, and a first launch gets the long timeout
    assert isolated_search == [([str(bundled), "-ver"], 15)]


def test_broken_bundled_copy_falls_back_to_path(tmp_path, monkeypatch, isolated_search):
    bundled = touch(tmp_path / "bundle" / "ffmpeg.exe")
    monkeypatch.setattr(dc, "bundled_bin_dir", lambda start: bundled.parent)
    on_path = touch(tmp_path / "path" / "ffmpeg.exe")
    monkeypatch.setattr(dc.shutil, "which", lambda name: str(on_path) if name == "ffmpeg.exe" else None)
    monkeypatch.setattr(dc, "_is_valid_executable", lambda cmd, timeout=3: Path(cmd[0]) == on_path)

    assert dc._find_tool("ffmpeg", "Windows") == on_path


def test_bundled_folder_without_the_tool(tmp_path, monkeypatch, isolated_search):
    (tmp_path / "bundle").mkdir()
    monkeypatch.setattr(dc, "bundled_bin_dir", lambda start: tmp_path / "bundle")
    on_path = touch(tmp_path / "path" / "ffmpeg")
    monkeypatch.setattr(dc.shutil, "which", lambda name: str(on_path))

    assert dc._find_tool("ffmpeg", "Linux") == on_path
    assert isolated_search == [([str(on_path), "-version"], 3)]


def test_broken_tool_on_path_is_skipped(tmp_path, monkeypatch, isolated_search):
    # On PATH but outside tmp_path -> the fake validator rejects it
    monkeypatch.setattr(dc.shutil, "which", lambda name: str(tmp_path.parent / "elsewhere" / name))
    assert dc._find_tool("ffmpeg", "FreeBSD") is None


def test_ffprobe_next_to_ffmpeg(tmp_path, isolated_search):
    ffprobe = touch(tmp_path / "ffmpeg_dir" / "ffprobe")
    assert dc._find_tool("ffprobe", "Linux", known_ffmpeg_dir=ffprobe.parent) == ffprobe
    # Only ffprobe looks there
    touch(tmp_path / "ffmpeg_dir" / "exiftool")
    assert dc._find_tool("exiftool", "FreeBSD", known_ffmpeg_dir=ffprobe.parent) is None
    # Nothing in the ffmpeg folder either
    assert dc._find_tool("ffprobe", "FreeBSD", known_ffmpeg_dir=tmp_path / "empty") is None


@pytest.mark.parametrize("system, rel_dir, exec_name", [
    ("Darwin", "bin", "ffmpeg"),
    ("Darwin", ".local/bin", "exiftool"),
    ("Linux", ".local/bin", "ffprobe"),
    ("Windows", "ffmpeg/bin", "ffmpeg.exe"),
    ("Windows", "exiftool", "exiftool.exe"),
])
def test_os_fallback_folders_in_home(tmp_path, isolated_search, system, rel_dir, exec_name):
    tool = touch(tmp_path / "home" / rel_dir / exec_name)
    assert dc._find_tool(exec_name.removesuffix(".exe"), system) == tool


def test_os_fallback_ignores_a_folder_with_the_tool_name(tmp_path, isolated_search):
    (tmp_path / "home" / "bin" / "ffmpeg").mkdir(parents=True)
    assert dc._find_tool("ffmpeg", "Darwin") is None


def test_windows_program_files_from_environment(tmp_path, monkeypatch, isolated_search):
    monkeypatch.setenv("PROGRAMFILES", str(tmp_path / "Program Files"))
    tool = touch(tmp_path / "Program Files" / "exiftool" / "exiftool.exe")
    assert dc._find_tool("exiftool", "Windows") == tool


def test_windows_winget_packages(tmp_path, monkeypatch, isolated_search):
    # winget unpacks into a versioned folder deep inside Packages
    packages = tmp_path / "LocalAppData" / "Microsoft" / "WinGet" / "Packages"
    ffmpeg = touch(packages / "Gyan.FFmpeg_Microsoft.Winget.Source" / "ffmpeg-7.1-full_build" / "bin" / "ffmpeg.exe")
    exiftool = touch(packages / "OliverBetz.ExifTool" / "exiftool.exe")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))

    assert dc._find_tool("ffmpeg", "Windows") == ffmpeg
    assert dc._find_tool("exiftool", "Windows") == exiftool
    assert dc._find_tool("ffprobe", "Windows") is None


def test_nothing_found(isolated_search):
    for system in ("Darwin", "Linux", "Windows", "FreeBSD"):
        assert dc._find_tool("ffmpeg", system) is None


# --- get_installation_instructions for single tools --------------------------------

def test_instructions_only_name_the_missing_tool():
    mac = dc.get_installation_instructions(["exiftool"], "Darwin")
    assert "Missing required external dependencies: 'exiftool'" in mac
    assert "brew install exiftool" in mac and "brew install ffmpeg" not in mac

    win = dc.get_installation_instructions(["ffprobe"], "Windows")
    assert "winget install FFmpeg" in win and "ExifTool" not in win

    linux = dc.get_installation_instructions(["exiftool"], "Linux")
    assert "sudo apt update && sudo apt install libimage-exiftool-perl" in linux
    assert "sudo pacman -S perl-image-exiftool" in linux and "ffmpeg" not in linux
    assert linux.endswith("please restart the application.")


# --- check_dependencies --------------------------------------------------------------

@pytest.fixture
def fake_tools(tmp_path, monkeypatch):
    """_find_tool answers from a dict; returns (found, calls)."""
    found = {"ffmpeg": tmp_path / "ff" / "ffmpeg", "ffprobe": tmp_path / "ff" / "ffprobe",
             "exiftool": tmp_path / "et" / "exiftool"}
    calls = []

    def find(tool, system, known_ffmpeg_dir=None):
        calls.append((tool, known_ffmpeg_dir))
        return found.get(tool)

    monkeypatch.setattr(dc, "_find_tool", find)
    monkeypatch.setattr(dc.platform, "system", lambda: "Linux")
    return found, calls


def test_check_dependencies_prepends_tool_folders_to_path(tmp_path, monkeypatch, fake_tools):
    found, calls = fake_tools
    already = str(tmp_path / "et")
    monkeypatch.setenv("PATH", os.pathsep.join([already, "orig"]))

    assert dc.check_dependencies() == found
    # ffprobe is looked for next to the ffmpeg that was found (the folder is
    # passed on to exiftool too, where _find_tool ignores it)
    assert calls == [("ffmpeg", None), ("ffprobe", tmp_path / "ff"), ("exiftool", tmp_path / "ff")]
    # The ffmpeg folder is added once; the exiftool folder already was there
    assert os.environ["PATH"].split(os.pathsep) == [str(tmp_path / "ff"), already, "orig"]


def test_check_dependencies_skipped_in_worker_process(monkeypatch, fake_tools):
    _, calls = fake_tools
    monkeypatch.setattr(dc.multiprocessing, "current_process", lambda: types.SimpleNamespace(name="SpawnProcess-1"))
    assert dc.check_dependencies() == {}
    assert calls == []


def test_check_dependencies_missing_reports_on_stderr(monkeypatch, fake_tools, capsys):
    found, _ = fake_tools
    del found["ffmpeg"], found["exiftool"]
    with pytest.raises(SystemExit) as exc:
        dc.check_dependencies(is_gui=False)
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "ERROR: MISSING REQUIRED EXTERNAL DEPENDENCIES" in err
    assert "Missing required external dependencies: 'ffmpeg', 'exiftool'" in err
    assert "sudo apt install ffmpeg libimage-exiftool-perl" in err


class _FakeMessageBox:
    Critical = "critical"
    shown = []

    def setIcon(self, icon):
        self.icon = icon

    def setWindowTitle(self, title):
        self.title = title

    def setText(self, text):
        self.text = text

    def setInformativeText(self, text):
        self.info = text

    def exec(self):
        _FakeMessageBox.shown.append(self)


def _fake_qtwidgets(monkeypatch, message_box):
    apps = []
    module = types.ModuleType("PySide6.QtWidgets")
    module.QApplication = type("QApplication", (), {"instance": staticmethod(lambda: None),
                                                    "__init__": lambda self, argv: apps.append(argv)})
    module.QMessageBox = message_box
    monkeypatch.setitem(sys.modules, "PySide6.QtWidgets", module)
    return apps


def test_check_dependencies_missing_shows_gui_dialog(monkeypatch, fake_tools, capsys):
    found, _ = fake_tools
    del found["ffprobe"]
    apps = _fake_qtwidgets(monkeypatch, _FakeMessageBox)
    _FakeMessageBox.shown = []

    with pytest.raises(SystemExit):
        dc.check_dependencies(is_gui=True)
    assert len(apps) == 1  # no app yet -> one is created for the dialog
    [box] = _FakeMessageBox.shown
    assert box.icon == "critical"
    assert box.title == "Missing External Dependencies"
    assert box.text == "Required external dependency missing: ffprobe"
    assert "sudo apt update && sudo apt install ffmpeg" in box.info
    # The terminal still gets the report too
    assert "MISSING REQUIRED EXTERNAL DEPENDENCIES" in capsys.readouterr().err


def test_check_dependencies_dialog_failure_still_exits(monkeypatch, fake_tools, capsys):
    found, _ = fake_tools
    del found["exiftool"]

    class BrokenBox(_FakeMessageBox):
        def exec(self):
            raise RuntimeError("no display")

    _fake_qtwidgets(monkeypatch, BrokenBox)
    with pytest.raises(SystemExit) as exc:
        dc.check_dependencies(is_gui=True)
    assert exc.value.code == 1
    assert "Could not display GUI error dialog: no display" in capsys.readouterr().err
