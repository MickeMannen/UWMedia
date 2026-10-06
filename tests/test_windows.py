"""Windows-only checks: Pillow photo saving, NVENC / D3D11 hardware
acceleration, paths with spaces, exiftool and --convert. Skipped on other
platforms. They use the small fixture media in tests/fixtures."""
import shutil
import sys

import pytest

from conftest import DJI_CLIP, PHOTO, run_cli

pytestmark = [pytest.mark.windows,
              pytest.mark.skipif(sys.platform != "win32", reason="Windows specific test suite")]

RAW_PHOTO = PHOTO


@pytest.fixture
def short_video():
    """The 2 s HEVC fixture clip (tests/fixtures/README.md)."""
    return DJI_CLIP


@pytest.mark.render
def test_windows_photo_pillow_processing(tmp_path):
    """Photo processing uses Pillow on Windows, with no PIL errors or cv2 fallbacks."""
    assert RAW_PHOTO.exists()
    out_photo = tmp_path / "photo_win_out.jpg"
    res = run_cli(RAW_PHOTO, out_photo, "--color")
    assert res.returncode == 0, f"Photo processing failed: {res.stderr}"
    assert out_photo.exists()
    assert "No module named 'PIL'" not in res.stderr
    assert "Error saving image with PIL" not in res.stderr


@pytest.mark.render
def test_windows_hw_accel_nvenc_color(tmp_path, short_video):
    """Video color correction with --hw-accel, without D3D11 / DXVA2 errors."""
    out_video = tmp_path / "vid_win_hw.mp4"
    res = run_cli(short_video, out_video, "--color", "--hw-accel")
    assert res.returncode == 0, f"HW accelerated video processing failed: {res.stderr}"
    assert out_video.exists()
    assert "Failed setup for format d3d11" not in res.stderr
    assert "Invalid setup for format dxva2_vld" not in res.stderr


@pytest.mark.render
def test_windows_path_handling_and_escaping(tmp_path):
    """Paths with spaces, drive letters (C:\\...) and --move-original."""
    space_dir = tmp_path / "Path With Spaces"
    space_dir.mkdir()
    src_copy = space_dir / "Test Photo Space.JPG"
    shutil.copy2(RAW_PHOTO, src_copy)
    out_dir = tmp_path / "Output Directory"
    out_dir.mkdir()
    orig_dir = tmp_path / "Originals Backup"
    orig_dir.mkdir()

    res = run_cli(src_copy, out_dir, "--color", "--filename-format", "Test_Photo_Space",
                  "--move-original", orig_dir)
    assert res.returncode == 0, f"Path with spaces processing failed: {res.stderr}"

    expected_out = out_dir / "Test_Photo_Space.jpg"
    expected_moved = orig_dir / "Test Photo Space.JPG"
    assert expected_out.exists(), f"Output file missing: {expected_out}"
    assert expected_moved.exists(), f"Original file not moved to: {expected_moved}"
    assert not src_copy.exists(), "Source file was not moved from original location"


@pytest.mark.render
def test_windows_exiftool_metadata_tags(tmp_path):
    """ExifTool metadata modification and timezone fixing."""
    test_photo = tmp_path / "meta_win_test.jpg"
    shutil.copy2(RAW_PHOTO, test_photo)
    res = run_cli(test_photo, tmp_path / "meta_win_out.jpg", "--force-media-tz", "+8", "--fix-tz")
    assert res.returncode == 0, f"ExifTool timezone fix failed: {res.stderr}"


@pytest.mark.render
def test_windows_convert_resolution(tmp_path, short_video):
    """Resolution conversion (--convert 1080p)."""
    out_subfolder = tmp_path / "convert_1080p_out"
    res = run_cli(short_video, out_subfolder, "--convert", "1080p")
    assert res.returncode == 0, f"Resolution conversion failed: {res.stderr}"
    expected_file = out_subfolder / f"{short_video.stem} 1080p{short_video.suffix.lower()}"
    assert expected_file.exists(), f"Converted file missing: {expected_file}"


def test_windows_hud_rendering_and_fonts():
    """The HUD renderer draws with Pillow TrueType fonts on Windows."""
    import numpy as np
    from datetime import datetime
    from gui.hud_renderer import draw_hud
    from models.dive import Waypoint

    dummy_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    wp = Waypoint(timestamp=datetime.now(), depth=15.5, temp=24.0, time_since_start=120)
    dummy_layout = {
        "hud_skin": {
            "type": "shape", "width": 400, "height": 200,
            "linked_elements": [{"type": "text", "field": "depth", "rel_x": 0.1, "rel_y": 0.1, "font_size": 24}],
        }
    }
    draw_hud(dummy_frame, layout=dummy_layout, waypoint=wp)
    assert dummy_frame.sum() > 0, "HUD renderer produced empty frame"
