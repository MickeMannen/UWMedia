import cv2
import numpy as np
import math
import subprocess as sp
import json
import re
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from tqdm import tqdm
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
                      dive: Optional[Dive] = None, stabilize: Optional[str] = None, 
                      overlay: bool = False, 
                      layout_path: Optional[Path] = None,
                      start_time: Optional[str] = None, end_time: Optional[str] = None,
                      tz_offset_mins: Optional[int] = None,
                      color_correct: bool = True):
        """Analyze video and process frames through OpenCV then pipe to FFmpeg."""
        cap = cv2.VideoCapture(str(input_path))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = int(total_frames / fps) if fps else 0

        # 1. Stabilization (Deshake)
        if stabilize:
            print(f"Stabilization enabled (level: {stabilize})...")

        # 2. Analysis Phase
        filter_indices, filter_matrices = [], []
        if color_correct:
            print(f"Analyzing {input_path.name}...")
            count = 0
            with tqdm(total=total_frames, desc="Analysis", unit="frame") as pbar:
                while cap.isOpened():
                    ret, frame = cap.read()
                    if not ret: break
                    if count % int(fps * SAMPLE_SECONDS) == 0:
                        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        filter_indices.append(count)
                        filter_matrices.append(self.get_filter_matrix(rgb))
                    pbar.update(1)
                    count += 1
            cap.release()
            filter_matrices = np.array(filter_matrices)
        else:
            cap.release()
            # Identity matrix fallback
            filter_indices = [0]
            filter_matrices = np.array([[1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0]])

        # 3. Telemetry Generation
        ass_path = None
        hud_filter = ""
        layout = {}
        actual_hud_path = None
        # Always use OpenCV text rendering when in the pipe for reliability
        use_opencv_text = True 
        img_skin_alpha = None # For OpenCV skin overlay

        if layout_path and dive:
            print(f"Generating telemetry overlay using layout: {layout_path.name}")
            with open(layout_path, 'r') as f:
                layout = json.load(f)
            
            # print(f"DEBUG: Layout Content: {json.dumps(layout, indent=2)}")
            
            # Resolve actual_hud_path correctly relative to layout_path
            if "hud_skin" in layout:
                skin_rel_path = layout["hud_skin"].get("path")
                if skin_rel_path:
                    actual_hud_path = layout_path.parent / skin_rel_path
            
            if "hud_skin" in layout and actual_hud_path and actual_hud_path.exists():
                print(f"HUD Skin found at: {actual_hud_path}")
                # We handle the HUD entirely in OpenCV now to ensure correct layering
                img_skin_alpha = cv2.imread(str(actual_hud_path), cv2.IMREAD_UNCHANGED)
                if img_skin_alpha is None:
                    print(f"ERROR: Could not load HUD skin image at {actual_hud_path}")
                hud_filter = "" # Disable FFmpeg HUD overlay
            elif "hud_skin" in layout:
                print(f"Warning: HUD skin not found at {actual_hud_path}")
            else:
                if self.ffmpeg_tool.has_filter("subtitles"):
                    ass_path = self.ffmpeg_tool._generate_ass_file(dive, creation_date, duration, layout, output_path)
                else:
                    use_opencv_text = True

        # 4. Processing & Encoding Phase
        print(f"Processing and encoding with {self.ffmpeg_tool.get_encoder()}...")
        cap = cv2.VideoCapture(str(input_path))
        
        # Build FFmpeg Filter Complex for the pipe
        filters = []
        if stabilize:
            if stabilize == "low":
                filters.append("deshake=blocksize=8:rx=16:ry=16:edge=mirror")
            elif stabilize == "mid":
                filters.append("deshake=blocksize=16:rx=32:ry=32:edge=mirror")
            else:  # high
                filters.append("deshake=blocksize=32:rx=64:ry=64:edge=mirror")
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

        if hud_filter:
            cmd.extend(['-i', str(actual_hud_path)]) # Input 2
            
            last_label_match = re.findall(r'\[([^\]]+)\]$', hud_filter.split(';')[-1])
            last_label = f"[{last_label_match[0]}]" if last_label_match else "[v_hud]"

            if filters:
                combined_filter = hud_filter + f";{last_label}{','.join(filters)}[v_out]"
                cmd.extend(['-filter_complex', combined_filter])
                filter_target = "[v_out]"
            else:
                cmd.extend(['-filter_complex', hud_filter])
                filter_target = last_label
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
        cmd.extend(["-movflags", "+faststart+use_metadata_tags"])
        
        # Compatibility and Color Metadata
        cmd.extend(["-tag:v", "hvc1"])
        cmd.extend([
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
            cmd.extend(["-metadata", f"creation_time={iso_date}"])

        cmd.extend([
            '-vcodec', self.ffmpeg_tool.get_encoder(),
            '-pix_fmt', 'yuv420p',
            '-acodec', 'copy',
            str(output_path)
        ])

        # Prepare for OpenCV text rendering if needed
        hud_skin = layout.get("hud_skin", {})
        linked_elements = hud_skin.get("linked_elements", []) if use_opencv_text else []
        skin_scale = hud_skin.get("scale", 1.0)
        skin_opacity = hud_skin.get("opacity", 1.0)
        
        raw_x_pct = hud_skin.get("x_pct", 0.0)
        raw_y_pct = hud_skin.get("y_pct", 0.0)
        skin_x = int(raw_x_pct * width)
        skin_y = int(raw_y_pct * height)

        if self.ffmpeg_tool.debug:
            print(f"DEBUG: Layout Positioning:")
            print(f"  Video Res: {width}x{height}")
            print(f"  Skin Target Pct: ({raw_x_pct:.3f}, {raw_y_pct:.3f})")
            print(f"  Skin Target Pixel: ({skin_x}, {skin_y})")
            print(f"  Skin Scale: {skin_scale:.2f} | Opacity: {skin_opacity:.2f}")

        # Pre-process skin for OpenCV overlay
        preloaded_skin = None
        if layout:
            hud_skin = layout.get("hud_skin", {})
            skin_path = hud_skin.get("path")
            if skin_path:
                img_skin = cv2.imread(skin_path, cv2.IMREAD_UNCHANGED)
                if img_skin is not None:
                    # Use design_width from layout or default to 1920
                    design_w = float(layout.get("design_width", 1920))
                    user_scale = hud_skin.get("scale", 1.0)
                    res_scale = width / design_w
                    final_skin_scale = user_scale * res_scale
                    
                    skin_opacity = hud_skin.get("opacity", 1.0)
                    h_orig, w_orig = img_skin.shape[:2]
                    w_scaled = int(w_orig * final_skin_scale)
                    h_scaled = int(h_orig * final_skin_scale)
                    
                    if w_scaled < 1: w_scaled = 1
                    if h_scaled < 1: h_scaled = 1
                    
                    preloaded_skin = cv2.resize(img_skin, (w_scaled, h_scaled), interpolation=cv2.INTER_AREA)
                    if preloaded_skin.shape[2] == 4:
                        preloaded_skin[:, :, 3] = (preloaded_skin[:, :, 3] * skin_opacity).astype(np.uint8)
                    print(f"HUD Skin Pre-loaded: {w_scaled}x{h_scaled} (res_scale: {res_scale:.2f} based on design_w: {design_w})")
                else:
                    print(f"Warning: Could not pre-load HUD skin from {skin_path}")

        print(cmd)
        process = sp.Popen(cmd, stdin=sp.PIPE)

        # Time range parsing
        s_sec = self.ffmpeg_tool._parse_time(start_time) or 0.0
        e_sec = self.ffmpeg_tool._parse_time(end_time) or float(duration)
        s_frame, e_frame = int(s_sec * fps), int(e_sec * fps)
        total_to_process = e_frame - s_frame + 1

        import time
        start_time_proc = time.time()
        
        count = 0
        try:
            # Seek to start frame
            if s_frame > 0:
                cap.set(cv2.CAP_PROP_POS_FRAMES, s_frame)
                count = s_frame

            with tqdm(total=total_to_process, desc="Processing", unit="frame") as pbar:
                while cap.isOpened() and count <= e_frame:
                    ret, frame = cap.read()
                    if not ret: break
                    
                    # Apply OpenCV Color Correction and HUD
                    if color_correct:
                        current_filter = [np.interp(count, filter_indices, filter_matrices[..., x]) for x in range(len(filter_matrices[0]))]
                        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        corrected_rgb = self.apply_filter(rgb, np.array(current_filter))
                        frame = cv2.cvtColor(corrected_rgb, cv2.COLOR_RGB2BGR)

                    if layout and dive:
                        # Find closest waypoint
                        elapsed_total = count / fps
                        current_time = creation_date + timedelta(seconds=elapsed_total)
                        wp = dive.get_waypoint_at(current_time)
                        
                        if wp:
                            from gui.hud_renderer import draw_hud
                            draw_hud(frame, layout, wp, preloaded_skin=preloaded_skin)


                    process.stdin.write(frame.tobytes())
                    pbar.update(1)
                    count += 1
        finally:
            cap.release()
            process.stdin.close()
            process.wait()
            if ass_path and ass_path.exists(): ass_path.unlink()
        
        print(f"\nProcessing complete: {output_path.name}")
