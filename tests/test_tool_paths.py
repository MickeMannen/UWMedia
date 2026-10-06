"""utils/tool_paths.py: which ffmpeg / ffprobe / exiftool the app runs. The
user's override from settings.json wins while the file exists; otherwise
dependency_check._find_tool searches (patched here, so no real lookup)."""
from pathlib import Path

import pytest

import utils.tool_paths as tp


@pytest.fixture
def lookup(monkeypatch):
    """Patch settings and the search; records each _find_tool call."""
    state = {"settings": {}, "calls": []}

    def fake_find(name, system, known_ffmpeg_dir=None):
        state["calls"].append((name, known_ffmpeg_dir))
        return Path(f"/found/{name}")

    monkeypatch.setattr(tp, "load_settings", lambda: state["settings"])
    monkeypatch.setattr(tp, "_find_tool", fake_find)
    return state


def test_no_override_searches(lookup):
    assert tp.get_ffmpeg_path() == Path("/found/ffmpeg")
    assert tp.get_exiftool_path() == Path("/found/exiftool")
    assert [c[0] for c in lookup["calls"]] == ["ffmpeg", "exiftool"]


def test_existing_override_wins(lookup, tmp_path):
    ffmpeg, exiftool = tmp_path / "ffmpeg", tmp_path / "exiftool"
    ffmpeg.touch()
    exiftool.touch()
    lookup["settings"].update(ffmpeg_path=str(ffmpeg), exiftool_path=str(exiftool))
    assert tp.get_ffmpeg_path() == ffmpeg
    assert tp.get_exiftool_path() == exiftool
    assert lookup["calls"] == []


def test_missing_override_falls_back_to_search(lookup, tmp_path):
    lookup["settings"]["ffmpeg_path"] = str(tmp_path / "gone" / "ffmpeg")
    assert tp.get_ffmpeg_path() == Path("/found/ffmpeg")


def test_ffprobe_looks_next_to_ffmpeg(lookup, tmp_path):
    custom = tmp_path / "bin" / "ffmpeg"
    assert tp.get_ffprobe_path(custom) == Path("/found/ffprobe")
    assert lookup["calls"] == [("ffprobe", tmp_path / "bin")]

    lookup["calls"].clear()
    tp.get_ffprobe_path()  # no ffmpeg given: resolves ffmpeg first
    assert lookup["calls"] == [("ffmpeg", None), ("ffprobe", Path("/found"))]


def test_validity_checks_need_an_existing_working_file(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(tp, "_is_valid_executable", lambda cmd: seen.append(cmd) or True)
    tool = tmp_path / "tool"
    assert not tp.is_valid_ffmpeg(None)
    assert not tp.is_valid_exiftool(tmp_path / "missing")
    assert seen == []

    tool.touch()
    assert tp.is_valid_ffmpeg(tool) and tp.is_valid_exiftool(tool)
    assert seen == [[str(tool), "-version"], [str(tool), "-ver"]]

    monkeypatch.setattr(tp, "_is_valid_executable", lambda cmd: False)
    assert not tp.is_valid_ffmpeg(tool)
