import pytest
import os
import shutil
import subprocess
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent.parent
TEST_DATA_DIR = BASE_DIR / "test_data" / "release_test"
RESULTS_DIR = BASE_DIR / "test_data" / "test_results"
LAYOUT_PATH = BASE_DIR / "overlays"
LOGS_DIR = BASE_DIR / "test_data" / "logs" / "uddf"

@pytest.fixture(scope="module", autouse=True)
def setup_results_dir():
    """Ensure the target test_results directory exists and clean old test outputs."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    # Clean up previous test outputs matching test_color pattern
    for file in RESULTS_DIR.glob("test_color_*"):
        try:
            if file.is_file():
                file.unlink()
            elif file.is_dir():
                shutil.rmtree(file)
        except Exception:
            pass
    yield

def test_color_only_video():
    """Scenario 1: Test --color only on a video file. This executes the fast 3D LUT path."""
    source_video = TEST_DATA_DIR / "20251019_M0284.MP4"
    assert source_video.exists()

    cmd = [
        "python3", "cli_main.py",
        str(source_video),
        str(RESULTS_DIR),
        "--color", "default",
        "--start-time", "00:00",
        "--end-time", "00:05",
        "--filename-format", "test_color_only_video_result",
        "--hw-accel"
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, f"Command failed: {result.stderr}"
    
    expected_output = RESULTS_DIR / "test_color_only_video_result.mp4"
    assert expected_output.exists(), "Output video file was not created"

def test_color_and_layout_video():
    """Scenario 2: Test --color combined with --layout overlay on a video. This executes the threaded python path."""
    source_video = TEST_DATA_DIR / "20251019_M0284.MP4"

    assert source_video.exists()
    assert LAYOUT_PATH.exists()
    assert LOGS_DIR.exists()

    for file in LAYOUT_PATH.glob("*.zip"):

        cmd = [
            "python3", "cli_main.py",
            str(source_video),
            str(RESULTS_DIR),
            "--color", "vivid",
            "--layout", str(file),
            "--logs", str(LOGS_DIR),
            "--start-time", "00:00",
            "--end-time", "00:05",
            "--filename-format", f"test_color_layout_video_result_{file.stem}",
            "--hw-accel"
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode == 0, f"Command failed: {result.stderr}"

        expected_output = RESULTS_DIR / f"test_color_layout_video_result_{file.stem}.mp4"
        assert expected_output.exists(), "Output video file with overlay was not created"

def test_color_clipping_options():
    """Scenario 3: Test --color with precise start/end clipping parameters and custom filename format."""
    source_video = TEST_DATA_DIR / "20251019_M0284.MP4"
    assert source_video.exists()

    cmd = [
        "python3", "cli_main.py",
        str(source_video),
        str(RESULTS_DIR),
        "--color", "subtle",
        "--start-time", "00:02",
        "--end-time", "00:07",
        "--filename-format", "test_color_clipped_result",
        "--hw-accel"
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, f"Command failed: {result.stderr}"
    
    expected_output = RESULTS_DIR / "test_color_clipped_result.mp4"
    assert expected_output.exists(), "Output clipped video was not created"

def test_color_photo():
    """Scenario 4: Test --color on a photo file."""
    source_photo = TEST_DATA_DIR / "DSC03491.JPG"
    assert source_photo.exists()

    cmd = [
        "python3", "cli_main.py",
        str(source_photo),
        str(RESULTS_DIR),
        "--color", "default",
        "--filename-format", "test_color_photo_result"
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, f"Command failed: {result.stderr}"
    
    expected_output = RESULTS_DIR / "test_color_photo_result_980.jpg"
    assert expected_output.exists(), f"Output photo was not created: {expected_output}"
