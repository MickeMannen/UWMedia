import pytest
import os
import shutil
import subprocess
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent.parent
TEST_DATA_DIR = BASE_DIR / "test_data" / "release_test"
RESULTS_DIR = BASE_DIR / "test_data" / "test_results"

@pytest.fixture(scope="module", autouse=True)
def setup_results_dir():
    """Ensure target test_results directory exists and clean old test outputs."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    # Clean up previous test outputs matching test_convert pattern
    for file in RESULTS_DIR.glob("test_convert_*"):
        try:
            if file.is_file():
                file.unlink()
            elif file.is_dir():
                shutil.rmtree(file)
        except Exception:
            pass
    yield

def test_convert_video_resolution():
    """Scenario 1: Test --convert downscaling on a video file. Confirms 1080p resolution folder output."""
    source_video = TEST_DATA_DIR / "20251019_M0284.MP4"
    assert source_video.exists()

    output_subfolder = RESULTS_DIR / "test_convert_1080p"
    
    cmd = [
        "python3", "cli_main.py",
        str(source_video),
        str(output_subfolder),
        "--convert", "1080p",
        "--start-time", "00:00",
        "--end-time", "00:05"
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, f"Command failed: {result.stderr}"
    
    # The --convert command places the converted resolution file inside output_dir with the pattern: [source_stem]_[resolution].[ext]
    expected_file = output_subfolder / f"{source_video.stem}_1080p{source_video.suffix.lower()}"
    assert expected_file.exists(), f"Converted file was not created: {expected_file}"
