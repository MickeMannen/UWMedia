import pytest
import os
import shutil
import subprocess
from pathlib import Path
from datetime import datetime

from parsers.garmin import GarminParser
from parsers.uddf import UDDFParser
from metadata.exif import MetadataHandler

# Paths
BASE_DIR = Path(__file__).parent.parent
TEST_DATA_DIR = BASE_DIR / "test_data" / "release_test"
TEST_DATA_COLOR_DIR = BASE_DIR / "test_data" / "color_correction"
FIT_DIR = BASE_DIR / "test_data" / "logs" / "fit"
UDDF_DIR = BASE_DIR / "test_data" / "logs" / "uddf"
SSRF_DIR = BASE_DIR / "test_data" / "logs" / "ssrf"
OUTPUT_DIR = BASE_DIR / "test_data" / "test_results"  # Unified test output target
COMPUTERS_DIR = BASE_DIR / "computers"


@pytest.fixture(scope="session", autouse=True)
def setup_output_dir():
    """Ensure the target output/results directory exists and is clean before release tests."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # Clean previous release test outputs to avoid duplication/collision
    for file in OUTPUT_DIR.glob("release_test_*"):
        try:
            if file.is_file():
                file.unlink()
            elif file.is_dir():
                shutil.rmtree(file)
        except Exception:
            pass
    yield


class TestRelease:
    """
    Release Test suite designed to quickly verify core end-to-end functionality
    of the package (Metadata reading, Log parsers, Color Correction, Video Overlay,
    Convert downscaling, Standalone Log rendering, and JSON exports) before deployment.
    
    All video tests are constrained to 15-second segments using --start-time and --end-time
    to ensure the entire release validation suite completes in seconds rather than minutes.
    """

    # 1. Metadata Verification Tests
    def test_01_metadata_video(self):
        """Verify video creation date and timestamp extraction from metadata works correctly."""
        video_file = TEST_DATA_DIR / "20251019_M0284.MP4"
        handler = MetadataHandler()
        create_date = handler.get_standardized_creation_date(video_file)
        creation_date = handler.get_local_creation_date(video_file)
        assert create_date is not None
        assert creation_date is not None
        assert creation_date.year == 2025
        assert creation_date.month == 10
        assert creation_date.day == 19
        assert creation_date.hour == 10
        assert creation_date.minute == 21
        assert creation_date.second == 31

    def test_02_metadata_photo(self):
        """Verify photo timestamp extraction works properly."""
        photo_file = TEST_DATA_DIR / "DSC03491.JPG"
        handler = MetadataHandler()
        creation_date = handler.get_local_creation_date(photo_file)
        assert creation_date is not None
        assert creation_date.year == 2025
        assert creation_date.month == 12
        assert creation_date.day == 3
        assert creation_date.hour == 9
        assert creation_date.minute == 15
        assert creation_date.second == 48

    # 2. Garmin Parser Tests
    def test_03_garmin_parser(self):
        """Verify parsing Garmin .fit log files works and loads telemetry waypoints and tanks."""
        parser = GarminParser()
        fit_files = list(FIT_DIR.glob("*.fit"))
        assert len(fit_files) > 0

        target = FIT_DIR / "461 Sipadan, Turtle Tomb.fit"
        dives = parser.parse(target)
        assert len(dives) > 0
        dive = dives[0]
        assert dive.max_depth > 10.0
        assert len(dive.waypoints) > 100
        for wp in dive.waypoints:
            if wp.tanks:
                assert len(wp.tanks) >= 1
                break

    # 3. UDDF Parser Tests
    def test_04_uddf_parser(self):
        """Verify parsing UDDF log files works and loads telemetry details."""
        parser = UDDFParser()
        uddf_files = list(UDDF_DIR.glob("*.uddf"))
        assert len(uddf_files) > 0

        target = UDDF_DIR / "Perdix 2 453 2025-10-19 16-44-12.uddf"
        dives = parser.parse(target)
        assert len(dives) > 0
        dive = dives[0]
        assert dive.max_depth > 10.0
        assert len(dive.waypoints) > 100

    # 4. Color Correction (Fast LUT Path)
    def test_05_color_correction_video(self):
        """Verify video color correction (fast LUT path) on a short 1-second segment."""
        src = TEST_DATA_DIR / "20251019_M0284.MP4"
        cmd = [
            "python3", "cli_main.py", str(src), str(OUTPUT_DIR),
            "--color", "--filename-format", "release_test_test05_color",
            "--start-time", "00:00", "--end-time", "00:15", "--hw-accel"
        ]
        subprocess.run(cmd, check=True)

        found = list(OUTPUT_DIR.glob("release_test_test05_color.mp4"))
        assert len(found) == 1

    def test_06_color_correction_photo(self):
        """Verify photo color correction works on all JPGs in release_test directory."""
        i = 0
        for file in TEST_DATA_DIR.glob("*.JPG"):
            i += 1
            cmd = [
                "python3", "cli_main.py", str(file), str(OUTPUT_DIR),
                "--color", "--filename-format", f"release_test_test06_color_{file.stem}"
            ]
            subprocess.run(cmd, check=True)

        found = list(OUTPUT_DIR.glob("release_test_test06_color_*.jpg"))
        assert len(found) == i

    def test_06c_color_correction_photo_profiles(self):
        """Verify photo color correction profiles (vivid, subtle) are correctly parsed and run."""
        file = TEST_DATA_DIR / "DSC03491.JPG"
        for profile in ["vivid", "subtle"]:
            cmd = [
                "python3", "cli_main.py", str(file), str(OUTPUT_DIR),
                "--color", profile, "--filename-format", f"release_test_test06c_{profile}"
            ]
            subprocess.run(cmd, check=True)
            found = list(OUTPUT_DIR.glob(f"release_test_test06c_{profile}_*.jpg"))
            assert len(found) == 1

    def test_05b_color_correction_video_profiles(self):
        """Verify video color correction profiles on short 1-second segments."""
        src = TEST_DATA_DIR / "20251019_M0284.MP4"
        for profile in ["vivid", "subtle"]:
            cmd = [
                "python3", "cli_main.py", str(src), str(OUTPUT_DIR),
                "--color", profile, "--filename-format", f"release_test_test05_profile_{profile}",
                "--start-time", "00:00", "--end-time", "00:15", "--hw-accel"
            ]
            subprocess.run(cmd, check=True)
            found = list(OUTPUT_DIR.glob(f"release_test_test05_profile_{profile}.mp4"))
            assert len(found) == 1

    def test_06b_color_correction_photo_sidebyside(self):
        """Verify side-by-side JPG photo comparisons generated correctly."""
        import cv2
        import numpy as np

        i = 0
        for file in TEST_DATA_COLOR_DIR.glob("*.JPG"):
            edited_path = TEST_DATA_COLOR_DIR / f"{file.stem}_Edited.JPEG"
            if not edited_path.exists():
                continue

            i += 1
            temp_format = f"release_test_temp_sidebyside_{file.stem}"
            cmd = [
                "python3", "cli_main.py", str(file), str(OUTPUT_DIR),
                "--color", "--filename-format", temp_format
            ]
            subprocess.run(cmd, check=True)

            corrected_files = list(OUTPUT_DIR.glob(f"*{temp_format}*.jpg"))
            assert len(corrected_files) == 1
            corrected_path = corrected_files[0]

            edit_img = cv2.imread(str(edited_path))
            corr_img = cv2.imread(str(corrected_path))

            assert edit_img is not None
            assert corr_img is not None

            h, w = corr_img.shape[:2]
            edit_img_resized = cv2.resize(edit_img, (w, h))
            sidebyside = np.hstack([edit_img_resized, corr_img])

            target_path = OUTPUT_DIR / f"release_test_{file.stem}_color_sidebyside.jpg"
            cv2.imwrite(str(target_path), sidebyside)
            corrected_path.unlink()

        found = list(OUTPUT_DIR.glob("release_test_*_color_sidebyside.jpg"))
        assert len(found) == i

    # 5. Color Correction with Overlay
    def test_07_overlay_video(self):
        """Verify video overlay (threaded processing) works on short 1-second clips for different layouts."""
        src = TEST_DATA_DIR / "DJI_20260502110658_0002_D_A001.MP4"
        logs = FIT_DIR

        layouts = [COMPUTERS_DIR / "Garmin_x50_simple.zip", COMPUTERS_DIR / "generic_depth_temp.zip"]

        target_list = []
        for layout in layouts:
            target_list.append(layout.stem)
            cmd = [
                "python3", "cli_main.py", str(src), str(OUTPUT_DIR),
                "--color", "--layout", str(layout), "--logs", str(logs),
                "--filename-format", f"release_test_test07_{layout.stem}",
                "--start-time", "00:00", "--end-time", "00:15", "--hw-accel"
            ]
            subprocess.run(cmd, check=True)

        for t in target_list:
            n = len(list(OUTPUT_DIR.glob(f"release_test_test07_{t}.mp4")))
            assert n == 1

    def test_08_overlay_photo(self):
        """Verify photo layout overlays work for different layout styles."""
        src = TEST_DATA_DIR / "DSC03491.JPG"
        layouts = [COMPUTERS_DIR / "Garmin_x50_simple.zip", COMPUTERS_DIR / "generic_depth_temp.zip"]
        logs = FIT_DIR
        target_list = []

        for layout in layouts:
            target_list.append(layout.stem)
            cmd = [
                "python3", "cli_main.py", str(src), str(OUTPUT_DIR),
                "--color", "--layout", str(layout), "--logs", str(logs),
                "--filename-format", f"release_test_test08_{layout.stem}", "--hw-accel"
            ]
            subprocess.run(cmd, check=True)

        for t in target_list:
            n = len(list(OUTPUT_DIR.glob(f"release_test_test08_{t}_*.jpg")))
            assert n == 1

    # 6. Standalone Log Rendering
    def test_09_render_log_fit(self):
        """Verify standalone telemetry video generation from Garmin FIT log files."""
        log = FIT_DIR / "488 Phuket, Camera Bay.fit"

        for file in COMPUTERS_DIR.glob("*.zip"):
            output_file = OUTPUT_DIR / f"release_test_render_log_{log.stem}_{file.stem}.mp4"

            cmd = [
                "python3", "cli_main.py", str(output_file),
                "--render-log", str(log), "20",  # Limit waypoints to speed up test execution
                "--layout", str(file), "--hw-accel"
            ]
            subprocess.run(cmd, check=True)
            assert output_file.exists()

    def test_10_render_log_uddf(self):
        """Verify standalone telemetry video generation from UDDF log files."""
        log = UDDF_DIR / "Perdix 2 453 2025-10-19 16-44-12.uddf"
        layout = COMPUTERS_DIR / "generic_depth_temp.zip"
        output_file = OUTPUT_DIR / f"release_test_render_log_{log.stem}_generic.mp4"

        cmd = [
            "python3", "cli_main.py", str(output_file),
            "--render-log", str(log), "20",  # Limit waypoints
            "--layout", str(layout)
        ]
        subprocess.run(cmd, check=True)
        assert output_file.exists()

    def test_11_overlay_photo(self):
        """Verify photo overlays with SSRF logs."""
        src = TEST_DATA_DIR / "DSC06422.JPG"
        layout = COMPUTERS_DIR / "generic_depth_temp.zip"
        logs = SSRF_DIR
        cmd = [
            "python3", "cli_main.py", str(src), str(OUTPUT_DIR),
            "--color", "--layout", str(layout), "--logs", str(logs),
            "--filename-format", "release_test_test11_overlay_generic"
        ]
        subprocess.run(cmd, check=True)

        target = list(OUTPUT_DIR.glob("release_test_test11_overlay_generic_*.jpg"))[0]
        assert target.exists()

    def test_12_export_json(self):
        """Verify JSON telemetry exports from log files."""
        temp_log_dir = OUTPUT_DIR / "release_test_export_logs_test"
        if temp_log_dir.exists():
            shutil.rmtree(temp_log_dir)
        temp_log_dir.mkdir(parents=True)

        fit_src = FIT_DIR / "488 Phuket, Camera Bay.fit"
        uddf_src = UDDF_DIR / "Perdix 2 453 2025-10-19 16-44-12.uddf"
        ssrf_src = SSRF_DIR / "494.ssrf"

        shutil.copy2(fit_src, temp_log_dir)
        shutil.copy2(uddf_src, temp_log_dir)
        shutil.copy2(ssrf_src, temp_log_dir)

        cmd = [
            "python3", "cli_main.py",
            "--export-json", str(temp_log_dir)
        ]
        subprocess.run(cmd, check=True)

        fit_json = temp_log_dir / "488 Phuket, Camera Bay.json"
        uddf_json = temp_log_dir / "Perdix 2 453 2025-10-19 16-44-12.json"
        ssrf_json = temp_log_dir / "494.json"

        assert fit_json.exists()
        assert uddf_json.exists()
        assert ssrf_json.exists()

        import json
        with open(fit_json, "r") as f:
            waypoints = json.load(f)

        assert isinstance(waypoints, list)
        assert len(waypoints) > 0

        first_wp = waypoints[0]
        assert "timestamp" in first_wp
        assert "depth" in first_wp
        assert isinstance(first_wp["timestamp"], str)
        assert isinstance(first_wp["depth"], float)

        datetime.strptime(first_wp["timestamp"], "%Y-%m-%d %H:%M:%S")
        
        # Clean up temporary logs folder
        shutil.rmtree(temp_log_dir)
