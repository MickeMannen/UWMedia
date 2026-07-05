import os
import sys
import platform
import shutil
import subprocess
import multiprocessing
from pathlib import Path
from typing import Dict, List, Optional

def _is_valid_executable(cmd: List[str]) -> bool:
    """Runs command with -version or -ver to test if executable works."""
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
        return res.returncode == 0
    except Exception:
        return False

def _find_tool(tool_name: str, system: str, known_ffmpeg_dir: Optional[Path] = None) -> Optional[Path]:
    """Finds an executable tool in PATH or common OS installation paths."""
    exec_name = f"{tool_name}.exe" if system == "Windows" else tool_name
    
    # 1. Check PATH
    found = shutil.which(exec_name)
    if found:
        p = Path(found)
        cmd = [str(p), "-ver" if tool_name == "exiftool" else "-version"]
        if _is_valid_executable(cmd):
            return p

    # 2. Check known ffmpeg dir if checking ffprobe
    if tool_name == "ffprobe" and known_ffmpeg_dir:
        candidate = known_ffmpeg_dir / exec_name
        if candidate.exists():
            if _is_valid_executable([str(candidate), "-version"]):
                return candidate

    # 3. Check OS specific fallback paths
    search_dirs: List[Path] = []
    home = Path.home()
    
    if system == "Darwin":
        search_dirs.extend([
            Path("/opt/homebrew/bin"),
            Path("/usr/local/bin"),
            Path("/opt/local/bin"),
            home / "bin",
            home / ".local/bin"
        ])
    elif system == "Windows":
        local_app_data = Path(os.environ.get("LOCALAPPDATA", r"C:\Users\Default\AppData\Local"))
        program_files = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
        program_files_x86 = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
        program_data = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
        
        search_dirs.extend([
            Path(r"C:\ffmpeg\bin"),
            program_files / "ffmpeg" / "bin",
            program_files_x86 / "ffmpeg" / "bin",
            program_data / "chocolatey" / "bin",
            home / "ffmpeg" / "bin",
            Path(r"C:\exiftool"),
            Path(r"C:\Windows"),
            program_files / "exiftool",
            home / "exiftool",
        ])
        
        # Check WinGet packages directory if available
        winget_dir = local_app_data / "Microsoft" / "WinGet" / "Packages"
        if winget_dir.exists():
            for p in winget_dir.glob("**/ffmpeg*.exe"):
                search_dirs.append(p.parent)
            for p in winget_dir.glob("**/exiftool*.exe"):
                search_dirs.append(p.parent)

    elif system == "Linux":
        search_dirs.extend([
            Path("/usr/bin"),
            Path("/usr/local/bin"),
            Path("/usr/bin/vendor_perl"),
            Path("/snap/bin"),
            home / ".local/bin"
        ])

    for s_dir in search_dirs:
        candidate = s_dir / exec_name
        if candidate.exists() and candidate.is_file():
            cmd = [str(candidate), "-ver" if tool_name == "exiftool" else "-version"]
            if _is_valid_executable(cmd):
                return candidate
                
    return None

def get_installation_instructions(missing_tools: List[str], system: str) -> str:
    """Generates user-friendly, OS-specific installation instructions for missing tools."""
    missing_str = ", ".join(f"'{m}'" for m in missing_tools)
    
    lines = [
        f"Missing required external dependencies: {missing_str}",
        "",
        "To resolve this issue, please install the missing software for your system:",
        ""
    ]
    
    if system == "Darwin":
        lines.append("--- macOS Installation ---")
        lines.append("Option 1: Using Homebrew (Recommended)")
        if "ffmpeg" in missing_tools or "ffprobe" in missing_tools:
            lines.append("  brew install ffmpeg")
        if "exiftool" in missing_tools:
            lines.append("  brew install exiftool")
        lines.append("")
        lines.append("Option 2: Manual Download")
        if "ffmpeg" in missing_tools or "ffprobe" in missing_tools:
            lines.append("  • FFmpeg/FFprobe: Download static binaries from https://evermeet.cx/ffmpeg/ or https://ffmpeg.org/download.html")
            lines.append("    Extract and copy 'ffmpeg' and 'ffprobe' to /usr/local/bin or /opt/homebrew/bin")
        if "exiftool" in missing_tools:
            lines.append("  • ExifTool: Download the MacOS package from https://exiftool.org/")

    elif system == "Windows":
        lines.append("--- Windows Installation ---")
        lines.append("Option 1: Using Package Manager (winget / chocolatey)")
        if "ffmpeg" in missing_tools or "ffprobe" in missing_tools:
            lines.append("  winget install FFmpeg   (or: choco install ffmpeg)")
        if "exiftool" in missing_tools:
            lines.append("  winget install OliverBetz.ExifTool   (or: choco install exiftool)")
        lines.append("")
        lines.append("Option 2: Manual Download")
        if "ffmpeg" in missing_tools or "ffprobe" in missing_tools:
            lines.append("  • FFmpeg: Download build from https://www.gyan.dev/ffmpeg/builds/")
            lines.append("    Extract zip and add the 'bin' folder to your System PATH.")
        if "exiftool" in missing_tools:
            lines.append("  • ExifTool: Download Windows executable from https://exiftool.org/")
            lines.append("    Rename 'exiftool(-k).exe' to 'exiftool.exe' and add to System PATH (or C:\\Windows).")

    else: # Linux
        lines.append("--- Linux Installation ---")
        lines.append("Ubuntu / Debian:")
        apt_pkgs = []
        if "ffmpeg" in missing_tools or "ffprobe" in missing_tools:
            apt_pkgs.append("ffmpeg")
        if "exiftool" in missing_tools:
            apt_pkgs.append("libimage-exiftool-perl")
        lines.append(f"  sudo apt update && sudo apt install {' '.join(apt_pkgs)}")
        lines.append("")
        lines.append("Fedora / RHEL:")
        dnf_pkgs = []
        if "ffmpeg" in missing_tools or "ffprobe" in missing_tools:
            dnf_pkgs.append("ffmpeg")
        if "exiftool" in missing_tools:
            dnf_pkgs.append("perl-Image-ExifTool")
        lines.append(f"  sudo dnf install {' '.join(dnf_pkgs)}")
        lines.append("")
        lines.append("Arch Linux:")
        pac_pkgs = []
        if "ffmpeg" in missing_tools or "ffprobe" in missing_tools:
            pac_pkgs.append("ffmpeg")
        if "exiftool" in missing_tools:
            pac_pkgs.append("perl-image-exiftool")
        lines.append(f"  sudo pacman -S {' '.join(pac_pkgs)}")

    lines.append("")
    lines.append("After installing the missing dependencies, please restart the application.")
    return "\n".join(lines)

def check_dependencies(is_gui: bool = False) -> Dict[str, Path]:
    """
    Checks for required external applications: ffmpeg, ffprobe, and exiftool.
    If any are missing, prints/displays an OS-specific error message and exits the app.
    Returns a dict mapping tool names to their found executable Path objects.
    """
    # Skip check in worker processes spawned by multiprocessing
    if multiprocessing.current_process().name != "MainProcess":
        return {}

    system = platform.system()
    required_tools = ["ffmpeg", "ffprobe", "exiftool"]
    found_tools: Dict[str, Path] = {}
    missing_tools: List[str] = []

    ffmpeg_path: Optional[Path] = None

    for tool in required_tools:
        path = _find_tool(tool, system, known_ffmpeg_dir=ffmpeg_path.parent if ffmpeg_path else None)
        if path:
            found_tools[tool] = path
            if tool == "ffmpeg":
                ffmpeg_path = path
            # Prepend directory to PATH if not already present
            parent_dir = str(path.parent)
            current_path = os.environ.get("PATH", "")
            if parent_dir not in current_path.split(os.pathsep):
                os.environ["PATH"] = parent_dir + os.pathsep + current_path
        else:
            missing_tools.append(tool)

    if missing_tools:
        instructions = get_installation_instructions(missing_tools, system)
        
        banner = "=" * 80
        cli_error_msg = f"\n{banner}\nERROR: MISSING REQUIRED EXTERNAL DEPENDENCIES\n{banner}\n{instructions}\n{banner}\n"
        sys.stderr.write(cli_error_msg)
        sys.stderr.flush()

        if is_gui:
            try:
                from PySide6.QtWidgets import QApplication, QMessageBox
                app = QApplication.instance()
                if not app:
                    app = QApplication(sys.argv)
                
                msg_box = QMessageBox()
                msg_box.setIcon(QMessageBox.Critical)
                msg_box.setWindowTitle("Missing External Dependencies")
                msg_box.setText(f"Required external dependency missing: {', '.join(missing_tools)}")
                msg_box.setInformativeText(instructions)
                msg_box.exec()
            except Exception as e:
                sys.stderr.write(f"Could not display GUI error dialog: {e}\n")

        sys.exit(1)

    return found_tools
