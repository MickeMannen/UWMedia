"""Resolve the ffmpeg/ffprobe/exiftool executables to actually use.

Checks the user's configured override (set from the GUI's Advanced page, or
directly in settings.json) first, falling back to PATH / common install
locations via `dependency_check._find_tool` when no override is set or the
configured path no longer exists.
"""

import platform
from pathlib import Path
from typing import Optional

from utils.app_settings import load_settings
from utils.dependency_check import _find_tool, _is_valid_executable


def _resolve(tool_name: str, settings_key: str, known_ffmpeg_dir: Optional[Path] = None) -> Optional[Path]:
    override = load_settings().get(settings_key)
    if override:
        p = Path(override)
        if p.exists():
            return p
    return _find_tool(tool_name, platform.system(), known_ffmpeg_dir=known_ffmpeg_dir)


def get_ffmpeg_path() -> Optional[Path]:
    return _resolve("ffmpeg", "ffmpeg_path")


def get_ffprobe_path(ffmpeg_path: Optional[Path] = None) -> Optional[Path]:
    # No separate override for ffprobe - it's expected to live alongside
    # ffmpeg, so a custom ffmpeg_path's directory is checked as a fallback.
    ffmpeg_path = ffmpeg_path if ffmpeg_path is not None else get_ffmpeg_path()
    known_dir = ffmpeg_path.parent if ffmpeg_path else None
    return _find_tool("ffprobe", platform.system(), known_ffmpeg_dir=known_dir)


def get_exiftool_path() -> Optional[Path]:
    return _resolve("exiftool", "exiftool_path")


def is_valid_ffmpeg(path: Optional[Path]) -> bool:
    return bool(path) and Path(path).exists() and _is_valid_executable([str(path), "-version"])


def is_valid_exiftool(path: Optional[Path]) -> bool:
    return bool(path) and Path(path).exists() and _is_valid_executable([str(path), "-ver"])
