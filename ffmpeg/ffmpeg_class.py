import shutil
import platform
import subprocess
import json
import re
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
from tqdm import tqdm
from models.dive import Dive, Waypoint
from ffmpeg.hud_filter import generate_hud_filter_complex

# @
class FfmpegClass:
    """
    A wrapper for the locally installed FFmpeg binary.
    Handles finding the executable and performing video processing.
    """
    def __init__(self, hw_accel: bool = True, debug: bool = False):
        self.hw_accel = hw_accel
        self.debug = debug
        self.os_type = platform.system()
        self.executable_path = self._find_ffmpeg()
        if not self.executable_path:
            raise RuntimeError("FFmpeg executable not found in PATH or common installation locations.")

    def _is_actually_ffmpeg(self, path: Path) -> bool:
        try:
            result = subprocess.run([str(path), "-version"], capture_output=True, text=True, timeout=2)
            return "ffmpeg version" in result.stdout.lower()
        except:
            return False

    def _find_ffmpeg(self) -> Optional[Path]:
        ffmpeg_bin = shutil.which("ffmpeg")
        if ffmpeg_bin:
            p = Path(ffmpeg_bin)
            if self._is_actually_ffmpeg(p):
                return p

        # Common locations
        search_paths = []
        if self.os_type == "Windows":
            search_paths.extend([
                Path("C:/ffmpeg/bin/ffmpeg.exe"),
                Path("C:/Program Files/ffmpeg/bin/ffmpeg.exe"),
                Path(Path.home() / "ffmpeg/bin/ffmpeg.exe"),
            ])
        elif self.os_type == "Darwin":
            search_paths.extend([
                Path("/usr/local/bin/ffmpeg"),
                Path("/opt/homebrew/bin/ffmpeg"),
            ])
        
        for p in search_paths:
            if p.exists() and self._is_actually_ffmpeg(p):
                return p
        return None

    def get_path(self) -> Path:
        return self.executable_path

    def run_command(self, args: List[str], duration: Optional[float] = None) -> subprocess.CompletedProcess:
        cmd = [str(self.executable_path)] + args
        
        if self.debug:
            return subprocess.run(cmd, text=True, check=True)

        # Standard processing with progress bar
        cmd.extend(["-progress", "pipe:2", "-nostats", "-loglevel", "error"])
        
        process = subprocess.Popen(
            cmd,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )

        import time
        start_time = time.time()
        stderr_content = []
        
        try:
            # Custom bar_format to show percentage with one decimal (e.g. 50.1%)
            bar_fmt = "{desc}: {percentage:3.1f}%|{bar}| {elapsed}<{remaining}"
            pbar = tqdm(total=100, desc="Encoding", disable=not duration, bar_format=bar_fmt)
            last_pct = 0.0
            
            while True:
                line = process.stderr.readline()
                if not line and process.poll() is not None:
                    break
                
                if line:
                    stderr_content.append(line)
                
                if duration and "out_time_us=" in line:
                    try:
                        time_us = int(line.split("=")[1])
                        current_secs = time_us / 1000000.0
                        pct = min(100.0, (current_secs / duration) * 100)
                        
                        pbar.update(pct - last_pct)
                        last_pct = pct
                    except:
                        pass
            
            pbar.close()
            process.wait()
            if process.returncode != 0:
                error_msg = "".join(stderr_content)
                print(f"\nFFmpeg Error (Exit {process.returncode}):\n{error_msg}")
                raise subprocess.CalledProcessError(process.returncode, cmd, stderr=error_msg)
                
            return subprocess.CompletedProcess(cmd, process.returncode)
            
        except Exception as e:
            if process.poll() is None:
                process.kill()
            raise e

    def get_version(self) -> str:
        cmd = [str(self.executable_path), "-version"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.splitlines()[0]

    def get_encoder(self) -> str:
        if not self.hw_accel:
            return "libx265"
        if self.os_type == "Darwin":
            return "hevc_videotoolbox"
        elif self.os_type == "Windows":
            return "hevc_nvenc"
        return "libx265"

    def has_filter(self, filter_name: str) -> bool:
        """Check if a specific filter is available in the current FFmpeg build."""
        try:
            cmd = [str(self.get_path()), "-filters"]
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode()
            return f" {filter_name} " in output or f" {filter_name}\n" in output
        except:
            return False

    def get_video_duration(self, input_path: Path) -> float:
        """Uses ffprobe to get video duration."""
        ffprobe_bin = shutil.which("ffprobe")
        if not ffprobe_bin:
            ffprobe_bin = str(self.executable_path).replace("ffmpeg", "ffprobe")
            if not Path(ffprobe_bin).exists():
                raise RuntimeError("ffprobe not found.")

        cmd = [
            str(ffprobe_bin),
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(input_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())

    def get_video_bitrate(self, input_path: Path) -> int:
        """Uses ffprobe to get video bitrate."""
        ffprobe_bin = shutil.which("ffprobe")
        if not ffprobe_bin:
            ffprobe_bin = str(self.executable_path).replace("ffmpeg", "ffprobe")
        
        cmd = [
            str(ffprobe_bin),
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=bit_rate",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(input_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        out = result.stdout.strip()
        # Fallback if bitrate is not in stream (try format)
        if not out or out == "N/A":
            cmd = [
                str(ffprobe_bin),
                "-v", "error",
                "-show_entries", "format=bit_rate",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(input_path)
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            out = result.stdout.strip()
        
        return int(out) if out.isdigit() else 10000000 # Default 10Mbps if unknown

    def _parse_time(self, time_str: Optional[str]) -> Optional[float]:
        if not time_str: return None
        try:
            parts = list(map(int, time_str.split(':')))
            if len(parts) == 3: return float(parts[0] * 3600 + parts[1] * 60 + parts[2])
            if len(parts) == 2: return float(parts[0] * 60 + parts[1])
            return float(time_str)
        except:
            return None

    def _generate_ass_file(self, dive: Dive, creation_date: datetime, duration: int, layout: Dict[str, Any], output_path: Path) -> Path:
        """Generates an Advanced Substation Alpha (ASS) file for high-performance telemetry."""
        ass_path = output_path.with_suffix(".ass")
        video_start_offset = (dive.start_time - creation_date).total_seconds()
        
        with open(ass_path, "w") as f:
            f.write("[Script Info]\nPlayResX: 1920\nPlayResY: 1080\n\n")
            f.write("[V4+ Styles]\n")
            f.write("Format: Name, Fontname, Fontsize, PrimaryColour, BackColour, Bold, Italic, Alignment, Outline, Shadow, MarginV\n")
            f.write("Style: Telemetry,Arial,36,&H00FFFFFF,&H80000000,1,0,7,1,1,10\n\n")
            f.write("[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
            
            for t in range(duration):
                start_ts = f"{t//3600:01}:{ (t%3600)//60 :02}:{t%60:02}.00"
                end_ts = f"{(t+1)//3600:01}:{ ((t+1)%3600)//60 :02}:{(t+1)%60:02}.00"
                
                wp_idx = int(t - video_start_offset)
                if wp_idx < 0: wp = Waypoint(timestamp=creation_date, depth=0, temp=0, time_since_start=0)
                elif wp_idx >= len(dive.waypoints): wp = dive.waypoints[-1]
                else: wp = dive.waypoints[wp_idx]
                
                for key, config in layout.items():
                    val = f"Depth: {wp.depth:.1f}m" if key == "depth" else f"Temp: {wp.temp:.1f}C" if key == "temp" else ""
                    if val:
                        x = int(config['x'] * 19.2)
                        y = int(config['y'] * 10.8)
                        f.write(f"Dialogue: 0,{start_ts},{end_ts},Telemetry,,0,0,0,,{{\\pos({x},{y})}}{val}\n")
        
        return ass_path

    def get_video_dimensions(self, input_path: Path) -> tuple[int, int]:
        """Uses ffprobe to get video width and height."""
        ffprobe_bin = shutil.which("ffprobe") or str(self.executable_path).replace("ffmpeg", "ffprobe")
        cmd = [
            ffprobe_bin, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0",
            str(input_path)
        ]
        result = subprocess.check_output(cmd).decode().strip()
        return map(int, result.split('x'))

    def get_video_pix_fmt(self, input_path: Path) -> str:
        """Uses ffprobe to get video pixel format."""
        ffprobe_bin = shutil.which("ffprobe") or str(self.executable_path).replace("ffmpeg", "ffprobe")
        cmd = [
            ffprobe_bin, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=pix_fmt", "-of", "default=noprint_wrappers=1:nokey=1",
            str(input_path)
        ]
        return subprocess.check_output(cmd).decode().strip()

    def process_video(self, input_path: Path, output_path: Path, creation_date: datetime, dive: Optional[Dive] = None, 
                      stabilize: Optional[str] = None, color_correct: bool = False, overlay: bool = False,
                      layout_path: Optional[Path] = None,
                      start_time: Optional[str] = None, end_time: Optional[str] = None,
                      tz_offset_mins: Optional[int] = None,
                      target_resolution: Optional[tuple[int, int]] = None,
                      bitrate: Optional[str] = None):
        
        args = ["-y"]
        s_sec = self._parse_time(start_time) or 0.0
        e_sec = self._parse_time(end_time) or self.get_video_duration(input_path)
        clip_duration = max(0, e_sec - s_sec)

        if start_time:
            args.extend(["-ss", start_time])
        if end_time:
            args.extend(["-to", end_time])

        duration = int(self.get_video_duration(input_path))
        width, height = self.get_video_dimensions(input_path)
        print(f"Video: {width}x{height} | Duration: {duration}s")
        
        # 1. Stabilization (Deshake)
        if stabilize:
            print(f"Stabilization enabled (level: {stabilize})...")

        # 2. Construct Filter Chain
        filters = []
        
        # Scale filter
        if target_resolution:
            tw, th = target_resolution
            print(f"Downscaling to {tw}x{th}...")
            # Use -2 to maintain aspect ratio if one dimension is set, 
            # but here we provide both, so we use scale=w:h and ensure even numbers
            filters.append(f"scale={tw}:{th}:force_original_aspect_ratio=decrease,pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2")

        if stabilize:
            if stabilize == "low":
                filters.append("deshake=blocksize=8:rx=16:ry=16:edge=mirror")
            elif stabilize == "mid":
                filters.append("deshake=blocksize=16:rx=32:ry=32:edge=mirror")
            else:  # high
                filters.append("deshake=blocksize=32:rx=64:ry=64:edge=mirror")

        ass_path = None
        hud_filter = ""
        layout = {}
        actual_hud_path = None

        if overlay and layout_path and dive:
            print("Generating telemetry overlay...")
            with open(layout_path, 'r') as f:
                layout = json.load(f)
            
            # Resolve actual_hud_path correctly relative to layout_path
            if "hud_skin" in layout:
                skin_rel_path = layout["hud_skin"].get("path")
                if skin_rel_path:
                    # Skin path should be relative to the layout file
                    actual_hud_path = layout_path.parent / Path(skin_rel_path).name
            
            # Only generate FFmpeg-based HUD if we aren't using the OpenCV path
            if not color_correct:
                if "hud_skin" in layout and actual_hud_path and actual_hud_path.exists():
                    hud_filter = generate_hud_filter_complex(layout, width, height, actual_hud_path)
                elif "hud_skin" in layout:
                    print(f"Warning: HUD skin not found at {actual_hud_path}")
                else:
                    ass_path = self._generate_ass_file(dive, creation_date, duration, layout, output_path)
                    filters.append(f"subtitles='{ass_path}'")

        inputs = ["-i", str(input_path)]
        filter_complex = ""
        
        if hud_filter:
            inputs.extend(["-i", str(actual_hud_path)])
            if filters:
                last_label_match = re.findall(r'\[([^\]]+)\]$', hud_filter.split(';')[-1])
                last_label = f"[{last_label_match[0]}]" if last_label_match else "[v_hud]"
                filter_complex = hud_filter + f";{last_label}{','.join(filters)}[v_out]"
            else:
                filter_complex = hud_filter + "[v_out]"
        elif filters:
            filter_complex = ",".join(filters)

        # 3. Final Assembly
        # Passthrough mode: Use -c copy if no video adjustments are requested
        is_passthrough = not (filter_complex or stabilize or target_resolution or bitrate or color_correct)
        
        full_args = args + inputs
        
        if is_passthrough:
            print("No adjustments requested. Using fast stream copy (passthrough)...")
            # Map video and audio, but ignore unsupported data/metadata streams in container
            # Using -map 0:v -map 0:a -map 0:s? to get video, audio, and optional subtitles
            full_args.extend(["-c", "copy", "-map", "0:v", "-map", "0:a?", "-map", "0:s?", "-map_metadata", "0"])
            
            # Creation date with timezone
            if tz_offset_mins is not None:
                sign = "+" if tz_offset_mins >= 0 else "-"
                hours = abs(tz_offset_mins) // 60
                mins = abs(tz_offset_mins) % 60
                tz_str = f"{sign}{hours:02}{mins:02}"
                iso_date = creation_date.strftime("%Y-%m-%dT%H:%M:%S") + tz_str
                full_args.extend(["-metadata", f"creation_time={iso_date}"])
            
            full_args.extend(["-movflags", "+faststart+use_metadata_tags"])
            full_args.extend([str(output_path)])
            
            if self.debug:
                print(full_args)
            try:
                self.run_command(full_args, duration=float(clip_duration))
            finally:
                if ass_path and ass_path.exists(): ass_path.unlink()
            return

        filter_target = "0:v"
        if filter_complex:
            full_args.extend(["-filter_complex", filter_complex])
            if "[v_out]" in filter_complex:
                filter_target = "[v_out]"
                full_args.extend(["-map", "[v_out]", "-map", "0:a?"])
        
        full_args.extend(["-vcodec", self.get_encoder()])
        
        # Quality preservation or override
        if bitrate:
            print(f"Applying target bitrate: {bitrate}")
            full_args.extend(["-b:v", bitrate])
        else:
            try:
                src_bitrate = self.get_video_bitrate(input_path)
                print(f"Preserving source bitrate: {src_bitrate/1e6:.1f} Mbps")
                full_args.extend(["-b:v", str(src_bitrate)])
            except:
                pass

        # Metadata preservation
        full_args.extend(["-map_metadata", "0"])
        full_args.extend(["-movflags", "+faststart+use_metadata_tags"])
        
        # Compatibility and Color Metadata
        full_args.extend(["-tag:v", "hvc1"])
        full_args.extend([
            "-color_primaries", "1",
            "-color_trc", "1",
            "-colorspace", "1"
        ])
        
        # Creation date with timezone
        if tz_offset_mins is not None:
            sign = "+" if tz_offset_mins >= 0 else "-"
            hours = abs(tz_offset_mins) // 60
            mins = abs(tz_offset_mins) % 60
            tz_str = f"{sign}{hours:02}{mins:02}"
            iso_date = creation_date.strftime("%Y-%m-%dT%H:%M:%S") + tz_str
            full_args.extend(["-metadata", f"creation_time={iso_date}"])

        full_args.extend(["-acodec", "copy"])
        full_args.extend(["-pix_fmt", "yuv420p"]) 
        full_args.extend([str(output_path)])

        print(f"Executing FFmpeg with {self.get_encoder()}...")
        # if self.debug:
        #     print(full_args)
        try:
            self.run_command(full_args, duration=float(clip_duration))
        finally:
            if ass_path and ass_path.exists(): ass_path.unlink()
