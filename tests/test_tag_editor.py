"""
The Tag Editor: the shared helpers in utils/tag_editor.py and the page
backend (uwmedia/backends/tag_editor_backend.py). Every write goes to copies
of the fixture media in tmp_path. The folder dialog is stubbed, so no window
opens.
"""
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from conftest import DJI_CLIP, PHOTO, SONY_CLIP
from metadata.exif import MetadataHandler
import uwmedia.backends.tag_editor_backend as teb
from uwmedia.backends.tag_editor_backend import TagEditorBackend
from utils.tag_editor import (
    TZ_MODE_OPTIONS,
    TZ_OFFSETS,
    apply_batch_timezone_to_file,
    calculate_dji_datetimes,
    local_tz_offset_string,
    parse_date_from_filename,
)

KEEP_LOCAL, FROM_UTC = TZ_MODE_OPTIONS
# The DJI fixture's OriginalFilePath names 10:06:59 local; its CreateDate is 03:06:59 UTC.
DJI_FIXED = {
    "QuickTime:CreationDate": "2026:05:02 10:06:59+07:00",
    "QuickTime:CreateDate": "2026:05:02 03:06:59",
    "EXIF:DateTimeOriginal": "2026:05:02 10:06:59",
    "EXIF:CreateDate": "2026:05:02 10:06:59",
}


# ---------------------------------------------------------------------------
# utils/tag_editor.py
# ---------------------------------------------------------------------------

def test_local_tz_offset_string_matches_the_system_offset():
    td = datetime.now().astimezone().utcoffset()
    mins = int(td.total_seconds() // 60)
    expected = f"{'+' if mins >= 0 else '-'}{abs(mins) // 60:02}:{abs(mins) % 60:02}"
    assert local_tz_offset_string() == expected


@pytest.mark.parametrize("name, expected", [
    ("DJI_20260502100659_0002_D.MP4", datetime(2026, 5, 2, 10, 6, 59)),
    ("DJI_20260502_100659.MP4", datetime(2026, 5, 2, 10, 6, 59)),
    ("IMG_2025-10-19_112233.jpg", datetime(2025, 10, 19, 11, 22, 33)),
    ("C0042.MP4", None),
    ("DJI_20261399_250000.MP4", None),  # not a real date
])
def test_parse_date_from_filename(name, expected):
    assert parse_date_from_filename(Path(name)) == expected


def test_dji_datetimes_from_the_filename_when_original_path_is_missing():
    tags = {"QuickTime:CreateDate": "2026-05-02 03:06:59"}
    got = calculate_dji_datetimes(Path("DJI_20260502100659_0002_D.MP4"), tags)
    assert got == DJI_FIXED


@pytest.mark.parametrize("name, tags", [
    ("C0042.MP4", {"QuickTime:CreateDate": "2026:05:02 03:06:59"}),  # not a DJI name
    ("DJI_20260502100659.MP4", {}),  # no UTC time to compare with
    ("DJI_20260502100659.MP4", {"QuickTime:CreateDate": "garbage"}),
    ("DJI_20261340100659.MP4", {"QuickTime:CreateDate": "2026:05:02 03:06:59"}),
])
def test_dji_datetimes_give_up_without_usable_data(name, tags):
    assert calculate_dji_datetimes(Path(name), tags) is None


def test_dji_offsets_round_to_the_nearest_quarter_hour():
    # 5:45 ahead plus 40 s of clock drift -> Nepal's +05:45
    tags = {"QuickTime:CreateDate": "2026:05:02 04:21:19"}
    got = calculate_dji_datetimes(Path("DJI_20260502100659.MP4"), tags)
    assert got["QuickTime:CreationDate"].endswith("+05:45")
    tags = {"QuickTime:CreateDate": "2026:05:02 15:06:59"}
    got = calculate_dji_datetimes(Path("DJI_20260502100659.MP4"), tags)
    assert got["QuickTime:CreationDate"].endswith("-05:00")


@pytest.fixture
def meta():
    return MetadataHandler()


def _copy(src, folder, name=None):
    dest = folder / (name or src.name)
    shutil.copy2(src, dest)
    return dest


@pytest.mark.render
def test_batch_timezone_recalculates_a_video_from_utc(tmp_path, meta):
    clip = _copy(SONY_CLIP, tmp_path)  # 02:21:31 UTC
    tz = timezone(timedelta(hours=-3))
    assert apply_batch_timezone_to_file(meta, clip, FROM_UTC, tz, "-03:00")
    tags = meta.get_tags(clip, ["QuickTime:CreationDate", "QuickTime:CreateDate"])
    assert tags["QuickTime:CreationDate"] == "2025:10:18 23:21:31-03:00"
    assert tags["QuickTime:CreateDate"] == "2025:10:19 02:21:31"  # UTC untouched


@pytest.mark.render
def test_batch_timezone_keeps_a_photos_local_time(tmp_path, meta):
    photo = _copy(PHOTO, tmp_path)  # 09:15:48 local, +08:00
    tz = timezone(timedelta(hours=2))
    assert apply_batch_timezone_to_file(meta, photo, KEEP_LOCAL, tz, "+02:00")
    tags = meta.get_tags(photo, ["EXIF:DateTimeOriginal", "EXIF:OffsetTimeOriginal", "EXIF:OffsetTime"])
    assert tags["EXIF:DateTimeOriginal"] == "2025:12:03 09:15:48"
    assert tags["EXIF:OffsetTimeOriginal"] == "+02:00"
    assert tags["EXIF:OffsetTime"] == "+02:00"


class _NoDates:
    """A metadata handler that finds no dates, so the helpers fall back."""

    def __init__(self):
        self.written = None

    def get_local_creation_date(self, path):
        raise ValueError("no date")

    def get_standardized_creation_date(self, path):
        raise ValueError("no date")

    def get_tags(self, path, names):
        return {}

    def set_tags(self, path, tags):
        self.written = tags


def test_batch_timezone_falls_back_to_the_filename(tmp_path):
    f = tmp_path / "DJI_20260502100659.jpg"
    f.write_bytes(b"")
    handler = _NoDates()
    tz = timezone(timedelta(hours=7))
    assert apply_batch_timezone_to_file(handler, f, FROM_UTC, tz, "+07:00")
    assert handler.written["EXIF:DateTimeOriginal"] == "2026:05:02 10:06:59"
    assert handler.written["EXIF:OffsetTime"] == "+07:00"


def test_batch_timezone_falls_back_to_the_file_time(tmp_path):
    f = tmp_path / "clip.mov"
    f.write_bytes(b"")
    handler = _NoDates()
    tz = timezone(timedelta(hours=1))
    assert apply_batch_timezone_to_file(handler, f, KEEP_LOCAL, tz, "+01:00")
    local = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y:%m:%d %H:%M:%S")
    assert handler.written["QuickTime:CreationDate"] == local + "+01:00"
    assert handler.written["QuickTime:TimeZone"] == "+01:00"


# ---------------------------------------------------------------------------
# uwmedia/backends/tag_editor_backend.py
# ---------------------------------------------------------------------------

@pytest.fixture
def media_dir(tmp_path):
    folder = tmp_path / "media"
    folder.mkdir()
    _copy(DJI_CLIP, folder, "b_drone.mp4")
    _copy(PHOTO, folder, "a_photo.JPG")
    (folder / "notes.txt").write_text("not media")
    return folder


@pytest.fixture
def backend(settings_file, monkeypatch, media_dir):
    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(media_dir)))
    return TagEditorBackend()


def test_backend_offers_the_local_offset_first_when_it_is_unusual(settings_file, monkeypatch):
    monkeypatch.setattr(teb, "local_tz_offset_string", lambda: "+08:15")
    b = TagEditorBackend()
    assert b.tzOptionList[0] == "+08:15"
    assert b.currentTz == "+08:15"
    assert len(b.tzOptionList) == len(TZ_OFFSETS) + 1
    assert b.tzModeList == TZ_MODE_OPTIONS
    assert [g["tag"] for g in b.tagGuide] == list(b.tagValues)


def test_backend_with_no_folder_does_nothing(settings_file):
    b = TagEditorBackend()
    assert b.dirLabel == "No directory selected"
    assert b.fileNames == []
    b.writeTags()
    b.revertChanges()
    b.viewAllMetadata()
    b.onUpdateAllTagsClicked()
    assert b.statusText == "No files in the list to update."
    b.onApplyTimezoneClicked()
    assert b.statusText == "No files in the list to update."


@pytest.mark.render
def test_backend_lists_media_and_shows_dji_fixes(backend, media_dir, settings_file):
    backend.selectDirectory()
    assert backend.dirLabel == str(media_dir)
    assert backend.fileNames == ["a_photo.JPG", "b_drone.mp4"]  # sorted, no .txt
    assert backend.selectedFileName == "a_photo.JPG"
    assert backend.viewMetadataEnabled
    assert not backend.djiVisible
    assert backend.tagValues["EXIF:DateTimeOriginal"] == "2025:12:03 09:15:48"
    assert str(media_dir) in json.loads(settings_file.read_text())["fields"].values()  # folder remembered

    backend.selectFileAtIndex(1)
    assert backend.djiVisible
    assert backend.tagValues == DJI_FIXED

    backend.selectFileAtIndex(5)
    assert not backend.viewMetadataEnabled


@pytest.mark.render
def test_backend_writes_edited_tags_and_reverts(backend, media_dir):
    backend.selectDirectory()
    backend.writeTags()
    assert backend.statusText == "No changes detected to update."

    backend.setTagValue("EXIF:DateTimeOriginal", "2025:12:03 10:00:00")
    backend.revertChanges()
    assert backend.tagValues["EXIF:DateTimeOriginal"] == "2025:12:03 09:15:48"

    backend.setTagValue("EXIF:DateTimeOriginal", " 2025:12:03 10:00:00 ")
    backend.writeTags()
    assert backend.statusText == "Updated 1 tags successfully."
    on_disk = MetadataHandler().get_tags(media_dir / "a_photo.JPG", ["EXIF:DateTimeOriginal"])
    assert on_disk["EXIF:DateTimeOriginal"] == "2025:12:03 10:00:00"


@pytest.mark.render
def test_backend_update_all_fixes_dji_files_after_confirming(backend, media_dir):
    backend.selectDirectory()
    asked = []
    backend.confirmRequested.connect(lambda title, text: asked.append(title))
    backend.onUpdateAllTagsClicked()
    assert asked == ["Confirm Update All"]

    backend.cancelPendingAction()
    backend.confirmPendingAction()  # nothing pending any more
    clip = media_dir / "b_drone.mp4"
    assert not MetadataHandler().get_tags(clip, ["EXIF:DateTimeOriginal"])["EXIF:DateTimeOriginal"]

    backend.onUpdateAllTagsClicked()
    backend.confirmPendingAction()
    assert backend.statusText == "Successfully updated 1 files."
    assert not backend.busy
    # MP4 files hold no EXIF group, so exiftool stores only the QuickTime dates.
    tags = MetadataHandler().get_tags(clip, ["QuickTime:CreationDate", "QuickTime:CreateDate"])
    assert tags["QuickTime:CreationDate"] == DJI_FIXED["QuickTime:CreationDate"]
    assert tags["QuickTime:CreateDate"] == DJI_FIXED["QuickTime:CreateDate"]


@pytest.mark.render
def test_backend_applies_a_timezone_to_every_file(backend, media_dir):
    backend.selectDirectory()
    backend.currentTz = "nonsense"
    backend.onApplyTimezoneClicked()
    assert backend.statusText == "Invalid timezone format: 'nonsense'."

    backend.currentTz = "+03:00"
    backend.currentTzMode = KEEP_LOCAL
    backend.onApplyTimezoneClicked()
    backend.confirmPendingAction()
    assert backend.statusText == "Successfully updated timezone for 2 files."
    meta = MetadataHandler()
    assert meta.get_tags(media_dir / "a_photo.JPG", ["EXIF:OffsetTime"])["EXIF:OffsetTime"] == "+03:00"
    creation = meta.get_tags(media_dir / "b_drone.mp4", ["QuickTime:CreationDate"])["QuickTime:CreationDate"]
    assert creation.endswith("+03:00")


@pytest.mark.render
def test_backend_metadata_viewer_filters_rows(backend):
    backend.selectDirectory()
    backend.viewAllMetadata()
    assert backend.metadataVisible
    assert backend.metadataTitle == "Metadata Viewer - a_photo.JPG"
    all_rows = backend.metadataRows
    assert any(r["tag"] == "EXIF:DateTimeOriginal" for r in all_rows)
    backend.metadataFilter = "offsettime"
    rows = backend.metadataRows
    assert rows and len(rows) < len(all_rows)
    assert all("offsettime" in r["tag"].lower() for r in rows)
