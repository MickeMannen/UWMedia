import shutil

import pytest

from conftest import LOGS_DIR, RELEASE_MEDIA, REPO_ROOT, run_cli
from metadata.exif import MetadataHandler

LAYOUT_PATH = REPO_ROOT / "overlays" / "Shearwater_Perdix2_simple.zip"
UDDF_LOGS = LOGS_DIR / "uddf"

pytestmark = pytest.mark.render


def test_render_video_log_feature(tmp_path):
    """Scenario 1: Test --render-video-log batch telemetry video/photo generation from source media and matching logs."""
    video_source = RELEASE_MEDIA / "20251019_M0284.MP4"
    photo_source = RELEASE_MEDIA / "DSC03491.JPG"

    assert video_source.exists()
    assert photo_source.exists()
    assert LAYOUT_PATH.exists()
    assert UDDF_LOGS.exists()

    # An input folder with just these two files
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    shutil.copy2(video_source, input_dir)
    shutil.copy2(photo_source, input_dir)
    output_dir = tmp_path / "output"

    result = run_cli(input_dir, output_dir, "--render-video-log", "--layout", LAYOUT_PATH,
                     "--logs", UDDF_LOGS, "--tz-adjust", "0")
    assert result.returncode == 0, f"CLI command failed: {result.stderr}"

    # Verify filenames conform to format: original stem + '_' + layout stem + original suffix
    expected_video_out = output_dir / f"{video_source.stem}_{LAYOUT_PATH.stem}{video_source.suffix.lower()}"
    expected_photo_out = output_dir / f"{photo_source.stem}_{LAYOUT_PATH.stem}{photo_source.suffix.lower()}"

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
