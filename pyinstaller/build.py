import os
import sys
import subprocess
import argparse
import re
import platform
from pathlib import Path

def get_next_revision():
    """Reads current REVISION from main.py and increments the patch version."""
    main_path = Path(__file__).parent.parent / "main.py"
    if not main_path.exists():
        return "0.0.1"
    
    content = main_path.read_text()
    match = re.search(r'REVISION = "(.*?)"', content)
    if not match:
        return "0.0.1"
    
    current = match.group(1)
    parts = current.split('.')
    try:
        # Increment the last numeric part
        parts[-1] = str(int(parts[-1]) + 1)
        return ".".join(parts)
    except (ValueError, IndexError):
        return current + ".1"

def update_revision(revision):
    """Updates the REVISION variable in main.py."""
    # Since we are in pyinstaller/, main.py is in the parent directory
    main_path = Path(__file__).parent.parent / "main.py"
    if not main_path.exists():
        print(f"Error: {main_path} not found")
        return
    
    content = main_path.read_text()
    if 'REVISION =' in content:
        # Replace existing REVISION
        content = re.sub(r'REVISION = ".*"', f'REVISION = "{revision}"', content)
    else:
        # Add REVISION at top
        content = f'REVISION = "{revision}"\n' + content
    
    main_path.write_text(content)
    print(f"Set main.py REVISION to: {revision}")

def build_app(target, revision, os_name, arch):
    """Runs PyInstaller to build a onefile executable."""
    root_dir = Path(__file__).parent.parent
    pyinstaller_dir = Path(__file__).parent
    dist_path = pyinstaller_dir / "dist"
    work_path = pyinstaller_dir / "build"
    
    targets = {
        "cli": root_dir / "main.py",
        "gui": root_dir / "gui_main.py",
        "tag_editor": root_dir / "tag_editor_main.py",
        "tag_editor_main": root_dir / "tag_editor_main.py"
    }
    
    if target not in targets:
        print(f"Error: Unknown target {target}")
        return

    entry_point = targets[target]
    exe_target_name = target.replace('_', '-')
    exe_name = f"uwmedia-{exe_target_name}-{os_name}-{arch}"
    
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onedir",
        "--clean",
        "--noconfirm",
        "--name", exe_name,
        "--distpath", str(dist_path),
        "--workpath", str(work_path),
        "--specpath", str(pyinstaller_dir),
        str(entry_point)
    ]
    
    # OS specific flags
    if os_name.lower() == "darwin":
        if target in ["gui", "tag_editor", "tag_editor_main"]:
            cmd.append("--windowed")
    elif os_name.lower() == "windows" or os_name.lower() == "win32":
        if target in ["gui", "tag_editor", "tag_editor_main"]:
            cmd.append("--noconsole")
            
    # Add hidden imports if necessary (common with PySide6, Pydantic, and Pillow)
    cmd.extend([
        "--hidden-import", "pydantic_core._pydantic_core",
        "--hidden-import", "PIL._imaging",
        "--hidden-import", "PIL.ImageFont",
        "--hidden-import", "yaml"
    ])
    
    print(f"\n>>> Building {target.upper()}...")
    print(f">>> Command: {' '.join(cmd)}")
    
    try:
        subprocess.run(cmd, check=True)
        print(f"\nSUCCESS: {target} build complete.")
        
        # Create ZIP archive
        import shutil
        zip_name = dist_path / f"{exe_name}"
        dir_to_zip = dist_path / exe_name
        
        if dir_to_zip.exists():
            print(f">>> Creating ZIP archive: {zip_name}.zip")
            shutil.make_archive(str(zip_name), 'zip', str(dir_to_zip))
            print(f"Archive created at: {zip_name}.zip")
            
    except subprocess.CalledProcessError as e:
        print(f"\nFAILED: {target} build failed with exit code {e.returncode}")

def get_default_os():
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform.startswith("darwin"):
        return "macos"
    return "linux"

def get_default_arch():
    machine = platform.machine().lower()
    if "arm" in machine or "aarch64" in machine:
        return "arm64"
    if "x86_64" in machine or "amd64" in machine:
        return "x64"
    return machine

def main():
    parser = argparse.ArgumentParser(description="UWMedia PyInstaller Build Script")
    parser.add_argument("--target", choices=["cli", "gui", "tag_editor", "tag_editor_main", "both", "all"], default="both", help="Build target (default: both)")
    parser.add_argument("--revision", help="Revision/Version string (e.g. 1.0.4). If omitted, increments patch version in main.py.")
    parser.add_argument("--os", default=get_default_os(), 
                        help="OS label for filename (e.g., windows, macos, linux)")
    parser.add_argument("--arch", default=get_default_arch(), 
                        help="Architecture label for filename (e.g., x64, arm64)")
    
    args = parser.parse_args()

    revision = args.revision
    if not revision:
        revision = get_next_revision()
    
    # 1. Inject Revision into main.py
    update_revision(revision)
    
    # 2. Perform Builds
    if args.target in ["cli", "both", "all"]:
        build_app("cli", revision, args.os, args.arch)
    
    if args.target in ["gui", "both", "all"]:
        build_app("gui", revision, args.os, args.arch)

    if args.target in ["tag_editor", "all"]:
        build_app("tag_editor", revision, args.os, args.arch)
    elif args.target == "tag_editor_main":
        build_app("tag_editor_main", revision, args.os, args.arch)

if __name__ == "__main__":
    main()
