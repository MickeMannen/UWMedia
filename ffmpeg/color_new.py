import cv2
import numpy as np
import math
import subprocess as sp
import json
import re
import time
import sys
import yaml
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from tqdm import tqdm
from ffmpeg.ffmpeg_class import FfmpegClass
from models.dive import Dive, Waypoint

# Constants for analysis
SAMPLE_SECONDS = 2

class ColorCorrectionEngine:
    """
    Simplified Underwater Color Correction Engine.
    Executes the following 4-step pipeline:
    1. Red Channel Compensation (physics-based recovery)
    2. Histogram Stretching (per-channel white balance)
    3. CLAHE Processing (localized dehaze and contrast enhancement)
    4. HSV Shifting (selective target color tuning)
    """
    def __init__(self, ffmpeg_tool: FfmpegClass, color_profile: Optional[str] = "default"):
        self.ffmpeg_tool = ffmpeg_tool
        self.color_profile = color_profile or "default"
        
        # Load parameters from color.yaml
        color_name = "color.yaml"
        cwd_path = Path.cwd() / color_name
        if getattr(sys, 'frozen', False):
            app_path = Path(sys.executable).parent / color_name
        else:
            app_path = Path(__file__).parent.parent / color_name

        yaml_path = None
        if cwd_path.exists():
            yaml_path = cwd_path
        elif app_path.exists():
            yaml_path = app_path

        if not yaml_path:
            raise FileNotFoundError(f"Could not find {color_name} in current directory or app directory.")

        with open(yaml_path, 'r') as f:
            data = yaml.safe_load(f) or {}

        if self.color_profile not in data:
            if "default" in data:
                print(f"Warning: Profile '{self.color_profile}' not found in {color_name}. Falling back to 'default'.")
                self.color_profile = "default"
            else:
                raise ValueError(f"Profile '{self.color_profile}' not found and no 'default' profile exists in {color_name}.")

        profile = data[self.color_profile]
        
        # Target color tuning configurations (constant HSV profiles)
        # Bins: 12 bins of 30 degrees each (Hue range 0-360 mapped to OpenCV Hue range 0-180)
        # Tuned to make background more water-blue (slight cyan-blue shift) and desaturated,
        # while keeping deep blue fins rich, blue (no purple shift), and saturated.
        self.bin_shifts = np.array(profile["bin_shifts"]) / 2.0
        self.bin_sats = np.array(profile["bin_sats"])
        self.bin_vals = np.array(profile["bin_vals"])
        self.clahe_blend = float(profile.get("clahe_blend", 0.3))
        self.clahe_clip_limit = float(profile.get("clahe_clip_limit", 1.0))
        grid_size = profile.get("clahe_grid_size", [8, 8])
        self.clahe_grid_size = (int(grid_size[0]), int(grid_size[1]))

        # Denoising
        self.denoise_type = profile.get("denoise_type", "bilateral")
        self.denoise_d = int(profile.get("denoise_d", 5))
        self.denoise_sigma_color = float(profile.get("denoise_sigma_color", 15.0))
        self.denoise_sigma_space = float(profile.get("denoise_sigma_space", 15.0))

        # Red Boost
        self.red_boost_alpha = float(profile.get("red_boost_alpha", 1.5))

        # Gray World WB gains
        self.wb_red_gain = float(profile.get("wb_red_gain", 0.15))
        self.wb_green_gain = float(profile.get("wb_green_gain", 0.9))
        self.wb_blue_gain = float(profile.get("wb_blue_gain", 0.9))

        # Global Saturation
        self.global_saturation_factor = float(profile.get("global_saturation_factor", 1.0))

        # Sharpening
        self.sharpen_type = profile.get("sharpen_type", "kernel")
        self.sharpen_amount = float(profile.get("sharpen_amount", 0.25))
        self.sharpen_radius = float(profile.get("sharpen_radius", 1.0))

    def get_filter_matrix(self, frame_rgb: np.ndarray) -> np.ndarray:
        """
        Analyzes keyframe to calculate dynamic scene parameters (means & stretch limits).
        """
        # Resize for faster analysis
        small = cv2.resize(frame_rgb, (256, 256))
        
        # Step 1: Denoise
        if self.denoise_type == "bilateral":
            small_denoised = cv2.bilateralFilter(small, self.denoise_d, self.denoise_sigma_color, self.denoise_sigma_space)
        elif self.denoise_type == "gaussian":
            small_denoised = cv2.GaussianBlur(small, (5, 5), 0)
        else:
            small_denoised = small
            
        r = small_denoised[..., 0].astype(np.float32)
        g = small_denoised[..., 1].astype(np.float32)
        b = small_denoised[..., 2].astype(np.float32)
        
        # Calculate channel means BEFORE Red Channel Boost
        pre_mean_r = np.mean(r)
        pre_mean_g = np.mean(g)
        pre_mean_b = np.mean(b)
        
        # Step 2: Red Channel Boost
        blue_factor = np.minimum(g / np.maximum(b, 1.0), 1.0)
        g_factor = 0.4 + 0.6 * (g / 255.0)
        r_boosted = r + self.red_boost_alpha * (pre_mean_g - pre_mean_r) * ((1.0 - r / 255.0) ** 2) * g_factor * blue_factor
        r_boosted = np.clip(r_boosted, 0, 255)
        
        # Calculate channel means AFTER Red Channel Boost (for Gray World WB)
        post_mean_r = np.mean(r_boosted)
        post_mean_g = np.mean(g)
        post_mean_b = np.mean(b)
        
        return np.array([
            pre_mean_r, pre_mean_g, pre_mean_b,
            post_mean_r, post_mean_g, post_mean_b
        ], dtype=np.float32)

    def apply_filter(self, mat: np.ndarray, filt: np.ndarray) -> np.ndarray:
        """
        Applies the 7-step color correction workflow:
        Input → Denoise → Red Channel Boost → Gray World WB → CLAHE → Saturation → Sharpen → Output
        """
        # Unpack interpolated keyframe parameters
        pre_mean_r, pre_mean_g, pre_mean_b = filt[0], filt[1], filt[2]
        post_mean_r, post_mean_g, post_mean_b = filt[3], filt[4], filt[5]
        
        # 1. Denoise
        if self.denoise_type == "bilateral":
            denoised = cv2.bilateralFilter(mat, self.denoise_d, self.denoise_sigma_color, self.denoise_sigma_space)
        elif self.denoise_type == "gaussian":
            denoised = cv2.GaussianBlur(mat, (5, 5), 0)
        else:
            denoised = mat
            
        # 2. Red Channel Boost
        denoised_f = denoised.astype(np.float32)
        r = denoised_f[..., 0]
        g = denoised_f[..., 1]
        b = denoised_f[..., 2]
        
        blue_factor = np.minimum(g / np.maximum(b, 1.0), 1.0)
        g_factor = 0.4 + 0.6 * (g / 255.0)
        r_boosted = r + self.red_boost_alpha * (pre_mean_g - pre_mean_r) * ((1.0 - r / 255.0) ** 2) * g_factor * blue_factor
        r_boosted = np.clip(r_boosted, 0, 255)
        
        # 3. Gray World WB (referenced to Green/Blue average to preserve exposure)
        mean_gb = (post_mean_g + post_mean_b) / 2.0
        
        # Calculate raw scaling factors
        scale_r = mean_gb / post_mean_r if post_mean_r > 0 else 1.0
        scale_g = mean_gb / post_mean_g if post_mean_g > 0 else 1.0
        scale_b = mean_gb / post_mean_b if post_mean_b > 0 else 1.0
        
        # Blend with 1.0 based on channel gain factors from YAML to control over-boosting (especially red)
        scale_r = 1.0 + (scale_r - 1.0) * self.wb_red_gain
        scale_g = 1.0 + (scale_g - 1.0) * self.wb_green_gain
        scale_b = 1.0 + (scale_b - 1.0) * self.wb_blue_gain
        
        r_wb = np.clip(r_boosted * scale_r, 0, 255)
        g_wb = np.clip(g * scale_g, 0, 255)
        b_wb = np.clip(b * scale_b, 0, 255)
        
        wb_img = np.dstack([r_wb, g_wb, b_wb]).astype(np.uint8)
        
        # 4. CLAHE
        lab = cv2.cvtColor(wb_img, cv2.COLOR_RGB2Lab)
        l, a, lab_b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=self.clahe_clip_limit, tileGridSize=self.clahe_grid_size)
        l_enhanced = clahe.apply(l)
        l_final = cv2.addWeighted(l_enhanced, self.clahe_blend, l, 1.0 - self.clahe_blend, 0)
        lab_enhanced = cv2.merge([l_final, a, lab_b])
        clahe_img = cv2.cvtColor(lab_enhanced, cv2.COLOR_Lab2RGB)
        
        # 5. Saturation (Selective HSV Shifting + Global Saturation)
        hsv = cv2.cvtColor(clahe_img, cv2.COLOR_RGB2HSV)
        h, s, v = cv2.split(hsv)
        
        bin_centers = np.arange(12) * 15.0 + 7.5
        x_points = np.concatenate([[-7.5], bin_centers, [187.5]])
        y_shifts = np.concatenate([[self.bin_shifts[-1]], self.bin_shifts, [self.bin_shifts[0]]])
        y_sats = np.concatenate([[self.bin_sats[-1]], self.bin_sats, [self.bin_sats[0]]])
        y_vals = np.concatenate([[self.bin_vals[-1]], self.bin_vals, [self.bin_vals[0]]])
        
        interpolated_shifts = np.interp(h, x_points, y_shifts)
        interpolated_sats = np.interp(h, x_points, y_sats)
        interpolated_vals = np.interp(h, x_points, y_vals)
        
        h_new = np.mod(h.astype(np.float32) + interpolated_shifts, 180.0).astype(np.uint8)
        s_new = np.clip(s.astype(np.float32) * interpolated_sats * self.global_saturation_factor, 0, 255).astype(np.uint8)
        v_new = np.clip(v.astype(np.float32) * interpolated_vals, 0, 255).astype(np.uint8)
        
        hsv_new = cv2.merge([h_new, s_new, v_new])
        sat_img = cv2.cvtColor(hsv_new, cv2.COLOR_HSV2RGB)
        
        # 6. Sharpen
        if self.sharpen_type == "kernel":
            amt = self.sharpen_amount
            kernel = np.array([[0, -amt, 0],
                               [-amt, 1 + 4*amt, -amt],
                               [0, -amt, 0]])
            sharpened = cv2.filter2D(sat_img, -1, kernel)
            final_img = np.clip(sharpened, 0, 255).astype(np.uint8)
        elif self.sharpen_type == "unsharp":
            rad = self.sharpen_radius
            amt = self.sharpen_amount
            ksize = int(2 * round(3 * rad) + 1)
            blurred = cv2.GaussianBlur(sat_img, (ksize, ksize), rad)
            sharpened = cv2.addWeighted(sat_img, 1.0 + amt, blurred, -amt, 0)
            final_img = np.clip(sharpened, 0, 255).astype(np.uint8)
        else:
            final_img = sat_img
            
        return final_img

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
            # Identity/noop parameters fallback
            filter_indices = [0]
            filter_matrices = np.array([[128, 128, 128, 128, 128, 128]])

        # HUD and overlay initialization
        ass_path = None
        hud_filter = ""
        layout = {}
        actual_hud_path = None
        use_opencv_text = True 
        preloaded_skin = None

        if layout_path and dive:
            print(f"Generating telemetry overlay using layout: {layout_path.name}")
            with open(layout_path, 'r') as f:
                layout = json.load(f)
            
            if "hud_skin" in layout:
                skin_rel_path = layout["hud_skin"].get("path")
                if skin_rel_path:
                    actual_hud_path = layout_path.parent / skin_rel_path
            
            if "hud_skin" in layout and actual_hud_path and actual_hud_path.exists():
                print(f"HUD Skin found at: {actual_hud_path}")
                hud_filter = "" 
            else:
                if self.ffmpeg_tool.has_filter("subtitles"):
                    ass_path = self.ffmpeg_tool._generate_ass_file(dive, creation_date, duration, layout, output_path)
                else:
                    use_opencv_text = True

        # Pre-process skin overlay
        if layout:
            hud_skin = layout.get("hud_skin", {})
            skin_path = hud_skin.get("path")
            if skin_path:
                img_skin = cv2.imread(skin_path, cv2.IMREAD_UNCHANGED)
                if img_skin is not None:
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

        # Re-open video capture for processing phase
        cap = cv2.VideoCapture(str(input_path))

        # Build FFmpeg pipe
        filters = []
        if stabilize:
            if stabilize == "low":
                filters.append("deshake=blocksize=8:rx=16:ry=16:edge=mirror")
            elif stabilize == "mid":
                filters.append("deshake=blocksize=16:rx=32:ry=32:edge=mirror")
            else:
                filters.append("deshake=blocksize=32:rx=64:ry=64:edge=mirror")
        if ass_path:
            filters.append(f"subtitles='{ass_path}'")
        
        cmd = [
            str(self.ffmpeg_tool.get_path()), '-y',
            '-f', 'rawvideo', '-vcodec', 'rawvideo',
            '-s', f'{width}x{height}', '-pix_fmt', 'bgr24', '-r', str(fps),
            '-i', '-', 
            '-i', str(input_path)
        ]

        if not self.ffmpeg_tool.debug:
            cmd.extend(["-nostats", "-loglevel", "error"])

        filter_target = "0:v"
        if hud_filter:
            cmd.extend(['-i', str(actual_hud_path)])
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

        cmd.extend(['-map', filter_target, '-map', '1:a?'])
        
        try:
            bitrate = self.ffmpeg_tool.get_video_bitrate(input_path)
            cmd.extend(['-b:v', str(bitrate)])
        except:
            pass

        cmd.extend(["-map_metadata", "1"])
        cmd.extend(["-movflags", "+faststart+use_metadata_tags"])
        cmd.extend(["-tag:v", "hvc1"])
        cmd.extend([
            "-color_primaries", "1",
            "-color_trc", "1",
            "-colorspace", "1"
        ])
        
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

        process = sp.Popen(cmd, stdin=sp.PIPE)

        s_sec = self.ffmpeg_tool._parse_time(start_time) or 0.0
        e_sec = self.ffmpeg_tool._parse_time(end_time) or float(duration)
        s_frame, e_frame = int(s_sec * fps), int(e_sec * fps)
        total_to_process = e_frame - s_frame + 1

        count = 0
        try:
            if s_frame > 0:
                cap.set(cv2.CAP_PROP_POS_FRAMES, s_frame)
                count = s_frame

            with tqdm(total=total_to_process, desc="Processing", unit="frame") as pbar:
                while cap.isOpened() and count <= e_frame:
                    ret, frame = cap.read()
                    if not ret: break
                    
                    if color_correct:
                        current_filter = [np.interp(count, filter_indices, filter_matrices[..., x]) for x in range(len(filter_matrices[0]))]
                        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        corrected_rgb = self.apply_filter(rgb, np.array(current_filter))
                        frame = cv2.cvtColor(corrected_rgb, cv2.COLOR_RGB2BGR)

                    if layout and dive:
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
