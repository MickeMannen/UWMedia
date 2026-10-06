import pytest

from conftest import LOGS_DIR, RELEASE_MEDIA, REPO_ROOT, run_cli

pytestmark = pytest.mark.render

LAYOUT_PATH = REPO_ROOT / "overlays"
UDDF_LOGS = LOGS_DIR / "uddf"


def test_color_only_video(tmp_path):
    """Scenario 1: Test --color only on a video file. This executes the fast 3D LUT path."""
    source_video = RELEASE_MEDIA / "20251019_M0284.MP4"
    assert source_video.exists()

    result = run_cli(source_video, tmp_path, "--color", "default",
                     "--filename-format", "test_color_only_video_result", "--hw-accel")
    assert result.returncode == 0, f"Command failed: {result.stderr}"

    expected_output = tmp_path / "test_color_only_video_result.mp4"
    assert expected_output.exists(), "Output video file was not created"


@pytest.mark.parametrize("layout", sorted(LAYOUT_PATH.glob("*.zip")), ids=lambda p: p.stem)
def test_color_and_layout_video(tmp_path, layout):
    """Scenario 2: Test --color combined with --layout overlay on a video. This executes the threaded python path."""
    source_video = RELEASE_MEDIA / "20251019_M0284.MP4"
    assert source_video.exists()
    assert UDDF_LOGS.exists()

    result = run_cli(source_video, tmp_path, "--color", "vivid", "--layout", layout, "--logs", UDDF_LOGS,
                     "--filename-format", f"test_color_layout_video_result_{layout.stem}", "--hw-accel")
    assert result.returncode == 0, f"Command failed: {result.stderr}"

    expected_output = tmp_path / f"test_color_layout_video_result_{layout.stem}.mp4"
    assert expected_output.exists(), "Output video file with overlay was not created"


def test_color_photo(tmp_path):
    """Scenario 4: Test --color on a photo file."""
    source_photo = RELEASE_MEDIA / "DSC03491.JPG"
    assert source_photo.exists()

    result = run_cli(source_photo, tmp_path, "--color", "default", "--filename-format", "test_color_photo_result")
    assert result.returncode == 0, f"Command failed: {result.stderr}"

    expected_output = tmp_path / "test_color_photo_result_980.jpg"
    assert expected_output.exists(), f"Output photo was not created: {expected_output}"
