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
UDDF_LOG = BASE_DIR / "test_data" / "logs" / "uddf" / "Perdix 2 453 2025-10-19 16-44-12.uddf"
FIT_LOG = BASE_DIR / "test_data" / "logs" / "fit" / "488 Phuket, Camera Bay.fit"

@pytest.fixture(scope="module", autouse=True)
def setup_results_dir():
    """Ensure target test_results directory exists and clean old test outputs."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    # Clean up previous test outputs matching test_render_log pattern
    for file in RESULTS_DIR.glob("test_render_log_*"):
        try:
            file.unlink()
        except Exception:
            pass
    yield

def test_render_log_uddf():
    """Scenario 1: Test --render-log using a UDDF file with a waypoint limit."""
    assert UDDF_LOG.exists()
    assert LAYOUT_PATH.exists()

    expected_output = RESULTS_DIR / "test_render_log_uddf_result.mp4"

    cmd = [
        "python3", "cli_main.py",
        str(expected_output),
        "--render-log", str(UDDF_LOG), "20",  # limit to 20 waypoints to speed up test
        "--layout", str(LAYOUT_PATH),
        "--tz-adjust", "0"
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, f"Command failed: {result.stderr}"
    assert expected_output.exists(), f"Output file does not exist: {expected_output}"

def test_render_log_fit():
    """Scenario 2: Test --render-log using a Garmin FIT file with a waypoint limit."""
    assert FIT_LOG.exists()
    assert LAYOUT_PATH.exists()

    expected_output = RESULTS_DIR / "test_render_log_fit_result.mp4"

    cmd = [
        "python3", "cli_main.py",
        str(expected_output),
        "--render-log", str(FIT_LOG), "10",  # limit to 10 waypoints to keep test fast
        "--layout", str(LAYOUT_PATH),
        "--tz-adjust", "0"
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, f"Command failed: {result.stderr}"
    assert expected_output.exists(), f"Output file does not exist: {expected_output}"
