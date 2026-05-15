import cv2
import numpy as np
from datetime import timedelta
from PIL import Image, ImageDraw, ImageFont
import os

# Font path for macOS (Standard Arial)
ARIAL_FONT_PATH = "/System/Library/Fonts/Supplemental/Arial.ttf"

# Cache for loaded fonts to avoid repeated disk I/O
_font_cache = {}

def get_font(size):
    """Retrieves or loads a TrueType font at the specified size."""
    if size not in _font_cache:
        try:
            _font_cache[size] = ImageFont.truetype(ARIAL_FONT_PATH, size)
        except Exception as e:
            print(f"Warning: Could not load Arial font from {ARIAL_FONT_PATH}: {e}")
            _font_cache[size] = ImageFont.load_default()
    return _font_cache[size]

def format_telemetry_value(field, raw_val):
    """Unified formatting for telemetry values."""
    if field == "gasmix":
        return str(raw_val) if raw_val is not None else "N/A"
    elif field in ["ndl", "air_remaining"] and raw_val is not None:
        val_mins = int(raw_val / 60)
        if field == "ndl" and val_mins > 99: 
            return "99+"
        else: 
            return f"{val_mins:02d}" if field == "ndl" else str(val_mins)
    elif field in ["dive_time", "tts"] and raw_val is not None:
        mins = int(raw_val // 60)
        secs = int(raw_val % 60)
        return f"{mins:02d}:{secs:02d}"
    elif field in ["depth", "max_depth"] and raw_val is not None:
        return f"{raw_val:.1f}"
    elif field in ["primary_tank_pressure", "volume_sac"] and raw_val is not None:
        return str(int(float(raw_val)))
    elif raw_val is None:
        return "N/A"
    elif isinstance(raw_val, float):
        return f"{raw_val:.1f}"
    else:
        return str(raw_val)

def draw_hud(frame, layout, waypoint, preloaded_skin=None):
    """
    Complete HUD rendering logic used by both CLI and GUI Review.
    preloaded_skin: Optional pre-resized and alpha-applied skin image (BGRA or BGR)
    """
    h_v, w_v = frame.shape[:2]
    hud_skin = layout.get("hud_skin", {})
    
    skin_scale = hud_skin.get("scale", 1.0)
    skin_x_pct = hud_skin.get("x_pct", 0.0)
    skin_y_pct = hud_skin.get("y_pct", 0.0)
    skin_opacity = hud_skin.get("opacity", 1.0)

    # 1. Get Skin Image
    img_skin = preloaded_skin
    if img_skin is None:
        skin_path = hud_skin.get("path")
        if not skin_path:
            return
        img_skin = cv2.imread(skin_path, cv2.IMREAD_UNCHANGED)
        if img_skin is None:
            return
        
        # Basic resizing if not pre-loaded
        h_orig, w_orig = img_skin.shape[:2]
        w_scaled = int(w_orig * skin_scale)
        h_scaled = int(h_orig * skin_scale)
        img_skin = cv2.resize(img_skin, (w_scaled, h_scaled), interpolation=cv2.INTER_AREA)
        if img_skin.shape[2] == 4:
            img_skin[:, :, 3] = (img_skin[:, :, 3] * skin_opacity).astype(np.uint8)

    h_scaled, w_scaled = img_skin.shape[:2]

    # 2. Target coordinates
    skin_x = int(skin_x_pct * w_v)
    skin_y = int(skin_y_pct * h_v)

    # 3. Apply Skin Overlay (Manual Alpha Blending)
    tx1, ty1 = max(0, skin_x), max(0, skin_y)
    tx2, ty2 = min(w_v, skin_x + w_scaled), min(h_v, skin_y + h_scaled)
    sx1, sy1 = max(0, -skin_x), max(0, -skin_y)
    sx2, sy2 = sx1 + (tx2 - tx1), sy1 + (ty2 - ty1)

    if ty2 > ty1 and tx2 > tx1:
        overlay_part = img_skin[sy1:sy2, sx1:sx2]
        target_roi = frame[ty1:ty2, tx1:tx2]
        if overlay_part.shape[2] == 4:
            alpha = overlay_part[:, :, 3:4] / 255.0
            color = overlay_part[:, :, :3]
            blended = (color * alpha + target_roi * (1.0 - alpha)).astype(np.uint8)
            frame[ty1:ty2, tx1:tx2] = blended
        else:
            frame[ty1:ty2, tx1:tx2] = overlay_part[:, :, :3]

    # 4. Draw Telemetry
    skin_info = {
        'x': skin_x,
        'y': skin_y,
        'w': w_scaled,
        'h': h_scaled,
        'scale': skin_scale
    }
    draw_telemetry_on_frame(frame, layout, waypoint, skin_info)

def draw_telemetry_on_frame(frame, layout, waypoint, skin_info):
    """
    Renders the HUD telemetry elements using Pillow for TrueType (Arial) parity.
    """
    linked_elements = layout.get("hud_skin", {}).get("linked_elements", [])
    skin_x = skin_info['x']
    skin_y = skin_info['y']
    w_scaled = skin_info['w']
    h_scaled = skin_info['h']
    skin_scale = skin_info['scale']

    # Convert BGR frame to Pillow Image (RGB)
    pil_img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_img)

    for elem in linked_elements:
        field = elem.get("field", "")
        if field.startswith("custom:"):
            val = field.replace("custom:", "")
        else:
            raw_val = getattr(waypoint, field, None)
            val = format_telemetry_value(field, raw_val)

        rel_x = elem.get("rel_x", 0.0)
        rel_y = elem.get("rel_y", 0.0)
        
        # Base coordinates (exactly matches Qt Designer's top-left)
        abs_x = int(skin_x + (rel_x * w_scaled))
        abs_y = int(skin_y + (rel_y * h_scaled))
        
        color_hex = elem.get("color", "#FFFFFF").lstrip('#')
        # Pillow uses RGB
        color_rgb = tuple(int(color_hex[i:i+2], 16) for i in (0, 2, 4))

        base_font_size = elem.get("font_size", 16)
        item_scale = elem.get("scale", 1.0)
        
        # Final pixel size: designer_size * skin_scale * item_scale
        # No more 45.0 divisor!
        final_size = int(base_font_size * skin_scale * item_scale)
        if final_size < 1: final_size = 1
        
        font = get_font(final_size)
        
        # Draw black outline (4 directions for a solid border)
        o_dist = max(1, int(final_size / 20)) # Proportional outline
        for dx, dy in [(-o_dist, -o_dist), (o_dist, -o_dist), (-o_dist, o_dist), (o_dist, o_dist)]:
            draw.text((abs_x + dx, abs_y + dy), str(val), font=font, fill=(0, 0, 0))
            
        # Draw main text
        draw.text((abs_x, abs_y), str(val), font=font, fill=color_rgb)

    # Convert back to BGR for OpenCV
    frame[:] = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
