"""
Shared, GUI-toolkit-free logic for the metadata tag editor, used by the native
Toga Tag Editor section (uwmedia/app.py) and by tests/test_metadata.py.
"""
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Tags to manage, with metadata guidance shown next to each field.
TAG_GUIDE = [
    {
        "tag": "QuickTime:CreationDate",
        "tz": "Local Time + Offset",
        "example": "2026:05:21 06:58:22+08:00",
        "hint": "Primary date used by Apple Photos for sorting.",
    },
    {
        "tag": "QuickTime:CreateDate",
        "tz": "UTC (Universal Time)",
        "example": "2026:05:20 22:58:22",
        "hint": "Technical creation time, usually stored in UTC.",
    },
    {
        "tag": "EXIF:DateTimeOriginal",
        "tz": "Local Time (Naive)",
        "example": "2026:05:21 06:58:22",
        "hint": "Original capture time for photos.",
    },
    {
        "tag": "EXIF:CreateDate",
        "tz": "Local Time (Naive)",
        "example": "2026:05:21 06:58:22",
        "hint": "Standard digitized creation date for photos.",
    },
]
TARGET_TAGS = [g["tag"] for g in TAG_GUIDE]

TAG_EDITOR_EXTENSIONS = {".mp4", ".mov", ".m4v", ".jpg", ".jpeg", ".png", ".fit"}

TZ_MODE_OPTIONS = ["Keep local time, set offset", "Recalculate local time from UTC"]

TZ_OFFSETS = [
    "+14:00", "+13:00", "+12:45", "+12:00", "+11:00", "+10:30", "+10:00",
    "+09:30", "+09:00", "+08:00", "+07:00", "+06:30", "+06:00", "+05:45",
    "+05:30", "+05:00", "+04:30", "+04:00", "+03:30", "+03:00", "+02:00",
    "+01:00", "+00:00", "-01:00", "-02:00", "-03:00", "-03:30", "-04:00",
    "-05:00", "-06:00", "-07:00", "-08:00", "-09:00", "-09:30", "-10:00",
    "-11:00", "-12:00",
]


def local_tz_offset_string() -> str:
    """The current system UTC offset, formatted like '+08:00'."""
    try:
        now_tz = datetime.now().astimezone().tzinfo
        if now_tz:
            td = now_tz.utcoffset(None)
            if td is not None:
                offset_mins = int(td.total_seconds() / 60)
                sign = "+" if offset_mins >= 0 else "-"
                hours = abs(offset_mins) // 60
                mins = abs(offset_mins) % 60
                return f"{sign}{hours:02}:{mins:02}"
    except Exception:
        pass
    return "+00:00"


_DJI_PATTERN = re.compile(r"DJI_(\d{4})(\d{2})(\d{2})_?(\d{2})(\d{2})(\d{2})", re.IGNORECASE)


def calculate_dji_datetimes(file_path: Path, current_tags: Dict[str, str]) -> Optional[Dict[str, str]]:
    """
    DJI drones write a correct local capture time into the filename (and
    OriginalFilePath) but not into most EXIF/QuickTime date tags. If this
    looks like a DJI file, derive the tag values that fix that, by comparing
    the filename's local time against the file's (correct) UTC CreateDate.
    """
    original_fp = current_tags.get("QuickTime:OriginalFilePath") or ""
    match = _DJI_PATTERN.search(str(original_fp)) or _DJI_PATTERN.search(file_path.name)
    if not match:
        return None

    year, month, day, hour, minute, second = match.groups()
    try:
        local_dt = datetime(int(year), int(month), int(day), int(hour), int(minute), int(second))
    except ValueError:
        return None

    utc_str = current_tags.get("QuickTime:CreateDate") or current_tags.get("CreateDate")
    if not utc_str:
        return None

    utc_dt = None
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            utc_dt = datetime.strptime(str(utc_str)[:19], fmt)
            break
        except ValueError:
            continue
    if not utc_dt:
        return None

    diff_seconds = (local_dt - utc_dt).total_seconds()
    offset_mins = round(diff_seconds / 60 / 15) * 15
    sign = "+" if offset_mins >= 0 else "-"
    hours = abs(offset_mins) // 60
    mins = abs(offset_mins) % 60
    tz_offset_str = f"{sign}{hours:02}:{mins:02}"

    local_str = local_dt.strftime("%Y:%m:%d %H:%M:%S")
    return {
        "QuickTime:CreationDate": local_str + tz_offset_str,
        "QuickTime:CreateDate": utc_dt.strftime("%Y:%m:%d %H:%M:%S"),
        "EXIF:DateTimeOriginal": local_str,
        "EXIF:CreateDate": local_str,
    }


def parse_date_from_filename(file_path: Path) -> Optional[datetime]:
    """Best-effort local capture time parsed from common filename conventions."""
    filename = file_path.name

    dji_match = re.search(r"(\d{4})(\d{2})(\d{2})_?(\d{2})(\d{2})(\d{2})", filename)
    if dji_match:
        try:
            year, month, day, hour, minute, second = dji_match.groups()
            return datetime(int(year), int(month), int(day), int(hour), int(minute), int(second))
        except ValueError:
            pass

    std_match = re.search(r"(\d{4})[_-]?(\d{2})[_-]?(\d{2})[_-](\d{2})(\d{2})(\d{2})", filename)
    if std_match:
        try:
            year, month, day, hour, minute, second = std_match.groups()
            return datetime(int(year), int(month), int(day), int(hour), int(minute), int(second))
        except ValueError:
            pass

    return None


def apply_batch_timezone_to_file(meta_handler, file_path: Path, mode: str, tz, tz_iso: str) -> bool:
    """
    Writes a resolved local-time + timezone-offset tag set to one file. `mode` is
    either "Keep local time, set offset" (use the file's own local time, just
    stamp the given offset onto it) or "Recalculate local time from UTC" (derive
    local time by converting the file's UTC creation time into `tz`). `tz` is a
    datetime.timezone for the offset; `tz_iso` is its "+HH:MM"/"-HH:MM" string form.
    Returns True if a tag update was written, False if no usable date was found.
    """
    local_dt = None
    if mode == "Keep local time, set offset":
        try:
            local_dt = meta_handler.get_local_creation_date(file_path)
        except Exception:
            pass
        if not local_dt:
            local_dt = parse_date_from_filename(file_path)
        if not local_dt:
            try:
                local_dt = datetime.fromtimestamp(file_path.stat().st_mtime)
            except Exception:
                pass
    else:  # "Recalculate local time from UTC"
        utc_dt = None
        try:
            utc_dt = meta_handler.get_standardized_creation_date(file_path)
        except Exception:
            tags_got = meta_handler.get_tags(file_path, ["QuickTime:CreateDate", "CreateDate"])
            create_str = tags_got.get("QuickTime:CreateDate") or tags_got.get("CreateDate")
            if create_str:
                try:
                    utc_dt = datetime.strptime(str(create_str)[:19], "%Y:%m:%d %H:%M:%S").replace(
                        tzinfo=timezone.utc
                    )
                except Exception:
                    pass
        if utc_dt:
            local_dt = utc_dt.astimezone(tz).replace(tzinfo=None)
        else:
            try:
                local_dt = meta_handler.get_local_creation_date(file_path)
            except Exception:
                pass
            if not local_dt:
                local_dt = parse_date_from_filename(file_path)
            if not local_dt:
                try:
                    local_dt = datetime.fromtimestamp(file_path.stat().st_mtime)
                except Exception:
                    pass

    if not local_dt:
        return False

    local_str = local_dt.strftime("%Y:%m:%d %H:%M:%S")
    suffix = file_path.suffix.lower()
    if suffix in (".mp4", ".mov", ".m4v"):
        updates = {
            "QuickTime:CreationDate": local_str + tz_iso,
            "QuickTime:Timezone": tz_iso,
            "QuickTime:TimeZone": tz_iso,
            "EXIF:DateTimeOriginal": local_str,
            "EXIF:CreateDate": local_str,
        }
    else:
        updates = {
            "EXIF:DateTimeOriginal": local_str,
            "EXIF:CreateDate": local_str,
            "EXIF:OffsetTime": tz_iso,
            "EXIF:OffsetTimeOriginal": tz_iso,
            "EXIF:OffsetTimeDigitized": tz_iso,
        }
    meta_handler.set_tags(file_path, updates)
    return True


def filter_metadata_rows(rows: List[Dict[str, Any]], text: str) -> List[Dict[str, Any]]:
    """Rows (each a {'tag': ..., 'value': ...} dict) whose tag or value contains
    `text` (case-insensitive) - the filter behind the Tag Editor's metadata viewer."""
    text = (text or "").lower()
    return [r for r in rows if text in r["tag"].lower() or text in str(r["value"]).lower()]
