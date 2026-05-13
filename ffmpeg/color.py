import cv2
import numpy as np
import math
import subprocess as sp
import json
import re
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
from ffmpeg.ffmpeg_class import FfmpegClass
from ffmpeg.hud_filter import generate_hud_filter_complex
from models.dive import Dive, Waypoint

# THRESHOLD_RATIO	2000	1000	Reduces highlight clipping/shining
# MIN_AVG_RED	60	45	Prevents over-saturation of reds/yellows
# BLUE_MAGIC_VALUE	1.2	0.9	Makes the overall tone less "metallic"
# MAX_HUE_SHIFT	120

# Constants (previously from Settings)
SAMPLE_SECONDS = 2
MIN_AVG_RED = 60
# Adjustment: Try lowering MIN_AVG_RED to 40 or 50. This reduces the "force" applied to the red channel,
# which should keep yellows from looking neon or washed out.
MAX_HUE_SHIFT = 60
THRESHOLD_RATIO = 2000
# Adjustment: Try decreasing this value to 1000 or 1200. This will make the normalization less aggressive,
# helping to preserve detail in bright areas like yellow corals or fish.
BLUE_MAGIC_VALUE = 1.2

# Adjustment: Try reducing this to 1.0 or even 0.8. This will tone down the "artificial" feel of the color correction.

class ColorCorrectionEngine:
    """
    Advanced Color Correction using OpenCV for processing and FFmpeg piping for encoding.
    Implementation based on bornfree/dive-color-corrector.
    """
    def __init__(self, ffmpeg_tool: FfmpegClass):
        self.ffmpeg_tool = ffmpeg_tool
        self.mat = None

    def hue_shift_red(self, mat: np.ndarray, h: float) -> np.ndarray:
        U = math.cos(h * math.pi / 180)
        W = math.sin(h * math.pi / 180)
        
        # Matrix weights for hue shifting red channel
        r = (0.299 + 0.701 * U + 0.168 * W) * mat[..., 0]
        g = (0.587 - 0.587 * U + 0.330 * W) * mat[..., 1]
        b = (0.114 - 0.114 * U - 0.497 * W) * mat[..., 2]
        
        return np.dstack([r, g, b])

    def normalizing_interval(self, array: np.ndarray):
        high, low, max_dist = 255, 0, 0
        for i in range(1, len(array)):
            dist = array[i] - array[i - 1]
            if dist > max_dist:
                max_dist = dist
                high, low = array[i], array[i - 1]
        return (low, high)

    def get_filter_matrix(self, frame_rgb: np.ndarray) -> np.ndarray:
        # Resize for faster analysis
        mat = cv2.resize(frame_rgb, (256, 256))
        avg_mat = np.array(cv2.mean(mat)[:3], dtype=np.uint8)

        # Find hue shift
        new_avg_r = avg_mat[0]
        hue_shift = 0
        while new_avg_r < MIN_AVG_RED and hue_shift < MAX_HUE_SHIFT:
            shifted = self.hue_shift_red(avg_mat, hue_shift)
            new_avg_r = np.sum(shifted)
            hue_shift += 1

        # Apply hue shift and replace red channel
        shifted_mat = self.hue_shift_red(mat, hue_shift)
        new_r_channel = np.clip(np.sum(shifted_mat, axis=2), 0, 255)
        mat[..., 0] = new_r_channel

        # Histogram calculation for normalization
        threshold_level = (mat.shape[0] * mat.shape[1]) / THRESHOLD_RATIO
        normalize_mat = np.zeros((256, 3))
        
        for ch in range(3):
            hist = cv2.calcHist([mat], [ch], None, [256], [0, 256])
            for x in range(256):
                if hist[x] < threshold_level:
                    normalize_mat[x][ch] = x
            normalize_mat[255][ch] = 255

        adj_r_low, adj_r_high = self.normalizing_interval(normalize_mat[..., 0])
        adj_g_low, adj_g_high = self.normalizing_interval(normalize_mat[..., 1])
        adj_b_low, adj_b_high = self.normalizing_interval(normalize_mat[..., 2])

        # Calculate gains
        red_gain = 256 / (adj_r_high - adj_r_low) if adj_r_high > adj_r_low else 1.0
        green_gain = 256 / (adj_g_high - adj_g_low) if adj_g_high > adj_g_low else 1.0
        blue_gain = 256 / (adj_b_high - adj_b_low) if adj_b_high > adj_b_low else 1.0

        red_offset = (-adj_r_low / 256) * red_gain
        green_offset = (-adj_g_low / 256) * green_gain
        blue_offset = (-adj_b_low / 256) * blue_gain

        shifted = self.hue_shift_red(np.array([1, 1, 1]), hue_shift)
        shifted_r, shifted_g, shifted_b = shifted[0][0]

        return np.array([
            shifted_r * red_gain, shifted_g * red_gain, shifted_b * red_gain * BLUE_MAGIC_VALUE, 0, red_offset,
            0, green_gain, 0, 0, green_offset,
            0, 0, blue_gain, 0, blue_offset,
            0, 0, 0, 1, 0,
        ])

    def apply_filter(self, mat: np.ndarray, filt: np.ndarray) -> np.ndarray:
        r, g, b = mat[..., 0], mat[..., 1], mat[..., 2]
        
        res_r = r * filt[0] + g * filt[1] + b * filt[2] + filt[4] * 255
        res_g = g * filt[6] + filt[9] * 255
        res_b = b * filt[12] + filt[14] * 255
        
        return np.clip(np.dstack([res_r, res_g, res_b]), 0, 255).astype(np.uint8)

    def process_video(self, input_path: Path, output_path: Path, creation_date: datetime, 
                      dive: Optional[Dive] = None, stabilize: bool = False, 
                      overlay: bool = False, two_pass: bool = False, 
                      layout_path: Optional[Path] = None, hud_path: Optional[Path] = None,
                      start_time: Optional[str] = None, end_time: Optional[str] = None,
                      tz_offset_mins: Optional[int] = None):
        """Analyze video and process frames through OpenCV then pipe to FFmpeg."""
        cap = cv2.VideoCapture(str(input_path))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = int(total_frames / fps) if fps else 0

        # 1. Stabilization Pass 1
        trf_file = output_path.with_suffix(".trf")
        if stabilize and two_pass:
            print("Running stabilization pass 1...")
            self.ffmpeg_tool.run_command([
                "-i", str(input_path),
                "-vf", f"vidstabdetect=stepsize=32:result='{trf_file}'",
                "-f", "null", "-"
            ], quiet=True)

        # 2. Analysis Phase
        print(f"Analyzing {input_path.name}...")
        filter_indices, filter_matrices = [], []
        count = 0
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret: break
            if count % int(fps * SAMPLE_SECONDS) == 0:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                filter_indices.append(count)
                filter_matrices.append(self.get_filter_matrix(rgb))
            if count % int(fps * 2) == 0:
                print(f"Analysis Progress: {100 * count / total_frames:.1f}%", end='\r')
            count += 1
        print(f"Analysis Progress: 100.0%")
        cap.release()
        filter_matrices = np.array(filter_matrices)

        # 3. Telemetry Generation
        ass_path = None
        hud_filter = ""
        layout = {}
        if overlay and layout_path and dive:
            print("Generating telemetry overlay...")
            with open(layout_path, 'r') as f:
                layout = json.load(f)
            
            if "hud_skin" in layout:
                hud_filter = generate_hud_filter_complex(layout, width, height)
            else:
                ass_path = self.ffmpeg_tool._generate_ass_file(dive, creation_date, duration, layout, output_path)

        # 4. Processing & Encoding Phase
        print(f"Processing and encoding with {self.ffmpeg_tool.get_encoder()}...")
        cap = cv2.VideoCapture(str(input_path))
        
        # Build FFmpeg Filter Complex for the pipe
        filters = []
        if stabilize:
            filters.append(f"vidstabtransform=input='{trf_file}'" if two_pass else "deshake")
        if ass_path:
            filters.append(f"subtitles='{ass_path}'")
        
        # Build FFmpeg pipe
        # Input 0: Raw video from stdin
        # Input 1: Source video file (for audio and metadata)
        # Input 2: HUD PNG (if present)
        cmd = [
            str(self.ffmpeg_tool.get_path()), '-y',
            '-f', 'rawvideo', '-vcodec', 'rawvideo',
            '-s', f'{width}x{height}', '-pix_fmt', 'bgr24', '-r', str(fps),
            '-i', '-', # Input 0
            '-i', str(input_path) # Input 1 (for audio and metadata)
        ]

        if not self.ffmpeg_tool.debug:
            cmd.extend(["-nostats", "-loglevel", "error"])

        filter_target = "0:v"

        # Determine HUD path from layout or argument

        actual_hud_path = hud_path
        if "hud_skin" in layout:
            actual_hud_path = Path(layout["hud_skin"]["path"])

        if hud_filter:
            cmd.extend(['-i', str(actual_hud_path)]) # Input 2
            # Use the complex filter generated
            if filters:
                import re
                last_label_match = re.findall(r'\[([^\]]+)\]$', hud_filter.split(';')[-1])
                last_label = f"[{last_label_match[0]}]" if last_label_match else "[v_hud]"
                
                combined_filter = hud_filter + f";{last_label}{','.join(filters)}[v_out]"
                cmd.extend(['-filter_complex', combined_filter])
                filter_target = "[v_out]"
            else:
                cmd.extend(['-filter_complex', hud_filter + "[v_out]"])
                filter_target = "[v_out]"
        elif actual_hud_path and actual_hud_path.exists():
            cmd.extend(['-i', str(actual_hud_path)]) # Input 2
            overlay_filter = "[0:v][2:v]overlay=0:0"
            if filters:
                cmd.extend(['-filter_complex', f"{overlay_filter},{','.join(filters)}[v_out]"])
                filter_target = "[v_out]"
            else:
                cmd.extend(['-filter_complex', f"{overlay_filter}[v_out]"])
                filter_target = "[v_out]"
        elif filters:
            cmd.extend(['-vf', ",".join(filters)])
            filter_target = "0:v"

        # Quality preservation
        cmd.extend(['-map', filter_target, '-map', '1:a?'])
        
        try:
            bitrate = self.ffmpeg_tool.get_video_bitrate(input_path)
            print(f"Preserving source bitrate: {bitrate/1e6:.1f} Mbps")
            cmd.extend(['-b:v', str(bitrate)])
        except:
            pass

        # Metadata preservation
        cmd.extend(["-map_metadata", "1"])
        cmd.extend(["-movflags", "use_metadata_tags"])
        
        # Creation date with timezone
        if tz_offset_mins is not None:
            sign = "+" if tz_offset_mins >= 0 else "-"
            hours = abs(tz_offset_mins) // 60
            mins = abs(tz_offset_mins) % 60
            tz_str = f"{sign}{hours:02}{mins:02}"
            iso_date = creation_date.strftime("%Y-%m-%dT%H:%M:%S") + tz_str
            cmd.extend(["-metadata", f"creation_time={iso_date}"])

        cmd.extend([
            '-vcodec', self.ffmpeg_tool.get_encoder(),
            '-pix_fmt', 'yuv420p',
            '-acodec', 'copy',
            str(output_path)
        ])

        print(cmd)
        process = sp.Popen(cmd, stdin=sp.PIPE)

        # Time range parsing
        s_sec = self.ffmpeg_tool._parse_time(start_time) or 0.0
        e_sec = self.ffmpeg_tool._parse_time(end_time) or float(duration)
        s_frame, e_frame = int(s_sec * fps), int(e_sec * fps)

        import time
        start_time_proc = time.time()
        
        count = 0
        try:
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret: break
                
                # Apply Color Correction if within range
                if s_frame <= count <= e_frame:
                    current_filter = [np.interp(count, filter_indices, filter_matrices[..., x]) for x in range(len(filter_matrices[0]))]
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    corrected_rgb = self.apply_filter(rgb, np.array(current_filter))
                    frame = cv2.cvtColor(corrected_rgb, cv2.COLOR_RGB2BGR)
                
                process.stdin.write(frame.tobytes())
                if count % int(fps * 2) == 0:
                    pct = min(100.0, 100 * count / total_frames)
                    elapsed = time.time() - start_time_proc
                    if count > 0:
                        total_est = (elapsed / count) * total_frames
                        remaining = max(0, total_est - elapsed)
                        mins, secs = divmod(int(remaining), 60)
                        print(f"Progress: {pct:5.1f}% | Remaining: {mins:02d}:{secs:02d}", end='\r')
                count += 1
            print(f"Progress: 100.0% | Remaining: 00:00")
        finally:
            cap.release()
            process.stdin.close()
            process.wait()
            if ass_path and ass_path.exists(): ass_path.unlink()
            if trf_file and trf_file.exists(): trf_file.unlink()
        
        print(f"\nProcessing complete: {output_path.name}")
