"""
Color page live preview (ui_rework.md Pass 2, ported to the QML backend per
qml_development.md's Toga-removal cutover): _first_source_file()'s
directory-vs-single-file resolution, _extract_preview_frame()'s frame-10 (or
last-available-frame fallback) extraction, and real dive-log-matched
telemetry (EXIF/creation-date matching for photos, the scrub slider
re-seeking + re-matching together for video - mirrors the HUD Designer
tab's own dive-matching mechanism).

Driven against ColorBackend.__new__(ColorBackend) + PySide6's own
QObject.__init__ (skips ColorBackend.__init__'s body - which reads real
settings.json and does real file IO on construction, by design for
production use - so tests get a blank, isolated instance instead, same
intent as the old Toga UWMediaApp.__new__(UWMediaApp) trick). Plain
QObject.__new__() without also calling QObject.__init__() leaves the
underlying C++ object unusable ("Signal source has been deleted" on the
first emit) - confirmed empirically, the one real mechanical difference
from the old plain-Python UWMediaApp.__new__() pattern this file used to
use. No QApplication instance needed - plain signal emission with no
receivers works fine without one.

_load_dive_logs (called internally by _extract_preview_frame) rebuilds
dive_manager from disk based on logs_text - monkeypatched to a no-op in
the dive-matching tests below so a directly-injected fake DiveManager
survives the call, same effect as the old test never routing through an
equivalent load step.
"""
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import numpy as np
import pytest
from PySide6.QtCore import QObject

from metadata.exif import MetadataHandler
from models.dive import Dive, Waypoint
from models.manager import DiveManager
from uwmedia.backends.color_backend import PREVIEW_WORKING_WIDTH, ColorBackend

BASE_DIR = Path(__file__).parent.parent
TEST_DATA_DIR = BASE_DIR / "test_data" / "release_test"
TMP_DIR = BASE_DIR / "test_data" / "test_results" / "test_color_preview_tmp"


def make_fake_backend(source_value=""):
    app = ColorBackend.__new__(ColorBackend)
    QObject.__init__(app)  # valid QObject, but skips ColorBackend.__init__'s real-settings reads
    app._source_text = source_value
    app._logs_text = ""
    app.preview_frame = None
    app.preview_view_w = float(PREVIEW_WORKING_WIDTH)
    app.preview_view_h = float(PREVIEW_WORKING_WIDTH) * 9.0 / 16.0
    app.preview_video_cap = None
    app.preview_video_fps = 30.0
    app.preview_creation_date = None
    app.preview_current_dive = None
    app.preview_current_waypoint = None
    app.dive_manager = DiveManager()
    app._preview_revision = 0
    app._scrub_enabled = False
    app._scrub_min = 0
    app._scrub_max = 0
    app._scrub_value = 0
    app._scrub_time_text = "--"
    return app


@pytest.fixture(scope="module", autouse=True)
def setup_tmp_dir():
    if TMP_DIR.exists():
        shutil.rmtree(TMP_DIR)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    yield
    shutil.rmtree(TMP_DIR, ignore_errors=True)


def write_short_video(path, num_frames, size=(64, 48), fourcc="mp4v"):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*fourcc), 10.0, size)
    for i in range(num_frames):
        # Distinct flat color per frame index so the picked frame is
        # identifiable later purely from its pixel content.
        frame = np.full((size[1], size[0], 3), 0, dtype=np.uint8)
        frame[:, :, 0] = (i * 20) % 256  # B channel encodes frame index
        writer.write(frame)
    writer.release()


# --- _first_source_file: directory vs single file, sorted, dotfiles skipped

def test_first_source_file_picks_sorted_first_in_directory():
    src_dir = TMP_DIR / "dir_source"
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / ".hidden.mp4").write_bytes(b"not a real video")
    (src_dir / "b_second.jpg").write_bytes(b"fake")
    (src_dir / "a_first.jpg").write_bytes(b"fake")

    app = make_fake_backend(str(src_dir))
    result = app._first_source_file()
    assert result == src_dir / "a_first.jpg"


def test_first_source_file_single_file():
    single_file = TEST_DATA_DIR / "DSC03491.JPG"
    assert single_file.exists()
    app = make_fake_backend(str(single_file))
    assert app._first_source_file() == single_file


def test_first_source_file_empty_or_missing():
    assert make_fake_backend("")._first_source_file() is None
    assert make_fake_backend(str(TMP_DIR / "does_not_exist"))._first_source_file() is None


# --- _extract_preview_frame: frame 10, and <10-frame fallback --------------

def test_extract_preview_frame_uses_frame_10_for_a_long_video():
    video_path = TMP_DIR / "long.mp4"
    write_short_video(video_path, num_frames=20)

    app = make_fake_backend(str(video_path))
    app._extract_preview_frame()

    assert app.preview_frame is not None
    assert app.preview_frame.shape[1] == PREVIEW_WORKING_WIDTH
    # Frame 10's B channel was written as (10*20) % 256 == 200.
    assert app.preview_frame[0, 0, 0] == pytest.approx(200, abs=5)


def test_extract_preview_frame_falls_back_to_last_frame_when_short():
    video_path = TMP_DIR / "short.mp4"
    write_short_video(video_path, num_frames=4)

    app = make_fake_backend(str(video_path))
    app._extract_preview_frame()

    assert app.preview_frame is not None
    # Only 4 frames (indices 0-3) exist; frame 10 doesn't - must fall back
    # to the last one. Frame 3's B channel was written as (3*20) % 256 == 60.
    assert app.preview_frame[0, 0, 0] == pytest.approx(60, abs=5)


def test_extract_preview_frame_loads_still_image_directly():
    photo_path = TEST_DATA_DIR / "DSC03491.JPG"
    assert photo_path.exists()

    app = make_fake_backend(str(photo_path))
    app._extract_preview_frame()

    assert app.preview_frame is not None
    assert app.preview_frame.shape[1] == PREVIEW_WORKING_WIDTH


def test_extract_preview_frame_no_source_clears_preview():
    app = make_fake_backend("")
    app.preview_frame = np.zeros((10, 10, 3), dtype=np.uint8)
    app._extract_preview_frame()
    assert app.preview_frame is None


# --- real dive-matched telemetry: EXIF/creation-date matching, scrub slider

def _make_dive(start_time, seconds_offsets):
    waypoints = [
        Waypoint(
            timestamp=start_time + timedelta(seconds=t),
            time_since_start=t,
            depth=float(t),
            temp=20.0,
        )
        for t in seconds_offsets
    ]
    return Dive(
        start_time=start_time,
        end_time=start_time + timedelta(seconds=seconds_offsets[-1]),
        waypoints=waypoints,
        log_filename="test.uddf",
        device="TestComputer",
        manufactor="Test",
    )


def test_extract_preview_frame_matches_real_waypoint_for_video(monkeypatch):
    fixed_date = datetime(2026, 1, 1, 8, 0, 0)
    monkeypatch.setattr(MetadataHandler, "get_local_creation_date", lambda self, path: fixed_date)
    monkeypatch.setattr(ColorBackend, "_load_dive_logs", lambda self: None)

    video_path = TMP_DIR / "matched.mp4"
    write_short_video(video_path, num_frames=20)  # 10 fps -> frame 10 = 1.0s elapsed

    app = make_fake_backend(str(video_path))
    app.dive_manager.add_dives([_make_dive(fixed_date, [0, 1, 2, 3])])

    app._extract_preview_frame()

    assert app.preview_current_dive is not None
    # frame 10 at 10fps -> elapsed 1.0s -> first waypoint with timestamp >= +1.0s
    assert app.preview_current_waypoint.time_since_start == 1


def test_extract_preview_frame_matches_real_waypoint_for_photo(monkeypatch):
    fixed_date = datetime(2026, 1, 1, 8, 0, 0)
    monkeypatch.setattr(MetadataHandler, "get_local_creation_date", lambda self, path: fixed_date)
    monkeypatch.setattr(ColorBackend, "_load_dive_logs", lambda self: None)

    photo_path = TEST_DATA_DIR / "DSC03491.JPG"
    assert photo_path.exists()

    app = make_fake_backend(str(photo_path))
    app.dive_manager.add_dives([_make_dive(fixed_date, [0, 1, 2, 3])])

    app._extract_preview_frame()

    # Photo -> elapsed always 0 -> matches the very first waypoint.
    assert app.preview_current_waypoint.time_since_start == 0
    assert app.scrubEnabled is False


def test_extract_preview_frame_no_matching_dive_leaves_waypoint_none(monkeypatch):
    fixed_date = datetime(2026, 1, 1, 8, 0, 0)
    monkeypatch.setattr(MetadataHandler, "get_local_creation_date", lambda self, path: fixed_date)
    monkeypatch.setattr(ColorBackend, "_load_dive_logs", lambda self: None)

    photo_path = TEST_DATA_DIR / "DSC03491.JPG"
    app = make_fake_backend(str(photo_path))
    # dive_manager left empty - nothing to match against
    app._extract_preview_frame()

    assert app.preview_current_dive is None
    assert app.preview_current_waypoint is None


def test_time_change_reseeks_frame_and_rematches_waypoint(monkeypatch):
    fixed_date = datetime(2026, 1, 1, 8, 0, 0)
    monkeypatch.setattr(MetadataHandler, "get_local_creation_date", lambda self, path: fixed_date)
    monkeypatch.setattr(ColorBackend, "_load_dive_logs", lambda self: None)

    video_path = TMP_DIR / "scrub.mp4"
    write_short_video(video_path, num_frames=20)  # 10 fps

    app = make_fake_backend(str(video_path))
    app.dive_manager.add_dives([_make_dive(fixed_date, [0, 1, 2, 3])])
    app._extract_preview_frame()
    assert app.preview_current_waypoint.time_since_start == 1

    # Move the slider to frame 15 -> elapsed 1.5s -> first waypoint >= +1.5s is t=2.
    app.onScrubChanged(15)

    # Frame 15's B channel was written as (15*20) % 256 == 300 % 256 == 44.
    assert app.preview_frame[0, 0, 0] == pytest.approx(44, abs=5)
    assert app.preview_current_waypoint.time_since_start == 2
    assert app.scrubTimeText == str(timedelta(seconds=1))
