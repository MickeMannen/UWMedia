import cv2
import numpy as np
import math
import json
import shutil
import time
import sys
from io import StringIO
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from tqdm import tqdm
from ffmpeg.ffmpeg_class import FfmpegClass
from models.dive import Dive, Waypoint
from utils.color_profiles import load_merged_color_profiles
from utils.resource_paths import app_temp_dir

# Constants for analysis
SAMPLE_SECONDS = 2

# Option 2: Adaptive Highlight Damping to prevent spotlight/flashlight oversaturation
ENABLE_ADAPTIVE_DAMPING = False

# Share of a file's UWMEDIA_FFMPEG_PROGRESS spent before the encode: the
# frame-sampling analysis, then (overlay runs only) drawing the HUD layers
ANALYSIS_PROGRESS_END = 10.0
HUD_PROGRESS_END = 14.0


class _FileProgress:
    """Labeled UWMEDIA_FFMPEG_PROGRESS lines for the phases before the encode
    (FfmpegClass.run_command reports the encode itself), throttled to 1%."""

    def __init__(self, label):
        self.label = label
        self.last = -1.0

    def report(self, pct):
        if self.label and pct - self.last >= 1.0:
            print(f"UWMEDIA_FFMPEG_PROGRESS {pct:.1f} {self.label}", flush=True)
            self.last = pct


def _show_bars() -> bool:
    """tqdm bars only on a terminal - piped to the GUI they are noise
    between the UWMEDIA_* lines it reads."""
    return sys.stdout.isatty()


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

        data = load_merged_color_profiles()
        if not data:
            raise FileNotFoundError("Could not find color.yaml in current directory, app directory, user data directory, or bundled assets.")

        if self.color_profile not in data:
            if "default" in data:
                print(f"Warning: Profile '{self.color_profile}' not found. Falling back to 'default'.")
                self.color_profile = "default"
            else:
                raise ValueError(f"Profile '{self.color_profile}' not found and no 'default' profile exists.")

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
        self.sharpness = float(profile.get("sharpness", 0.0))
        self.darkness = float(profile.get("darkness", 0.0))

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
        """Applies the rendering sequence on a given RGB frame. Returns RGB uint8."""
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
        if ENABLE_ADAPTIVE_DAMPING:
            # Calculate pixel brightness (Luma) using standard Rec709 coefficients.
            # This identifies bright regions (e.g. spotlight illuminated zones).
            luma = 0.299 * values[..., 0] + 0.587 * values[..., 1] + 0.114 * values[..., 2]
            
            # Compute a damping factor. We smoothly transition from 1.0 (fully active color restoration
            # in darker/normal regions below 40% brightness) down to 0.0 (no color restoration
            # in highlights above 80% brightness).
            damping = np.clip((0.8 - luma) / 0.4, 0.0, 1.0)
            
            # Apply the color restoration, scaled down in bright regions to prevent spotlight oversaturation
            values[..., 0] = values[..., 0] + cfval[0] * (1.0 - values[..., 0]) * values[..., 1] * damping
            values[..., 2] = values[..., 2] + cfval[1] * (1.0 - values[..., 2]) * values[..., 1] * damping
        else:
            # Old/legacy channel restoration (global application)
            values[..., 0] = values[..., 0] + cfval[0] * (1.0 - values[..., 0]) * values[..., 1]
            values[..., 2] = values[..., 2] + cfval[1] * (1.0 - values[..., 2]) * values[..., 1]

        # Black floor optimization & balance
        values = values - np.array(bpval)
        values = np.clip(values * np.array(gwfval), 0.0, 1.0)

        # Dehaze adjustment curves & Darkness correction
        max_value = np.max(values, axis=-1, keepdims=True)
        new_dhf = max_value / dhfval + 1.0 - max_value
        adjusted_expf = expfval * (1.0 - self.darkness)
        values = adjusted_expf * (new_dhf * (values - 1.0) + 1.0)
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

        # Apply Sharpness (unsharp mask)
        if self.sharpness > 0.0:
            blurred = cv2.GaussianBlur(final_rgb, (0, 0), 1.0)
            final_rgb = cv2.addWeighted(final_rgb, 1.0 + self.sharpness, blurred, -self.sharpness, 0)

        return final_rgb

    def generate_3d_lut(self, filt: np.ndarray, size: int = 64) -> np.ndarray:
        """Takes a filter parameter array (11 floats) and generates a 3D LUT."""
        # Create grid of all RGB input values (0-255)
        steps = np.linspace(0, 255, size).astype(np.uint8)
        # .cube format order: R fastest, G middle, B slowest
        bb, gg, rr = np.meshgrid(steps, steps, steps, indexing='ij')
        grid = np.stack([rr.ravel(), gg.ravel(), bb.ravel()], axis=1).astype(np.uint8)
        # apply_filter expects (H, W, 3) uint8 RGB input
        grid_img = grid.reshape(1, -1, 3)
        corrected = self.apply_filter(grid_img, filt)
        # Normalize to 0.0-1.0
        return corrected.reshape(size, size, size, 3).astype(np.float32) / 255.0

    def write_cube_file(self, lut: np.ndarray, path: Path, title: str = 'UWMedia'):
        """Writes the LUT to .cube format."""
        size = lut.shape[0]
        buf = StringIO()
        buf.write(f'TITLE "{title}"\n')
        buf.write(f'LUT_3D_SIZE {size}\n\n')
        flat = lut.reshape(-1, 3)
        for row in flat:
            buf.write(f'{row[0]:.6f} {row[1]:.6f} {row[2]:.6f}\n')
        path.write_text(buf.getvalue())

    def _build_lut3d_filter(self, filter_indices, filter_matrices, fps: float, lut_dir: Path) -> str:
        """Deduplicates consecutive similar filter matrices, writes one .cube LUT
        file per unique filter into lut_dir, and returns an FFmpeg -vf value that
        applies them natively (a single lut3d filter, or lut3d + sendcmd for
        multiple, switching at each filter's timestamp). Shared by
        process_video_lut and process_video."""
        unique_filters = [filter_matrices[0]]
        unique_indices = [filter_indices[0]]
        for i in range(1, len(filter_matrices)):
            if not np.allclose(filter_matrices[i], unique_filters[-1], atol=0.01):
                unique_filters.append(filter_matrices[i])
                unique_indices.append(filter_indices[i])

        print(f"Generating {len(unique_filters)} 3D LUT(s) (64³)...")
        lut_paths = []
        lut_timestamps = []
        with tqdm(total=len(unique_filters), desc="LUT Generation", unit="lut", disable=not _show_bars()) as pbar:
            for i, filt in enumerate(unique_filters):
                lut = self.generate_3d_lut(filt)
                lut_path = lut_dir / f"lut_{i:04d}.cube"
                self.write_cube_file(lut, lut_path)
                lut_paths.append(lut_path)
                lut_timestamps.append(unique_indices[i] / fps)
                pbar.update(1)

        first_lut = str(lut_paths[0]).replace('\\', '/').replace(':', '\\:')
        if len(lut_paths) == 1:
            return f"lut3d=file='{first_lut}':interp=trilinear"

        sendcmd_path = lut_dir / "sendcmd.txt"
        with open(sendcmd_path, 'w') as f:
            for lp, ts in zip(lut_paths, lut_timestamps):
                lp_str = str(lp).replace('\\', '/').replace(':', '\\:')
                f.write(f"{ts:.3f} [enter] lut3d file '{lp_str}';\n")
        sendcmd_str = str(sendcmd_path).replace('\\', '/').replace(':', '\\:')
        return f"sendcmd=f='{sendcmd_str}',lut3d=file='{first_lut}':interp=trilinear"

    def _open_video_capture(self, input_path: Path) -> cv2.VideoCapture:
        """Safely open OpenCV VideoCapture without triggering D3D11/DXVA2 hardware decoding errors on 10-bit video streams."""
        if self.ffmpeg_tool and self.ffmpeg_tool.hw_accel and self.ffmpeg_tool.os_type != "Windows":
            cap = cv2.VideoCapture(str(input_path), cv2.CAP_FFMPEG, [
                cv2.CAP_PROP_HW_ACCELERATION, cv2.VIDEO_ACCELERATION_ANY
            ])
            if cap.isOpened():
                return cap
        return cv2.VideoCapture(str(input_path))

    def _probe(self, input_path: Path):
        """fps, width, height, frame count and whether the source is 10-bit."""
        cap = self._open_video_capture(input_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
        is_10bit = False
        try:
            if self.ffmpeg_tool:
                src_pix_fmt = self.ffmpeg_tool.get_video_pix_fmt(input_path)
                if "10" in src_pix_fmt or "12" in src_pix_fmt or "p010" in src_pix_fmt:
                    is_10bit = True
                    print(f"Detected 10-bit input ({src_pix_fmt}). Enabling 10-bit preservation.")
        except Exception:
            pass
        return fps, width, height, total_frames, is_10bit

    def _analyze(self, input_path: Path, fps: float, total_frames: int, progress: _FileProgress):
        """Samples a frame every SAMPLE_SECONDS and returns (frame indices,
        filter matrices, number of samples) for _build_lut3d_filter."""
        print(f"Analyzing {input_path.name}...")
        step = int(fps * SAMPLE_SECONDS)
        if step <= 0:
            step = 30
        sample_frames = list(range(0, total_frames, step))
        if (total_frames - 1) not in sample_frames and total_frames > 0:
            sample_frames.append(total_frames - 1)

        filter_indices, filter_matrices = [], []
        cap = self._open_video_capture(input_path)
        try:
            with tqdm(total=len(sample_frames), desc="Analysis", unit="frame", disable=not _show_bars()) as pbar:
                for n, idx in enumerate(sample_frames, start=1):
                    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                    ret, frame = cap.read()
                    if ret:
                        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        filter_indices.append(idx)
                        filter_matrices.append(self.get_filter_matrix(rgb))
                    pbar.update(1)
                    progress.report(ANALYSIS_PROGRESS_END * n / len(sample_frames))
        finally:
            cap.release()
        return filter_indices, np.array(filter_matrices), len(sample_frames)

    def _output_args(self, input_path: Path, output_path: Path, creation_date: datetime,
                     tz_offset_mins: Optional[int], is_10bit: bool) -> List[str]:
        """Bitrate, metadata, colour tags and encoder - input 0 is the source."""
        args = []
        try:
            bitrate = self.ffmpeg_tool.get_video_bitrate(input_path)
            args.extend(["-b:v", str(bitrate)])
        except Exception:
            pass

        args.extend(["-map_metadata", "0"])
        args.extend(["-movflags", "+faststart+use_metadata_tags"])
        args.extend(["-tag:v", "hvc1"])
        args.extend([
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
            args.extend(["-metadata", f"creation_time={iso_date}"])

        # p010le (standard YUV 10-bit) for 10-bit color preservation, otherwise standard yuv420p
        output_pix_fmt = 'p010le' if is_10bit else 'yuv420p'
        args.extend([
            "-vcodec", self.ffmpeg_tool.get_encoder(),
            "-pix_fmt", output_pix_fmt,
            "-acodec", "copy",
            str(output_path)
        ])
        return args

    def _input_args(self, input_path: Path) -> List[str]:
        args = ["-y"]
        if not self.ffmpeg_tool.debug:
            args.extend(["-nostats", "-loglevel", "error"])
        # Hardware-accelerated decoding of the source, when the decoder can take it
        if self.ffmpeg_tool.hw_accel and self.ffmpeg_tool.hw_decodable(input_path):
            if self.ffmpeg_tool.os_type == "Darwin":
                args.extend(["-hwaccel", "videotoolbox"])
            else:
                args.extend(["-hwaccel", "auto"])
        return args

    def process_video_lut(self, input_path: Path, output_path: Path, creation_date: datetime,
                          tz_offset_mins: Optional[int] = None,
                          color_correct: bool = True):
        """Fast path: analyze video, generate 3D LUTs, and process natively via FFmpeg lut3d filter."""
        progress = _FileProgress(input_path.name)
        fps, _width, _height, total_frames, is_10bit = self._probe(input_path)
        duration = total_frames / fps if fps else 0

        t_start_analysis = time.time()
        filter_indices, filter_matrices, n_samples = self._analyze(input_path, fps, total_frames, progress)
        analysis_duration = time.time() - t_start_analysis

        if len(filter_matrices) == 0:
            print("Error: Could not analyze any frames.")
            return

        t_start_lut = time.time()
        lut_dir = app_temp_dir('uwmedia_lut_')
        try:
            vf = self._build_lut3d_filter(filter_indices, filter_matrices, fps, lut_dir)
            lut_gen_duration = time.time() - t_start_lut

            args = self._input_args(input_path)
            args.extend(["-i", str(input_path)])
            args.extend(["-vf", vf])
            args.extend(["-map", "0:v:0", "-map", "0:a?"])
            args.extend(self._output_args(input_path, output_path, creation_date, tz_offset_mins, is_10bit))

            print(f"Processing {input_path.name} using fast LUT path...")
            t_start_render = time.time()
            self.ffmpeg_tool.run_command(args, duration=duration, progress_label=input_path.name,
                                         progress_range=(ANALYSIS_PROGRESS_END, 100.0))
            render_duration = time.time() - t_start_render
            print(f"\nProcessing complete: {output_path.name}")

            return {
                "total_frames": total_frames,
                "analysis_time": analysis_duration,
                "analysis_fps": n_samples / analysis_duration if analysis_duration > 0 else 0,
                "lut_gen_time": lut_gen_duration,
                "render_time": render_duration,
                "render_fps": total_frames / render_duration if render_duration > 0 else 0,
            }

        finally:
            # Clean up temp LUT files
            shutil.rmtree(lut_dir, ignore_errors=True)

    # =========================================================================
    # 3. VIDEO PROCESSING INTERFACE
    # =========================================================================

    def _preload_hud_skin(self, layout: dict, frame_width: int):
        """Loads+resizes a resolved layout's hud_skin image once, ahead of
        drawing it - shared by process_video's single-layout (layout_path)
        and multi-overlay (overlay_instances) paths so both get the
        identical premultiplied-opacity preload draw_hud() expects via its
        preloaded_skin param. Returns None for shape skins (nothing to
        preload) or when the skin image can't be read."""
        hud_skin = layout.get("hud_skin", {})
        skin_path = hud_skin.get("path")
        if not skin_path:
            return None
        img_skin = cv2.imread(skin_path, cv2.IMREAD_UNCHANGED)
        if img_skin is None:
            return None
        design_w = float(layout.get("design_width", 1920))
        user_scale = hud_skin.get("scale", 1.0)
        res_scale = frame_width / design_w
        final_skin_scale = user_scale * res_scale

        skin_opacity = hud_skin.get("opacity", 1.0)
        h_orig, w_orig = img_skin.shape[:2]
        w_scaled = max(1, int(w_orig * final_skin_scale))
        h_scaled = max(1, int(h_orig * final_skin_scale))

        preloaded_skin = cv2.resize(img_skin, (w_scaled, h_scaled), interpolation=cv2.INTER_AREA)
        if preloaded_skin.shape[2] == 4:
            preloaded_skin[:, :, 3] = (preloaded_skin[:, :, 3] * skin_opacity).astype(np.uint8)
        return preloaded_skin

    def _hud_layers(self, layout_path, overlay_instances, width, height):
        """HudLayers in drawing order: the single --layout first, then each
        overlay instance (last on top, the Color page's z-order)."""
        from gui.hud_renderer import resolve_overlay_instance_layout
        from ffmpeg.hud_layers import HudLayer
        layers = []
        if layout_path:
            print(f"Generating telemetry overlay using layout: {Path(layout_path).name}")
            with open(layout_path, 'r') as f:
                layout = json.load(f)
            layers.append(HudLayer(layout, self._preload_hud_skin(layout, width), width, height, resolved=False))
        if overlay_instances:
            print(f"Generating telemetry overlay using {len(overlay_instances)} composited layer(s)")
            for inst in overlay_instances:
                with open(Path(inst["layout_path"]), 'r') as f:
                    raw_layout = json.load(f)
                resolved = resolve_overlay_instance_layout(
                    raw_layout, inst.get("x", 0.0), inst.get("y", 0.0), inst.get("scale", 1.0), width, height
                )
                layers.append(HudLayer(resolved, self._preload_hud_skin(resolved, width), width, height, resolved=True))
        return layers

    def process_video(self, input_path: Path, output_path: Path, creation_date: datetime,
                      dive: Optional[Dive] = None,
                      overlay: bool = False,
                      layout_path: Optional[Path] = None,
                      overlay_instances: Optional[list] = None,
                      tz_offset_mins: Optional[int] = None,
                      color_correct: bool = True):
        """Colour correction plus HUD overlays, all composited by FFmpeg.

        The HUD changes only when the dive sample does, so each layer is
        drawn once per sample as a transparent PNG (ffmpeg/hud_layers.py)
        rather than onto every frame in Python. FFmpeg then decodes the
        source, applies the lut3d colour correction and overlays the layers
        on top in one pass - after the correction, so the HUD keeps its own
        colours (a neutral Garmin X50i bezel came out red-tinted when it was
        corrected along with the footage, 2026-09-27)."""
        from ffmpeg.hud_layers import hud_segments, overlay_filter_complex, write_layer_stream

        progress = _FileProgress(input_path.name)
        fps, width, height, total_frames, is_10bit = self._probe(input_path)
        duration = total_frames / fps if fps else 0

        t_start_analysis = time.time()
        filter_indices, filter_matrices, n_samples = [], np.array([]), 0
        if color_correct:
            filter_indices, filter_matrices, n_samples = self._analyze(input_path, fps, total_frames, progress)
        analysis_duration = time.time() - t_start_analysis

        work_dir = app_temp_dir('uwmedia_overlay_')
        try:
            color_vf = None
            if color_correct and len(filter_matrices) > 0:
                color_vf = self._build_lut3d_filter(filter_indices, filter_matrices, fps, work_dir)

            # HUD layers - nothing to draw without a matched dive
            t_start_hud = time.time()
            streams = []
            if dive and dive.waypoints:
                layers = self._hud_layers(layout_path, overlay_instances, width, height)
                segments = hud_segments(dive, creation_date, fps, total_frames)
                steps = max(1, len(layers) * len(segments))
                for li, layer in enumerate(layers):
                    def on_segment(i, li=li):
                        done = li * len(segments) + i + 1
                        progress.report(ANALYSIS_PROGRESS_END + (HUD_PROGRESS_END - ANALYSIS_PROGRESS_END) * done / steps)
                    stream = write_layer_stream(layer, segments, dive.waypoints, fps, work_dir, li, on_segment)
                    if stream:
                        streams.append(stream)
            hud_duration = time.time() - t_start_hud

            args = self._input_args(input_path)
            args.extend(["-i", str(input_path)])
            for concat_path, _x, _y in streams:
                args.extend(["-f", "concat", "-safe", "0", "-i", str(concat_path)])
            graph, out_label = overlay_filter_complex(color_vf, [(x, y) for _c, x, y in streams])
            args.extend(["-filter_complex", graph, "-map", out_label, "-map", "0:a?"])
            args.extend(self._output_args(input_path, output_path, creation_date, tz_offset_mins, is_10bit))

            print(f"Processing {input_path.name} with {len(streams)} HUD layer(s)...")
            t_start_render = time.time()
            self.ffmpeg_tool.run_command(args, duration=duration, progress_label=input_path.name,
                                         progress_range=(HUD_PROGRESS_END, 100.0))
            render_duration = time.time() - t_start_render
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

        print(f"\nProcessing complete: {output_path.name}")
        return {
            "total_frames": total_frames,
            "analysis_time": analysis_duration,
            "analysis_fps": n_samples / analysis_duration if analysis_duration > 0 else 0,
            "hud_time": hud_duration,
            "render_time": render_duration,
            "render_fps": total_frames / render_duration if render_duration > 0 else 0,
        }
