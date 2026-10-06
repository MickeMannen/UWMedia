import shutil

import pytest

from conftest import SONY_CLIP, run_cli


@pytest.mark.render
def test_convert_video_resolution(tmp_path):
    """Scenario 1: Test --convert on a video file. Confirms the 1080p output file and folder."""
    # A neutral name: the fixture's own "_720p" would be swapped for the
    # target resolution (see test_convert_resolution_replacement_naming).
    source_video = tmp_path / "dive_clip.mp4"
    shutil.copy2(SONY_CLIP, source_video)

    output_subfolder = tmp_path / "test_convert_1080p"
    result = run_cli(source_video, output_subfolder, "--convert", "1080p")
    assert result.returncode == 0, f"Command failed: {result.stderr}"

    # The --convert command places the converted resolution file inside output_dir with the pattern: [source_stem] [resolution].[ext]
    expected_file = output_subfolder / f"{source_video.stem} 1080p{source_video.suffix.lower()}"
    assert expected_file.exists(), f"Converted file was not created: {expected_file}"


@pytest.mark.parametrize("source, res_name, expected", [
    ("filename 4k.mp4", "1080p", "filename 1080p.mp4"),
    ("filename_4k.mp4", "1080p", "filename 1080p.mp4"),
    ("filename 4K.MP4", "720p", "filename 720p.mp4"),
    ("filename_4K.MP4", "720p", "filename 720p.mp4"),
    ("dive_clip.mp4", "1080p", "dive_clip 1080p.mp4"),
])
def test_convert_resolution_replacement_naming(source, res_name, expected):
    """'_4k' or ' 4k' (case insensitive) is replaced by the target resolution -
    the one naming rule both --convert and the Convertion page use."""
    from pathlib import Path

    from utils.convert_naming import convert_output_filename

    assert convert_output_filename(Path(source), res_name) == expected
