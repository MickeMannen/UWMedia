import argparse
import sys
from pathlib import Path
from datetime import timedelta
from parsers.shearwater import ShearwaterParser
from parsers.garmin import GarminParser
from metadata.handler import MetadataHandler
from models.manager import DiveManager
from ffmpeg import FfmpegClass

def main():
    parser = argparse.ArgumentParser(description="Underwater Media Processor CLI")
    parser.add_argument("source", type=Path, help="Source video file path")
    parser.add_argument("output", type=Path, help="Output video file path")
    parser.add_argument("--logs", type=Path, help="Directory containing dive logs", required=True)
    parser.add_argument("--color", action="store_true", help="Apply color correction")
    parser.add_argument("--stabilize", action="store_true", help="Apply stabilization")
    parser.add_argument("--overlay", action="store_true", help="Apply telemetry overlay")
    parser.add_argument("--two-pass", action="store_true", help="Use 2-pass stabilization")
    parser.add_argument("--hw-accel", action="store_true", default=True, help="Enable hardware acceleration")
    parser.add_argument("--layout", type=Path, help="JSON layout file for overlay")
    parser.add_argument("--hud", type=Path, help="PNG HUD background for overlay")
    parser.add_argument("--tz-adjust", type=int, default=0, help="Timezone adjustment in hours (for Shearwater)")

    args = parser.parse_args()

    # 1. Load Dive Logs
    manager = DiveManager()
    shearwater = ShearwaterParser()
    garmin = GarminParser()

    if not args.logs.is_dir():
        print(f"Error: Log directory {args.logs} not found.")
        sys.exit(1)

    for path in args.logs.iterdir():
        if path.suffix == ".uddf":
            print(f"Parsing Shearwater log: {path.name}")
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
    dive = manager.find_dive_for_timestamp(creation_date)
    if not dive:
        print("Warning: No matching dive log found for this video.")
    else:
        print(f"Matched dive starting at {dive.start_time}")

    # 4. Process Video
    engine = FfmpegClass(hw_accel=args.hw_accel)
    engine.process_video(
        input_path=args.source,
        output_path=args.output,
        creation_date=creation_date,
        dive=dive,
        stabilize=args.stabilize,
        color_correct=args.color,
        overlay=args.overlay,
        two_pass=args.two_pass,
        layout_path=args.layout,
        hud_path=args.hud
    )

    print("Processing complete.")

if __name__ == "__main__":
    main()
