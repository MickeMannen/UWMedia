from datetime import datetime

import pytest

from conftest import REPO_ROOT, run_cli, write_synthetic_log

LAYOUT_PATH = REPO_ROOT / "overlays" / "Shearwater_Perdix2_simple.zip"
DIVE_START = datetime(2025, 10, 19, 16, 44, 12)

pytestmark = pytest.mark.render


def test_render_log_uddf(tmp_path):
    """Scenario 1: Test --render-log using a UDDF file with a waypoint limit."""
    log = write_synthetic_log(tmp_path / "dive.uddf", DIVE_START)
    expected_output = tmp_path / "test_render_log_uddf_result.mp4"
    result = run_cli(expected_output, "--render-log", log, "20",  # limit to 20 waypoints to speed up test
                     "--layout", LAYOUT_PATH, "--tz-adjust", "0")
    assert result.returncode == 0, f"Command failed: {result.stderr}"
    assert expected_output.exists(), f"Output file does not exist: {expected_output}"


def test_render_log_fit(tmp_path):
    """Scenario 2: Test --render-log using a Garmin FIT file with a waypoint limit."""
    log = write_synthetic_log(tmp_path / "dive.fit", DIVE_START, computer="Garmin Descent X50i")
    expected_output = tmp_path / "test_render_log_fit_result.mp4"
    result = run_cli(expected_output, "--render-log", log, "10",  # limit to 10 waypoints to keep test fast
                     "--layout", LAYOUT_PATH, "--tz-adjust", "0")
    assert result.returncode == 0, f"Command failed: {result.stderr}"
    assert expected_output.exists(), f"Output file does not exist: {expected_output}"
