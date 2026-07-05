import pytest
import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

from utils.dependency_check import (
    _find_tool,
    get_installation_instructions,
    check_dependencies
)

def test_find_tool_present():
    """Verify finding existing tools on the host system."""
    import platform
    system = platform.system()
    
    ffmpeg_path = _find_tool("ffmpeg", system)
    assert ffmpeg_path is not None
    assert ffmpeg_path.exists()

    ffprobe_path = _find_tool("ffprobe", system, known_ffmpeg_dir=ffmpeg_path.parent)
    assert ffprobe_path is not None
    assert ffprobe_path.exists()

    exiftool_path = _find_tool("exiftool", system)
    assert exiftool_path is not None
    assert exiftool_path.exists()

def test_installation_instructions_darwin():
    instructions = get_installation_instructions(["ffmpeg", "exiftool"], "Darwin")
    assert "macOS Installation" in instructions
    assert "brew install ffmpeg" in instructions
    assert "brew install exiftool" in instructions
    assert "https://exiftool.org/" in instructions

def test_installation_instructions_windows():
    instructions = get_installation_instructions(["ffmpeg", "exiftool"], "Windows")
    assert "Windows Installation" in instructions
    assert "winget install FFmpeg" in instructions
    assert "winget install OliverBetz.ExifTool" in instructions
    assert "https://www.gyan.dev/ffmpeg/builds/" in instructions

def test_installation_instructions_linux():
    instructions = get_installation_instructions(["ffmpeg", "exiftool"], "Linux")
    assert "Linux Installation" in instructions
    assert "sudo apt update && sudo apt install ffmpeg libimage-exiftool-perl" in instructions
    assert "sudo dnf install ffmpeg perl-Image-ExifTool" in instructions
    assert "sudo pacman -S ffmpeg perl-image-exiftool" in instructions

def test_check_dependencies_success():
    # Should complete without error when all tools are found
    found = check_dependencies(is_gui=False)
    assert "ffmpeg" in found
    assert "ffprobe" in found
    assert "exiftool" in found

def test_check_dependencies_missing_exit():
    # Mock _find_tool to return None for exiftool
    def mock_find(tool, system, known_ffmpeg_dir=None):
        if tool == "exiftool":
            return None
        return Path("/usr/local/bin") / tool

    with patch("utils.dependency_check._find_tool", side_effect=mock_find):
        with pytest.raises(SystemExit) as exc_info:
            check_dependencies(is_gui=False)
        assert exc_info.value.code == 1
