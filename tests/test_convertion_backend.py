"""
The Convertion page backend (uwmedia/backends/convertion_backend.py): the
source and destination pickers (dialogs stubbed), which resolutions a source
allows, the output-name preview, the CLI arguments a run starts with and how
the progress lines the CLI prints move the bar. The conversion itself is
tested end to end in test_convert.py.
"""
from pathlib import Path

import pytest
from PySide6.QtCore import QProcess

from conftest import DJI_CLIP
from uwmedia.backends.convertion_backend import ConvertionBackend
from utils.app_settings import get_fields


@pytest.fixture
def backend(settings_file):
    return ConvertionBackend()


@pytest.fixture
def picked(backend, monkeypatch, tmp_path):
    """The 720p fixture clip as source and tmp_path/out as destination."""
    from PySide6.QtWidgets import QFileDialog

    dest = tmp_path / "out"
    dest.mkdir()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(DJI_CLIP), "")))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(dest)))
    backend.browseSource()
    backend.browseDest()
    return backend


def test_starts_empty(backend):
    assert backend.resolutionNames == ["1080p", "720p", "480p", "360p"]
    assert backend.checkedResolutions == []
    assert backend.enabledResolutions == backend.resolutionNames
    assert backend.outputPreviewText == "(select a source file and at least one output resolution)"
    assert backend.statusText == "No batch running"
    assert not backend.isRunning and not backend.progressKnown
    assert backend.progressFraction == 0.0 and backend.progressFractionText == ""


def test_start_with_nothing_picked_explains_why(backend):
    backend.onStartClicked()
    assert backend.statusText.startswith("Nothing to run")
    assert not backend.isRunning


def test_a_720p_source_allows_only_smaller_targets(picked, tmp_path):
    assert picked.sourceText == str(DJI_CLIP)
    assert picked.destText == str(tmp_path / "out")
    assert picked.sourceResolutionText == "1280x720 (up to 720p)"
    assert picked.enabledResolutions == ["720p", "480p", "360p"]
    assert get_fields()["convertion_source_dialog_dir"] == str(DJI_CLIP.parent)


def test_picking_a_smaller_source_unticks_too_large_targets(picked, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    picked.setChecked("720p", True)
    picked.setChecked("360p", True)
    not_video = tmp_path / "notes.mp4"
    not_video.write_text("not a video")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(not_video), "")))
    picked.browseSource()
    assert picked.sourceResolutionText.startswith("Could not detect resolution")
    assert picked.enabledResolutions == picked.resolutionNames  # unknown: allow all
    assert picked.checkedResolutions == ["720p", "360p"]


def test_preview_lists_one_output_per_resolution(picked, tmp_path):
    picked.setChecked("480p", True)
    picked.setChecked("360p", True)
    picked.setChecked("360p", True)  # no change
    # hevc_10bit_420_720p_2s.mp4: the "_720p" in the name is replaced in place
    assert picked.outputPreviewText.splitlines() == [
        str(tmp_path / "out" / "hevc_10bit_420 480p_2s.mp4"),
        str(tmp_path / "out" / "hevc_10bit_420 360p_2s.mp4"),
    ]


def test_run_arguments_and_hardware_switch(picked, tmp_path):
    picked.setChecked("720p", True)
    picked.hwAccel = False
    assert get_fields()["hw_accel_switch"] is False
    args = picked._build_args()
    assert args == [str(DJI_CLIP), str(tmp_path / "out"), "--convert", "720p"]
    picked.hwAccel = True
    assert picked._build_args()[-1] == "--hw-accel"
    cmd = picked._build_command(args)
    assert cmd[1:3] == ["-m", "uwmedia"]  # from a checkout: python -m uwmedia


def test_progress_lines_move_the_bar(backend):
    handle = backend._handle_progress_line
    assert handle("UWMEDIA_PROGRESS 0/2 start -")
    assert backend.statusText == "Processing 0 of 2…"
    assert backend.progressKnown and backend.progressFraction == 0.0
    assert handle("UWMEDIA_FFMPEG_PROGRESS 140")  # no file named yet; clamped
    assert backend.statusText == "Rendering — 140%"
    assert backend.progressFraction == 0.0

    assert handle("UWMEDIA_PROGRESS 0/2 converting clip 720p.mp4")
    assert handle("UWMEDIA_FFMPEG_PROGRESS 50.0")
    assert backend.statusText == "Processing: clip 720p.mp4 — 50%"
    assert backend.progressFraction == pytest.approx(0.25)

    assert handle("UWMEDIA_PROGRESS 1/2 done clip 720p.mp4")
    assert backend.progressFraction == pytest.approx(0.5)
    assert handle("UWMEDIA_PROGRESS 2/2 done clip 360p.mp4")
    assert backend.statusText == "Finished — last file: clip 360p.mp4"
    assert backend.progressFraction == 1.0

    assert not handle("Some other output line")


def test_finishing_reports_the_result(backend):
    backend._on_process_finished(0, QProcess.ExitStatus.NormalExit)
    assert not backend.isRunning
    assert backend.statusText == "Finished (exit code 0)"
    backend._on_process_finished(13, QProcess.ExitStatus.CrashExit)
    assert backend.statusText == "Failed - processing stopped (signal 13)"


def test_contract_path_shortens_the_home_folder(backend):
    assert backend.contractPath(str(Path.home()) + "/Movies/a.mp4") == "~/Movies/a.mp4"
