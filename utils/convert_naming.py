"""The resolutions Convertion offers and the names of the files it writes,
shared by cli_main.py's --convert and the Convertion page's preview, so the
preview always shows the names the CLI then uses."""
import re
from pathlib import Path

# (name, width, height, HEVC bit rate)
CONVERT_RESOLUTIONS = [
    ("1080p", 1920, 1080, "24M"),
    ("720p", 1280, 720, "12M"),
    ("480p", 854, 480, "7M"),
    ("360p", 640, 360, "4M"),
]
RESOLUTION_NAME_RE = re.compile(r"(?i)[ _](4k|2160p|1080p|720p|480p|360p)")


def convert_output_filename(source_path: Path, res_name: str) -> str:
    """'Dive 4K.MP4' -> 'Dive 1080p.mp4'; a name with no resolution in it
    gets one added: 'Dive.MP4' -> 'Dive 1080p.mp4'."""
    stem = source_path.stem
    if RESOLUTION_NAME_RE.search(stem):
        new_stem = RESOLUTION_NAME_RE.sub(f" {res_name}", stem)
    else:
        new_stem = f"{stem} {res_name}"
    return f"{new_stem}{source_path.suffix.lower()}"
