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


def test_render_log_transparent_prores_and_png_sequence(tmp_path):
    """--overlay-format prores writes a .mov with an alpha channel; png a
    folder with one PNG per frame, each RGBA."""
    import subprocess
    import cv2
    log = write_synthetic_log(tmp_path / "dive.uddf", DIVE_START)
    result = run_cli(tmp_path / "alpha.mp4", "--render-log", log, "6", "--layout", LAYOUT_PATH, "--tz-adjust", "0",
                     "--overlay-format", "prores")
    assert result.returncode == 0, f"Command failed: {result.stderr}"
    mov = tmp_path / "alpha.mov"
    assert mov.exists() and not (tmp_path / "alpha.mp4").exists()
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name,pix_fmt",
                            "-of", "default=nw=1", str(mov)], capture_output=True, text=True)
    assert "codec_name=prores" in probe.stdout and "yuva444p" in probe.stdout, probe.stdout  # ffprobe reports the decoder's 12-bit pix_fmt

    result = run_cli(tmp_path / "frames.mp4", "--render-log", log, "6", "--layout", LAYOUT_PATH, "--tz-adjust", "0",
                     "--overlay-format", "png")
    assert result.returncode == 0, f"Command failed: {result.stderr}"
    folder = tmp_path / "frames"
    frames = sorted(folder.glob("frame_*.png"))
    assert folder.is_dir() and len(frames) > 30  # 6 waypoints at 2 s spacing, 30 fps
    first = cv2.imread(str(frames[0]), cv2.IMREAD_UNCHANGED)
    assert first.shape[2] == 4 and first[:, :, 3].max() == 255 and first[:, :, 3].min() == 0

