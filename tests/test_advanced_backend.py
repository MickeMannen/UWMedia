"""
The Advanced page backend (uwmedia/backends/advanced_backend.py): the
persisted Debug/Summary switches, the folder and tool-path overrides (browse,
validate, save, reset) and the Tank Sensor Names window (add, rename, remove,
scan a folder of .fit logs, save to config.yaml). The file dialogs, message
boxes and the FIT reader are stubbed; settings.json and config.yaml live in
tmp_path, never the real Application Support folder.
"""
import pytest

import utils.config as config_mod
import utils.tool_paths as tool_paths
import uwmedia.backends.advanced_backend as ab
from utils.app_settings import get_fields, load_settings
from utils.config import ConfigManager, get_config, user_config_yaml_path
from utils.resource_paths import user_config_dir, user_data_dir
from uwmedia.backends.advanced_backend import AdvancedBackend


@pytest.fixture
def fresh_config(monkeypatch):
    """A new ConfigManager singleton that reads only the per-test config dir
    (not the repo's own config.yaml)."""
    monkeypatch.setattr(ConfigManager, "_instance", None)
    monkeypatch.setattr(config_mod, "bundled_config_yaml_path", lambda: None)


@pytest.fixture
def backend(settings_file, fresh_config):
    return AdvancedBackend()


@pytest.fixture
def dialogs(monkeypatch):
    """Stubbed QFileDialog/QMessageBox. Set `dirs` / `files` to what the next
    dialog returns; every call (with its start folder) and every message box
    is recorded."""
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    state = {"dir": "", "file": "", "dir_calls": [], "file_calls": [], "critical": [], "information": []}

    def get_dir(parent, title, start):
        state["dir_calls"].append((title, start))
        return state["dir"]

    def get_file(parent, title, start, *a):
        state["file_calls"].append((title, start))
        return state["file"], ""

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(get_dir))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(get_file))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda p, title, text: state["critical"].append((title, text))))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda p, title, text: state["information"].append((title, text))))
    return state


def _count(signal):
    seen = []
    signal.connect(lambda: seen.append(1))
    return seen


# ---------------------------------------------------------------- switches

def test_switches_default_off(backend):
    assert backend.debug is False
    assert backend.summary is False


def test_switches_are_saved_and_read_back(backend):
    emitted = _count(backend.switchesChanged)
    backend.debug = True
    backend.summary = True
    assert len(emitted) == 2
    assert get_fields()["debug_switch"] is True
    assert get_fields()["summary_switch"] is True

    again = AdvancedBackend()
    assert again.debug is True and again.summary is True

    again.debug = False
    assert AdvancedBackend().debug is False
    assert AdvancedBackend().summary is True


# ------------------------------------------------------- folder overrides

def test_default_locations(backend):
    assert backend.layoutsDirText == str(user_data_dir() / "layouts")
    assert backend.templatesDirText == str(user_data_dir() / "templates")
    assert backend.colorDirText == str(user_config_dir())
    assert backend.tankNamesPathText == str(user_config_yaml_path())


@pytest.mark.parametrize("kind, key, prop", [
    ("layouts", "layouts_dir", "layoutsDirText"),
    ("templates", "templates_dir", "templatesDirText"),
    ("color", "color_profiles_dir", "colorDirText"),
])
def test_choose_and_reset_a_folder(backend, dialogs, tmp_path, kind, key, prop):
    chosen = tmp_path / f"my_{kind}"
    chosen.mkdir()
    default = getattr(backend, prop)
    emitted = _count(backend.locationsChanged)

    dialogs["dir"] = str(chosen)
    backend.choosePath(kind)

    assert load_settings()[key] == str(chosen)
    assert getattr(backend, prop) == str(chosen)
    assert get_fields()[f"advanced_{kind}_dialog_dir"] == str(chosen)
    assert len(emitted) == 1

    # The next browse starts in the folder picked last time
    backend.choosePath(kind)
    assert dialogs["dir_calls"][-1][1] == str(chosen)

    backend.resetPath(kind)
    assert load_settings()[key] is None
    assert getattr(backend, prop) == default
    assert len(emitted) == 3


def test_cancelled_folder_dialog_changes_nothing(backend, dialogs, settings_file):
    emitted = _count(backend.locationsChanged)
    dialogs["dir"] = ""
    backend.choosePath("layouts")
    assert len(dialogs["dir_calls"]) == 1
    assert emitted == []
    assert load_settings()["layouts_dir"] is None
    assert not settings_file.exists()


def test_unknown_kind_is_ignored(backend, dialogs, settings_file):
    emitted = _count(backend.locationsChanged) + _count(backend.toolsChanged)
    backend.choosePath("nonsense")
    backend.resetPath("nonsense")
    assert dialogs["dir_calls"] == [] and dialogs["file_calls"] == []
    assert emitted == []
    assert not settings_file.exists()


# --------------------------------------------------------------- tool paths

@pytest.mark.parametrize("kind, key, prop, validator", [
    ("ffmpeg", "ffmpeg_path", "ffmpegPathText", "is_valid_ffmpeg"),
    ("exiftool", "exiftool_path", "exiftoolPathText", "is_valid_exiftool"),
])
def test_choose_a_valid_tool(backend, dialogs, monkeypatch, tmp_path, kind, key, prop, validator):
    tool_dir = tmp_path / "tools"
    tool_dir.mkdir()
    tool = tool_dir / kind
    tool.write_text("")
    monkeypatch.setattr(ab, validator, lambda path: str(path) == str(tool))
    emitted = _count(backend.toolsChanged)

    dialogs["file"] = str(tool)
    backend.choosePath(kind)

    assert load_settings()[key] == str(tool)
    assert getattr(backend, prop) == str(tool)
    assert get_fields()[ab.TOOL_DIR_FIELD] == str(tool_dir)
    assert dialogs["critical"] == []
    assert len(emitted) == 1

    backend.resetPath(kind)
    assert load_settings()[key] is None
    assert len(emitted) == 2


@pytest.mark.parametrize("kind, key", [("ffmpeg", "ffmpeg_path"), ("exiftool", "exiftool_path")])
def test_an_invalid_tool_is_rejected(backend, dialogs, tmp_path, kind, key):
    # A plain text file: running it with -version / -ver fails (real check)
    bogus = tmp_path / "not_a_tool.txt"
    bogus.write_text("hello")
    emitted = _count(backend.toolsChanged)

    dialogs["file"] = str(bogus)
    backend.choosePath(kind)

    assert load_settings()[key] is None
    assert len(dialogs["critical"]) == 1
    title, text = dialogs["critical"][0]
    assert title == f"Not a valid {kind} executable"
    assert str(bogus) in text
    assert emitted == []
    # The folder is still remembered for the next browse
    assert get_fields()[ab.TOOL_DIR_FIELD] == str(tmp_path)


@pytest.mark.parametrize("kind", ["ffmpeg", "exiftool"])
def test_cancelled_tool_dialog_changes_nothing(backend, dialogs, settings_file, kind):
    dialogs["file"] = ""
    backend.choosePath(kind)
    assert len(dialogs["file_calls"]) == 1
    assert dialogs["critical"] == []
    assert not settings_file.exists()


def test_tool_not_found(backend, monkeypatch):
    monkeypatch.setattr(tool_paths, "_find_tool", lambda *a, **k: None)
    assert backend.ffmpegPathText == "Not found"
    assert backend.exiftoolPathText == "Not found"


def test_tool_override_that_is_gone_falls_back(backend, monkeypatch, tmp_path):
    from utils.app_settings import update_settings

    update_settings(ffmpeg_path=str(tmp_path / "deleted_ffmpeg"))
    fallback = tmp_path / "found_on_path"
    monkeypatch.setattr(tool_paths, "_find_tool", lambda *a, **k: fallback)
    assert backend.ffmpegPathText == str(fallback)


# ------------------------------------------------------- tank sensor names

def _write_tanks(mapping):
    get_config().save_config([])
    for serial, name in mapping.items():
        get_config().set_tank_name(serial, name)


def test_tank_window_opens_with_the_saved_names(backend):
    _write_tanks({"222": "Stage", "111": "Back gas"})
    emitted = _count(backend.tankNamesChanged)
    backend.openTankNamesWindow()
    assert backend.tankWindowVisible is True
    assert backend.tankRows == [{"serial": "111", "name": "Back gas"}, {"serial": "222", "name": "Stage"}]
    assert backend.tankStatusText == ""
    backend.closeTankNamesWindow()
    assert backend.tankWindowVisible is False
    assert len(emitted) == 2


def test_add_manual_serial(backend):
    backend.newSerialText = "  333  "
    backend.addManualSerial()
    assert backend.tankRows == [{"serial": "333", "name": "Tank 333"}]
    assert backend.newSerialText == ""

    # Blank and duplicate serials are ignored
    backend.newSerialText = "   "
    backend.addManualSerial()
    backend.newSerialText = "333"
    backend.addManualSerial()
    assert backend.tankRows == [{"serial": "333", "name": "Tank 333"}]
    assert backend.newSerialText == "333"


def test_rename_and_remove_rows_then_save(backend, dialogs):
    _write_tanks({"111": "Back gas", "222": "Stage", "444": "Old"})
    backend.openTankNamesWindow()
    backend.setTankName("111", "  Left  ")
    backend.setTankName("222", "   ")        # blank -> default name on save
    backend.setTankName("999", "Not a row")  # unknown serial is ignored
    backend.removeTankRow("444")
    backend.removeTankRow("missing")         # no error
    backend.newSerialText = "555"
    backend.addManualSerial()
    locations = _count(backend.locationsChanged)

    backend.saveTankNames()

    expected = {"111": "Left", "222": "Tank 222", "555": "Tank 555"}
    assert get_config().get_tank_mapping() == expected
    assert backend.tankWindowVisible is False
    assert len(locations) == 1
    assert dialogs["information"] == [("Saved", f"Sensor names saved to:\n{user_config_yaml_path()}")]
    # Written to the per-test config.yaml, read back by a fresh manager
    ConfigManager._instance = None
    assert get_config().get_tank_mapping() == expected
    assert AdvancedBackend().tankRows == [{"serial": s, "name": n} for s, n in sorted(expected.items())]


def test_scan_logs_folder_adds_new_serials(backend, dialogs, monkeypatch, tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    # Empty stand-ins; the FIT reader is stubbed (no dive logs in the tests)
    for name in ("dive1.fit", "dive2.FIT", "notes.txt"):
        (logs / name).write_text("")
    serials = {"dive1.fit": ["111", "222"], "dive2.FIT": ["222", "333"]}
    read = []

    def fake_serials(self, path):
        read.append(path.name)
        return serials[path.name]

    monkeypatch.setattr(ab.GarminParser, "get_unique_tank_serials", fake_serials)
    _write_tanks({"111": "Back gas"})
    backend.openTankNamesWindow()

    dialogs["dir"] = str(logs)
    backend.scanLogsFolder()

    assert sorted(read) == ["dive1.fit", "dive2.FIT"]
    assert backend.tankRows == [
        {"serial": "111", "name": "Back gas"},
        {"serial": "222", "name": "Tank 222"},
        {"serial": "333", "name": "Tank 333"},
    ]
    assert backend.tankStatusText == "Found 3 sensor(s) in .fit files, added 2 new."
    assert get_fields()[ab.FIT_LOGS_DIR_FIELD] == str(logs)
    # Scanning only edits the window; nothing is saved until Save
    assert get_config().get_tank_mapping() == {"111": "Back gas"}


def test_scan_folder_without_sensors(backend, dialogs, tmp_path):
    dialogs["dir"] = str(tmp_path)
    backend.scanLogsFolder()
    assert backend.tankStatusText == "No tank sensors found in that folder."
    assert backend.tankRows == []


def test_scan_cancelled(backend, dialogs, settings_file):
    dialogs["dir"] = ""
    emitted = _count(backend.tankNamesChanged)
    backend.scanLogsFolder()
    assert emitted == []
    assert not settings_file.exists()


def test_scan_reports_an_unreadable_log(backend, dialogs, monkeypatch, tmp_path):
    (tmp_path / "broken.fit").write_text("")

    def broken(self, path):
        raise ValueError("bad FIT header")

    monkeypatch.setattr(ab.GarminParser, "get_unique_tank_serials", broken)
    dialogs["dir"] = str(tmp_path)
    backend.scanLogsFolder()
    assert dialogs["critical"] == [("Error", "Failed to scan folder: bad FIT header")]
    assert backend.tankRows == []
    assert backend.tankStatusText == ""
