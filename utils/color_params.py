"""
Shared spec for the underwater color-correction tuning parameters:
(key, label, min, max, default, is_int). Single source of truth for the
sliders in both the Qt tuning tool (color_tuning_gui.py) and the native
Toga Color Tuning section (uwmedia/app.py) - values are the ffmpeg.color
.ColorCorrectionEngine attribute names and their ranges/defaults.
"""

PARAM_GROUPS = [
    ("Color Restoration & Blend", [
        ("cifval", "Blend Weight", 0.0, 1.0, 1.0, False),
        ("red_threshold", "Red Threshold", 0.0, 1.0, 0.3, False),
        ("red_scale", "Red Scale", 0.01, 1.0, 0.2, False),
        ("blue_threshold", "Blue Threshold", 0.0, 1.0, 0.3, False),
        ("blue_scale", "Blue Scale", 0.01, 2.0, 0.6, False),
    ]),
    ("Black Point Floors", [
        ("black_point_cutoff", "CDF Cutoff Floor", 0.0001, 0.01, 0.001, False),
    ]),
    ("Gray World White Balance", [
        ("gw_mask_mult", "Mask Multiplier", 0.5, 3.0, 1.5, False),
        ("gw_mask_fallback", "Mask Fallback Weight", 0.0, 1.0, 0.2, False),
        ("gw_blur_radius", "Gaussian Blur Radius", 1, 31, 9, True),
        ("gw_blur_sigma", "Gaussian Blur Sigma", 0.1, 5.0, 1.8, False),
        ("gw_isolation_threshold", "Isolation Variation", 0.001, 0.5, 0.07, False),
        ("gw_isolation_min_sum", "Isolation Min Sum", 10, 500, 100, True),
    ]),
    ("De-haze Adjustment", [
        ("dehaze_sat_cutoff", "Saturation Cutoff", 0.01, 0.5, 0.1, False),
        ("dehaze_sat_scale", "Saturation Divisor", 0.1, 2.0, 0.75, False),
        ("dehaze_min", "Dehaze Min Bound", 0.5, 1.0, 0.81, False),
        ("dehaze_max", "Dehaze Max Bound", 1.0, 2.0, 1.0, False),
    ]),
    ("Exposure Normalization", [
        ("exposure_cdf_cutoff", "CDF Brightness Cutoff", 0.001, 0.1, 0.01, False),
        ("exposure_numerator", "Target Reference Brightness", 0.1, 2.0, 0.5, False),
        ("exposure_min", "Exposure Min Mult", 0.5, 2.0, 1.0, False),
        ("exposure_max", "Exposure Max Mult", 1.0, 4.0, 2.0, False),
    ]),
    ("OKLCh Blue Hue Translation", [
        ("bh_min_idx", "Min Hue Scanning Bin", 0, 255, 155, True),
        ("bh_max_idx", "Max Hue Scanning Bin", 0, 255, 218, True),
        ("bh_decay", "Scan Decay Weight", 0.0, 1.0, 0.85, False),
        ("bh_fallback", "Fallback Blue Hue", 0.0, 1.0, 0.67, False),
    ]),
    ("Final Adjustments", [
        ("sharpness", "Sharpness", 0.0, 3.0, 0.0, False),
        ("darkness", "Darkness", -1.0, 1.0, 0.0, False),
    ]),
]

# Flat (key -> (label, min, max, default, is_int)) lookup, handy for
# reset-to-default and profile-loading fallbacks.
PARAMS_BY_KEY = {
    key: (label, lo, hi, default, is_int)
    for _, params in PARAM_GROUPS
    for key, label, lo, hi, default, is_int in params
}
