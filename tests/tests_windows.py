import os
import sys
import shutil
import subprocess
import pytest
from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).parent.parent
TEST_DATA_DIR = BASE_DIR / "test_data"
RESULTS_DIR = TEST_DATA_DIR / "test_results"
RAW_VIDEO = TEST_DATA_DIR / "DJI_20260626153257_0011_D_A001.MP4"
SHORT_VIDEO = TEST_DATA_DIR / "DJI_20260626153257_0011_D_A001_10s.MP4"
RAW_PHOTO = TEST_DATA_DIR / "DJI_20260626173304_0026_D_A001.JPG"


def ensure_short_video():
    """Ensure a shortened 10-second test video exists with all original metadata copied."""
    if SHORT_VIDEO.exists() and SHORT_VIDEO.stat().st_size > 0:
        return SHORT_VIDEO
    
    assert RAW_VIDEO.exists(), f"Source video not found at {RAW_VIDEO}"
    
    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
    cmd = [
        ffmpeg_bin, "-y",
        "-ss", "0", "-t", "10",
        "-i", str(RAW_VIDEO),
        "-c", "copy",
        "-map", "0:v:0", "-map", "0:a?",
        "-map_metadata", "0",
        "-movflags", "+faststart+use_metadata_tags",
        str(SHORT_VIDEO)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"Failed to generate 10s short video: {res.stderr}"
    assert SHORT_VIDEO.exists() and SHORT_VIDEO.stat().st_size > 0
    return SHORT_VIDEO


@pytest.fixture(scope="module", autouse=True)
def setup_windows_test_environment():
    """Set up results directory and short video file for tests."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ensure_short_video()
    yield


@pytest.mark.skipif(sys.platform != "win32", reason="Windows specific test suite")
def test_windows_photo_pillow_processing(tmp_path):
    """Test photo processing using Pillow on Windows to ensure no PIL errors or cv2 fallbacks."""
    assert RAW_PHOTO.exists()
    out_photo = tmp_path / "photo_win_out.jpg"
    
    cmd = [
        sys.executable, "cli_main.py",
        str(RAW_PHOTO),
        str(out_photo),
        "--color"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"Photo processing failed: {res.stderr}"
    assert out_photo.exists()
    assert "No module named 'PIL'" not in res.stderr
    assert "Error saving image with PIL" not in res.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="Windows specific test suite")
def test_windows_hw_accel_nvenc_color(tmp_path):
    """Test video color correction with --hw-accel on Windows without D3D11 / DXVA2 errors."""
    short_vid = ensure_short_video()
    out_video = tmp_path / "vid_win_hw.mp4"
    
    cmd = [
        sys.executable, "cli_main.py",
        str(short_vid),
        str(out_video),
        "--color",
        "--hw-accel"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"HW accelerated video processing failed: {res.stderr}"
    assert out_video.exists()
    
    # Ensure no Direct3D11 / DXVA2 hwaccel initialisation error lines were outputted
    assert "Failed setup for format d3d11" not in res.stderr
    assert "Invalid setup for format dxva2_vld" not in res.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="Windows specific test suite")
def test_windows_path_handling_and_escaping(tmp_path):
    """Test path handling with spaces, drive letters (C:\\...), and move-original functionality."""
    space_dir = tmp_path / "Path With Spaces"
    space_dir.mkdir(parents=True, exist_ok=True)
    
    src_copy = space_dir / "Test Photo Space.JPG"
    shutil.copy2(RAW_PHOTO, src_copy)
    
    out_dir = tmp_path / "Output Directory"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    orig_dir = tmp_path / "Originals Backup"
    orig_dir.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        sys.executable, "cli_main.py",
        str(src_copy),
        str(out_dir),
        "--color",
        "--filename-format", "Test_Photo_Space",
        "--move-original", str(orig_dir)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"Path with spaces processing failed: {res.stderr}"
    
    expected_out = out_dir / "Test_Photo_Space.jpg"
    expected_moved = orig_dir / "Test Photo Space.JPG"
    
    assert expected_out.exists(), f"Output file missing: {expected_out}"
    assert expected_moved.exists(), f"Original file not moved to: {expected_moved}"
    assert not src_copy.exists(), "Source file was not moved from original location"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows specific test suite")
def test_windows_exiftool_metadata_tags(tmp_path):
    """Test ExifTool metadata modification and timezone fixing on Windows."""
    assert RAW_PHOTO.exists()
    test_photo = tmp_path / "meta_win_test.jpg"
    shutil.copy2(RAW_PHOTO, test_photo)
    
    cmd = [
        sys.executable, "cli_main.py",
        str(test_photo),
        str(tmp_path / "meta_win_out.jpg"),
        "--force-media-tz", "+8",
        "--fix-tz"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"ExifTool timezone fix failed: {res.stderr}"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows specific test suite")
def test_windows_convert_resolution(tmp_path):
    """Test resolution conversion (--convert 1080p) on Windows."""
    short_vid = ensure_short_video()
    out_subfolder = tmp_path / "convert_1080p_out"
    
    cmd = [
        sys.executable, "cli_main.py",
        str(short_vid),
        str(out_subfolder),
        "--convert", "1080p"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"Resolution conversion failed: {res.stderr}"
    
    expected_file = out_subfolder / f"{short_vid.stem} 1080p{short_vid.suffix.lower()}"
    assert expected_file.exists(), f"Converted file missing: {expected_file}"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows specific test suite")
def test_windows_hud_rendering_and_fonts():
    """Test HUD renderer on Windows using Pillow TrueType fonts."""
    import numpy as np
    from datetime import datetime
    from gui.hud_renderer import draw_hud
    from models.dive import Waypoint
    
    dummy_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    wp = Waypoint(timestamp=datetime.now(), depth=15.5, temp=24.0, time_since_start=120)
    
    dummy_layout = {
        "hud_skin": {
            "type": "shape",
            "width": 400,
            "height": 200,
            "linked_elements": [
                {"type": "text", "field": "depth", "rel_x": 0.1, "rel_y": 0.1, "font_size": 24}
            ]
        }
    }
    # Render HUD overlay on frame
    draw_hud(dummy_frame, layout=dummy_layout, waypoint=wp)
    
    # Verify frame was modified (rendered HUD text/graphics)
    assert dummy_frame.sum() > 0, "HUD renderer produced empty frame"
