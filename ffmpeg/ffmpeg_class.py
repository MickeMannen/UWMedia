import platform
import subprocess
import time
from pathlib import Path
from typing import Optional, List
from datetime import datetime
from tqdm import tqdm
from utils.tool_paths import get_ffmpeg_path, get_ffprobe_path

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
        self.executable_path = get_ffmpeg_path()
        if not self.executable_path:
            raise RuntimeError(
                "FFmpeg executable not found. Configure its location on the "
                "Advanced page, or install FFmpeg and ensure it's on your PATH."
            )
        self.ffprobe_path = get_ffprobe_path(self.executable_path)

    def get_path(self) -> Path:
        return self.executable_path

    def run_command(
        self, args: List[str], duration: Optional[float] = None, progress_label: Optional[str] = None
    ) -> subprocess.CompletedProcess:
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
            last_emitted_pct = 0.0

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
                        # Surfaced to the GUI (color_backend.py parses this to
                        # drive the Progress bar mid-file) - throttled so a
                        # high-fps source doesn't flood the pipe with an
                        # update per frame. progress_label (when given -
                        # ffmpeg/color.py's color-correction path passes the
                        # source filename) lets the GUI attribute this
                        # percentage to a specific file even when several
                        # run concurrently in a real batch, instead of only
                        # trusting a bare percentage for a single-file run.
                        if pct - last_emitted_pct >= 1.0 or pct >= 100.0:
                            if progress_label:
                                print(f"UWMEDIA_FFMPEG_PROGRESS {pct:.1f} {progress_label}", flush=True)
                            else:
                                print(f"UWMEDIA_FFMPEG_PROGRESS {pct:.1f}", flush=True)
                            last_emitted_pct = pct
                    except:
                        pass
            
            pbar.close()
            process.wait()
            if process.returncode != 0:
                error_msg = "".join(stderr_content)
                print(f"\nFFmpeg Error (Exit {process.returncode}):\n{error_msg}")
                raise subprocess.CalledProcessError(process.returncode, cmd, stderr=error_msg)
                
            return subprocess.CompletedProcess(cmd, process.returncode)
            
        except BaseException as e:
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

    def get_video_duration(self, input_path: Path) -> float:
        """Uses ffprobe to get video duration."""
        if not self.ffprobe_path:
            raise RuntimeError(
                "ffprobe executable not found. Configure FFmpeg's location on "
                "the Advanced page (ffprobe is expected alongside it), or "
                "install FFmpeg and ensure it's on your PATH."
            )

        cmd = [
            str(self.ffprobe_path),
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(input_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())

    def get_video_bitrate(self, input_path: Path) -> int:
        """Uses ffprobe to get video bitrate."""
        cmd = [
            str(self.ffprobe_path),
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
                str(self.ffprobe_path),
                "-v", "error",
                "-show_entries", "format=bit_rate",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(input_path)
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            out = result.stdout.strip()
        
        return int(out) if out.isdigit() else 10000000 # Default 10Mbps if unknown

    def get_video_dimensions(self, input_path: Path) -> tuple[int, int]:
        """Uses ffprobe to get video width and height."""
        cmd = [
            str(self.ffprobe_path), "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0",
            str(input_path)
        ]
        result = subprocess.check_output(cmd).decode().strip()
        return map(int, result.split('x'))

    def get_video_frame_count(self, input_path: Path) -> int:
        """Uses ffprobe to get video frame count."""
        cmd = [
            str(self.ffprobe_path), "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=nb_frames", "-of", "default=noprint_wrappers=1:nokey=1",
            str(input_path)
        ]
        try:
            out = subprocess.check_output(cmd).decode().strip()
            if out.isdigit():
                return int(out)
        except:
            pass
        try:
            duration = self.get_video_duration(input_path)
            return int(duration * 30.0)
        except:
            return 0

    def get_video_pix_fmt(self, input_path: Path) -> str:
        """Uses ffprobe to get video pixel format."""
        cmd = [
            str(self.ffprobe_path), "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=pix_fmt", "-of", "default=noprint_wrappers=1:nokey=1",
            str(input_path)
        ]
        return subprocess.check_output(cmd).decode().strip()

    def process_video(self, input_path: Path, output_path: Path, creation_date: datetime,
                      color_correct: bool = False,
                      tz_offset_mins: Optional[int] = None,
                      target_resolution: Optional[tuple[int, int]] = None,
                      bitrate: Optional[str] = None):

        args = ["-y"]
        duration = int(self.get_video_duration(input_path))
        width, height = self.get_video_dimensions(input_path)
        print(f"Video: {width}x{height} | Duration: {duration}s")
        
        # 2. Construct Filter Chain
        filters = []
        
        # Scale filter
        if target_resolution:
            tw, th = target_resolution
            print(f"Downscaling to {tw}x{th}...")
            # Use -2 to maintain aspect ratio if one dimension is set, 
            # but here we provide both, so we use scale=w:h and ensure even numbers
            filters.append(f"scale={tw}:{th}:force_original_aspect_ratio=decrease,pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2")



        inputs = ["-i", str(input_path)]
        filter_complex = ",".join(filters) if filters else ""

        # 3. Final Assembly
        # Passthrough mode: Use -c copy if no video adjustments are requested
        is_passthrough = not (filter_complex or target_resolution or bitrate or color_correct)
        
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
            self.run_command(full_args, duration=float(duration))
            return

        if filter_complex:
            full_args.extend(["-filter_complex", filter_complex])

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
        t_start = time.time()
        self.run_command(full_args, duration=float(duration))
        render_duration = time.time() - t_start
        
        total_frames = self.get_video_frame_count(input_path)
        
        return {
            "total_frames": total_frames,
            "render_time": render_duration,
            "render_fps": total_frames / render_duration if render_duration > 0 else 0,
        }
