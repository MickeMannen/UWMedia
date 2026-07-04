import argparse
import sys
import os
import time
import tempfile
import shutil
import json
from pathlib import Path
from datetime import timedelta, datetime
import zipfile
from tqdm import tqdm
from parsers.uddf import UDDFParser
from parsers.garmin import GarminParser
from parsers.subsurface import SubsurfaceParser
from metadata.exif import MetadataHandler
from models.dive import Waypoint, Dive
from models.manager import DiveManager
from ffmpeg import FfmpegClass

import cv2
import numpy as np

def generate_fcpxml(video_path: Path, duration: float, fps: float = 30.0, width: int = 1920, height: int = 1080):
    """Generates a minimal FCPXML 1.10 file for the given video."""
    xml_path = video_path.with_suffix(".xml")
    
    # FCP uses fractional durations for precision
    # For exactly 30fps, 1/30s is correct.
    frame_duration = "1/30s"
    if fps == 24.0: frame_duration = "1/24s"
    elif fps == 60.0: frame_duration = "1/60s"
    
    # Duration in rational format or simple seconds with 's' suffix
    dur_str = f"{duration}s"
    
    # File URL must be absolute and prefixed with file:///
    abs_path = video_path.resolve()
    # file:// + absolute path (which starts with /) = file:///
    file_url = f"file://{abs_path}"

    # Resource name should reflect resolution
    res_name = f"{width}x{height}"
    if width == 1920 and height == 1080: res_name = "1080p"
    elif width == 3840 and height == 2160: res_name = "4K"

    content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.10">
    <resources>
        <format id="r1" name="FFVideoFormat{res_name}{int(fps)}" frameDuration="{frame_duration}" width="{width}" height="{height}"/>
        <asset id="r2" name="{video_path.stem}" start="0s" duration="{dur_str}" hasVideo="1" format="r1" src="{file_url}"/>
    </resources>
    <library>
        <event name="UWMedia Import">
            <asset-clip name="{video_path.stem}" ref="r2" offset="0s" start="0s" duration="{dur_str}" format="r1"/>
        </event>
    </library>
</fcpxml>"""

    with open(xml_path, "w") as f:
        f.write(content)
    print(f"FCPXML generated: {xml_path.name}")

def process_log_only(log_path: Path, output_dir: Path, args, manager, tmp_hud_dir):
    """Generates a video from a dive log and layout on a black background."""
    print(f"\n--- Generating Video from Log: {log_path.name} ---")
    
    # 1. Parse the specific log file
    suffix = log_path.suffix.lower()
    dives = []
    if suffix == ".uddf":
        parser = UDDFParser()
        if args.tz_adjust:
            parser.update_timezone(log_path, args.tz_adjust * 60)
        dives = parser.parse(log_path)
        if args.tz_adjust:
            for d in dives:
                d.start_time += timedelta(hours=args.tz_adjust)
                d.end_time += timedelta(hours=args.tz_adjust)
                for wp in d.waypoints:
                    wp.timestamp += timedelta(hours=args.tz_adjust)
                d.invalidate_timestamp_cache()
    elif suffix == ".fit":
        parser = GarminParser()
        dives = parser.parse(log_path)
    elif suffix in (".ssrf", ".xml"):
        parser = SubsurfaceParser()
        dives = parser.parse(log_path)
        if args.tz_adjust:
            for d in dives:
                d.start_time += timedelta(hours=args.tz_adjust)
                d.end_time += timedelta(hours=args.tz_adjust)
                for wp in d.waypoints:
                    wp.timestamp += timedelta(hours=args.tz_adjust)
                d.invalidate_timestamp_cache()
    else:
        print(f"Error: Unsupported log format {suffix}")
        sys.exit(1)

    if not dives:
        print(f"Error: No dives found in {log_path.name}")
        sys.exit(1)
    
    # Process the first dive found in the file
    dive = dives[0]
    
    # Slice waypoints and adjust end_time if limit_waypoints is set
    limit_waypoints = getattr(args, 'limit_waypoints', None)
    if limit_waypoints is not None and len(dive.waypoints) > 0:
        dive.waypoints = dive.waypoints[:limit_waypoints]
        dive.end_time = dive.waypoints[-1].timestamp
        dive.invalidate_timestamp_cache()
        
    duration = dive.duration
    if duration <= 0:
        print("Error: Dive duration is zero.")
        sys.exit(1)

    # 2. Determine Output Filename: divelog filename + layoutname.mp4
    layout_name = args.original_layout_stem or "default"
    
    if output_dir.suffix: # User specified a full path as output
        target_path = output_dir
    else:
        filename = f"{log_path.stem}_{layout_name}.mp4"
        target_path = output_dir / filename
        target_path = get_unique_path(target_path)

    print(f"Output path: {target_path}")

    # 3. Setup FFmpeg and HUD
    ff = FfmpegClass(hw_accel=args.hw_accel, debug=args.debug)
    
    # Pre-load layout
    with open(args.layout, 'r') as f:
        layout = json.load(f)
    
    hud_skin = layout.get("hud_skin", {})
    skin_path = hud_skin.get("path")
    preloaded_skin = None
    
    # Determine resolution of standalone telemetry video based on HUD dimensions
    skin_type = hud_skin.get("type", "image")
    user_scale = hud_skin.get("scale", 1.0)
    
    if skin_type == "shape":
        width = int(hud_skin.get("width", 400))
        height = int(hud_skin.get("height", 200))
    else:
        if skin_path:
            img_temp = cv2.imread(skin_path, cv2.IMREAD_UNCHANGED)
            if img_temp is not None:
                width = int(img_temp.shape[1] * user_scale)
                height = int(img_temp.shape[0] * user_scale)
            else:
                width, height = 1920, 1080
        else:
            width, height = 1920, 1080

    # Ensure width and height are divisible by 2 for FFmpeg
    if width % 2 != 0:
        width += 1
    if height % 2 != 0:
        height += 1
    
    # 4. Processing Phase (Similar to ColorCorrectionEngine.process_video but without source video)
    fps = 30.0
    total_frames = int(duration * fps)
    
    cmd = [
        str(ff.get_path()), '-y',
        '-f', 'rawvideo', '-vcodec', 'rawvideo',
        '-s', f'{width}x{height}', '-pix_fmt', 'bgr24', '-r', str(fps),
        '-i', '-', 
        '-vcodec', ff.get_encoder(),
        '-pix_fmt', 'yuv420p',
        '-tag:v', 'hvc1', # Force HEVC
        '-crf', '20',
        str(target_path)
    ]

    if not args.debug:
        cmd.extend(["-nostats", "-loglevel", "error"])

    print(f"Generating video frames ({total_frames} frames)...")
    import subprocess as sp
    from gui.hud_renderer import draw_hud
    import threading
    from queue import Queue
    
    process = sp.Popen(cmd, stdin=sp.PIPE)
    
    # Pre-allocate a reusable frame buffer (avoids np.zeros allocation per waypoint change)
    frame_buffer = np.zeros((height, width, 3), dtype=np.uint8)
    cached_bytes = None
    last_wp = None
    
    # Create a dummy waypoint for when current_wp is None
    # This allows draw_hud to still render something (which will show "--" due to format_telemetry_value)
    dummy_wp = Waypoint(timestamp=dive.start_time, depth=None, temp=None, time_since_start=0)

    # =====================================================================
    # Threaded Pipeline: Render → Write
    # - Main thread: renders HUD frames (CPU-bound, Pillow text drawing)
    # - Write thread: writes bytes to FFmpeg stdin (I/O-bound)
    # Bounded queue prevents memory blowup while overlapping render + encode.
    # =====================================================================
    WRITE_QUEUE_SIZE = 8
    write_q = Queue(maxsize=WRITE_QUEUE_SIZE)
    write_error = [None]
    _SENTINEL = None

    def _write_worker():
        """Writes pre-serialized frame bytes to FFmpeg stdin."""
        try:
            while True:
                data = write_q.get()
                if data is _SENTINEL:
                    break
                process.stdin.write(data)
        except Exception as e:
            write_error[0] = e

    write_thread = threading.Thread(target=_write_worker, name="ffmpeg-write", daemon=True)
    write_thread.start()

    try:
        # Use rate_noinv_fmt (string) instead of rate_noinv (float/None) to avoid crash at t=0
        bar_format = "{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_noinv_fmt}]"
        with tqdm(total=total_frames, desc="Rendering", unit="frame", bar_format=bar_format) as pbar:
            for i in range(total_frames):
                # Get waypoint
                current_time = dive.start_time + timedelta(seconds=i/fps)
                wp = dive.get_waypoint_at(current_time)
                
                # Check if we need to redraw
                # We compare by timestamp to detect "new" waypoints from the log
                wp_timestamp = wp.timestamp if wp else None
                last_wp_timestamp = last_wp.timestamp if last_wp else None
                
                if cached_bytes is None or wp_timestamp != last_wp_timestamp:
                    # Clear and redraw on the pre-allocated buffer
                    frame_buffer[:] = 0
                    draw_hud(frame_buffer, layout, wp or Waypoint(timestamp=current_time, depth=0, temp=0), render_log=True, waypoints=dive.waypoints)
                    # Cache the serialized bytes so identical frames don't re-serialize
                    cached_bytes = frame_buffer.tobytes()
                    last_wp = wp
                
                write_q.put(cached_bytes)
                pbar.update(1)
    finally:
        write_q.put(_SENTINEL)
        write_thread.join(timeout=10)
        process.stdin.close()
        process.wait()

    # Propagate any write thread errors
    if write_error[0]:
        raise write_error[0]

    # 5. Generate FCPXML
    generate_fcpxml(target_path, duration, fps=fps, width=width, height=height)

    # 6. Write Date Taken / Creation Date metadata to matching Log Time
    print("Writing creation date metadata...")
    try:
        from metadata.exif import MetadataHandler
        meta_handler = MetadataHandler()
        
        # Calculate timezone adjust
        tz_offset_mins = int(args.tz_adjust * 60) if getattr(args, 'tz_adjust', None) is not None else 0
        sign = "+" if tz_offset_mins >= 0 else "-"
        hours = abs(tz_offset_mins) // 60
        mins = abs(tz_offset_mins) % 60
        tz_iso = f"{sign}{hours:02}:{mins:02}"
        
        local_dt = dive.start_time
        utc_dt = local_dt - timedelta(minutes=tz_offset_mins)
        
        utc_str = utc_dt.strftime("%Y:%m:%d %H:%M:%S")
        local_with_tz_str = local_dt.strftime("%Y:%m:%d %H:%M:%S") + tz_iso
        
        tags = {
            "QuickTime:CreateDate": utc_str,
            "QuickTime:CreationDate": local_with_tz_str,
            "QuickTime:TrackCreateDate": utc_str,
            "QuickTime:MediaCreateDate": utc_str,
            "QuickTime:Timezone": tz_iso,
            "QuickTime:TimeZone": tz_iso,
            "EXIF:DateTimeOriginal": local_dt.strftime("%Y:%m:%d %H:%M:%S"),
            "EXIF:CreateDate": local_dt.strftime("%Y:%m:%d %H:%M:%S")
        }
        meta_handler.set_tags(target_path, tags)
    except Exception as e:
        print(f"Warning: Failed to write creation date metadata: {e}")

    print(f"\nDone: {target_path.name}")

def validate_layout(layout_path: Path, manager: DiveManager):
    """Validates the HUD layout against loaded dive logs."""
    if not layout_path or not layout_path.exists():
        return

    try:
        with open(layout_path, 'r') as f:
            layout_data = json.load(f)
    except Exception as e:
        print(f"Error: Failed to parse layout JSON {layout_path.name}: {e}")
        sys.exit(1)

    hud_skin = layout_data.get("hud_skin", {})
    linked_elements = hud_skin.get("linked_elements", [])
    
    if not linked_elements:
        print(f"Warning: Layout {layout_path.name} has no linked telemetry elements.")
        return

    # Basic field validation
    # Use Pydantic's model_fields to get valid Waypoint fields
    valid_fields = set(Waypoint.model_fields.keys()) | {"gasmix", "primary_tank_pressure"}
    
    layout_fields = [elem.get("field") for elem in linked_elements if elem.get("field")]
    
    tank_serials_in_layout = set()
    invalid_fields = []
    
    for field in layout_fields:
        if field.startswith("custom:"):
            continue
        if field.startswith("tank_pressure:") or field.startswith("tank_name:"):
            serial = field.split(":", 1)[1]
            tank_serials_in_layout.add(serial)
            continue
        
        if field not in valid_fields:
            invalid_fields.append(field)

    if invalid_fields:
        print(f"Error: Layout {layout_path.name} contains unknown fields: {', '.join(invalid_fields)}")
        sys.exit(1)

    if tank_serials_in_layout and manager.dives:
        found_serials = set()
        for dive in manager.dives.values():
            if dive.waypoints:
                # We check all waypoints because a tank might appear later in a dive (though unlikely)
                # but for validation, any occurrence is enough.
                # Actually, checking first waypoint is usually enough.
                # Let's check first waypoint that has any tanks.
                for wp in dive.waypoints:
                    if wp.tanks:
                        found_serials.update(wp.tanks.keys())
                        break
        
        missing_serials = tank_serials_in_layout - found_serials
        if missing_serials:
            print(f"Warning: Layout references tank serials not found in loaded logs: {', '.join(missing_serials)}")

def get_unique_path(path: Path) -> Path:
    """If file exists, append _1, _2, etc. Always returns lowercase extension."""
    suffix = path.suffix.lower()
    path = path.with_suffix(suffix)
    
    if not path.exists():
        return path
    
    stem = path.stem
    directory = path.parent
    counter = 1
    
    while True:
        new_path = directory / f"{stem}_{counter}{suffix}"
        if not new_path.exists():
            return new_path
        counter += 1

def process_conversions(source: Path, output_dir: Path, args, creation_date, tz_offset_mins, meta_handler):
    """Handles multi-resolution conversion for a video with optimized bitrates."""
    # Resolutions and their target bitrates for HEVC
    resolutions = {
        '1080p': (1920, 1080, "24M"),
        '720p': (1280, 720, "12M"),
        '480p': (854, 480, "7M"),
        '360p': (640, 360, "4M")
    }

    ff = FfmpegClass(hw_accel=args.hw_accel, debug=args.debug)
    
    for res_name in args.convert:
        if res_name not in resolutions:
            continue
            
        target_w, target_h, target_bitrate = resolutions[res_name]
        filename = f"{source.stem}_{res_name}{source.suffix.lower()}"
        target_path = output_dir / filename
        target_path = get_unique_path(target_path)
        
        print(f"\n--- Converting to {res_name} ({target_bitrate}): {target_path.name} ---")
        
        ff.process_video(
            input_path=source,
            output_path=target_path,
            creation_date=creation_date,
            tz_offset_mins=tz_offset_mins,
            target_resolution=(target_w, target_h),
            bitrate=target_bitrate
        )
        
        # Post-processing metadata
        try:
            forced_tz_mins = int(args.force_media_tz * 60) if args.force_media_tz is not None else None
            meta_handler.copy_all(source, target_path, force_tz_mins=forced_tz_mins, custom_tags=args.modify_quicktime)
        except Exception as e:
            print(f"Warning: Failed to copy metadata: {e}")

def process_single_file(source: Path, output_dir: Path, args, manager, meta_handler, tmp_hud_dir, forced_filename=None):
    """Processes a single video or photo file."""
    t_file_start = time.time()
    print(f"\n--- Processing: {source.name} ---")
    
    stats = {
        "file": source.name,
        "type": "video" if source.suffix.lower() in ['.mp4', '.mov', '.m4v', '.mkv', '.avi'] else "photo",
        "stages": []
    }
    
    # Extract Metadata
    try:
        creation_date = meta_handler.get_local_creation_date(source)
        print(f"Local Creation Date: {creation_date}")
    except Exception as e:
        print(f"Error extracting metadata for {source}: {e}")
        return {"file": source.name, "error": f"Error extracting metadata: {e}"}

    # Determine Output Path
    if args.render_video_log:
        layout_name = args.original_layout_stem or "default"
        filename = f"{source.stem}_{layout_name}{source.suffix.lower()}"
    elif forced_filename:
        # If forced, still ensure extension is lower case if it has one
        p = Path(forced_filename)
        filename = p.stem + p.suffix.lower()
    else:
        format_to_use = args.filename_format
        if not format_to_use and (output_dir != source.parent or args.source.is_dir()):
            # Default date format if outputting to a different directory or batch processing
            format_to_use = "%Y%m%d_%H%M%S"

        if format_to_use:
            try:
                filename = creation_date.strftime(format_to_use) + source.suffix.lower()
            except Exception as e:
                print(f"Error formatting filename with pattern '{format_to_use}': {e}")
                filename = source.stem + source.suffix.lower()
        else:
            filename = source.stem + source.suffix.lower()

    # Add milliseconds to photo filenames (limit to 3 digits)
    is_video = source.suffix.lower() in ['.mp4', '.mov', '.m4v', '.mkv', '.avi']
    if not args.render_video_log and not is_video and creation_date.microsecond > 0:
        ms = creation_date.microsecond // 1000
        p = Path(filename)
        filename = f"{p.stem}_{ms:03d}{p.suffix}"
    
    target_path = output_dir / filename

    # Check no-overwrite option
    if (args.color or args.layout or args.render_video_log) and args.no_overwrite:
        if target_path.exists():
            print(f"Skipping: Target file {target_path} already exists (--no-overwrite is active).")
            return {"file": source.name, "skipped": True}

    target_path = get_unique_path(target_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    
    print(f"Output path: {target_path}")

    # Calculate Timezone Offset for Media
    if args.force_media_tz is not None:
        tz_offset_mins = int(args.force_media_tz * 60)
        print(f"Using Forced Timezone Offset: {args.force_media_tz:+.1f} hours")
    else:
        tz_offset_mins = meta_handler.get_timezone_offset(source)
        if tz_offset_mins is not None:
            print(f"Detected Timezone Offset: {tz_offset_mins/60:+.1f} hours")

    # Fast Timezone Fix Mode
    if args.fix_tz:
        if args.force_media_tz is None and args.modify_quicktime is None:
            print("Error: --fix-tz requires --force-media-tz or --modify-quicktime to be specified.")
            sys.exit(1)
            
        print(f"Fast Mode: Copying file and fixing metadata -> {target_path.name}")
        shutil.copy2(source, target_path)
        t_meta_start = time.time()
        try:
            meta_handler.copy_all(source, target_path, force_tz_mins=tz_offset_mins, custom_tags=args.modify_quicktime)
            print("Success: Metadata updated.")
            meta_time = time.time() - t_meta_start
            stats["stages"].append({"name": "Metadata Copying", "time": meta_time})
        except Exception as e:
            print(f"Error updating metadata: {e}")
        stats["total_time"] = time.time() - t_file_start
        return stats

    # Match Dive
    dive = manager.find_dive_for_timestamp(creation_date) if manager.dives else None
    if manager.dives and not dive:
        print("Warning: No matching dive log found for this file.")
        print(f"Creation Date: {creation_date}")
    elif dive:
        print(f"Matched dive starting at {dive.start_time}")

    overlay = True if args.layout else False

    # Determine if it's a video
    is_video = source.suffix.lower() in ['.mp4', '.mov', '.m4v', '.mkv', '.avi']

    if args.render_video_log:
        t_proc_start = time.time()
        # Load layout to determine output video resolution
        with open(args.layout, 'r') as f:
            layout = json.load(f)

        hud_skin = layout.get("hud_skin", {})
        skin_path = hud_skin.get("path")
        skin_type = hud_skin.get("type", "image")
        user_scale = hud_skin.get("scale", 1.0)

        if skin_type == "shape":
            width = int(hud_skin.get("width", 400))
            height = int(hud_skin.get("height", 200))
        else:
            if skin_path:
                img_temp = cv2.imread(skin_path, cv2.IMREAD_UNCHANGED)
                if img_temp is not None:
                    width = int(img_temp.shape[1] * user_scale)
                    height = int(img_temp.shape[0] * user_scale)
                else:
                    width, height = 1920, 1080
            else:
                width, height = 1920, 1080

        if width % 2 != 0: width += 1
        if height % 2 != 0: height += 1

        if is_video:
            # Probe original video properties (for fps and duration)
            cap = cv2.VideoCapture(str(source))
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            cap.release()

            ff = FfmpegClass(hw_accel=args.hw_accel, debug=args.debug)
            cmd = [
                str(ff.get_path()), '-y',
                '-f', 'rawvideo', '-vcodec', 'rawvideo',
                '-s', f'{width}x{height}', '-pix_fmt', 'bgr24', '-r', str(fps),
                '-i', '-', 
                '-vcodec', ff.get_encoder(),
                '-pix_fmt', 'yuv420p',
                '-tag:v', 'hvc1',
                '-crf', '20',
                str(target_path)
            ]
            if not args.debug:
                cmd.extend(["-nostats", "-loglevel", "error"])

            import subprocess as sp
            import threading
            from queue import Queue
            from gui.hud_renderer import draw_hud

            process = sp.Popen(cmd, stdin=sp.PIPE)

            frame_buffer = np.zeros((height, width, 3), dtype=np.uint8)
            cached_bytes = None
            last_wp = None

            # Load layout has been moved earlier to determine resolution
            preloaded_skin = None
            if skin_path:
                img_skin = cv2.imread(skin_path, cv2.IMREAD_UNCHANGED)
                if img_skin is not None:
                    skin_opacity = hud_skin.get("opacity", 1.0)
                    preloaded_skin = cv2.resize(img_skin, (width, height), interpolation=cv2.INTER_AREA)
                    if preloaded_skin.shape[2] == 4:
                        preloaded_skin[:, :, 3] = (preloaded_skin[:, :, 3] * skin_opacity).astype(np.uint8)

            WRITE_QUEUE_SIZE = 8
            write_q = Queue(maxsize=WRITE_QUEUE_SIZE)
            write_error = [None]
            _SENTINEL = None

            def _write_worker():
                try:
                    while True:
                        data = write_q.get()
                        if data is _SENTINEL:
                            break
                        process.stdin.write(data)
                except Exception as e:
                    write_error[0] = e

            write_thread = threading.Thread(target=_write_worker, name="ffmpeg-write", daemon=True)
            write_thread.start()

            try:
                with tqdm(total=total_frames, desc=f"Rendering {source.name}", unit="frame") as pbar:
                    for i in range(total_frames):
                        elapsed = i / fps
                        current_time = creation_date + timedelta(seconds=elapsed)
                        wp = dive.get_waypoint_at(current_time) if dive else None

                        wp_timestamp = wp.timestamp if wp else None
                        last_wp_timestamp = last_wp.timestamp if last_wp else None

                        if cached_bytes is None or wp_timestamp != last_wp_timestamp:
                            frame_buffer[:] = 0
                            draw_hud(frame_buffer, layout, wp or Waypoint(timestamp=current_time, depth=0, temp=0, time_since_start=0), render_log=True, preloaded_skin=preloaded_skin, waypoints=dive.waypoints if dive else None)
                            cached_bytes = frame_buffer.tobytes()
                            last_wp = wp

                        write_q.put(cached_bytes)
                        pbar.update(1)
            finally:
                write_q.put(_SENTINEL)
                write_thread.join(timeout=10)
                process.stdin.close()
                process.wait()

            if write_error[0]:
                raise write_error[0]

            proc_time = time.time() - t_proc_start
            stats["stages"].append({"name": "Telemetry Video Render", "time": proc_time})
        else:
            # Load layout to determine output photo resolution
            with open(args.layout, 'r') as f:
                layout = json.load(f)

            hud_skin = layout.get("hud_skin", {})
            skin_path = hud_skin.get("path")
            skin_type = hud_skin.get("type", "image")
            user_scale = hud_skin.get("scale", 1.0)

            if skin_type == "shape":
                width = int(hud_skin.get("width", 400))
                height = int(hud_skin.get("height", 200))
            else:
                if skin_path:
                    img_temp = cv2.imread(skin_path, cv2.IMREAD_UNCHANGED)
                    if img_temp is not None:
                        width = int(img_temp.shape[1] * user_scale)
                        height = int(img_temp.shape[0] * user_scale)
                    else:
                        width, height = 1920, 1080
                else:
                    width, height = 1920, 1080

            if width % 2 != 0: width += 1
            if height % 2 != 0: height += 1

            frame_buffer = np.zeros((height, width, 3), dtype=np.uint8)

            preloaded_skin = None
            if skin_path:
                img_skin = cv2.imread(skin_path, cv2.IMREAD_UNCHANGED)
                if img_skin is not None:
                    skin_opacity = hud_skin.get("opacity", 1.0)
                    preloaded_skin = cv2.resize(img_skin, (width, height), interpolation=cv2.INTER_AREA)
                    if preloaded_skin.shape[2] == 4:
                        preloaded_skin[:, :, 3] = (preloaded_skin[:, :, 3] * skin_opacity).astype(np.uint8)

            from gui.hud_renderer import draw_hud
            wp = dive.get_waypoint_at(creation_date) if dive else None
            draw_hud(frame_buffer, layout, wp or Waypoint(timestamp=creation_date, depth=0, temp=0, time_since_start=0), render_log=True, preloaded_skin=preloaded_skin, waypoints=dive.waypoints if dive else None)

            subsampling = -1
            qtables = None
            if source.suffix.lower() in ('.jpg', '.jpeg'):
                try:
                    from PIL import Image, JpegImagePlugin
                    with Image.open(source) as img:
                        subsampling = JpegImagePlugin.get_sampling(img)
                        qtables = img.quantization
                except Exception as e:
                    pass

            try:
                from PIL import Image
                rgb_frame = cv2.cvtColor(frame_buffer, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(rgb_frame)
                if qtables is not None:
                    pil_img.save(target_path, qtables=qtables, subsampling=subsampling, optimize=True)
                else:
                    pil_img.save(target_path, quality=100, subsampling=subsampling, optimize=True)
            except Exception as e:
                cv2.imwrite(str(target_path), frame_buffer)

            proc_time = time.time() - t_proc_start
            stats["stages"].append({"name": "Telemetry Photo Render", "time": proc_time})

        # Post-process metadata to preserve QuickTime date taken / Exif
        print("Post-processing metadata...")
        t_meta_start = time.time()
        try:
            forced_tz_mins = int(args.force_media_tz * 60) if args.force_media_tz is not None else None
            meta_handler.copy_all(source, target_path, force_tz_mins=forced_tz_mins, custom_tags=args.modify_quicktime)
            meta_time = time.time() - t_meta_start
            stats["stages"].append({"name": "Metadata Copying", "time": meta_time})
        except Exception as e:
            print(f"Warning: Failed to copy metadata: {e}")

        stats["total_time"] = time.time() - t_file_start
        return stats
    
    if is_video and args.convert:
        # Multi-resolution conversion mode
        t_conv_start = time.time()
        process_conversions(source, output_dir, args, creation_date, tz_offset_mins, meta_handler)
        conv_time = time.time() - t_conv_start
        stats["stages"].append({"name": "Multi-res Conversion", "time": conv_time})
        stats["total_time"] = time.time() - t_file_start
        return stats

    if is_video:
        ff = FfmpegClass(hw_accel=args.hw_accel, debug=args.debug)
        needs_color = args.color
        needs_overlay = True if args.layout else False
        
        # Use fast LUT path for color-only processing (no overlay)
        use_lut_path = needs_color and not needs_overlay
        
        t_proc_start = time.time()
        if use_lut_path:
            from ffmpeg.color import ColorCorrectionEngine
            engine = ColorCorrectionEngine(ff, color_profile=needs_color)
            lut_stats = engine.process_video_lut(
                input_path=source,
                output_path=target_path,
                creation_date=creation_date,
                start_time=args.start_time,
                end_time=args.end_time,
                tz_offset_mins=tz_offset_mins
            )
            proc_time = time.time() - t_proc_start
            
            if lut_stats:
                total_frames = lut_stats.get("total_frames", 0)
                stats["stages"].append({"name": "Analysis Phase", "time": lut_stats["analysis_time"], "fps": lut_stats["analysis_fps"]})
                stats["stages"].append({"name": "LUT Generation", "time": lut_stats["lut_gen_time"]})
                stats["stages"].append({"name": "Processing/Encoding", "time": lut_stats["render_time"], "fps": lut_stats["render_fps"]})
                if total_frames > 0:
                    stats["overall_fps"] = total_frames / proc_time
        elif needs_color or needs_overlay:
            from ffmpeg.color import ColorCorrectionEngine
            engine = ColorCorrectionEngine(ff, color_profile=needs_color)
            legacy_stats = engine.process_video(
                input_path=source,
                output_path=target_path,
                creation_date=creation_date,
                dive=dive,
                overlay=needs_overlay,
                layout_path=args.layout,
                start_time=args.start_time,
                end_time=args.end_time,
                tz_offset_mins=tz_offset_mins,
                color_correct=needs_color
            )
            proc_time = time.time() - t_proc_start
            
            if legacy_stats:
                total_frames = legacy_stats.get("total_frames", 0)
                stats["stages"].append({"name": "Analysis Phase", "time": legacy_stats["analysis_time"], "fps": legacy_stats["analysis_fps"]})
                stats["stages"].append({"name": "Processing/Encoding", "time": legacy_stats["render_time"], "fps": legacy_stats["render_fps"]})
                if total_frames > 0:
                    stats["overall_fps"] = total_frames / proc_time
        else:
            ff_stats = ff.process_video(
                input_path=source,
                output_path=target_path,
                creation_date=creation_date,
                dive=dive,
                color_correct=False,
                overlay=needs_overlay,
                layout_path=args.layout,
                start_time=args.start_time,
                end_time=args.end_time,
                tz_offset_mins=tz_offset_mins
            )
            proc_time = time.time() - t_proc_start
            
            if ff_stats:
                total_frames = ff_stats.get("total_frames", 0)
                stats["stages"].append({"name": "FFmpeg Native Processing", "time": ff_stats["render_time"], "fps": ff_stats["render_fps"]})
                if total_frames > 0:
                    stats["overall_fps"] = total_frames / proc_time
    else:
        # Photo Processing with optional Color/Overlay
        needs_color = args.color
        needs_overlay = True if args.layout else False

        if needs_color or needs_overlay:
            print(f"Applying processing to photo: {source.name}")
            t_read = time.time()
            frame = cv2.imread(str(source))
            read_time = time.time() - t_read
            stats["stages"].append({"name": "Reading Photo", "time": read_time})
            
            if frame is None:
                print(f"Error: Could not read image {source}")
                shutil.copy2(source, target_path)
            else:
                # 1. Color Correction
                if needs_color:
                    t_color = time.time()
                    from ffmpeg.color import ColorCorrectionEngine
                    ff = FfmpegClass(hw_accel=args.hw_accel, debug=args.debug)
                    engine = ColorCorrectionEngine(ff, color_profile=needs_color)
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    filt = engine.get_filter_matrix(rgb)
                    corrected_rgb = engine.apply_filter(rgb, filt)
                    frame = cv2.cvtColor(corrected_rgb, cv2.COLOR_RGB2BGR)
                    color_time = time.time() - t_color
                    stats["stages"].append({"name": "Color Correction", "time": color_time})
                
                # 2. HUD Overlay
                if needs_overlay and dive:
                    t_overlay = time.time()
                    from gui.hud_renderer import draw_hud
                    with open(args.layout, 'r') as f:
                        layout = json.load(f)
                    
                    # Match waypoint to photo creation time
                    wp = dive.get_waypoint_at(creation_date)
                    if wp:
                        draw_hud(frame, layout, wp, waypoints=dive.waypoints)
                    else:
                        print("Warning: No dive data matched for this photo's timestamp.")
                    overlay_time = time.time() - t_overlay
                    stats["stages"].append({"name": "HUD Overlay", "time": overlay_time})

                t_save = time.time()
                if target_path.suffix.lower() in ('.jpg', '.jpeg'):
                    subsampling = -1
                    qtables = None
                    if source.suffix.lower() in ('.jpg', '.jpeg'):
                        try:
                            from PIL import Image, JpegImagePlugin
                            with Image.open(source) as img:
                                subsampling = JpegImagePlugin.get_sampling(img)
                                qtables = img.quantization
                        except Exception as e:
                            print(f"Warning: Could not read subsampling/quantization from {source}: {e}")
                    
                    try:
                        from PIL import Image
                        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        pil_img = Image.fromarray(rgb_frame)
                        if qtables is not None:
                            pil_img.save(target_path, qtables=qtables, subsampling=subsampling, optimize=True)
                        else:
                            pil_img.save(target_path, quality=100, subsampling=subsampling, optimize=True)
                    except Exception as e:
                        print(f"Error saving image with PIL: {e}. Falling back to cv2.imwrite")
                        cv2.imwrite(str(target_path), frame)
                else:
                    cv2.imwrite(str(target_path), frame)
                save_time = time.time() - t_save
                stats["stages"].append({"name": "Saving Photo", "time": save_time})
        else:
            # Simple copy for photos for now
            print(f"Skipping video processing for: {source.name} (Copying as photo)")
            t_copy = time.time()
            shutil.copy2(source, target_path)
            copy_time = time.time() - t_copy
            stats["stages"].append({"name": "Copying Photo", "time": copy_time})

    # Post-processing metadata
    print("Post-processing metadata...")
    t_meta_start = time.time()
    try:
        forced_tz_mins = int(args.force_media_tz * 60) if args.force_media_tz is not None else None
        meta_handler.copy_all(source, target_path, force_tz_mins=forced_tz_mins, custom_tags=args.modify_quicktime)
        meta_time = time.time() - t_meta_start
        stats["stages"].append({"name": "Metadata Copying", "time": meta_time})
    except Exception as e:
        print(f"Warning: Failed to copy metadata: {e}")

    # Move original source file if requested (only when running --color or --layout)
    if (args.color or args.layout) and args.move_original:
        dest_dir = Path(args.move_original)
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_path = dest_dir / source.name
            dest_path = get_unique_path(dest_path)
            print(f"Moving original file to: {dest_path}")
            t_move = time.time()
            shutil.move(str(source), str(dest_path))
            move_time = time.time() - t_move
            stats["stages"].append({"name": "Moving Original File", "time": move_time})
        except Exception as e:
            print(f"Error moving original file {source} to {dest_dir}: {e}")

    stats["total_time"] = time.time() - t_file_start
    return stats

def _parallel_worker(task):
    """Worker function for multi-core parallel processing of a single file."""
    file, output_dir, args, manager, tmp_hud_dir = task
    # Re-initialize MetadataHandler locally inside the subprocess to prevent ExifTool locking/resource conflicts
    local_meta_handler = MetadataHandler()
    try:
        stats = process_single_file(file, output_dir, args, manager, local_meta_handler, tmp_hud_dir)
        return True, file.name, stats
    except Exception as e:
        import traceback
        return False, file.name, f"{e}\n{traceback.format_exc()}"

class UWMediaParser(argparse.ArgumentParser):
    def error(self, message):
        print(f"Error: {message}")
        print("Use --help for usage information.")
        sys.exit(2)

def main():
    # Ignore helper subprocesses spawned by libraries (OpenCV, tqdm, etc.)
    # These often don't pass the original arguments.
    if len(sys.argv) > 1 and ("--multiprocessing-fork" in sys.argv or "spawn" in sys.argv):
        return
    
    # If we are in a subprocess but it didn't have the flags, 
    # check if we have any arguments at all.
    if len(sys.argv) == 1 and getattr(sys, 'frozen', False):
        return

    parser = UWMediaParser(description="Underwater Media Processor CLI")
    parser.add_argument("source", type=Path, nargs='?', help="Source video/photo file or directory")
    parser.add_argument("output", type=Path, nargs='?', help="Output file or directory")
    parser.add_argument("--logs", type=Path, help="Directory containing dive logs")
    parser.add_argument("--color", nargs='?', const='default', default=None, help="Apply color correction with selected profile (e.g. default, vivid, subtle). Defaults to 'default' if specified without a profile name.")
    parser.add_argument("--start-time", help="Start time for clipping/processing (HH:MM:SS or MM:SS)")
    parser.add_argument("--end-time", help="End time for clipping/processing (HH:MM:SS or MM:SS)")
    parser.add_argument("--hw-accel", action="store_true", default=False, help="Enable hardware acceleration")
    parser.add_argument("--layout", type=Path, help="JSON layout file or ZIP HUD package for overlay. Automatically enables overlay.")
    parser.add_argument("--tz-adjust", type=int, default=0, help="Timezone adjustment in hours (for Shearwater)")
    parser.add_argument("--force-media-tz", type=float, help="Force a specific timezone offset for media (in hours, e.g. +8 or -5.5)")
    parser.add_argument("--fix-tz", action="store_true", help="Only update the timezone metadata and exit (requires --force-media-tz)")
    parser.add_argument("--create-config", action="store_true", help="Scan log directory for tanks and create/overwrite config.yaml")
    parser.add_argument("--modify-quicktime", nargs='+', help="Manually modify QuickTime tags (e.g., 'QuickTime:CreateDate=2021:11:12 11:03:02')")
    parser.add_argument("--debug", action="store_true", help="Show verbose FFmpeg output and debugging info")
    parser.add_argument("--filename-format", help='Template for output filename (e.g. "%%Y%%m%%d_%%H%%M%%S_color")')
    parser.add_argument("--no-overwrite", action="store_true", help="Skip processing if target file exists (only when running --color or --layout)")
    parser.add_argument("--summary", action="store_true", default=False, help="Show detailed summary of the activity at the end, including stage timings and FPS")
    parser.add_argument("--move-original", type=Path, help="Directory to move original source file to after successful processing (only when running --color or --layout)")
    parser.add_argument("--convert", nargs='+', choices=['1080p', '720p', '480p', '360p'], help="Downscale to selected resolutions (multi allowed). Output will be a directory.")
    parser.add_argument("--render-log", nargs='+', help="Create a telemetry-only video from a specific dive log file (requires --layout). Can optionally take a second argument for number of waypoints.")
    parser.add_argument("--export-json", type=Path, help="Read logs from a directory and create a JSON file for each log file using same filename but json extension.")
    parser.add_argument("--render-video-log", action="store_true", default=False, help="Create a telemetry-only video/photo on a black background for all files in the input folder (requires --layout and --logs).")

    args = parser.parse_args()

    if args.render_log:
        if not args.layout:
            print("Error: --render-log requires --layout to be specified.")
            sys.exit(1)
        
        log_path_str = args.render_log[0]
        limit_waypoints = None
        if len(args.render_log) > 1:
            try:
                limit_waypoints = int(args.render_log[1])
            except ValueError:
                print(f"Error: Number of waypoints must be an integer, got '{args.render_log[1]}'")
                sys.exit(1)
        
        log_path = Path(log_path_str)
        if not log_path.exists():
            print(f"Error: Dive log file '{log_path}' does not exist.")
            sys.exit(1)
            
        args.render_log = log_path
        args.limit_waypoints = limit_waypoints
        
        # If only one positional argument is provided, treat it as the output directory/file
        if args.source and not args.output:
            args.output = args.source
            args.source = None
        
        # If no output is specified at all, default to current directory
        if not args.output:
            args.output = Path.cwd()
    elif args.render_video_log:
        if not args.layout:
            print("Error: --render-video-log requires --layout to be specified.")
            sys.exit(1)
        if not args.logs:
            print("Error: --render-video-log requires --logs to be specified.")
            sys.exit(1)
        if not args.source or not args.output:
            print("Error: Source (input folder) and output (output folder) are required when using --render-video-log.")
            sys.exit(2)
    elif args.export_json:
        args.export_json = args.export_json.resolve()
    else:
        if not args.source or not args.output:
            print("Error: Source and output are required unless using --render-log or --export-json.")
            sys.exit(2)

    # Resolve paths to absolute immediately to avoid issues with relative paths in bundled apps
    if args.source:
        args.source = args.source.resolve()
    if args.output:
        args.output = args.output.resolve()
    if args.logs:
        args.logs = args.logs.resolve()

    # Try to get revision from __main__
    revision = getattr(sys.modules['__main__'], 'REVISION', 'dev')
    print(f"UWMedia CLI - Revision: {revision}")

    if args.export_json:
        # Determine source (input) directory for logs
        # If --logs is specified, read logs from args.logs. Otherwise, read from args.export_json.
        input_dir = args.logs if args.logs else args.export_json
        output_dir = args.export_json
        
        if not input_dir.exists() or not input_dir.is_dir():
            print(f"Error: Log directory '{input_dir}' does not exist or is not a directory.")
            sys.exit(1)
            
        # Ensure output directory exists
        output_dir.mkdir(parents=True, exist_ok=True)
            
        print(f"Reading logs from: {input_dir}")
        print(f"Exporting JSONs to: {output_dir}")
        
        shearwater = UDDFParser()
        garmin = GarminParser()
        subsurface = SubsurfaceParser()
        
        log_files = [f for f in sorted(input_dir.iterdir()) if f.is_file() and not f.name.startswith('.')]
        
        processed_count = 0
        for path in log_files:
            suffix = path.suffix.lower()
            if suffix not in (".uddf", ".fit", ".ssrf", ".xml"):
                continue
            
            print(f"Processing log file: {path.name}")
            dives = []
            try:
                if suffix == ".uddf":
                    if args.tz_adjust:
                        shearwater.update_timezone(path, args.tz_adjust * 60)
                    dives = shearwater.parse(path)
                    if args.tz_adjust:
                        for d in dives:
                            d.start_time += timedelta(hours=args.tz_adjust)
                            d.end_time += timedelta(hours=args.tz_adjust)
                            for wp in d.waypoints:
                                wp.timestamp += timedelta(hours=args.tz_adjust)
                            d.invalidate_timestamp_cache()
                elif suffix == ".fit":
                    dives = garmin.parse(path)
                    if args.tz_adjust:
                        for d in dives:
                            d.start_time += timedelta(hours=args.tz_adjust)
                            d.end_time += timedelta(hours=args.tz_adjust)
                            for wp in d.waypoints:
                                wp.timestamp += timedelta(hours=args.tz_adjust)
                            d.invalidate_timestamp_cache()
                elif suffix in (".ssrf", ".xml"):
                    dives = subsurface.parse(path)
                    if args.tz_adjust:
                        for d in dives:
                            d.start_time += timedelta(hours=args.tz_adjust)
                            d.end_time += timedelta(hours=args.tz_adjust)
                            for wp in d.waypoints:
                                wp.timestamp += timedelta(hours=args.tz_adjust)
                            d.invalidate_timestamp_cache()
            except Exception as e:
                print(f"Error parsing {path.name}: {e}")
                continue

            if not dives:
                print(f"No dives found in {path.name}")
                continue

            # Extract waypoints
            all_waypoints = []
            for dive in dives:
                for wp in dive.waypoints:
                    formatted_ts = wp.timestamp.strftime("%Y-%m-%d %H:%M:%S")
                    all_waypoints.append({
                        "timestamp": formatted_ts,
                        "depth": wp.depth
                    })

            # Create json file in output_dir using same filename but json extension
            json_path = output_dir / f"{path.stem}.json"
            try:
                with open(json_path, "w") as f:
                    json.dump(all_waypoints, f, indent=2)
                print(f"Created JSON: {json_path.name}")
                processed_count += 1
            except Exception as e:
                print(f"Error writing JSON for {path.name}: {e}")

        print(f"Export completed. Processed {processed_count} log files.")
        sys.exit(0)

    # Basic Validation
    if args.source and not args.source.exists():
        print(f"Error: Source path '{args.source}' does not exist.")
        sys.exit(1)

    if args.output:
        if str(args.output).strip() == "." or str(args.output).strip() == "":
            # We already check for source == output, but let's be extra safe about empty/current dir
            pass

        try:
            if args.source:
                source_res = args.source.resolve()
                output_res = args.output.resolve() if args.output.exists() else args.output.parent.resolve()
                
                if source_res == output_res:
                    print("Error: Source and output paths cannot be the same.")
                    sys.exit(1)
        except Exception:
            pass

        # Check writability of output parent
        output_parent = args.output.parent if args.output.suffix else args.output
        if not os.access(output_parent if output_parent.exists() else output_parent.parent, os.W_OK):
            # Only warn if it exists, if it doesn't we'll try to create it later
            if output_parent.exists() and not os.access(output_parent, os.W_OK):
                print(f"Error: Output directory '{output_parent}' is not writable.")
                sys.exit(1)

    # Handle HUD Package / Layout
    tmp_hud_dir = None
    args.original_layout_stem = args.layout.stem if args.layout else None
    if args.layout and args.layout.suffix.lower() == ".zip":
        if not args.layout.exists():
            print(f"Error: HUD package {args.layout} not found.")
            sys.exit(1)
        
        tmp_hud_dir = tempfile.mkdtemp()
        with zipfile.ZipFile(args.layout, "r") as zip_file:
            zip_file.extractall(tmp_hud_dir)
            layout_path = Path(tmp_hud_dir) / "hud_layout.json"
            if not layout_path.exists():
                print("Error: HUD package missing hud_layout.json")
                sys.exit(1)
            
            # Point args.layout to the extracted JSON
            args.layout = layout_path

    # If layout is a direct JSON file, resolve relative skin path
    if args.layout and args.layout.suffix.lower() == ".json":
        with open(args.layout, 'r') as f:
            layout_data = json.load(f)
        
        skin_path = layout_data.get("hud_skin", {}).get("path")
        if skin_path and not Path(skin_path).is_absolute():
            # Resolve relative to the layout file
            abs_skin_path = str((args.layout.parent / skin_path).resolve())
            layout_data["hud_skin"]["path"] = abs_skin_path
            # Write back updated absolute path to temp or handle in memory? 
            # Easiest to handle in memory if we pass layout object instead of path.
            # But ffmpeg engine currently takes path. Let's rewrite it to a temp file or update engine.
            # Actually, the engine loads it later. Let's update the engine to load the object or ensure we write it back.
            with open(args.layout, 'w') as f:
                json.dump(layout_data, f, indent=2)

    # 1. Load Dive Logs
    manager = DiveManager()
    found_garmin = False
    if args.logs:
        shearwater = UDDFParser()
        garmin = GarminParser()
        subsurface = SubsurfaceParser()

        if not args.logs.is_dir():
            print(f"Error: Log directory {args.logs} not found.")
            sys.exit(1)

        # Handle Config Generation
        if args.create_config:
            print(f"Scanning {args.logs} for tanks...")
            all_serials = set()
            for path in args.logs.iterdir():
                if path.suffix == ".fit":
                    serials = garmin.get_unique_tank_serials(path)
                    all_serials.update(serials)
            
            from utils.config import get_config
            get_config().save_config(list(all_serials))
            print("You can now edit config.yaml to set friendly names for these tanks.")
            sys.exit(0)

        for path in args.logs.iterdir():
            if path.suffix == ".uddf":
                # ... (shearwater parsing)
                if args.tz_adjust:
                    shearwater.update_timezone(path, args.tz_adjust * 60)
                dives = shearwater.parse(path)
                if args.tz_adjust:
                    for d in dives:
                        d.start_time += timedelta(hours=args.tz_adjust)
                        d.end_time += timedelta(hours=args.tz_adjust)
                        for wp in d.waypoints:
                            wp.timestamp += timedelta(hours=args.tz_adjust)
                        d.invalidate_timestamp_cache()
                manager.add_dives(dives)
            elif path.suffix == ".fit":
                found_garmin = True
                manager.add_dives(garmin.parse(path))
            elif path.suffix in (".ssrf", ".xml"):
                dives = subsurface.parse(path)
                if args.tz_adjust:
                    for d in dives:
                        d.start_time += timedelta(hours=args.tz_adjust)
                        d.end_time += timedelta(hours=args.tz_adjust)
                        for wp in d.waypoints:
                            wp.timestamp += timedelta(hours=args.tz_adjust)
                        d.invalidate_timestamp_cache()
                manager.add_dives(dives)

    # Warning for Garmin logs without config
    from utils.config import get_config
    if found_garmin and not get_config().is_loaded():
        print("\n" + "!" * 60)
        print("WARNING: Garmin logs found but no config.yaml loaded.")
        print("Tank serial numbers will be used instead of friendly names.")
        print("Run with --create-config --logs <dir> to generate a mapping file.")
        print("!" * 60 + "\n")

    if args.layout:
        validate_layout(args.layout, manager)

    if args.render_log:
        process_log_only(args.render_log, args.output, args, manager, tmp_hud_dir)
        # Cleanup temp HUD files if used
        if tmp_hud_dir:
            shutil.rmtree(tmp_hud_dir)
        sys.exit(0)

    meta_handler = MetadataHandler()

    # Handle Source/Output combination
    if args.source.is_dir():
        if not args.output.exists():
            args.output.mkdir(parents=True)
        elif not args.output.is_dir():
            print("Error: Source is a directory but output is a file.")
            sys.exit(1)
        
        # Process all files in directory
        files = [f for f in sorted(args.source.iterdir()) if f.is_file() and not f.name.startswith('.')]
        stats_list = []
        if len(files) > 1:
            from concurrent.futures import ProcessPoolExecutor, as_completed
            import multiprocessing
            # Limit workers to min(4, CPU count) to avoid thrashing CPU/memory
            max_workers = min(4, os.cpu_count() or 4)
            print(f"Starting parallel batch processing with {max_workers} workers...")
            
            tasks = [(file, args.output, args, manager, tmp_hud_dir) for file in files]
            executor = ProcessPoolExecutor(max_workers=max_workers)
            shutdown_wait = True
            try:
                futures = {executor.submit(_parallel_worker, task): task[0] for task in tasks}
                for future in tqdm(as_completed(futures), total=len(futures), desc="Batch Processing", unit="file"):
                    success, filename, result = future.result()
                    if not success:
                        print(f"Error processing {filename}: {result}")
                        stats_list.append({"file": filename, "error": result})
                    else:
                        stats_list.append(result)
            except KeyboardInterrupt:
                print("\n[!] KeyboardInterrupt received. Terminating all worker processes...")
                shutdown_wait = False
                for proc in multiprocessing.active_children():
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                executor.shutdown(wait=False, cancel_futures=True)
                sys.exit(1)
            finally:
                executor.shutdown(wait=shutdown_wait)
        else:
            for file in tqdm(files, desc="Batch Processing", unit="file"):
                res = process_single_file(file, args.output, args, manager, meta_handler, tmp_hud_dir)
                if res:
                    stats_list.append(res)
    else:
        # Single file source
        forced_filename = None
        if args.output.suffix == "" or args.output.is_dir():
            # Output is a directory or intended to be one
            if not args.output.exists():
                args.output.mkdir(parents=True)
            output_dir = args.output
        else:
            # Output is a specific file path
            output_dir = args.output.parent
            if not args.filename_format:
                forced_filename = args.output.name

        stats = process_single_file(args.source, output_dir, args, manager, meta_handler, tmp_hud_dir, forced_filename=forced_filename)
        stats_list = [stats] if stats else []

    print("\nAll tasks complete.")
    
    # Print detailed activity summary if requested
    if args.summary and stats_list:
        print_summary(stats_list)
    
    # Cleanup temp HUD files if used
    if tmp_hud_dir:
        shutil.rmtree(tmp_hud_dir)

def print_summary(stats_list):
    CYAN = "\033[1;36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    MAGENTA = "\033[35m"
    RED = "\033[1;31m"
    RESET = "\033[0m"
    BOLD = "\033[1m"
    WHITE = "\033[1;37m"
    
    print("\n" + "=" * 60)
    print(f"{WHITE}{BOLD}                 UWMedia Activity Summary                 {RESET}")
    print("=" * 60)
    
    for s in stats_list:
        if not s:
            continue
        
        filename = s.get("file", "Unknown")
        if s.get("skipped"):
            print(f"{CYAN}{BOLD}File: {filename}{RESET} - {YELLOW}Skipped (Target exists){RESET}")
            print("-" * 60)
            continue
            
        if s.get("error"):
            print(f"{CYAN}{BOLD}File: {filename}{RESET} - {RED}Failed: {s['error']}{RESET}")
            print("-" * 60)
            continue
            
        file_type = s.get("type", "unknown").capitalize()
        print(f"{CYAN}{BOLD}File: {filename} ({file_type}){RESET}")
        
        stages = s.get("stages", [])
        for stage in stages:
            name = stage.get("name", "Unknown")
            t = stage.get("time", 0.0)
            fps = stage.get("fps")
            
            fps_str = f" ({MAGENTA}{fps:.1f} fps{RESET})" if fps is not None and fps > 0 else ""
            print(f"  {GREEN}{name:<25}{RESET} - Time: {YELLOW}{t:.2f}s{RESET}{fps_str}")
            
        total_time = s.get("total_time", 0.0)
        overall_fps = s.get("overall_fps")
        
        print("  " + "-" * 40)
        fps_summary = f" | Overall FPS: {MAGENTA}{overall_fps:.1f} fps{RESET}" if overall_fps is not None and overall_fps > 0 else ""
        print(f"  {BOLD}Total Time:{RESET} {YELLOW}{total_time:.2f}s{RESET}{fps_summary}")
        print("-" * 60)
    
    print("=" * 60 + "\n")

if __name__ == "__main__":
    main()
