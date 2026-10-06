import pytest

from conftest import LOGS_DIR, REPO_ROOT, run_cli

LAYOUT_PATH = REPO_ROOT / "overlays" / "Shearwater_Perdix2_simple.zip"
UDDF_LOG = LOGS_DIR / "uddf" / "Perdix 2 453 2025-10-19 16-44-12.uddf"
FIT_LOG = LOGS_DIR / "fit" / "488 Phuket, Camera Bay.fit"

pytestmark = pytest.mark.render


def test_render_log_uddf(tmp_path):
    """Scenario 1: Test --render-log using a UDDF file with a waypoint limit."""
    assert UDDF_LOG.exists()
    assert LAYOUT_PATH.exists()

    expected_output = tmp_path / "test_render_log_uddf_result.mp4"
    result = run_cli(expected_output, "--render-log", UDDF_LOG, "20",  # limit to 20 waypoints to speed up test
                     "--layout", LAYOUT_PATH, "--tz-adjust", "0")
    assert result.returncode == 0, f"Command failed: {result.stderr}"
    assert expected_output.exists(), f"Output file does not exist: {expected_output}"


def test_render_log_fit(tmp_path):
    """Scenario 2: Test --render-log using a Garmin FIT file with a waypoint limit."""
    assert FIT_LOG.exists()
    assert LAYOUT_PATH.exists()

    expected_output = tmp_path / "test_render_log_fit_result.mp4"
    result = run_cli(expected_output, "--render-log", FIT_LOG, "10",  # limit to 10 waypoints to keep test fast
                     "--layout", LAYOUT_PATH, "--tz-adjust", "0")
    assert result.returncode == 0, f"Command failed: {result.stderr}"
    assert expected_output.exists(), f"Output file does not exist: {expected_output}"
