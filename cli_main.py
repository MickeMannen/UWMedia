import argparse
import sys
import tempfile
import shutil
import json
from pathlib import Path
from datetime import timedelta, datetime
import zipfile
from parsers.shearwater import ShearwaterParser
from parsers.garmin import GarminParser
from metadata.exif import MetadataHandler
from models.manager import DiveManager
from ffmpeg import FfmpegClass

def get_unique_path(path: Path) -> Path:
    """If file exists, append _1, _2, etc."""
    if not path.exists():
        return path
    
    stem = path.stem
    suffix = path.suffix
    directory = path.parent
    counter = 1
    
    while True:
        new_path = directory / f"{stem}_{counter}{suffix}"
        if not new_path.exists():
            return new_path
        counter += 1

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
        filename = forced_filename
    else:
        format_to_use = args.filename_format
        if not format_to_use and (output_dir != source.parent or args.source.is_dir()):
            # Default date format if outputting to a different directory or batch processing
            format_to_use = "%Y%m%d_%H%M%S"

        if format_to_use:
            try:
                filename = creation_date.strftime(format_to_use) + source.suffix
            except Exception as e:
                print(f"Error formatting filename with pattern '{format_to_use}': {e}")
                filename = source.name
        else:
            filename = source.name
    
    target_path = output_dir / filename
    target_path = get_unique_path(target_path)
    
    print(f"Output path: {target_path}")

    # Match Dive
    dive = manager.find_dive_for_timestamp(creation_date) if manager.dives else None
    if manager.dives and not dive:
        print("Warning: No matching dive log found for this file.")
    elif dive:
        print(f"Matched dive starting at {dive.start_time}")

    # Calculate Timezone Offset for Media
    tz_offset_mins = meta_handler.get_timezone_offset(source)
    if tz_offset_mins is not None:
        print(f"Detected Timezone Offset: {tz_offset_mins/60:+.1f} hours")

    # Determine if it's a video
    is_video = source.suffix.lower() in ['.mp4', '.mov', '.m4v', '.mkv', '.avi']
    
    if is_video:
        if args.color:
            from ffmpeg.color import ColorCorrectionEngine
            engine = ColorCorrectionEngine(FfmpegClass(hw_accel=args.hw_accel, debug=args.debug))
            engine.process_video(
                input_path=source,
                output_path=target_path,
                creation_date=creation_date,
                dive=dive,
                stabilize=args.stabilize,
                overlay=args.overlay,
                two_pass=args.two_pass,
                layout_path=args.layout,
                hud_path=args.hud,
                start_time=args.start_time,
                end_time=args.end_time,
                tz_offset_mins=tz_offset_mins
            )
        else:
            engine = FfmpegClass(hw_accel=args.hw_accel, debug=args.debug)
            engine.process_video(
                input_path=source,
                output_path=target_path,
                creation_date=creation_date,
                dive=dive,
                stabilize=args.stabilize,
                color_correct=False,
                overlay=args.overlay,
                two_pass=args.two_pass,
                layout_path=args.layout,
                hud_path=args.hud,
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
        meta_handler.copy_all(source, target_path)
    except Exception as e:
        print(f"Warning: Failed to copy metadata: {e}")

def main():
    parser = argparse.ArgumentParser(description="Underwater Media Processor CLI")
    parser.add_argument("source", type=Path, help="Source video/photo file or directory")
    parser.add_argument("output", type=Path, help="Output file or directory")
    parser.add_argument("--logs", type=Path, help="Directory containing dive logs")
    parser.add_argument("--color", action="store_true", help="Apply color correction")
    parser.add_argument("--start-time", help="Start time for color correction (HH:MM:SS or MM:SS)")
    parser.add_argument("--end-time", help="End time for color correction (HH:MM:SS or MM:SS)")
    parser.add_argument("--stabilize", action="store_true", help="Apply stabilization")
    parser.add_argument("--overlay", action="store_true", help="Apply telemetry overlay")
    parser.add_argument("--two-pass", action="store_true", help="Use 2-pass stabilization")
    parser.add_argument("--hw-accel", action="store_true", default=True, help="Enable hardware acceleration")
    parser.add_argument("--layout", type=Path, help="JSON layout file for overlay")
    parser.add_argument("--hud", type=Path, help="PNG HUD background for overlay")
    parser.add_argument("--hud-pkg", type=Path, help="ZIP HUD package containing layout and skin")
    parser.add_argument("--tz-adjust", type=int, default=0, help="Timezone adjustment in hours (for Shearwater)")
    parser.add_argument("--debug", action="store_true", help="Show verbose FFmpeg output and debugging info")
    parser.add_argument("--filename-format", help='Template for output filename (e.g. "%%Y%%m%%d_%%H%%M%%S_color")')

    args = parser.parse_args()

    # Handle HUD Package
    tmp_hud_dir = None
    if args.hud_pkg:
        if not args.hud_pkg.exists():
            print(f"Error: HUD package {args.hud_pkg} not found.")
            sys.exit(1)
        
        tmp_hud_dir = tempfile.mkdtemp()
        with zipfile.ZipFile(args.hud_pkg, "r") as zip_file:
            zip_file.extractall(tmp_hud_dir)
            layout_path = Path(tmp_hud_dir) / "hud_layout.json"
            if not layout_path.exists():
                print("Error: HUD package missing hud_layout.json")
                sys.exit(1)
            
            with open(layout_path, 'r') as f:
                layout_data = json.load(f)
            
            skin_filename = layout_data.get("hud_skin", {}).get("path")
            args.layout = layout_path
            args.hud = Path(tmp_hud_dir) / skin_filename

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
        for file in sorted(args.source.iterdir()):
            if file.is_file() and not file.name.startswith('.'):
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
