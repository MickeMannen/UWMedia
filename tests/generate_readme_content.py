#!/usr/bin/env python3
import os
import sys
import shutil
import subprocess
from pathlib import Path

# Automatically switch to project .venv Python if dependencies (cv2) are missing
try:
    import cv2
    import numpy as np
except ImportError:
    BASE_DIR = Path(__file__).resolve().parent.parent
    venv_python = BASE_DIR / ".venv" / "bin" / "python3"
    if venv_python.exists() and sys.executable != str(venv_python):
        os.execv(str(venv_python), [str(venv_python)] + sys.argv)
    raise

# Paths setup relative to repository root
BASE_DIR = Path(__file__).parent.parent
TEST_DATA_DIR = BASE_DIR / "test_data" / "release_test"
LOGS_DIR = BASE_DIR / "test_data" / "logs" / "fit"
OVERLAYS_DIR = BASE_DIR / "overlays"
DEFAULT_OUTPUT_DIR = BASE_DIR / "test_data" / "show"

# Project root configuration files
COLOR_YAML = BASE_DIR / "color.yaml"
CONFIG_YAML = BASE_DIR / "config.yaml"

# Default layouts and inputs
GARMIN_SINGLE_LAYOUT = OVERLAYS_DIR / "Garmin_x50_simple.zip"
GARMIN_SIDEMOUNT_LAYOUT = OVERLAYS_DIR / "Garmin_x50_sidemount.zip"
PERDIX2_LAYOUT = OVERLAYS_DIR / "Shearwater_Perdix2_simple.zip"
DEFAULT_PHOTO = BASE_DIR / "test_data" / "color_correction" / "DSC06641.JPG"
DEFAULT_VIDEO = TEST_DATA_DIR / "20251019_M0284.MP4"
SIDEMOUNT_VIDEO = BASE_DIR / "test_data" / "videos_original" / "DJI_20260502110658_0002_D_A001.MP4"
PERDIX2_VIDEO = BASE_DIR / "test_data" / "videos_original" / "20260527_M0685.MP4"
DEFAULT_LOG = LOGS_DIR / "461 Sipadan, Turtle Tomb.fit"


def verify_root_configs():
    """Ensure color.yaml and config.yaml from project root directory exist."""
    if not COLOR_YAML.exists():
        raise FileNotFoundError(f"Required color.yaml not found in project root: {COLOR_YAML}")
    if not CONFIG_YAML.exists():
        raise FileNotFoundError(f"Required config.yaml not found in project root: {CONFIG_YAML}")
    print(f"[*] Using root color configuration: {COLOR_YAML}")
    print(f"[*] Using root tank configuration:  {CONFIG_YAML}")


def generate_photo_side_by_side(
    photo_path: Path = DEFAULT_PHOTO,
    output_path: Path = None,
    color_profile: str = "default"
) -> Path:
    """
    Creates a side-by-side comparison photo: Original Photo (Left) vs Color-Corrected Photo (Right).
    """
    photo_path = Path(photo_path)
    if output_path is None:
        output_path = DEFAULT_OUTPUT_DIR / f"{photo_path.stem}_side_by_side.jpg"
    else:
        output_path = Path(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = output_path.parent / "temp_photo_sbs"
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        temp_format = "temp_color"
        cmd = [
            sys.executable, "cli_main.py",
            str(photo_path),
            str(temp_dir),
            "--color", color_profile,
            "--filename-format", temp_format
        ]
        print(f"[*] Running photo color correction: {' '.join(cmd)}")
        subprocess.run(cmd, check=True, cwd=str(BASE_DIR))

        corrected_files = list(temp_dir.glob(f"*{temp_format}*.jpg"))
        if not corrected_files:
            raise FileNotFoundError(f"Failed to locate color corrected photo in {temp_dir}")
        corrected_path = corrected_files[0]

        orig_img = cv2.imread(str(photo_path))
        corr_img = cv2.imread(str(corrected_path))

        if orig_img is None or corr_img is None:
            raise ValueError("Error loading photo images for side-by-side stitching.")

        # Match dimensions
        h, w = corr_img.shape[:2]
        orig_resized = cv2.resize(orig_img, (w, h))

        # Add bold text labels
        font = cv2.FONT_HERSHEY_DUPLEX
        scale = max(1.0, w / 1200.0)
        thickness = max(3, int(scale * 3.5))

        cv2.putText(orig_resized, "ORIGINAL", (30, int(70 * scale)), font, scale, (0, 0, 0), thickness + 4, cv2.LINE_AA)
        cv2.putText(orig_resized, "ORIGINAL", (30, int(70 * scale)), font, scale, (255, 255, 255), thickness, cv2.LINE_AA)

        cv2.putText(corr_img, "COLOR CORRECTED", (30, int(70 * scale)), font, scale, (0, 0, 0), thickness + 4, cv2.LINE_AA)
        cv2.putText(corr_img, "COLOR CORRECTED", (30, int(70 * scale)), font, scale, (255, 255, 255), thickness, cv2.LINE_AA)

        # Add white vertical line between photos
        divider_width = max(4, int(w / 250.0))
        divider = np.full((h, divider_width, 3), 255, dtype=np.uint8)

        side_by_side = np.hstack([orig_resized, divider, corr_img])
        cv2.imwrite(str(output_path), side_by_side)
        print(f"[+] Photo side-by-side successfully created at: {output_path}")
        return output_path
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def generate_photo_color_overlay(
    photo_path: Path = DEFAULT_PHOTO,
    output_path: Path = None,
    layout_path: Path = GARMIN_SINGLE_LAYOUT,
    logs_dir: Path = LOGS_DIR,
    color_profile: str = "default"
) -> Path:
    """
    Creates a photo with Color Correction + Garmin Single Tank HUD Overlay.
    """
    photo_path = Path(photo_path)
    if output_path is None:
        output_path = DEFAULT_OUTPUT_DIR / f"{photo_path.stem}_color_garmin_overlay.jpg"
    else:
        output_path = Path(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = output_path.parent / "temp_photo_overlay"
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        temp_format = "temp_overlay_result"
        cmd = [
            sys.executable, "cli_main.py",
            str(photo_path),
            str(temp_dir),
            "--color", color_profile,
            "--layout", str(layout_path),
            "--logs", str(logs_dir),
            "--filename-format", temp_format
        ]
        print(f"[*] Running photo color + garmin overlay: {' '.join(cmd)}")
        subprocess.run(cmd, check=True, cwd=str(BASE_DIR))

        results = list(temp_dir.glob("*.jpg"))
        if not results:
            raise FileNotFoundError(f"Failed to generate photo with overlay in {temp_dir}")
        
        shutil.copy2(results[0], output_path)
        print(f"[+] Photo color + Garmin overlay created at: {output_path}")
        return output_path
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def generate_video_side_by_side(
    video_path: Path = DEFAULT_VIDEO,
    output_path: Path = None,
    duration: int = 10,
    start_time: str = "00:00",
    color_profile: str = "default"
) -> Path:
    """
    Creates a 10-second video of Original Video (Left) side-by-side with Color Corrected Video (Right).
    """
    video_path = Path(video_path)
    if output_path is None:
        output_path = DEFAULT_OUTPUT_DIR / f"{video_path.stem}_10s_video_side_by_side.mp4"
    else:
        output_path = Path(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = output_path.parent / "temp_video_sbs"
    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        end_seconds = duration
        end_time = f"00:{end_seconds:02d}"

        # 1. Color correct original clip
        cmd_color = [
            sys.executable, "cli_main.py",
            str(video_path),
            str(temp_dir),
            "--color", color_profile,
            "--start-time", start_time,
            "--end-time", end_time,
            "--filename-format", "color_clip",
            "--hw-accel"
        ]
        print(f"[*] Generating 10s color clip: {' '.join(cmd_color)}")
        subprocess.run(cmd_color, check=True, cwd=str(BASE_DIR))

        # Find produced color clip
        color_outputs = list(temp_dir.glob("color_clip*.mp4"))
        if not color_outputs:
            raise FileNotFoundError("Color video clip failed to generate.")
        color_clip_path = color_outputs[0]

        # 2. Trim raw original clip for side-by-side
        raw_clip_path = temp_dir / "raw_clip.mp4"
        cmd_trim = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-ss", start_time,
            "-t", str(duration),
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-an",
            str(raw_clip_path)
        ]
        print(f"[*] Trimming 10s raw clip: {' '.join(cmd_trim)}")
        subprocess.run(cmd_trim, check=True, cwd=str(BASE_DIR))

        if not raw_clip_path.exists():
            raise FileNotFoundError(f"Raw trimmed clip was not created at {raw_clip_path}")

        # 3. Stack side-by-side using FFmpeg hstack filter
        filter_complex = "[0:v][1:v]hstack=inputs=2[v]"
        cmd_hstack = [
            "ffmpeg", "-y",
            "-i", str(raw_clip_path),
            "-i", str(color_clip_path),
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-c:v", "libx264", "-crf", "20", "-preset", "fast",
            str(output_path)
        ]
        print(f"[*] Combining side-by-side video: {' '.join(cmd_hstack)}")
        subprocess.run(cmd_hstack, check=True, cwd=str(BASE_DIR))

        print(f"[+] 10s Video side-by-side created at: {output_path}")
        return output_path
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def generate_video_color_overlay(
    video_path: Path = DEFAULT_VIDEO,
    output_path: Path = None,
    layout_path: Path = GARMIN_SINGLE_LAYOUT,
    logs_dir: Path = LOGS_DIR,
    duration: int = 10,
    start_time: str = "00:00",
    color_profile: str = "default"
) -> Path:
    """
    Creates a 10-second video of Color Corrected Video with Garmin Single Overlay.
    """
    video_path = Path(video_path)
    if output_path is None:
        output_path = DEFAULT_OUTPUT_DIR / f"{video_path.stem}_10s_color_garmin_overlay.mp4"
    else:
        output_path = Path(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = output_path.parent / "temp_video_overlay"
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        end_seconds = duration
        end_time = f"00:{end_seconds:02d}"

        temp_format = "temp_color_overlay"
        cmd = [
            sys.executable, "cli_main.py",
            str(video_path),
            str(temp_dir),
            "--color", color_profile,
            "--layout", str(layout_path),
            "--logs", str(logs_dir),
            "--start-time", start_time,
            "--end-time", end_time,
            "--filename-format", temp_format,
            "--hw-accel"
        ]
        print(f"[*] Running 10s video color + garmin overlay: {' '.join(cmd)}")
        subprocess.run(cmd, check=True, cwd=str(BASE_DIR))

        results = list(temp_dir.glob("*.mp4"))
        if not results:
            raise FileNotFoundError("Video with color + overlay failed to generate.")

        shutil.copy2(results[0], output_path)
        print(f"[+] 10s Video color + Garmin overlay created at: {output_path}")
        return output_path
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def generate_video_color_overlay_sidemount(
    video_path: Path = SIDEMOUNT_VIDEO,
    output_path: Path = None,
    layout_path: Path = GARMIN_SIDEMOUNT_LAYOUT,
    logs_dir: Path = LOGS_DIR,
    start_time: str = "01:00",
    end_time: str = "01:15",
    color_profile: str = "vivid"
) -> Path:
    """
    Creates a video clip with Vivid Color Correction + Garmin Sidemount Overlay (01:00 to 01:15).
    """
    video_path = Path(video_path)
    if output_path is None:
        output_path = DEFAULT_OUTPUT_DIR / f"{video_path.stem}_color_garmin_sidemount_overlay.mp4"
    else:
        output_path = Path(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = output_path.parent / "temp_video_sidemount_overlay"
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        temp_format = "temp_sidemount_color_overlay"
        cmd = [
            sys.executable, "cli_main.py",
            str(video_path),
            str(temp_dir),
            "--color", color_profile,
            "--layout", str(layout_path),
            "--logs", str(logs_dir),
            "--start-time", start_time,
            "--end-time", end_time,
            "--filename-format", temp_format,
            "--hw-accel"
        ]
        print(f"[*] Running video color + garmin sidemount overlay: {' '.join(cmd)}")
        subprocess.run(cmd, check=True, cwd=str(BASE_DIR))

        results = list(temp_dir.glob("*.mp4"))
        if not results:
            raise FileNotFoundError("Video with sidemount overlay failed to generate.")

        shutil.copy2(results[0], output_path)
        print(f"[+] Video color + Garmin sidemount overlay created at: {output_path}")
        return output_path
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def generate_video_color_overlay_shearwater(
    video_path: Path = PERDIX2_VIDEO,
    output_path: Path = None,
    layout_path: Path = PERDIX2_LAYOUT,
    logs_dir: Path = LOGS_DIR,
    start_time: str = "00:25",
    end_time: str = "00:38",
    color_profile: str = "default"
) -> Path:
    """
    Creates a video clip with Color Correction + Shearwater Perdix2 Overlay (00:25 to 00:38).
    """
    video_path = Path(video_path)
    if output_path is None:
        output_path = DEFAULT_OUTPUT_DIR / f"{video_path.stem}_color_shearwater_perdix2_overlay.mp4"
    else:
        output_path = Path(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = output_path.parent / "temp_video_shearwater_overlay"
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        temp_format = "temp_shearwater_color_overlay"
        cmd = [
            sys.executable, "cli_main.py",
            str(video_path),
            str(temp_dir),
            "--color", color_profile,
            "--layout", str(layout_path),
            "--logs", str(logs_dir),
            "--start-time", start_time,
            "--end-time", end_time,
            "--filename-format", temp_format,
            "--hw-accel"
        ]
        print(f"[*] Running video color + Shearwater Perdix2 overlay: {' '.join(cmd)}")
        subprocess.run(cmd, check=True, cwd=str(BASE_DIR))

        results = list(temp_dir.glob("*.mp4"))
        if not results:
            raise FileNotFoundError("Video with Shearwater Perdix2 overlay failed to generate.")

        shutil.copy2(results[0], output_path)
        print(f"[+] Video color + Shearwater Perdix2 overlay created at: {output_path}")
        return output_path
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def generate_video_comparison(
    video_path: Path = DEFAULT_VIDEO,
    output_path: Path = None,
    layout_path: Path = GARMIN_SINGLE_LAYOUT,
    logs_dir: Path = LOGS_DIR,
    duration: int = 10,
    start_time: str = "00:00"
) -> Path:
    """
    Creates the complete README video sequence:
    10 seconds of Video Original Side-by-Side with Video Color, followed by
    10 seconds of Video Color with Video Overlay (Garmin single).
    """
    video_path = Path(video_path)
    if output_path is None:
        output_path = DEFAULT_OUTPUT_DIR / f"{video_path.stem}_readme_video_sequence.mp4"
    else:
        output_path = Path(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = output_path.parent / "temp_video_seq"
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Part 1: Side by Side (10s)
        sbs_path = temp_dir / "part1_sbs.mp4"
        generate_video_side_by_side(
            video_path=video_path,
            output_path=sbs_path,
            duration=duration,
            start_time=start_time
        )

        # Part 2: Color + Overlay (10s)
        overlay_path = temp_dir / "part2_overlay.mp4"
        generate_video_color_overlay(
            video_path=video_path,
            output_path=overlay_path,
            layout_path=layout_path,
            logs_dir=logs_dir,
            duration=duration,
            start_time=start_time
        )

        # Concatenate using FFmpeg concat filter (rescaling overlay to match SBS aspect if needed)
        cmd_concat = [
            "ffmpeg", "-y",
            "-i", str(sbs_path),
            "-i", str(overlay_path),
            "-filter_complex",
            "[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1[v0];"
            "[1:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1[v1];"
            "[v0][v1]concat=n=2:v=1:a=0[v]",
            "-map", "[v]",
            "-c:v", "libx264", "-crf", "20", "-preset", "fast",
            str(output_path)
        ]
        print(f"[*] Concatenating 10s side-by-side and 10s color+overlay sequence: {' '.join(cmd_concat)}")
        subprocess.run(cmd_concat, check=True, cwd=str(BASE_DIR))

        print(f"[+] Complete README video sequence created at: {output_path}")
        return output_path
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def generate_render_log_video(
    log_path: Path = DEFAULT_LOG,
    output_path: Path = None,
    layout_path: Path = GARMIN_SINGLE_LAYOUT,
    num_waypoints: int = 100
) -> Path:
    """
    Creates a standalone telemetry video on black background from dive log (--render-log).
    """
    log_path = Path(log_path)
    if output_path is None:
        output_path = DEFAULT_OUTPUT_DIR / f"render_log_{log_path.stem}.mp4"
    else:
        output_path = Path(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, "cli_main.py",
        str(output_path),
        "--render-log", str(log_path), str(num_waypoints),
        "--layout", str(layout_path),
        "--hw-accel"
    ]
    print(f"[*] Generating telemetry render-log video: {' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd=str(BASE_DIR))

    if not output_path.exists():
        raise FileNotFoundError(f"Failed to generate render log video at {output_path}")

    print(f"[+] Telemetry render-log video created at: {output_path}")
    return output_path


def generate_all_readme_content():
    """
    Executes all README asset creation functions.
    """
    print("==================================================")
    print("      Generating README Content & Assets          ")
    print("==================================================")

    verify_root_configs()
    DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)



    # 1. Photo original side by side with photo color
    photo_sbs = generate_photo_side_by_side()

    # 2. Photo color with photo overlay (use garmin single)
    photo_overlay = generate_photo_color_overlay()

    # 3. Video 10 seconds - video original side by side with video color and video color with video overlay
    video_seq = generate_video_comparison()

    # 4. Video of render-log
    render_log_vid = generate_render_log_video()

    # 5. Video color with Garmin sidemount overlay (01:00 to 01:15, vivid profile)
    sidemount_vid = generate_video_color_overlay_sidemount()

    # 6. Video color with Shearwater Perdix2 overlay (00:25 to 00:38)
    shearwater_vid = generate_video_color_overlay_shearwater()

    print("\n[+] All README content assets successfully generated:")
    print(f"  1. Photo Side-By-Side: {photo_sbs}")
    print(f"  2. Photo Color + Overlay (Garmin single): {photo_overlay}")
    print(f"  3. Video Sequence (SBS + Overlay): {video_seq}")
    print(f"  4. Video Render-Log: {render_log_vid}")
    print(f"  5. Video Color + Overlay (Garmin sidemount, vivid): {sidemount_vid}")
    print(f"  6. Video Color + Overlay (Shearwater Perdix2): {shearwater_vid}")


if __name__ == "__main__":
    generate_all_readme_content()
