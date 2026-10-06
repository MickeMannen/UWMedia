"""Pre-release validation on the full-size media in test_data/release_test
(4K video, 20 MB photos) and real dive logs: metadata, parsers, colour
correction, overlays, --render-log and --export-json end to end.

Run it with `tests/run_tests.sh 3` (or 4, everything); plain `pytest`
skips it. Its outputs stay in test_data/test_results/release_test for a
look afterwards, and are replaced on the next run."""
import json
import shutil
from datetime import datetime

import pytest

from conftest import LOGS_DIR, RELEASE_MEDIA, REPO_ROOT, TEST_DATA, run_cli
from metadata.exif import MetadataHandler
from parsers.garmin import GarminParser
from parsers.uddf import UDDFParser

TEST_DATA_DIR = RELEASE_MEDIA
FIT_DIR = LOGS_DIR / "fit"
UDDF_DIR = LOGS_DIR / "uddf"
SSRF_DIR = LOGS_DIR / "ssrf"
OUTPUT_DIR = TEST_DATA / "test_results" / "release_test"
OVERLAYS_DIR = REPO_ROOT / "overlays"

pytestmark = pytest.mark.release


@pytest.fixture(scope="session", autouse=True)
def setup_output_dir():
    """A fresh output folder for this run."""
    shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
    OUTPUT_DIR.mkdir(parents=True)
    yield


def _cli(*args):
    result = run_cli(*args)
    assert result.returncode == 0, f"cli_main.py {' '.join(map(str, args))} failed:\n{result.stderr[-2000:]}"
    return result


class TestRelease:
    """End-to-end checks on the full-size media (whole clips, not segments)."""

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
        """Verify video color correction (fast LUT path)."""
        src = TEST_DATA_DIR / "20251019_M0284.MP4"
        cmd = [
            str(src), str(OUTPUT_DIR),
            "--color", "--filename-format", "release_test_test05_color",
            "--hw-accel"
        ]
        _cli(*cmd)

        found = list(OUTPUT_DIR.glob("release_test_test05_color.mp4"))
        assert len(found) == 1

    def test_06_color_correction_photo(self):
        """Verify photo color correction works on all JPGs in release_test directory."""
        for f in OUTPUT_DIR.glob("release_test_test06_color_*.jpg"):
            try: f.unlink()
            except Exception: pass

        i = 0
        for file in sorted(TEST_DATA_DIR.glob("*.JPG")):
            i += 1
            cmd = [
                str(file), str(OUTPUT_DIR),
                "--color", "--filename-format", f"release_test_test06_color_{file.stem}"
            ]
            _cli(*cmd)

        found = list(OUTPUT_DIR.glob("release_test_test06_color_*.jpg"))
        assert len(found) == i

    def test_06c_color_correction_photo_profiles(self):
        """Verify photo color correction profiles (vivid, subtle) are correctly parsed and run."""
        file = TEST_DATA_DIR / "DSC03491.JPG"
        for f in OUTPUT_DIR.glob("release_test_test06c_*.jpg"):
            try: f.unlink()
            except Exception: pass

        for profile in ["vivid", "subtle"]:
            cmd = [
                str(file), str(OUTPUT_DIR),
                "--color", profile, "--filename-format", f"release_test_test06c_{profile}"
            ]
            _cli(*cmd)
            found = list(OUTPUT_DIR.glob(f"release_test_test06c_{profile}_*.jpg"))
            assert len(found) == 1

    def test_05b_color_correction_video_profiles(self):
        """Verify video color correction profiles."""
        src = TEST_DATA_DIR / "20251019_M0284.MP4"
        for profile in ["vivid", "subtle"]:
            cmd = [
                str(src), str(OUTPUT_DIR),
                "--color", profile, "--filename-format", f"release_test_test05_profile_{profile}",
                "--hw-accel"
            ]
            _cli(*cmd)
            found = list(OUTPUT_DIR.glob(f"release_test_test05_profile_{profile}.mp4"))
            assert len(found) == 1

    # 5. Color Correction with Overlay
    def test_07_overlay_video(self):
        """Verify video overlay works for different layouts."""
        src = TEST_DATA_DIR / "DJI_20260502110658_0002_D_A001.MP4"
        logs = FIT_DIR

        layouts = [OVERLAYS_DIR / "Garmin_x50_simple.zip", OVERLAYS_DIR / "generic_depth_temp.zip"]

        target_list = []
        for layout in layouts:
            target_list.append(layout.stem)
            cmd = [
                str(src), str(OUTPUT_DIR),
                "--color", "--layout", str(layout), "--logs", str(logs),
                "--filename-format", f"release_test_test07_{layout.stem}",
                "--hw-accel"
            ]
            _cli(*cmd)

        for t in target_list:
            n = len(list(OUTPUT_DIR.glob(f"release_test_test07_{t}.mp4")))
            assert n == 1

    def test_08_overlay_photo(self):
        """Verify photo layout overlays work for different layout styles."""
        src = TEST_DATA_DIR / "DSC03491.JPG"
        layouts = [OVERLAYS_DIR / "Garmin_x50_simple.zip", OVERLAYS_DIR / "generic_depth_temp.zip"]
        logs = FIT_DIR
        target_list = []

        for f in OUTPUT_DIR.glob("release_test_test08_*.jpg"):
            try: f.unlink()
            except Exception: pass

        for layout in layouts:
            target_list.append(layout.stem)
            cmd = [
                str(src), str(OUTPUT_DIR),
                "--color", "--layout", str(layout), "--logs", str(logs),
                "--filename-format", f"release_test_test08_{layout.stem}", "--hw-accel"
            ]
            _cli(*cmd)

        for t in target_list:
            n = len(list(OUTPUT_DIR.glob(f"release_test_test08_{t}_*.jpg")))
            assert n == 1

    # 6. Standalone Log Rendering
    def test_09_render_log_fit(self):
        """Verify standalone telemetry video generation from Garmin FIT log files."""
        log = FIT_DIR / "488 Phuket, Camera Bay.fit"

        for file in OVERLAYS_DIR.glob("*.zip"):
            output_file = OUTPUT_DIR / f"release_test_render_log_{log.stem}_{file.stem}.mp4"

            cmd = [
                str(output_file),
                "--render-log", str(log), "20",  # Limit waypoints to speed up test execution
                "--layout", str(file), "--hw-accel"
            ]
            _cli(*cmd)
            assert output_file.exists()

    def test_10_render_log_uddf(self):
        """Verify standalone telemetry video generation from UDDF log files."""
        log = UDDF_DIR / "Perdix 2 453 2025-10-19 16-44-12.uddf"
        layout = OVERLAYS_DIR / "generic_depth_temp.zip"
        output_file = OUTPUT_DIR / f"release_test_render_log_{log.stem}_generic.mp4"

        cmd = [
            str(output_file),
            "--render-log", str(log), "20",  # Limit waypoints
            "--layout", str(layout)
        ]
        _cli(*cmd)
        assert output_file.exists()

    def test_11_overlay_photo(self):
        """Verify photo overlays with SSRF logs."""
        src = TEST_DATA_DIR / "DSC06422.JPG"
        layout = OVERLAYS_DIR / "generic_depth_temp.zip"
        logs = SSRF_DIR
        cmd = [
            str(src), str(OUTPUT_DIR),
            "--color", "--layout", str(layout), "--logs", str(logs),
            "--filename-format", "release_test_test11_overlay_generic"
        ]
        _cli(*cmd)

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
            "--export-json", str(temp_log_dir)
        ]
        _cli(*cmd)

        fit_json = temp_log_dir / "488 Phuket, Camera Bay.json"
        uddf_json = temp_log_dir / "Perdix 2 453 2025-10-19 16-44-12.json"
        ssrf_json = temp_log_dir / "494.json"

        assert fit_json.exists()
        assert uddf_json.exists()
        assert ssrf_json.exists()

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

        shutil.rmtree(temp_log_dir)
