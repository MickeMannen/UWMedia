import ffmpeg
import platform
import json
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from models.dive import Dive, Waypoint

class FFmpegEngine:
    def __init__(self, hw_accel: bool = True):
        self.hw_accel = hw_accel
        self.os_type = platform.system()

    def get_encoder(self) -> str:
        if not self.hw_accel:
            return "libx265"
        
        if self.os_type == "Darwin":
            return "hevc_videotoolbox"
        elif self.os_type == "Windows":
            # Default to NVENC, could be AMF
            return "hevc_nvenc"
        return "libx265"

    def calculate_color_correction(self, depth: float) -> str:
        """
        Calculate RGB attenuation. 
        Simplified: Red light is absorbed first.
        At 10m, red is mostly gone.
        """
        # Simple linear approximation for demonstration
        # Real underwater color correction is more complex (exponential)
        red_gain = 1.0 + (depth * 0.1)  # Increase red as we go deeper
        green_gain = 1.0 + (depth * 0.02)
        blue_gain = 1.0
        
        # FFmpeg colorlevels filter or eq
        # colorlevels=rimax=0.5:gimax=0.8:bimax=1.0
        return f"colorlevels=rimax={max(0.1, 1.0/red_gain)}:gimax={max(0.1, 1.0/green_gain)}:bimax={max(0.1, 1.0/blue_gain)}"

    def build_telemetry_filters(self, waypoints: list[Waypoint], start_offset: float, layout: Dict[str, Any]) -> str:
        # This will generate a series of drawtext filters with enable='between(t, ...)'
        filters = []
        for i, wp in enumerate(waypoints):
            # Show each waypoint for 1 second (assuming 1Hz log)
            t_start = i
            t_end = i + 1
            
            # Position based on percentages
            # For each element in layout (depth, temp, etc.)
            for key, config in layout.items():
                val = ""
                if key == "depth": val = f"{wp.depth:.1f}m"
                elif key == "temp": val = f"{wp.temp:.1f}C"
                
                if val:
                    x = f"w*{config['x']/100}"
                    y = f"h*{config['y']/100}"
                    filters.append(
                        f"drawtext=text='{val}':x={x}:y={y}:fontcolor=white:fontsize=24:enable='between(t,{t_start},{t_end})'"
                    )
        return ",".join(filters)

    def process_video(self, input_path: str, output_path: str, dive: Optional[Dive] = None, 
                      stabilize: bool = False, color_correct: bool = False, overlay: bool = False,
                      two_pass: bool = False, layout_path: Optional[str] = None, hud_path: Optional[str] = None):
        
        # 1. Stabilization Pass 1
        if stabilize and two_pass:
            trf_file = "transforms.trf"
            print(f"Running stabilization pass 1...")
            ffmpeg.input(input_path).filter("vidstabdetect", stepsize=32, result=trf_file).output("null", format="null").run(overwrite_output=True, quiet=True)
            
        stream = ffmpeg.input(input_path)
        
        # 2. Add HUD Overlay
        if overlay and hud_path and os.path.exists(hud_path):
            hud = ffmpeg.input(hud_path)
            stream = ffmpeg.overlay(stream, hud, x=0, y=0)

        # 3. Build Filter Chain
        if stabilize:
            if two_pass:
                stream = stream.filter("vidstabtransform", input='transforms.trf')
            else:
                stream = stream.filter("deshake")

        if color_correct and dive and dive.waypoints:
            print("Applying dynamic color correction...")
            video_start_offset = (dive.start_time - creation_date).total_seconds()
            probe = ffmpeg.probe(input_path)
            duration = int(float(probe['format']['duration']))
            
            for t in range(0, duration, 5): # Update every 5 seconds to reduce filter count
                wp_idx = int(t - video_start_offset)
                if wp_idx < 0:
                    depth = 0
                elif wp_idx >= len(dive.waypoints):
                    depth = dive.waypoints[-1].depth
                else:
                    depth = dive.waypoints[wp_idx].depth
                
                correction = self.calculate_color_correction(depth)
                # Parse correction to get args
                name, args = correction.split("=", 1)
                stream = stream.filter(name, args, enable=f"between(t,{t},{t+5})")

        # 4. Add Telemetry Drawtext
        if overlay and layout_path and dive:
            with open(layout_path, 'r') as f:
                layout = json.load(f)
            
            # Calculate video start time offset relative to dive start
            # If video starts 5 mins before dive, offset is -300
            video_start_offset = (dive.start_time - creation_date).total_seconds()
            
            # Get video duration
            probe = ffmpeg.probe(input_path)
            duration = int(float(probe['format']['duration']))
            
            print(f"Generating telemetry for {duration} seconds...")
            for t in range(duration):
                t_start = t
                t_end = t + 1
                
                # Find the corresponding waypoint
                # Waypoint index in dive.waypoints is t - video_start_offset
                wp_idx = int(t - video_start_offset)
                
                if wp_idx < 0:
                    # Before dive: show 0
                    current_wp = Waypoint(timestamp=creation_date, depth=0, temp=0, time_since_start=0)
                elif wp_idx >= len(dive.waypoints):
                    # After dive: use last waypoint
                    current_wp = dive.waypoints[-1]
                else:
                    current_wp = dive.waypoints[wp_idx]

                for key, config in layout.items():
                    val = ""
                    if key == "depth": val = f"Depth: {current_wp.depth:.1f}m"
                    elif key == "temp": val = f"Temp: {current_wp.temp:.1f}C"
                    
                    if val:
                        stream = stream.drawtext(
                            text=val,
                            x=f"w*{config['x']/100}",
                            y=f"h*{config['y']/100}",
                            fontcolor="white",
                            fontsize=24,
                            enable=f"between(t,{t_start},{t_end})"
                        )

        # 5. Output with Hardware Acceleration
        encoder = self.get_encoder()
        print(f"Encoding video with {encoder}...")
        (
            stream
            .output(output_path, vcodec=encoder, acodec="copy")
            .run(overwrite_output=True)
        )
