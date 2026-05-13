import argparse
import sys
import tempfile
import shutil
import json
from pathlib import Path
from datetime import timedelta
import zipfile
from parsers.shearwater import ShearwaterParser
from parsers.garmin import GarminParser
from metadata.exif import MetadataHandler
from models.manager import DiveManager
from ffmpeg import FfmpegClass

def main():
    parser = argparse.ArgumentParser(description="Underwater Media Processor CLI")
    parser.add_argument("source", type=Path, help="Source video file path")
    parser.add_argument("output", type=Path, help="Output video file path")
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
            
            # Find the JSON file
            layout_path = Path(tmp_hud_dir) / "hud_layout.json"
            if not layout_path.exists():
                print("Error: HUD package missing hud_layout.json")
                sys.exit(1)
            
            with open(layout_path, 'r') as f:
                layout_data = json.load(f)
            
            skin_filename = layout_data.get("hud_skin", {}).get("path")
            if not skin_filename:
                print("Error: hud_layout.json missing skin path")
                sys.exit(1)
            
            args.layout = layout_path
            args.hud = Path(tmp_hud_dir) / skin_filename
            
            if not args.hud.exists():
                print(f"Error: Skin file {skin_filename} not found in package.")
                sys.exit(1)

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
                print(f"Parsing Shearwater log: {path.name}")
                
                # If script is run with timezone info, update original file per spec
                if args.tz_adjust:
                    shearwater.update_timezone(path, args.tz_adjust * 60)
                
                dives = shearwater.parse(path)
                # Apply timezone adjustment if requested
                if args.tz_adjust:
                    for d in dives:
                        d.start_time += timedelta(hours=args.tz_adjust)
                        d.end_time += timedelta(hours=args.tz_adjust)
                        for wp in d.waypoints:
                            wp.timestamp += timedelta(hours=args.tz_adjust)
                manager.add_dives(dives)
            elif path.suffix == ".fit":
                print(f"Parsing Garmin log: {path.name}")
                manager.add_dives(garmin.parse(path))

        manager.print_dives()
    # 2. Extract Video Metadata
    meta_handler = MetadataHandler()
    try:
        creation_date = meta_handler.get_local_creation_date(args.source)
        print(f"Video Local Creation Date: {creation_date}")
    except Exception as e:
        print(f"Error extracting metadata: {e}")
        sys.exit(1)

    # 3. Match Dive
    dive = manager.find_dive_for_timestamp(creation_date) if args.logs else None
    if args.logs and not dive:
        print("Warning: No matching dive log found for this video.")
    elif dive:
        print(f"Matched dive starting at {dive.start_time}")

    # 4. Calculate Timezone Offset for Media
    tz_offset_mins = meta_handler.get_timezone_offset(args.source)
    if tz_offset_mins is not None:
        print(f"Detected Timezone Offset: {tz_offset_mins/60:+.1f} hours")

    # 5. Process Video
    if args.color:
        from ffmpeg.color import ColorCorrectionEngine
        engine = ColorCorrectionEngine(FfmpegClass(hw_accel=args.hw_accel))
        engine.process_video(
            input_path=args.source,
            output_path=args.output,
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
        engine = FfmpegClass(hw_accel=args.hw_accel)
        engine.process_video(
            input_path=args.source,
            output_path=args.output,
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

    print("Processing complete.")
    
    # Cleanup temp HUD files if used
    if tmp_hud_dir:
        shutil.rmtree(tmp_hud_dir)

if __name__ == "__main__":
    main()
