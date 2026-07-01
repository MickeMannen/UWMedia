import pytest
import os
import shutil
import subprocess
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent.parent
TEST_DATA_DIR = BASE_DIR / "test_data" / "release_test"
RESULTS_DIR = BASE_DIR / "test_data" / "test_results"
LAYOUT_PATH = BASE_DIR / "computers" / "Shearwater_Perdix2_simple" / "hud_layout.json"
LOGS_DIR = BASE_DIR / "test_data" / "logs" / "uddf"

@pytest.fixture(scope="module", autouse=True)
def setup_results_dir():
    """Ensure target test_results directory exists and clean old test outputs."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    # Clean up previous test outputs matching test_color_legacy pattern
    for file in RESULTS_DIR.glob("test_color_legacy_*"):
        try:
            file.unlink()
        except Exception:
            pass
    yield

def test_color_legacy_only_video():
    """Scenario 1: Test --color-legacy on video (forces the legacy python per-frame rendering loop)."""
    source_video = TEST_DATA_DIR / "20251019_M0284.MP4"
    assert source_video.exists()

    cmd = [
        "python3", "cli_main.py",
        str(source_video),
        str(RESULTS_DIR),
        "--color", "default",
        "--color-legacy",
        "--start-time", "00:00",
        "--end-time", "00:05",
        "--filename-format", "test_color_legacy_video_result"
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, f"Command failed: {result.stderr}"
    
    expected_output = RESULTS_DIR / "test_color_legacy_video_result.mp4"
    assert expected_output.exists(), "Legacy path output video was not created"

def test_color_legacy_with_layout_video():
    """Scenario 2: Test --color-legacy with --layout overlay on a video."""
    source_video = TEST_DATA_DIR / "20251019_M0284.MP4"
    assert source_video.exists()
    assert LAYOUT_PATH.exists()
    assert LOGS_DIR.exists()

    cmd = [
        "python3", "cli_main.py",
        str(source_video),
        str(RESULTS_DIR),
        "--color", "default",
        "--color-legacy",
        "--layout", str(LAYOUT_PATH),
        "--logs", str(LOGS_DIR),
        "--start-time", "00:00",
        "--end-time", "00:05",
        "--filename-format", "test_color_legacy_layout_result"
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, f"Command failed: {result.stderr}"
    
    expected_output = RESULTS_DIR / "test_color_legacy_layout_result.mp4"
    assert expected_output.exists(), "Legacy overlay output video was not created"
