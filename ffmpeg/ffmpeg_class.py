import shutil
import platform
import subprocess
import json
import re
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
from models.dive import Dive, Waypoint
from ffmpeg.hud_filter import generate_hud_filter_complex


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

    def _find_ffmpeg(self) -> Optional[Path]:
        ffmpeg_bin = shutil.which("ffmpeg")
        if ffmpeg_bin:
            return Path(ffmpeg_bin)

        if self.os_type == "Windows":
            search_paths = [
                Path("C:/ffmpeg/bin/ffmpeg.exe"),
                Path("C:/Program Files/ffmpeg/bin/ffmpeg.exe"),
                Path(Path.home() / "ffmpeg/bin/ffmpeg.exe"),
            ]
            for p in search_paths:
                if p.exists():
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
        
        try:
            while True:
                line = process.stderr.readline()
                if not line and process.poll() is not None:
                    break
                
                if duration and "out_time_us=" in line:
                    try:
                        time_us = int(line.split("=")[1])
                        current_secs = time_us / 1000000.0
                        pct = min(100.0, (current_secs / duration) * 100)
                        
                        elapsed = time.time() - start_time
                        if current_secs > 0:
                            total_est = (elapsed / current_secs) * duration
                            remaining = max(0, total_est - elapsed)
                            mins, secs = divmod(int(remaining), 60)
                            print(f"Progress: {pct:5.1f}% | Remaining: {mins:02d}:{secs:02d}", end="\r")
                    except:
                        pass
            
            process.wait()
            if process.returncode != 0:
                raise subprocess.CalledProcessError(process.returncode, cmd)
            
            if duration:
                print(f"Progress: 100.0% | Remaining: 00:00")
                
            return subprocess.CompletedProcess(cmd, process.returncode)
            
        except Exception as e:
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

    def process_video(self, input_path: Path, output_path: Path, creation_date: datetime, dive: Optional[Dive] = None, 
                      stabilize: bool = False, color_correct: bool = False, overlay: bool = False,
                      two_pass: bool = False, layout_path: Optional[Path] = None, hud_path: Optional[Path] = None,
                      start_time: Optional[str] = None, end_time: Optional[str] = None,
                      tz_offset_mins: Optional[int] = None):
        
        args = ["-y"] 
        duration = int(self.get_video_duration(input_path))
        print(f"Video duration: {duration}s")
        
        # 1. Stabilization Pass 1
        trf_file = output_path.with_suffix(".trf")
        if stabilize and two_pass:
            print("Running stabilization pass 1...")
            self.run_command([
                "-i", str(input_path),
                "-vf", f"vidstabdetect=stepsize=32:result='{trf_file}'",
                "-f", "null",
                "-"
            ])

        # 2. Construct Filter Chain
        filters = []
        
        if stabilize:
            if two_pass:
                filters.append(f"vidstabtransform=input='{trf_file}'")
            else:
                filters.append("deshake")

        ass_path = None
        hud_filter = ""
        layout = {}
        # Get video dimensions for HUD scaling
        ffprobe_bin = shutil.which("ffprobe") or str(self.executable_path).replace("ffmpeg", "ffprobe")
        dim_cmd = [ffprobe_bin, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(input_path)]
        width, height = map(int, subprocess.check_output(dim_cmd).decode().strip().split('x'))

        if overlay and layout_path and dive:
            print("Generating telemetry overlay...")
            with open(layout_path, 'r') as f:
                layout = json.load(f)
            
            if "hud_skin" in layout:
                hud_filter = generate_hud_filter_complex(layout, width, height)
            else:
                ass_path = self._generate_ass_file(dive, creation_date, duration, layout, output_path)
                filters.append(f"subtitles='{ass_path}'")

        inputs = ["-i", str(input_path)]
        filter_complex = ""
        
        actual_hud_path = hud_path
        if "hud_skin" in layout:
            actual_hud_path = Path(layout["hud_skin"]["path"])

        if hud_filter:
            inputs.extend(["-i", str(actual_hud_path)])
            if filters:
                last_label_match = re.findall(r'\[([^\]]+)\]$', hud_filter.split(';')[-1])
                last_label = f"[{last_label_match[0]}]" if last_label_match else "[v_hud]"
                filter_complex = hud_filter + f";{last_label}{','.join(filters)}[v_out]"
            else:
                filter_complex = hud_filter + "[v_out]"
        elif actual_hud_path and actual_hud_path.exists():
            inputs.extend(["-i", str(actual_hud_path)])
            overlay_filter = "[0:v][1:v]overlay=0:0"
            if filters:
                filter_complex = f"{overlay_filter},{','.join(filters)}[v_out]"
            else:
                filter_complex = f"{overlay_filter}[v_out]"
        elif filters:
            filter_complex = ",".join(filters)

        # 3. Final Assembly
        full_args = args + inputs
        
        filter_target = "0:v"
        if filter_complex:
            full_args.extend(["-filter_complex", filter_complex])
            if "[v_out]" in filter_complex:
                filter_target = "[v_out]"
                full_args.extend(["-map", "[v_out]", "-map", "0:a?"])
        
        full_args.extend(["-vcodec", self.get_encoder()])
        
        # Quality preservation: Match source bitrate
        try:
            bitrate = self.get_video_bitrate(input_path)
            print(f"Preserving source bitrate: {bitrate/1e6:.1f} Mbps")
            full_args.extend(["-b:v", str(bitrate)])
        except:
            pass

        # Metadata preservation
        full_args.extend(["-map_metadata", "0"])
        full_args.extend(["-movflags", "use_metadata_tags"])
        
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
        try:
            self.run_command(full_args, duration=float(duration))
        finally:
            if ass_path and ass_path.exists(): ass_path.unlink()
            if trf_file and trf_file.exists(): trf_file.unlink()
