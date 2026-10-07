"""metadata/exif.py: MetadataHandler, the code that copies and rewrites the
metadata of users' files. Real exiftool round trips (write, then read the
tag back) for copy_all / set_quicktime_tags / set_xmp_data / get_tags /
set_tags on copies of the fixture media in tmp_path, and the date and
time-zone parsing in get_timezone_offset / get_standardized_creation_date /
get_local_creation_date fed with hand-made metadata dicts for the formats the
fixtures don't carry."""
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PIL import Image

from conftest import DJI_CLIP, PHOTO, SONY_CLIP
from metadata.exif import MetadataHandler
from utils.tool_paths import get_ffmpeg_path


@pytest.fixture
def handler():
    return MetadataHandler()


@pytest.fixture
def bare_mp4(tmp_path):
    """A one-frame MP4 with no dates (ffmpeg writes 0000:00:00 00:00:00),
    standing in for a freshly rendered output before copy_all runs."""
    path = tmp_path / "bare.mp4"
    subprocess.run([str(get_ffmpeg_path()), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=1",
                    "-frames:v", "1", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


@pytest.fixture
def bare_jpeg(tmp_path):
    """A JPEG with no EXIF at all, standing in for a rendered photo."""
    path = tmp_path / "bare.jpg"
    Image.new("RGB", (32, 32), (10, 60, 120)).save(path, quality=90)
    return path


def fake_metadata(monkeypatch, handler, meta):
    """get_metadata returns `meta` (None = exiftool could not read the file)."""
    monkeypatch.setattr(handler, "get_metadata", lambda path: meta)


# --- get_metadata / get_tags / set_tags on real files ------------------------

def test_get_metadata_reads_grouped_tags(handler):
    meta = handler.get_metadata(SONY_CLIP)
    assert meta["QuickTime:CreationDate"] == "2025:10:19 10:21:31+08:00"
    assert meta["QuickTime:CreateDate"] == "2025:10:19 02:21:31"


def test_get_metadata_missing_file_returns_none(handler, tmp_path):
    assert handler.get_metadata(tmp_path / "missing.mp4") is None


def test_get_tags_exact_suffix_and_missing(handler):
    tags = handler.get_tags(PHOTO, ["EXIF:DateTimeOriginal", "SubSecTimeOriginal", "XMP:Title"])
    # Exact group:name match
    assert tags["EXIF:DateTimeOriginal"] == "2025:12:03 09:15:48"
    # No group asked for: exiftool returns "EXIF:SubSecTimeOriginal", found by suffix
    assert tags["SubSecTimeOriginal"] == "980"
    # Absent tag -> empty string, never None
    assert tags["XMP:Title"] == ""


def test_get_tags_values_are_strings(handler):
    # exiftool's JSON gives numbers as numbers; get_tags promises strings
    tags = handler.get_tags(PHOTO, ["EXIF:SubSecTimeOriginal"])
    assert tags == {"EXIF:SubSecTimeOriginal": "980"}


def test_get_tags_missing_file_returns_empty_strings(handler, tmp_path):
    assert handler.get_tags(tmp_path / "missing.jpg", ["EXIF:Make", "EXIF:Model"]) == {"EXIF:Make": "", "EXIF:Model": ""}


def test_set_tags_round_trip_on_photo(handler, tmp_path):
    photo = tmp_path / "photo.jpg"
    shutil.copy2(PHOTO, photo)
    handler.set_tags(photo, {"EXIF:DateTimeOriginal": "2024:01:02 03:04:05", "EXIF:OffsetTimeOriginal": "-03:30"})

    tags = handler.get_tags(photo, ["EXIF:DateTimeOriginal", "EXIF:OffsetTimeOriginal", "EXIF:Model"])
    assert tags == {"EXIF:DateTimeOriginal": "2024:01:02 03:04:05", "EXIF:OffsetTimeOriginal": "-03:30",
                    "EXIF:Model": "ILCE-6700"}  # untouched tags stay
    # -overwrite_original: no "photo.jpg_original" backup left next to it
    assert sorted(p.name for p in tmp_path.glob("photo*")) == ["photo.jpg"]


def test_set_tags_empty_leaves_file_untouched(handler, tmp_path):
    photo = tmp_path / "photo.jpg"
    shutil.copy2(PHOTO, photo)
    before = photo.read_bytes()
    handler.set_tags(photo, {})
    assert photo.read_bytes() == before


def test_set_tags_error_is_raised(handler, tmp_path):
    # The tag editor shows the error to the user, so it must not be swallowed
    with pytest.raises(Exception):
        handler.set_tags(tmp_path / "missing.jpg", {"EXIF:Make": "SONY"})


# --- set_quicktime_tags --------------------------------------------------------

def test_set_quicktime_tags_string_value(handler, bare_mp4):
    stdout, stderr = handler.set_quicktime_tags(bare_mp4, {"QuickTime:CreationDate": "2025:10:19 10:21:31-02:30"})
    assert "1 image files updated" in stdout
    assert handler.get_tags(bare_mp4, ["QuickTime:CreationDate"]) == {"QuickTime:CreationDate": "2025:10:19 10:21:31-02:30"}


def test_set_quicktime_tags_aware_datetime_gets_colon_offset(handler, bare_mp4):
    when = datetime(2026, 5, 2, 10, 6, 59, tzinfo=timezone(timedelta(hours=7)))
    handler.set_quicktime_tags(bare_mp4, {"QuickTime:CreationDate": when})
    # strftime gives +0700; exiftool must be handed +07:00
    assert handler.get_tags(bare_mp4, ["QuickTime:CreationDate"])["QuickTime:CreationDate"] == "2026:05:02 10:06:59+07:00"


def test_set_quicktime_tags_naive_datetime_written_unchanged(handler, bare_mp4):
    # No offset: the "insert a colon" step must not mangle the seconds
    handler.set_quicktime_tags(bare_mp4, {"QuickTime:CreateDate": datetime(2026, 5, 2, 3, 6, 59)})
    assert handler.get_tags(bare_mp4, ["QuickTime:CreateDate"])["QuickTime:CreateDate"] == "2026:05:02 03:06:59"


# --- set_xmp_data ----------------------------------------------------------------

def test_set_xmp_data_maps_sony_xml_tags(handler, bare_mp4):
    sony_xml = {
        "XML:LastUpdate": "2025:09:13 09:37:36+07:00",
        "XML:CreationDateValue": "2025:09:13 09:30:00+07:00",
        "XML:VideoFormatVideoFrameCaptureFps": "50p",
        "XML:DeviceManufacturer": "Sony",
        "XML:DeviceModelName": "ILCE-6700",
        "XML:LensModelName": "E PZ 16-50mm F3.5-5.6 OSS",
        "QuickTime:Duration": 2.0,  # not in the mapping: ignored
    }
    assert handler.set_xmp_data(sony_xml, bare_mp4) is True

    tags = handler.get_tags(bare_mp4, ["XMP:MetadataDate", "XMP:CreateDate", "XMP:VideoFrameRate",
                                       "XMP:Make", "XMP:Model", "XMP:Lens"])
    assert tags == {
        "XMP:MetadataDate": "2025:09:13 09:37:36+07:00",
        "XMP:CreateDate": "2025:09:13 09:30:00+07:00",
        "XMP:VideoFrameRate": "50",  # the trailing "p" is stripped
        "XMP:Make": "Sony",
        "XMP:Model": "ILCE-6700",
        "XMP:Lens": "E PZ 16-50mm F3.5-5.6 OSS",
    }


def test_set_xmp_data_fractional_seconds_and_iso_formats(handler, bare_mp4):
    handler.set_xmp_data({"XML:LastUpdate": "2025:09:13 09:37:36.50-05:00",
                          "XML:CreationDateValue": "2025-09-13T09:30:00+01:00"}, bare_mp4)
    tags = handler.get_tags(bare_mp4, ["XMP:MetadataDate", "XMP:CreateDate"])
    # The format keeps whole seconds only
    assert tags == {"XMP:MetadataDate": "2025:09:13 09:37:36-05:00", "XMP:CreateDate": "2025:09:13 09:30:00+01:00"}


def test_set_xmp_data_nothing_to_write(handler, bare_mp4):
    before = bare_mp4.read_bytes()
    # No mapped keys, an unparseable date
    assert handler.set_xmp_data({"QuickTime:CreateDate": "2025:01:01 00:00:00",
                                 "XML:CreationDateValue": "yesterday"}, bare_mp4) is False
    assert bare_mp4.read_bytes() == before


@pytest.mark.parametrize("data", [{"XML:DeviceModelName": 6700},
                                  {"XML:CreationDateValue": datetime(2025, 9, 13, 9, 30, tzinfo=timezone.utc)}])
def test_set_xmp_data_non_string_values(handler, bare_mp4, data):
    # Expected: a number for a text tag is skipped (or written as text), a
    # datetime is written; either way no crash
    handler.set_xmp_data(data, bare_mp4)


def test_set_xmp_data_date_without_offset(handler, bare_mp4):
    handler.set_xmp_data({"XML:CreationDateValue": "2025:09:13 09:37:36"}, bare_mp4)
    assert handler.get_tags(bare_mp4, ["XMP:CreateDate"])["XMP:CreateDate"].startswith("2025:09:13 09:37:36")


def test_date_str_to_datetime_formats(handler):
    plus7 = timezone(timedelta(hours=7))
    parse = handler._date_str_to_datetime
    assert parse("2025:09:13 09:37:36.25+07:00") == datetime(2025, 9, 13, 9, 37, 36, 250000, tzinfo=plus7)
    assert parse("2025:09:13 09:37:36") == datetime(2025, 9, 13, 9, 37, 36)
    assert parse("2025:09:13 09:37:36+07:00") == datetime(2025, 9, 13, 9, 37, 36, tzinfo=plus7)
    assert parse("2025-09-13 09:37:36") == datetime(2025, 9, 13, 9, 37, 36)
    assert parse("2025-09-13 09:37:36-02:30") == datetime(2025, 9, 13, 9, 37, 36,
                                                          tzinfo=timezone(-timedelta(hours=2, minutes=30)))
    assert parse("2025-09-13T09:37:36+07:00") == datetime(2025, 9, 13, 9, 37, 36, tzinfo=plus7)
    assert parse("2025-09-13T09:37:36Z") == datetime(2025, 9, 13, 9, 37, 36)
    # Matches the shape but is not a real date -> None, not an exception
    assert parse("2025:13:45 09:37:36") is None
    assert parse("not a date") is None


# --- copy_all --------------------------------------------------------------------

def test_copy_all_video_takes_offset_from_source(handler, bare_mp4):
    handler.copy_all(SONY_CLIP, bare_mp4)
    tags = handler.get_tags(bare_mp4, ["QuickTime:CreateDate", "QuickTime:CreationDate"])
    assert tags == {"QuickTime:CreateDate": "2025:10:19 02:21:31",
                    "QuickTime:CreationDate": "2025:10:19 10:21:31+08:00"}
    assert handler.get_timezone_offset(bare_mp4) == 8 * 60


def test_copy_all_forced_negative_offset(handler, bare_mp4):
    # The forced offset replaces the source's +07:00, local time unchanged
    handler.copy_all(DJI_CLIP, bare_mp4, force_tz_mins=-(2 * 60 + 30))
    assert handler.get_tags(bare_mp4, ["QuickTime:CreationDate"])["QuickTime:CreationDate"] == "2026:05:02 10:06:59-02:30"
    assert handler.get_timezone_offset(bare_mp4) == -150


def test_copy_all_forced_utc(handler, bare_mp4):
    # 0 is a real offset, not "no offset"
    handler.copy_all(DJI_CLIP, bare_mp4, force_tz_mins=0)
    assert handler.get_tags(bare_mp4, ["QuickTime:CreationDate"])["QuickTime:CreationDate"] == "2026:05:02 10:06:59+00:00"


def test_copy_all_custom_tags(handler, bare_mp4):
    handler.copy_all(SONY_CLIP, bare_mp4, custom_tags=["XMP:Title=Reef dive", "QuickTime:Make=Sony"])
    tags = handler.get_tags(bare_mp4, ["XMP:Title", "QuickTime:Make", "QuickTime:CreationDate"])
    assert tags == {"XMP:Title": "Reef dive", "QuickTime:Make": "Sony",
                    "QuickTime:CreationDate": "2025:10:19 10:21:31+08:00"}


def test_copy_all_photo_keeps_dates_offsets_and_subseconds(handler, bare_jpeg, tmp_path):
    handler.copy_all(PHOTO, bare_jpeg)
    tags = handler.get_tags(bare_jpeg, ["EXIF:DateTimeOriginal", "EXIF:OffsetTimeOriginal", "EXIF:SubSecTimeOriginal",
                                        "EXIF:Make", "EXIF:Model", "QuickTime:CreationDate"])
    assert tags == {"EXIF:DateTimeOriginal": "2025:12:03 09:15:48", "EXIF:OffsetTimeOriginal": "+08:00",
                    "EXIF:SubSecTimeOriginal": "980", "EXIF:Make": "SONY", "EXIF:Model": "ILCE-6700",
                    "QuickTime:CreationDate": ""}  # no QuickTime tags forced into a JPEG
    assert handler.get_local_creation_date(bare_jpeg) == datetime(2025, 12, 3, 9, 15, 48, 980000)
    assert sorted(p.name for p in tmp_path.glob("bare*")) == ["bare.jpg"]


def test_copy_all_does_not_copy_thumbnail(handler, tmp_path, bare_jpeg):
    # A source with an embedded thumbnail: the stale preview must not be copied
    # onto the colour-corrected output
    src = tmp_path / "with_thumb.jpg"
    shutil.copy2(PHOTO, src)
    thumb = tmp_path / "thumb.jpg"
    Image.new("RGB", (8, 8), (255, 0, 0)).save(thumb)
    subprocess.run([handler.exiftool_path or "exiftool", "-q", "-overwrite_original", f"-ThumbnailImage<={thumb}",
                    str(src)], check=True)
    assert handler.get_tags(src, ["EXIF:ThumbnailImage"])["EXIF:ThumbnailImage"] != ""

    handler.copy_all(src, bare_jpeg)
    tags = handler.get_tags(bare_jpeg, ["EXIF:ThumbnailImage", "EXIF:DateTimeOriginal"])
    assert tags == {"EXIF:ThumbnailImage": "", "EXIF:DateTimeOriginal": "2025:12:03 09:15:48"}


def test_copy_all_maps_source_xml_to_xmp(handler, bare_mp4, monkeypatch):
    real_get_metadata = handler.get_metadata

    def with_sony_xml(path):
        meta = real_get_metadata(path)
        if Path(path) == SONY_CLIP:
            meta["XML:CreationDateValue"] = "2025:10:19 10:21:31+08:00"
            meta["XML:DeviceModelName"] = "ILCE-6700"
        return meta

    monkeypatch.setattr(handler, "get_metadata", with_sony_xml)
    handler.copy_all(SONY_CLIP, bare_mp4)
    tags = handler.get_tags(bare_mp4, ["XMP:CreateDate", "XMP:Model"])
    assert tags == {"XMP:CreateDate": "2025:10:19 10:21:31+08:00", "XMP:Model": "ILCE-6700"}


# --- _parse_timezone ---------------------------------------------------------------

@pytest.mark.parametrize("value, minutes", [
    ("+02:00", 120), ("02:00", 120), ("+0530", 330), ("-03:30", -210), ("-00:00", 0),
    (480, 480), (-150.0, -150),
])
def test_parse_timezone(handler, value, minutes):
    assert handler._parse_timezone(value) == timezone(timedelta(minutes=minutes))


@pytest.mark.parametrize("value", [None, "", "Z", "UTC", "+2"])
def test_parse_timezone_unparseable(handler, value):
    assert handler._parse_timezone(value) is None


def test_parse_timezone_zero_minutes_is_utc(handler):
    assert handler._parse_timezone(0) == timezone.utc


# --- get_timezone_offset -------------------------------------------------------------

def test_timezone_offset_from_fixtures(handler):
    assert handler.get_timezone_offset(SONY_CLIP) == 480
    assert handler.get_timezone_offset(DJI_CLIP) == 420
    # The photo has only EXIF dates and OffsetTime*: no QuickTime offset to find
    assert handler.get_timezone_offset(PHOTO) is None


def test_timezone_offset_from_date_difference(handler, monkeypatch):
    # CreationDate without an offset: local minus UTC, rounded to 15 minutes
    fake_metadata(monkeypatch, handler, {"QuickTime:CreateDate": "2025:10:19 02:21:31",
                                         "QuickTime:CreationDate": "2025:10:19 07:52:20"})
    assert handler.get_timezone_offset(Path("x.mp4")) == 330


def test_timezone_offset_negative_difference_ungrouped_keys(handler, monkeypatch):
    fake_metadata(monkeypatch, handler, {"CreateDate": "2025:10:19 02:00:00", "CreationDate": "2025:10:18 22:00:00"})
    assert handler.get_timezone_offset(Path("x.mp4")) == -240


def test_timezone_offset_sony_timezone_fallback(handler, monkeypatch):
    # Dates unreadable -> the TimeZone tag decides
    fake_metadata(monkeypatch, handler, {"QuickTime:CreateDate": "garbage", "QuickTime:CreationDate": "also garbage",
                                         "QuickTime:TimeZone": "-05:00"})
    assert handler.get_timezone_offset(Path("x.mp4")) == -300
    fake_metadata(monkeypatch, handler, {"Timezone": "+09:30"})
    assert handler.get_timezone_offset(Path("x.mp4")) == 570


def test_timezone_offset_nothing_found(handler, monkeypatch):
    fake_metadata(monkeypatch, handler, None)
    assert handler.get_timezone_offset(Path("x.mp4")) is None
    fake_metadata(monkeypatch, handler, {"QuickTime:TimeZone": "local"})
    assert handler.get_timezone_offset(Path("x.mp4")) is None


# --- get_standardized_creation_date (UTC) ----------------------------------------------

def test_standardized_creation_date_from_fixtures(handler):
    utc = handler.get_standardized_creation_date(SONY_CLIP)
    assert utc == datetime(2025, 10, 19, 2, 21, 31, tzinfo=timezone.utc)
    assert utc.tzinfo == timezone.utc
    assert handler.get_standardized_creation_date(DJI_CLIP) == datetime(2026, 5, 2, 3, 6, 59, tzinfo=timezone.utc)


def test_standardized_creation_date_falls_back_to_create_date(handler, monkeypatch):
    # CreationDate without an offset can't be converted; CreateDate is UTC
    fake_metadata(monkeypatch, handler, {"CreationDate": "2025:10:19 10:21:31", "CreateDate": "2025:10:19 02:21:31"})
    assert handler.get_standardized_creation_date(Path("x.mp4")) == datetime(2025, 10, 19, 2, 21, 31, tzinfo=timezone.utc)
    fake_metadata(monkeypatch, handler, {"QuickTime:CreationDate": "broken", "QuickTime:CreateDate": "2025:10:19 02:21:31"})
    assert handler.get_standardized_creation_date(Path("x.mp4")) == datetime(2025, 10, 19, 2, 21, 31, tzinfo=timezone.utc)


def test_standardized_creation_date_errors(handler, monkeypatch):
    fake_metadata(monkeypatch, handler, None)
    with pytest.raises(ValueError, match="Could not extract"):
        handler.get_standardized_creation_date(Path("x.mp4"))
    fake_metadata(monkeypatch, handler, {"File:FileName": "x.mp4"})
    with pytest.raises(ValueError, match="No valid creation date"):
        handler.get_standardized_creation_date(Path("x.mp4"))


def test_standardized_creation_date_with_subseconds(handler, monkeypatch):
    fake_metadata(monkeypatch, handler, {"QuickTime:CreationDate": "2025:10:19 10:21:31.98+08:00"})
    assert handler.get_standardized_creation_date(Path("x.mp4")) == datetime(2025, 10, 19, 2, 21, 31,
                                                                             tzinfo=timezone.utc)


# --- get_local_creation_date (naive local) ------------------------------------------------

def test_local_creation_date_from_fixtures(handler):
    assert handler.get_local_creation_date(SONY_CLIP) == datetime(2025, 10, 19, 10, 21, 31)
    assert handler.get_local_creation_date(DJI_CLIP) == datetime(2026, 5, 2, 10, 6, 59)
    # Photo: DateTimeOriginal plus SubSecTimeOriginal 980 -> .980
    assert handler.get_local_creation_date(PHOTO) == datetime(2025, 12, 3, 9, 15, 48, 980000)


def test_local_creation_date_subseconds_in_string(handler, monkeypatch):
    fake_metadata(monkeypatch, handler, {"EXIF:DateTimeOriginal": "2025:12:03 09:15:48.05",
                                         "EXIF:SubSecTimeOriginal": "999"})  # the string's own wins
    assert handler.get_local_creation_date(Path("x.jpg")) == datetime(2025, 12, 3, 9, 15, 48, 50000)


def test_local_creation_date_other_subsec_tags(handler, monkeypatch):
    fake_metadata(monkeypatch, handler, {"DateTimeOriginal": "2025:12:03 09:15:48", "SubSecTime": 7})
    assert handler.get_local_creation_date(Path("x.jpg")) == datetime(2025, 12, 3, 9, 15, 48, 700000)
    # A subsecond tag with no digits is ignored
    fake_metadata(monkeypatch, handler, {"EXIF:CreateDate": "2025:12:03 09:15:48", "EXIF:SubSecTimeDigitized": "  "})
    assert handler.get_local_creation_date(Path("x.jpg")) == datetime(2025, 12, 3, 9, 15, 48)


def test_local_creation_date_from_utc_and_timezone(handler, monkeypatch):
    # No local date tag (or an unreadable one): UTC CreateDate shifted by TimeZone
    fake_metadata(monkeypatch, handler, {"QuickTime:CreationDate": "0000:00:00 00:00:00",
                                         "QuickTime:CreateDate": "2025:10:19 22:21:31", "TimeZone": "+08:00"})
    assert handler.get_local_creation_date(Path("x.mp4")) == datetime(2025, 10, 20, 6, 21, 31)
    # Without a time zone the UTC time is returned as is
    fake_metadata(monkeypatch, handler, {"CreateDate": "2025:10:19 22:21:31"})
    assert handler.get_local_creation_date(Path("x.mp4")) == datetime(2025, 10, 19, 22, 21, 31)


def test_local_creation_date_falls_back_to_mtime(handler, tmp_path, monkeypatch):
    # Zero CreateDate (ffmpeg's default) or no dates at all -> the file's mtime
    path = tmp_path / "notes.txt"
    path.write_text("no dates in here")
    mtime = datetime(2024, 2, 29, 12, 30, 15).timestamp()
    os.utime(path, (mtime, mtime))
    assert handler.get_local_creation_date(path) == datetime(2024, 2, 29, 12, 30, 15)

    fake_metadata(monkeypatch, handler, {"QuickTime:CreateDate": "0000:00:00 00:00:00"})
    assert handler.get_local_creation_date(path) == datetime(2024, 2, 29, 12, 30, 15)
    fake_metadata(monkeypatch, handler, {"QuickTime:CreateDate": "2025:99:99 00:00:00"})
    assert handler.get_local_creation_date(path) == datetime(2024, 2, 29, 12, 30, 15)


def test_local_creation_date_errors(handler, tmp_path, monkeypatch):
    fake_metadata(monkeypatch, handler, None)
    with pytest.raises(ValueError, match="Could not extract"):
        handler.get_local_creation_date(tmp_path / "x.mp4")
    # Metadata without dates and a file that is gone: nothing to fall back to
    fake_metadata(monkeypatch, handler, {"File:FileName": "x.mp4"})
    with pytest.raises(ValueError, match="No valid creation date"):
        handler.get_local_creation_date(tmp_path / "x.mp4")
