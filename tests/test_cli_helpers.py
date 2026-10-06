"""cli_main.py helpers that the render tests only pass through:
get_unique_path (no overwrites) and print_summary (the end-of-run table)."""
import re

from cli_main import get_unique_path, print_summary


# --- get_unique_path ---------------------------------------------------------

def test_unique_path_free_name_is_kept_with_lowercase_extension(tmp_path):
    assert get_unique_path(tmp_path / "clip.MP4") == tmp_path / "clip.mp4"


def test_unique_path_counts_up_past_existing_files(tmp_path):
    (tmp_path / "clip.mp4").touch()
    (tmp_path / "clip_1.mp4").touch()
    assert get_unique_path(tmp_path / "clip.MP4") == tmp_path / "clip_2.mp4"


def test_unique_path_keeps_extension_case_for_moved_originals(tmp_path):
    assert get_unique_path(tmp_path / "DSC03491.JPG", lower_suffix=False) == tmp_path / "DSC03491.JPG"
    (tmp_path / "DSC03491.JPG").touch()
    assert get_unique_path(tmp_path / "DSC03491.JPG", lower_suffix=False) == tmp_path / "DSC03491_1.JPG"


# --- print_summary -----------------------------------------------------------

_ANSI = re.compile(r"\033\[[0-9;]*m")


def _summary(capsys, stats):
    print_summary(stats)
    return _ANSI.sub("", capsys.readouterr().out)


def test_summary_lists_stages_and_totals(capsys):
    out = _summary(capsys, [{
        "file": "dive_01.mp4", "type": "video",
        "stages": [
            {"name": "Overlay render", "time": 3.256, "fps": 41.04},
            {"name": "Metadata", "time": 0.1, "fps": None},
        ],
        "total_time": 3.356, "overall_fps": 39.8,
    }])
    assert "File: dive_01.mp4 (Video)" in out
    assert re.search(r"Overlay render\s+- Time: 3\.26s \(41\.0 fps\)", out)
    assert re.search(r"Metadata\s+- Time: 0\.10s\n", out)
    assert "Total Time: 3.36s | Overall FPS: 39.8 fps" in out


def test_summary_skipped_failed_and_empty_entries(capsys):
    out = _summary(capsys, [
        None,
        {"file": "a.mp4", "skipped": True},
        {"file": "b.jpg", "error": "no dive matched"},
        {"file": "c.jpg", "type": "photo", "total_time": 0.5, "overall_fps": 0},
    ])
    assert "File: a.mp4 - Skipped (Target exists)" in out
    assert "File: b.jpg - Failed: no dive matched" in out
    assert "File: c.jpg (Photo)" in out
    assert "Total Time: 0.50s\n" in out  # no FPS for a zero rate
    assert out.count("File:") == 3
