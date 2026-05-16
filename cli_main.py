import argparse
import sys
import os
import tempfile
import shutil
import json
from pathlib import Path
from datetime import timedelta, datetime
import zipfile
from tqdm import tqdm
from parsers.shearwater import ShearwaterParser
from parsers.garmin import GarminParser
from metadata.exif import MetadataHandler
from models.manager import DiveManager
from ffmpeg import FfmpegClass

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
    print(f"\n--- Processing: {source.name} ---")
    
    # Extract Metadata
    try:
        creation_date = meta_handler.get_local_creation_date(source)
        print(f"Local Creation Date: {creation_date}")
    except Exception as e:
        print(f"Error extracting metadata for {source}: {e}")
        return

    # Determine Output Path
    if forced_filename:
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
    
    target_path = output_dir / filename
    target_path = get_unique_path(target_path)
    
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
        try:
            meta_handler.copy_all(source, target_path, force_tz_mins=tz_offset_mins, custom_tags=args.modify_quicktime)
            print("Success: Metadata updated.")
        except Exception as e:
            print(f"Error updating metadata: {e}")
        return

    # Match Dive
    dive = manager.find_dive_for_timestamp(creation_date) if manager.dives else None
    if manager.dives and not dive:
        print("Warning: No matching dive log found for this file.")
    elif dive:
        print(f"Matched dive starting at {dive.start_time}")

    overlay = True if args.layout else False

    # Determine if it's a video
    is_video = source.suffix.lower() in ['.mp4', '.mov', '.m4v', '.mkv', '.avi']
    
    if is_video and args.convert:
        # Multi-resolution conversion mode
        process_conversions(source, output_dir, args, creation_date, tz_offset_mins, meta_handler)
        return

    if is_video:
        ff = FfmpegClass(hw_accel=args.hw_accel, debug=args.debug)
        needs_color = args.color
        needs_overlay = True if args.layout else False
        
        # Use OpenCV pipe if color correction OR overlay is requested
        # Telemetry overlays are much easier to sync in the OpenCV pipe
        use_opencv_pipe = needs_color or needs_overlay

        if use_opencv_pipe:
            from ffmpeg.color import ColorCorrectionEngine
            engine = ColorCorrectionEngine(ff)
            engine.process_video(
                input_path=source,
                output_path=target_path,
                creation_date=creation_date,
                dive=dive,
                stabilize=args.stabilize,
                overlay=needs_overlay,
                layout_path=args.layout,
                start_time=args.start_time,
                end_time=args.end_time,
                tz_offset_mins=tz_offset_mins,
                color_correct=needs_color
            )
        else:
            ff.process_video(
                input_path=source,
                output_path=target_path,
                creation_date=creation_date,
                dive=dive,
                stabilize=args.stabilize,
                color_correct=False,
                overlay=needs_overlay,
                layout_path=args.layout,
                start_time=args.start_time,
                end_time=args.end_time,
                tz_offset_mins=tz_offset_mins
            )
    else:
        # Simple copy for photos for now
        print(f"Skipping video processing for: {source.name} (Copying as photo)")
        shutil.copy2(source, target_path)

    # Post-processing metadata
    print("Post-processing metadata...")
    try:
        forced_tz_mins = int(args.force_media_tz * 60) if args.force_media_tz is not None else None
        meta_handler.copy_all(source, target_path, force_tz_mins=forced_tz_mins, custom_tags=args.modify_quicktime)
    except Exception as e:
        print(f"Warning: Failed to copy metadata: {e}")

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
    parser.add_argument("source", type=Path, help="Source video/photo file or directory")
    parser.add_argument("output", type=Path, help="Output file or directory")
    parser.add_argument("--logs", type=Path, help="Directory containing dive logs")
    parser.add_argument("--color", action="store_true", help="Apply color correction")
    parser.add_argument("--start-time", help="Start time for clipping/processing (HH:MM:SS or MM:SS)")
    parser.add_argument("--end-time", help="End time for clipping/processing (HH:MM:SS or MM:SS)")
    parser.add_argument("--stabilize", nargs='?', const='high', choices=['low', 'mid', 'high'], help="Stabilization level (low, mid, high). Default: high")
    parser.add_argument("--hw-accel", action="store_true", default=False, help="Enable hardware acceleration")
    parser.add_argument("--layout", type=Path, help="JSON layout file or ZIP HUD package for overlay. Automatically enables overlay.")
    parser.add_argument("--tz-adjust", type=int, default=0, help="Timezone adjustment in hours (for Shearwater)")
    parser.add_argument("--force-media-tz", type=float, help="Force a specific timezone offset for media (in hours, e.g. +8 or -5.5)")
    parser.add_argument("--fix-tz", action="store_true", help="Only update the timezone metadata and exit (requires --force-media-tz)")
    parser.add_argument("--modify-quicktime", nargs='+', help="Manually modify QuickTime tags (e.g., 'QuickTime:CreateDate=2021:11:12 11:03:02')")
    parser.add_argument("--debug", action="store_true", help="Show verbose FFmpeg output and debugging info")
    parser.add_argument("--filename-format", help='Template for output filename (e.g. "%%Y%%m%%d_%%H%%M%%S_color")')
    parser.add_argument("--convert", nargs='+', choices=['1080p', '720p', '480p', '360p'], help="Downscale to selected resolutions (multi allowed). Output will be a directory.")

    args = parser.parse_args()

    # Resolve paths to absolute immediately to avoid issues with relative paths in bundled apps
    args.source = args.source.resolve()
    args.output = args.output.resolve()

    # Try to get revision from __main__
    revision = getattr(sys.modules['__main__'], 'REVISION', 'dev')
    print(f"UWMedia CLI - Revision: {revision}")

    # Basic Validation
    if not args.source.exists():
        print(f"Error: Source path '{args.source}' does not exist.")
        sys.exit(1)

    if str(args.output).strip() == "." or str(args.output).strip() == "":
        # We already check for source == output, but let's be extra safe about empty/current dir
        pass

    try:
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
    if args.logs:
        shearwater = ShearwaterParser()
        garmin = GarminParser()

        if not args.logs.is_dir():
            print(f"Error: Log directory {args.logs} not found.")
            sys.exit(1)

        for path in args.logs.iterdir():
            if path.suffix == ".uddf":
                if args.tz_adjust:
                    shearwater.update_timezone(path, args.tz_adjust * 60)
                dives = shearwater.parse(path)
                if args.tz_adjust:
                    for d in dives:
                        d.start_time += timedelta(hours=args.tz_adjust)
                        d.end_time += timedelta(hours=args.tz_adjust)
                        for wp in d.waypoints:
                            wp.timestamp += timedelta(hours=args.tz_adjust)
                manager.add_dives(dives)
            elif path.suffix == ".fit":
                manager.add_dives(garmin.parse(path))

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
        for file in tqdm(files, desc="Batch Processing", unit="file"):
            process_single_file(file, args.output, args, manager, meta_handler, tmp_hud_dir)
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

        process_single_file(args.source, output_dir, args, manager, meta_handler, tmp_hud_dir, forced_filename=forced_filename)

    print("\nAll tasks complete.")
    
    # Cleanup temp HUD files if used
    if tmp_hud_dir:
        shutil.rmtree(tmp_hud_dir)

if __name__ == "__main__":
    main()
