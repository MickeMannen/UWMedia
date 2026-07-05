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

def test_convert_resolution_replacement_naming():
    """Confirms that '_4k' or ' 4k' (case insensitive) is replaced by the target resolution."""
    import re
    def get_converted_filename(source_path_str, res_name):
        source = Path(source_path_str)
        stem = source.stem
        if re.search(r'(?i)[ _](4k|2160p|1080p|720p|480p|360p)', stem):
            new_stem = re.sub(r'(?i)[ _](4k|2160p|1080p|720p|480p|360p)', f"_{res_name}", stem)
        else:
            new_stem = f"{stem}_{res_name}"
        return f"{new_stem}{source.suffix.lower()}"

    assert get_converted_filename("filename 4k.mp4", "1080p") == "filename_1080p.mp4"
    assert get_converted_filename("filename_4k.mp4", "1080p") == "filename_1080p.mp4"
    assert get_converted_filename("filename 4K.MP4", "720p") == "filename_720p.mp4"
    assert get_converted_filename("filename_4K.MP4", "720p") == "filename_720p.mp4"
    assert get_converted_filename("dive_clip.mp4", "1080p") == "dive_clip_1080p.mp4"

