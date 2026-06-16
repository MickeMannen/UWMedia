import pytest
import os
import shutil
import subprocess
from pathlib import Path
from datetime import datetime

from _pytest._py import path

from parsers.garmin import GarminParser
from parsers.uddf import UDDFParser
from metadata.exif import MetadataHandler

# Paths
BASE_DIR = Path(__file__).parent.parent
TEST_DATA_DIR = BASE_DIR / "test_data" / "release_test"
TEST_DATA_COLOR_DIR = BASE_DIR / "test_data" / "color_correction"
FIT_DIR = TEST_DATA_DIR / "fit"
UDDF_DIR = TEST_DATA_DIR / "uddf"
SSRF_DIR = TEST_DATA_DIR / "ssrf"
OUTPUT_DIR = TEST_DATA_DIR / "output"
COMPUTERS_DIR = BASE_DIR / "computers"


@pytest.fixture(scope="session", autouse=True)
def setup_output_dir():
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    yield


class TestRelease:

    # 1. Metadata Tests
    def test_01_metadata_video(self):
        video_file = TEST_DATA_DIR / "20251019_M0284.MP4"
        handler = MetadataHandler()
        # Verify extraction doesn't crash and returns valid dates
        create_date = handler.get_standardized_creation_date(video_file)
        creation_date = handler.get_local_creation_date(video_file)
        assert create_date is not None
        assert creation_date is not None
        # Specific check for this file (expected local time from filename prefix)
        assert creation_date.year == 2025
        assert creation_date.month == 10
        assert creation_date.day == 19
        assert creation_date.hour == 10
        assert creation_date.minute == 21
        assert creation_date.second == 31

    def test_02_metadata_photo(self):
        photo_file = TEST_DATA_DIR / "DSC03491.JPG"
        handler = MetadataHandler()
        creation_date = handler.get_local_creation_date(photo_file)
        assert creation_date is not None
        # Values updated based on actual file metadata found during first run
        assert creation_date.year == 2025
        assert creation_date.month == 12
        assert creation_date.day == 3
        assert creation_date.hour == 9
        assert creation_date.minute == 15
        assert creation_date.second == 48

    # 2. Garmin Parser Tests
    def test_03_garmin_parser(self):
        parser = GarminParser()
        fit_files = list(FIT_DIR.glob("*.fit"))
        assert len(fit_files) > 0

        # Test a specific one with known characteristics
        target = FIT_DIR / "461 Sipadan, Turtle Tomb.fit"
        dives = parser.parse(target)
        assert len(dives) > 0
        dive = dives[0]
        # max_depth is now a property
        assert dive.max_depth > 10.0
        assert len(dive.waypoints) > 100
        # Check tanks
        for wp in dive.waypoints:
            if wp.tanks:
                assert len(wp.tanks) >= 1
                break

    # 3. UDDF Parser Tests
    def test_04_uddf_parser(self):
        parser = UDDFParser()
        uddf_files = list(UDDF_DIR.glob("*.uddf"))
        assert len(uddf_files) > 0

        # Test a specific one
        target = UDDF_DIR / "Perdix 2 453 2025-10-19 16-44-12.uddf"
        dives = parser.parse(target)
        assert len(dives) > 0
        dive = dives[0]
        assert dive.max_depth > 10.0
        assert len(dive.waypoints) > 100

    # 4. Color Correction
    def test_05_color_correction_video(self):
        src = TEST_DATA_DIR / "20251019_M0284.MP4"
        # Expected filename: 20251019_102131_test04_color.mp4 (based on file date)
        # We use --filename-format to force the suffix
        cmd = [
            "python3", "cli_main.py", str(src), str(OUTPUT_DIR),
            "--color", "--filename-format", "%Y%m%d_%H%M%S_test05_color", "--hw-accel"
        ]
        subprocess.run(cmd, check=True)

        # Verify file exists in output
        found = list(OUTPUT_DIR.glob("*_test05_color.mp4"))
        assert len(found) == 1

    def test_06_color_correction_photo(self):

        i = 0
        for file in TEST_DATA_DIR.glob("*.JPG"):
            i += 1
            cmd = [
                "python3", "cli_main.py", str(file), str(OUTPUT_DIR),
                "--color", "--filename-format", "%Y%m%d_%H%M%S_test06_color"
            ]
            subprocess.run(cmd, check=True)

        found = list(OUTPUT_DIR.glob("*_test06_color_*.jpg"))
        assert len(found) == i

    def test_06c_color_correction_photo_profiles(self):
        file = TEST_DATA_DIR / "DSC03491.JPG"
        for profile in ["vivid", "subtle"]:
            cmd = [
                "python3", "cli_main.py", str(file), str(OUTPUT_DIR),
                "--color", profile, "--filename-format", f"%Y%m%d_%H%M%S_test06c_{profile}"
            ]
            subprocess.run(cmd, check=True)
            found = list(OUTPUT_DIR.glob(f"*_test06c_{profile}_*.jpg"))
            assert len(found) == 1

    def test_05b_color_correction_video_profiles(self):
        src = TEST_DATA_DIR / "20251019_M0284.MP4"
        for profile in ["vivid", "subtle"]:
            cmd = [
                "python3", "cli_main.py", str(src), str(OUTPUT_DIR),
                "--color", profile, "--filename-format", f"%Y%m%d_%H%M%S_test05_profile_{profile}", "--hw-accel"
            ]
            subprocess.run(cmd, check=True)
            found = list(OUTPUT_DIR.glob(f"*_test05_profile_{profile}.mp4"))
            assert len(found) == 1

    def test_06b_color_correction_photo_sidebyside(self):
        import cv2
        import numpy as np

        i = 0
        for file in TEST_DATA_COLOR_DIR.glob("*.JPG"):
            # Locate the manual edit file.stem_Edited.JPEG in TEST_DATA_COLOR_DIR
            edited_path = TEST_DATA_COLOR_DIR / f"{file.stem}_Edited.JPEG"
            if not edited_path.exists():
                continue

            i += 1
            # 1. First run the CLI to generate the corrected photo
            temp_format = f"temp_sidebyside_{file.stem}"
            cmd = [
                "python3", "cli_main.py", str(file), str(OUTPUT_DIR),
                "--color", "--filename-format", temp_format
            ]
            subprocess.run(cmd, check=True)

            # Find the generated corrected file
            corrected_files = list(OUTPUT_DIR.glob(f"*{temp_format}*.jpg"))
            assert len(corrected_files) == 1
            corrected_path = corrected_files[0]

            # 2. Read edited and corrected photos
            edit_img = cv2.imread(str(edited_path))
            corr_img = cv2.imread(str(corrected_path))

            assert edit_img is not None
            assert corr_img is not None

            # 3. Resize edited image to match corrected dimensions for stacking
            h, w = corr_img.shape[:2]
            edit_img_resized = cv2.resize(edit_img, (w, h))

            # 4. Stack them side-by-side (edited on left, corrected on right)
            sidebyside = np.hstack([edit_img_resized, corr_img])

            # 5. Save to the required name: original_name_color_sidebyside.jpg
            target_path = OUTPUT_DIR / f"{file.stem}_color_sidebyside.jpg"
            cv2.imwrite(str(target_path), sidebyside)

            # 6. Clean up the temporary corrected file
            corrected_path.unlink()

        # Verify the side-by-side files exist in output
        found = list(OUTPUT_DIR.glob("*_color_sidebyside.jpg"))
        assert len(found) == i

    # 5. Color Correction with Overlay
    def test_07_overlay_video(self):
        src = TEST_DATA_DIR / "DJI_20260502110658_0002_D_A001.MP4"
        logs = FIT_DIR  # Use FIT_DIR to find matching logs

        layouts = [COMPUTERS_DIR / "Garmin_x50_simple.zip", COMPUTERS_DIR / "generic_depth_temp.zip"]

        target_list = []
        for layout in layouts:
            target_list.append(layout.stem)
            cmd = [
                "python3", "cli_main.py", str(src), str(OUTPUT_DIR),
                "--color", "--layout", str(layout), "--logs", str(logs),
                "--filename-format", f"%Y%m%d_%H%M%S_test07_{layout.stem}", "--hw-accel"
            ]
            subprocess.run(cmd, check=True)

        for t in target_list:
            n = len(list(OUTPUT_DIR.glob(f"*{t}*")))
            assert n == 1

        #
        # # Verify metadata copy
        # handler = MetadataHandler()
        # meta = handler.get_metadata(target)
        # assert "QuickTime:CreateDate" in meta or "CreateDate" in meta

    def test_08_overlay_photo(self):
        src = TEST_DATA_DIR / "DSC03491.JPG"
        layouts = [COMPUTERS_DIR / "Garmin_x50_simple.zip", COMPUTERS_DIR / "generic_depth_temp.zip"]
        # layout = COMPUTERS_DIR / "generic_depth_temp.zip"
        logs = FIT_DIR
        target_list = []

        for layout in layouts:
            target_list.append(layout.stem)
            cmd = [
                "python3", "cli_main.py", str(src), str(OUTPUT_DIR),
                "--color", "--layout", str(layout), "--logs", str(logs),
                "--filename-format", f"%Y%m%d_%H%M%S_test08_{layout.stem}", "--hw-accel"
            ]
            subprocess.run(cmd, check=True)

        for t in target_list:
            n = len(list(OUTPUT_DIR.glob(f"*test08_{t}*.jpg")))
            assert n == 1

    # 6. Standalone Log Rendering
    def test_09_render_log_fit(self):
        log = FIT_DIR / "488 Phuket, Camera Bay.fit"

        for file in COMPUTERS_DIR.glob("*.zip"):
            # layout = COMPUTERS_DIR / "Garmin_x50_simple.zip"
            # Use OUTPUT_DIR instead of TEST_DATA_DIR to avoid permission or path issues
            output_file = OUTPUT_DIR / f"{log.stem}_{file.stem}.mp4"

            cmd = [
                "python3", "cli_main.py", str(output_file),
                "--render-log", str(log), "100", "--layout", str(file), "--hw-accel"
            ]
            subprocess.run(cmd, check=True)
            assert output_file.exists()

    def test_10_render_log_uddf(self):
        log = UDDF_DIR / "Perdix 2 453 2025-10-19 16-44-12.uddf"
        layout = COMPUTERS_DIR / "generic_depth_temp.zip"
        output_file = OUTPUT_DIR / f"{log.stem}_generic.mp4"

        cmd = [
            "python3", "cli_main.py", str(output_file),
            "--render-log", str(log), "100", "--layout", str(layout)
        ]
        subprocess.run(cmd, check=True)
        assert output_file.exists()

    def test_11_overlay_photo(self):
        src = TEST_DATA_DIR / "DSC06422.JPG"
        layout = COMPUTERS_DIR / "generic_depth_temp.zip"
        logs = SSRF_DIR
        cmd = [
            "python3", "cli_main.py", str(src), str(OUTPUT_DIR),
            "--color", "--layout", str(layout), "--logs", str(logs),
            "--filename-format", "%Y%m%d_%H%M%S_test11_overlay_generic"
        ]
        subprocess.run(cmd, check=True)

        target = list(OUTPUT_DIR.glob("*_test11_overlay_generic_*.jpg"))[0]
        assert target.exists()

    def test_12_export_json(self):
        # Create a temp log directory under OUTPUT_DIR
        temp_log_dir = OUTPUT_DIR / "export_logs_test"
        if temp_log_dir.exists():
            shutil.rmtree(temp_log_dir)
        temp_log_dir.mkdir(parents=True)

        # Copy some test log files (one uddf, one fit, one ssrf)
        fit_src = FIT_DIR / "488 Phuket, Camera Bay.fit"
        uddf_src = UDDF_DIR / "Perdix 2 453 2025-10-19 16-44-12.uddf"
        ssrf_src = SSRF_DIR / "494.ssrf"

        shutil.copy2(fit_src, temp_log_dir)
        shutil.copy2(uddf_src, temp_log_dir)
        shutil.copy2(ssrf_src, temp_log_dir)

        # Run export CLI command
        cmd = [
            "python3", "cli_main.py",
            "--export-json", str(temp_log_dir)
        ]
        subprocess.run(cmd, check=True)

        # Check that JSON files were created
        fit_json = temp_log_dir / "488 Phuket, Camera Bay.json"
        uddf_json = temp_log_dir / "Perdix 2 453 2025-10-19 16-44-12.json"
        ssrf_json = temp_log_dir / "494.json"

        assert fit_json.exists()
        assert uddf_json.exists()
        assert ssrf_json.exists()

        # Read one of the JSON files and verify its contents
        import json
        with open(fit_json, "r") as f:
            waypoints = json.load(f)

        assert isinstance(waypoints, list)
        assert len(waypoints) > 0

        # Verify keys and formats
        first_wp = waypoints[0]
        assert "timestamp" in first_wp
        assert "depth" in first_wp
        assert isinstance(first_wp["timestamp"], str)
        assert isinstance(first_wp["depth"], float)

        # Verify time format (should not raise ValueError)
        datetime.strptime(first_wp["timestamp"], "%Y-%m-%d %H:%M:%S")
