import pytest
import os
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
from metadata.exif import MetadataHandler

# Paths
BASE_DIR = Path(__file__).parent.parent
TEST_DATA_DIR = BASE_DIR / "test_data" / "release_test"
RESULTS_DIR = BASE_DIR / "test_data" / "test_results"
LAYOUT_PATH = BASE_DIR / "computers" / "Shearwater_Perdix2_simple.zip"
LOGS_DIR = BASE_DIR / "test_data" / "logs" / "uddf"

@pytest.fixture(scope="module", autouse=True)
def setup_results_dir():
    """Ensure target test_results directory exists and clean old test outputs."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    # Clean up previous test outputs matching test_render_video_log pattern
    for file in RESULTS_DIR.glob("*hud_layout*"):
        try:
            file.unlink()
        except Exception:
            pass
    yield

def test_render_video_log_feature():
    """Scenario 1: Test --render-video-log batch telemetry video/photo generation from source media and matching logs."""
    video_source = TEST_DATA_DIR / "20251019_M0284.MP4"
    photo_source = TEST_DATA_DIR / "DSC03491.JPG"
    
    assert video_source.exists()
    assert photo_source.exists()
    assert LAYOUT_PATH.exists()
    assert LOGS_DIR.exists()

    # Create a temp folder with just these two files to act as input folder
    temp_input_dir = BASE_DIR / "test_data" / "temp_render_video_log_input"
    if temp_input_dir.exists():
        shutil.rmtree(temp_input_dir)
    temp_input_dir.mkdir(parents=True, exist_ok=True)
    
    # We clip the video source manually or process directly.
    # Note: --render-video-log processes the full file, but we can copy the files to the temp dir.
    shutil.copy2(video_source, temp_input_dir)
    shutil.copy2(photo_source, temp_input_dir)

    # Run CLI command
    cmd = [
        "python3", "cli_main.py",
        str(temp_input_dir),
        str(RESULTS_DIR),
        "--render-video-log",
        "--layout", str(LAYOUT_PATH),
        "--logs", str(LOGS_DIR),
        "--tz-adjust", "0"
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, f"CLI command failed: {result.stderr}"

    # Verify filenames conform to format: original stem + '_' + layout stem + original suffix
    expected_video_out = RESULTS_DIR / f"{video_source.stem}_{LAYOUT_PATH.stem}{video_source.suffix.lower()}"
    expected_photo_out = RESULTS_DIR / f"{photo_source.stem}_{LAYOUT_PATH.stem}{photo_source.suffix.lower()}"
    
    assert expected_video_out.exists(), f"Output video does not exist: {expected_video_out}"
    assert expected_photo_out.exists(), f"Output photo does not exist: {expected_photo_out}"

    # Verify that EXIF/QuickTime metadata was successfully copied
    handler = MetadataHandler()
    
    orig_video_date = handler.get_local_creation_date(video_source)
    new_video_date = handler.get_local_creation_date(expected_video_out)
    assert orig_video_date == new_video_date, "Video creation date mismatched"

    orig_photo_date = handler.get_local_creation_date(photo_source)
    new_photo_date = handler.get_local_creation_date(expected_photo_out)
    assert orig_photo_date == new_photo_date, "Photo creation date mismatched"

    # Cleanup temp input
    shutil.rmtree(temp_input_dir)
