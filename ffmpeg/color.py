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
    Underwater Color Correction Engine.
    Exposes parameters for:
    1. Color factors (red/blue channel restoration thresholds)
    2. Black point floor histogram cutoff
    3. Gray World White Balance (adaptive blurring and isolation thresholds)
    4. Dehaze adjustment curves (saturation bins)
    5. Exposure compensation
    6. Perceptual Hue Translation in Oklch space
    """
    def __init__(self, ffmpeg_tool: Optional[FfmpegClass], color_profile: Optional[str] = "default"):
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
        
        # Expose parameters with fallbacks
        self.cifval = float(profile.get("cifval", 1.0))
        self.red_threshold = float(profile.get("red_threshold", 0.3))
        self.red_scale = float(profile.get("red_scale", 0.2))
        self.blue_threshold = float(profile.get("blue_threshold", 0.3))
        self.blue_scale = float(profile.get("blue_scale", 0.6))
        self.black_point_cutoff = float(profile.get("black_point_cutoff", 0.001))
        self.gw_mask_mult = float(profile.get("gw_mask_mult", 1.5))
        self.gw_mask_fallback = float(profile.get("gw_mask_fallback", 0.2))
        self.gw_blur_radius = int(profile.get("gw_blur_radius", 9))
        self.gw_blur_sigma = float(profile.get("gw_blur_sigma", 1.8))
        self.gw_isolation_threshold = float(profile.get("gw_isolation_threshold", 0.07))
        self.gw_isolation_min_sum = float(profile.get("gw_isolation_min_sum", 100.0))
        self.dehaze_sat_cutoff = float(profile.get("dehaze_sat_cutoff", 0.1))
        self.dehaze_sat_scale = float(profile.get("dehaze_sat_scale", 0.75))
        self.dehaze_min = float(profile.get("dehaze_min", 0.81))
        self.dehaze_max = float(profile.get("dehaze_max", 1.0))
        self.exposure_cdf_cutoff = float(profile.get("exposure_cdf_cutoff", 0.01))
        self.exposure_numerator = float(profile.get("exposure_numerator", 0.5))
        self.exposure_min = float(profile.get("exposure_min", 1.0))
        self.exposure_max = float(profile.get("exposure_max", 2.0))
        self.bh_min_idx = int(profile.get("bh_min_idx", 155))
        self.bh_max_idx = int(profile.get("bh_max_idx", 218))
        self.bh_decay = float(profile.get("bh_decay", 0.85))
        self.bh_fallback = float(profile.get("bh_fallback", 0.67))

        # Enable OpenCL (GPU Transparent API) if available
        if cv2.ocl.haveOpenCL():
            cv2.ocl.setUseOpenCL(True)

        # Precompute sRGB -> Linear lookup table (for 8-bit uint8 inputs)
        self.lut_linear = np.array([
            ((i / 255.0) / 12.92) if (i / 255.0) <= 0.04045
            else (((i / 255.0) + 0.055) / 1.055) ** 2.4
            for i in range(256)
        ], dtype=np.float32)

        # Precompute Linear -> sRGB lookup table (12-bit lookup for float inputs)
        self.lut_srgb = np.array([
            ((i / 4095.0) * 12.92) if (i / 4095.0) <= 0.0031308
            else (((i / 4095.0) ** 0.41666666667) * 1.055) - 0.055
            for i in range(4096)
        ], dtype=np.float32)

    # =========================================================================
    # 1. CORE ANALYTICAL PIPELINE (Exposes configuration hooks)
    # =========================================================================

    def calculate_color_factors(self, img_linear):
        """Analyzes green vs red/blue channel depletion to isolate scaling weights."""
        mean_r = np.mean(img_linear[..., 0])
        mean_g = np.mean(img_linear[..., 1])
        mean_b = np.mean(img_linear[..., 2])

        cf_red = 0.0
        if mean_g > mean_r and mean_g > 0:
            cf_red = max(0.0, min(1.0, (((mean_g - mean_r) / mean_g) - self.red_threshold) / self.red_scale))

        cf_blue = 0.0
        if mean_g > mean_b and mean_g > 0:
            cf_blue = max(0.0, min(1.0, (((mean_g - mean_b) / mean_g) - self.blue_threshold) / self.blue_scale))

        return cf_red, cf_blue

    def calculate_black_point(self, img_linear, cfval):
        """Finds the true black floor based on a histogram cut-off."""
        val = img_linear.copy()
        val[..., 0] = val[..., 0] + cfval[0] * (1.0 - val[..., 0]) * val[..., 1]
        val[..., 2] = val[..., 2] + cfval[1] * (1.0 - val[..., 2]) * val[..., 1]
        val = np.clip(val, 0.0, 1.0)

        # Convert to 8-bit quantized bins to build histogram
        val_8bit = (val * 255.0).astype(np.int32)

        bp = [0.0, 0.0, 0.0]
        total_pixels = val.shape[0] * val.shape[1]

        for ch in range(3):
            hist, _ = np.histogram(val_8bit[..., ch], bins=256, range=(0, 256))
            cdf = np.cumsum(hist) / total_pixels
            idx = np.where(cdf > self.black_point_cutoff)[0]
            if len(idx) > 0:
                bp[ch] = max((idx[0] - 1) / 255.0, 0.0)

        return tuple(bp)

    def calculate_grey_world_factors(self, img_linear, cfval, bpval):
        """Applies Gaussian blurring and calculates foreground-weighted coefficients."""
        val = img_linear.copy()
        val[..., 0] = val[..., 0] + cfval[0] * (1.0 - val[..., 0]) * val[..., 1]
        val[..., 2] = val[..., 2] + cfval[1] * (1.0 - val[..., 2]) * val[..., 1]
        val = np.clip(val - np.array(bpval), 0.0, 1.0)

        # Ensure odd kernel size for GaussianBlur
        ksize = self.gw_blur_radius
        if ksize % 2 == 0:
            ksize += 1
        blur = cv2.GaussianBlur(val, (ksize, ksize), self.gw_blur_sigma)

        r, g, b = val[..., 0], val[..., 1], val[..., 2]
        blur_g, blur_b = blur[..., 1], blur[..., 2]

        f12 = np.where(b < g * self.gw_mask_mult, 1.0, self.gw_mask_fallback)

        f13 = r * f12
        f14 = f13
        f15 = f12 * g
        f16 = f12 * b
        f17 = f12

        condition = (np.abs(g - blur_g) + np.abs(b - blur_b)) > self.gw_isolation_threshold

        f6 = np.sum(np.where(condition, f13, 0.0))
        f7 = np.sum(np.where(condition, f15, 0.0))
        f8 = np.sum(np.where(condition, f16, 0.0))
        f_sum = np.sum(np.where(condition, f17, 0.0))

        if f_sum > self.gw_isolation_min_sum:
            f18 = f6 / f_sum
            f19 = f7 / f_sum
            f20 = f8 / f_sum
            f_min = min(f18, f19, f20)
            return (f_min / f18, f_min / f19, f_min / f20)

        f21 = np.sum(f14) / np.sum(f17)
        f22 = np.sum(f15) / np.sum(f17)
        f23 = np.sum(f16) / np.sum(f17)
        f_min2 = min(f21, f22, f23)
        return (f_min2 / f21, f_min2 / f22, f_min2 / f23)

    def calculate_dehaze_factor(self, img_linear, cfval, bpval, gwfval):
        """Calculates dehaze metric using saturation threshold profiles."""
        val = img_linear.copy()
        val[..., 0] = val[..., 0] + cfval[0] * (1.0 - val[..., 0]) * val[..., 1]
        val[..., 2] = val[..., 2] + cfval[1] * (1.0 - val[..., 2]) * val[..., 1]
        val = np.clip((val - np.array(bpval)) * np.array(gwfval), 0.0, 1.0)

        r = (val[..., 0] * 255.0).astype(np.int32)
        g = (val[..., 1] * 255.0).astype(np.int32)
        b = (val[..., 2] * 255.0).astype(np.int32)

        i_max = np.maximum(np.maximum(r, g), b)
        i_min = np.minimum(np.minimum(r, g), b)

        sat_bin = np.zeros_like(i_max)
        nonzero_mask = i_max != 0
        sat_bin[nonzero_mask] = np.round(((i_max[nonzero_mask] - i_min[nonzero_mask]) / i_max[nonzero_mask]) * 255.0)

        hist, _ = np.histogram(sat_bin, bins=256, range=(0, 256))
        total_pixels = val.shape[0] * val.shape[1]

        f2 = 0.0
        f = 0.0
        for i in range(255, 1, -1):
            f2 += hist[i] / total_pixels
            if f2 > self.dehaze_sat_cutoff:
                f = i / 255.0
                break

        return max(self.dehaze_min, min(self.dehaze_max, f / self.dehaze_sat_scale))

    def calculate_exposure_factor(self, img_linear, cfval, bpval, gwfval, dhfval):
        """Calculates exposure compensation factor based on brightness distribution."""
        val = img_linear.copy()
        val[..., 0] = val[..., 0] + cfval[0] * (1.0 - val[..., 0]) * val[..., 1]
        val[..., 2] = val[..., 2] + cfval[1] * (1.0 - val[..., 2]) * val[..., 1]
        val = np.clip((val - np.array(bpval)) * np.array(gwfval), 0.0, 1.0)

        max_val = np.max(val, axis=-1)
        new_dhf = max_val / dhfval + 1.0 - max_val
        val = np.clip(1.0 * (new_dhf[..., np.newaxis] * (val - 1.0) + 1.0), 0.0, 1.0)

        r = (val[..., 0] * 255.0).astype(np.int32)
        g = (val[..., 1] * 255.0).astype(np.int32)
        b = (val[..., 2] * 255.0).astype(np.int32)

        lum_bin = np.round((np.maximum(np.maximum(r, g), b) + np.minimum(np.minimum(r, g), b)) / 2.0).astype(np.int32)

        hist, _ = np.histogram(lum_bin, bins=256, range=(0, 256))
        total_pixels = val.shape[0] * val.shape[1]

        f2 = 0.0
        f = 0.5
        for i in range(255, 1, -1):
            f2 += hist[i] / total_pixels
            if f2 > self.exposure_cdf_cutoff:
                f = i / 255.0
                break

        return min(self.exposure_max, max(self.exposure_min, self.exposure_numerator / f))

    def calculate_blue_hue(self, img_linear, cfval, bpval, gwfval, dhfval, expfval):
        """Determines the water-column background profile index."""
        val = img_linear.copy()
        val[..., 0] = val[..., 0] + cfval[0] * (1.0 - val[..., 0]) * val[..., 1]
        val[..., 2] = val[..., 2] + cfval[1] * (1.0 - val[..., 2]) * val[..., 1]
        val = np.clip((val - np.array(bpval)) * np.array(gwfval), 0.0, 1.0)

        max_val = np.max(val, axis=-1)
        new_dhf = max_val / dhfval + 1.0 - max_val
        val = np.clip(expfval * (new_dhf[..., np.newaxis] * (val - 1.0) + 1.0), 0.0, 1.0)

        l = 0.4122214708 * val[..., 0] + 0.5363325363 * val[..., 1] + 0.0514459929 * val[..., 2]
        m = 0.2119034982 * val[..., 0] + 0.6806995451 * val[..., 1] + 0.1073969566 * val[..., 2]
        s = 0.0883024619 * val[..., 0] + 0.2817188376 * val[..., 1] + 0.6299787005 * val[..., 2]

        l = np.cbrt(l)
        m = np.cbrt(m)
        s = np.cbrt(s)

        a = 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s
        b = 0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s

        h = np.arctan2(b, a) / (2.0 * np.pi)
        h[h < 0.0] += 1.0
        h = np.clip(h, 0.0, 1.0)

        h_8bit = (h * 255.0).astype(np.int32)
        hist, _ = np.histogram(h_8bit, bins=256, range=(0, 256))
        total_pixels = val.shape[0] * val.shape[1]

        f_arr = hist / total_pixels

        f = 0.0
        target_idx = 0
        min_idx = min(self.bh_min_idx, 254)
        max_idx = min(self.bh_max_idx, 255)
        if min_idx >= max_idx:
            min_idx = max_idx - 1
            
        for i5 in range(min_idx, max_idx):
            f2 = f_arr[i5] + (f_arr[i5 - 1] * self.bh_decay) + (f_arr[i5 + 1] * self.bh_decay)
            if f2 > f:
                target_idx = i5
                f = f2

        if f > 0.04:
            return target_idx / 255.0
        return self.bh_fallback

    def extract_all_parameters(self, img_srgb):
        """Downsamples and generates all 11 floats from the target image."""
        h, w, _ = img_srgb.shape
        scale = 1
        while w / scale > 200 and h / scale > 200:
            scale *= 2

        img_small = cv2.resize(img_srgb, (w // scale, h // scale), interpolation=cv2.INTER_AREA)
        img_linear = self.lut_linear[img_small]

        cfval = self.calculate_color_factors(img_linear)
        bpval = self.calculate_black_point(img_linear, cfval)
        gwfval = self.calculate_grey_world_factors(img_linear, cfval, bpval)
        dhfval = self.calculate_dehaze_factor(img_linear, cfval, bpval, gwfval)
        expfval = self.calculate_exposure_factor(img_linear, cfval, bpval, gwfval, dhfval)
        bhval = self.calculate_blue_hue(img_linear, cfval, bpval, gwfval, dhfval, expfval)

        return cfval, bpval, gwfval, dhfval, expfval, bhval

    # =========================================================================
    # 2. COMPATIBILITY INTERFACE
    # =========================================================================

    def get_filter_matrix(self, frame_rgb: np.ndarray) -> np.ndarray:
        """Analyzes frame and returns 1D array of 11 analytical values."""
        cfval, bpval, gwfval, dhfval, expfval, bhval = self.extract_all_parameters(frame_rgb)
        return np.array([
            cfval[0], cfval[1],
            bpval[0], bpval[1], bpval[2],
            gwfval[0], gwfval[1], gwfval[2],
            dhfval, expfval, bhval
        ], dtype=np.float32)

    def _rgb_to_oklch(self, rgb):
        l = 0.4122214708 * rgb[..., 0] + 0.5363325363 * rgb[..., 1] + 0.0514459929 * rgb[..., 2]
        m = 0.2119034982 * rgb[..., 0] + 0.6806995451 * rgb[..., 1] + 0.1073969566 * rgb[..., 2]
        s = 0.0883024619 * rgb[..., 0] + 0.2817188376 * rgb[..., 1] + 0.6299787005 * rgb[..., 2]

        l = np.cbrt(l)
        m = np.cbrt(m)
        s = np.cbrt(s)

        L_out = 0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s
        a = 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s
        b = 0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s

        C = np.sqrt(a**2 + b**2)
        h = np.arctan2(b, a) / (2.0 * np.pi)
        h[h < 0.0] += 1.0

        return np.stack([L_out, C, h], axis=-1)

    def _oklch_to_rgb(self, lch):
        L_in, C, h = lch[..., 0], lch[..., 1], lch[..., 2]
        h1 = 2.0 * np.pi * h
        a1 = C * np.cos(h1)
        b1 = C * np.sin(h1)

        l1 = L_in + 0.3963377774 * a1 + 0.2158037573 * b1
        m1 = L_in - 0.1055613458 * a1 - 0.0638541728 * b1
        s1 = L_in - 0.0894841775 * a1 - 1.2914855480 * b1

        l1 = l1 * l1 * l1
        m1 = m1 * m1 * m1
        s1 = s1 * s1 * s1

        r = 4.0767416621 * l1 - 3.3077115913 * m1 + 0.2309699292 * s1
        g = -1.2684380046 * l1 + 2.6097574011 * m1 - 0.3413193965 * s1
        b = -0.0041960863 * l1 - 0.7034186147 * m1 + 1.7076147010 * s1

        return np.stack([r, g, b], axis=-1)

    def apply_filter(self, mat: np.ndarray, filt: np.ndarray) -> np.ndarray:
        """Applies the rendering sequence on a given frame."""
        cfval = (filt[0], filt[1])
        bpval = (filt[2], filt[3], filt[4])
        gwfval = (filt[5], filt[6], filt[7])
        dhfval = filt[8]
        expfval = filt[9]
        bhval = filt[10]

        # sRGB to Linear via precomputed 8-bit LUT
        values = self.lut_linear[mat]

        original_values = values.copy()

        # Channel Restoration
        values[..., 0] = values[..., 0] + cfval[0] * (1.0 - values[..., 0]) * values[..., 1]
        values[..., 2] = values[..., 2] + cfval[1] * (1.0 - values[..., 2]) * values[..., 1]

        # Black floor optimization & balance
        values = values - np.array(bpval)
        values = np.clip(values * np.array(gwfval), 0.0, 1.0)

        # Dehaze adjustment curves
        max_value = np.max(values, axis=-1, keepdims=True)
        new_dhf = max_value / dhfval + 1.0 - max_value
        values = expfval * (new_dhf * (values - 1.0) + 1.0)
        values = np.clip(values, 0.0, 1.0)

        # Perceptual Hue Translation
        lch = self._rgb_to_oklch(values)
        h_ch = lch[..., 2]

        t = np.ones_like(h_ch)
        mask1 = h_ch > 0.81
        t[mask1] = 1.0 + (h_ch[mask1] - 0.81) / 0.07
        mask2 = h_ch < 0.65
        t[mask2] = 1.0 + (0.65 - h_ch[mask2]) / 0.07
        t = np.minimum(t, 1.5)

        h_ch = h_ch + ((self.bh_fallback - bhval) / t)
        h_ch[h_ch > 1.0] -= 1.0
        h_ch[h_ch < 0.0] += 1.0
        lch[..., 2] = h_ch

        values = np.clip(self._oklch_to_rgb(lch), 0.0, 1.0)

        # Blend
        if self.cifval != 1.0:
            values = values * self.cifval + original_values * (1.0 - self.cifval)
            lch_alt = self._rgb_to_oklch(values)
            values = np.clip(self._oklch_to_rgb(lch_alt), 0.0, 1.0)

        # Linear to sRGB via precomputed 12-bit LUT
        idx = np.clip(values * 4095.0 + 0.5, 0, 4095).astype(np.int32)
        final_rgb = (np.clip(self.lut_srgb[idx], 0.0, 1.0) * 255.0).astype(np.uint8)
        return final_rgb

    # =========================================================================
    # 3. VIDEO PROCESSING INTERFACE
    # =========================================================================

    def process_video(self, input_path: Path, output_path: Path, creation_date: datetime, 
                      dive: Optional[Dive] = None, stabilize: Optional[str] = None, 
                      overlay: bool = False, 
                      layout_path: Optional[Path] = None,
                      start_time: Optional[str] = None, end_time: Optional[str] = None,
                      tz_offset_mins: Optional[int] = None,
                      color_correct: bool = True):
        """Analyze video and process frames through OpenCV then pipe to FFmpeg."""
        # Open video capture with hardware acceleration support and safe fallback
        cap = cv2.VideoCapture(str(input_path), cv2.CAP_FFMPEG, [
            cv2.CAP_PROP_HW_ACCELERATION, cv2.VIDEO_ACCELERATION_ANY
        ])
        if not cap.isOpened():
            cap = cv2.VideoCapture(str(input_path))

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = int(total_frames / fps) if fps else 0

        # 10-bit Color Preservation detection
        is_10bit = False
        try:
            if self.ffmpeg_tool:
                src_pix_fmt = self.ffmpeg_tool.get_video_pix_fmt(input_path)
                if "10" in src_pix_fmt or "12" in src_pix_fmt or "p010" in src_pix_fmt:
                    is_10bit = True
                    print(f"Detected 10-bit/high bit-depth input ({src_pix_fmt}). Enabling 10-bit color preservation.")
        except Exception as e:
            pass

        if stabilize:
            print(f"Stabilization enabled (level: {stabilize})...")

        # 2. Analysis Phase (Seek-based fast analysis)
        filter_indices, filter_matrices = [], []
        if color_correct:
            print(f"Analyzing {input_path.name}...")
            step = int(fps * SAMPLE_SECONDS)
            if step <= 0:
                step = 30
            sample_frames = list(range(0, total_frames, step))
            if (total_frames - 1) not in sample_frames and total_frames > 0:
                sample_frames.append(total_frames - 1)
            
            with tqdm(total=len(sample_frames), desc="Analysis", unit="frame") as pbar:
                for idx in sample_frames:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                    ret, frame = cap.read()
                    if not ret:
                        continue
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    filter_indices.append(idx)
                    filter_matrices.append(self.get_filter_matrix(rgb))
                    pbar.update(1)
            cap.release()
            filter_matrices = np.array(filter_matrices)
        else:
            cap.release()
            # Identity/noop parameters fallback
            filter_indices = [0]
            filter_matrices = np.array([[0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.67]])

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

        # Re-open video capture for processing phase with hardware decoding and safe fallback
        cap = cv2.VideoCapture(str(input_path), cv2.CAP_FFMPEG, [
            cv2.CAP_PROP_HW_ACCELERATION, cv2.VIDEO_ACCELERATION_ANY
        ])
        if not cap.isOpened():
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

        # Use p010le (standard YUV 10-bit) for 10-bit color preservation, otherwise standard yuv420p
        output_pix_fmt = 'p010le' if is_10bit else 'yuv420p'
        cmd.extend([
            '-vcodec', self.ffmpeg_tool.get_encoder(),
            '-pix_fmt', output_pix_fmt,
            '-acodec', 'copy',
            str(output_path)
        ])

        process = sp.Popen(cmd, stdin=sp.PIPE)

        s_sec = self.ffmpeg_tool._parse_time(start_time) or 0.0
        e_sec = self.ffmpeg_tool._parse_time(end_time) or float(duration)
        s_frame, e_frame = int(s_sec * fps), int(e_sec * fps)
        total_to_process = e_frame - s_frame + 1

        # Precompute interpolated filters for all frames to avoid slow frame-by-frame interpolation
        interpolated_filters = None
        if color_correct and len(filter_matrices) > 0:
            all_counts = np.arange(total_frames)
            num_params = filter_matrices.shape[1]
            interpolated_filters = np.zeros((total_frames, num_params), dtype=np.float32)
            for x in range(num_params):
                interpolated_filters[:, x] = np.interp(all_counts, filter_indices, filter_matrices[:, x])

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
                        # Fetch precomputed filter for current frame index
                        idx_filter = min(count, len(interpolated_filters) - 1)
                        current_filter = interpolated_filters[idx_filter]
                        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        corrected_rgb = self.apply_filter(rgb, current_filter)
                        frame = cv2.cvtColor(corrected_rgb, cv2.COLOR_RGB2BGR)

                    if layout and dive:
                        elapsed_total = count / fps
                        current_time = creation_date + timedelta(seconds=elapsed_total)
                        wp = dive.get_waypoint_at(current_time)
                        
                        if wp:
                            from gui.hud_renderer import draw_hud
                            draw_hud(frame, layout, wp, preloaded_skin=preloaded_skin, waypoints=dive.waypoints)

                    process.stdin.write(frame.tobytes())
                    pbar.update(1)
                    count += 1
        finally:
            cap.release()
            process.stdin.close()
            process.wait()
            if ass_path and ass_path.exists(): ass_path.unlink()
        
        print(f"\nProcessing complete: {output_path.name}")
