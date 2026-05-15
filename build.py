import os
import sys
import subprocess
import argparse
import re
from pathlib import Path

def update_revision(revision):
    """Updates the REVISION variable in main.py."""
    main_path = Path("main.py")
    if not main_path.exists():
        print("Error: main.py not found")
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
    dist_path = Path("dist")
    
    targets = {
        "cli": "main.py",
        "gui": "gui_main.py"
    }
    
    if target not in targets:
        print(f"Error: Unknown target {target}")
        return

    entry_point = targets[target]
    exe_name = f"uwmedia-{target}-{os_name}-{arch}-{revision}"
    
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--clean",
        "--name", exe_name,
        entry_point
    ]
    
    # OS specific flags
    if os_name.lower() == "darwin":
        if target == "gui":
            cmd.append("--windowed")
    elif os_name.lower() == "windows" or os_name.lower() == "win32":
        if target == "gui":
            cmd.append("--noconsole")
            
    # Add hidden imports if necessary (common with PySide6, Pydantic, and Pillow)
    cmd.extend([
        "--hidden-import", "pydantic_core._pydantic_core",
        "--hidden-import", "PIL._imaging",
        "--hidden-import", "PIL.ImageFont"
    ])
    
    print(f"\n>>> Building {target.upper()}...")
    print(f">>> Command: {' '.join(cmd)}")
    
    try:
        subprocess.run(cmd, check=True)
        print(f"\nSUCCESS: {target} build complete.")
        exe_ext = ".exe" if os_name.lower() in ["windows", "win32"] else ""
        result_path = dist_path / f"{exe_name}{exe_ext}"
        if result_path.exists():
            print(f"Binary located at: {result_path}")
    except subprocess.CalledProcessError as e:
        print(f"\nFAILED: {target} build failed with exit code {e.returncode}")

def main():
    parser = argparse.ArgumentParser(description="UWMedia PyInstaller Build Script")
    parser.add_argument("--target", choices=["cli", "gui", "both"], default="both", help="Build target (default: both)")
    parser.add_argument("--revision", required=True, help="Revision/Version string (e.g. 1.0.4)")
    parser.add_argument("--os", default=sys.platform, help="OS label for filename (default: current sys.platform)")
    parser.add_argument("--arch", default="arm64" if "arm" in sys.platform.lower() or "darwin" in sys.platform.lower() else "x64", 
                        help="Architecture label for filename (default: detected)")
    
    args = parser.parse_args()
    
    # 1. Inject Revision into main.py
    update_revision(args.revision)
    
    # 2. Perform Builds
    if args.target in ["cli", "both"]:
        build_app("cli", args.revision, args.os, args.arch)
    
    if args.target in ["gui", "both"]:
        build_app("gui", args.revision, args.os, args.arch)

if __name__ == "__main__":
    main()
