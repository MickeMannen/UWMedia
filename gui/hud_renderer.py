import cv2
import numpy as np
import math
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
    elif field.startswith("tank_name:"):
        if raw_val:
            return str(raw_val)
        return field.replace("tank_name:", "")
    elif (field == "primary_tank_pressure" or field.startswith("tank_pressure:")) and raw_val is not None:
        return str(int(float(raw_val)))
    elif field in ["ndl", "air_remaining"] and raw_val is not None:
        val_mins = int(raw_val / 60)
        if field == "ndl":
            if val_mins > 99 or val_mins <= 0:
                return "99+"
            return f"{val_mins:02d}"
        else:
            return str(val_mins)
    elif field in ["dive_time", "tts"] and raw_val is not None:
        mins = int(raw_val // 60)
        secs = int(raw_val % 60)
        return f"{mins:02d}:{secs:02d}"
    elif field in ["depth", "max_depth"] and raw_val is not None:
        return f"{raw_val:.1f}"
    elif field in ["primary_tank_pressure", "volume_sac"] and raw_val is not None:
        return str(int(float(raw_val)))
    elif raw_val is None:
        return "--"
    elif isinstance(raw_val, float):
        return f"{raw_val:.1f}"
    else:
        return str(raw_val)

def draw_rounded_rect(img, pt1, pt2, color, thickness, r, d):
    x1, y1 = pt1
    x2, y2 = pt2
    
    # 1. Draw Corners (Ellipses)
    cv2.ellipse(img, (x1 + r, y1 + r), (r, r), 180, 0, 90, color, thickness)
    cv2.ellipse(img, (x2 - r, y1 + r), (r, r), 270, 0, 90, color, thickness)
    cv2.ellipse(img, (x2 - r, y2 - r), (r, r), 0, 0, 90, color, thickness)
    cv2.ellipse(img, (x1 + r, y2 - r), (r, r), 90, 0, 90, color, thickness)

    if thickness > 0:
        # Outlined: Draw 4 lines
        cv2.line(img, (x1 + r, y1), (x2 - r, y1), color, thickness)
        cv2.line(img, (x1 + r, y2), (x2 - r, y2), color, thickness)
        cv2.line(img, (x1, y1 + r), (x1, y2 - r), color, thickness)
        cv2.line(img, (x2, y1 + r), (x2, y2 - r), color, thickness)
    else:
        # Filled: Draw 2 rectangles to fill the center gaps between ellipses
        cv2.rectangle(img, (x1 + r, y1), (x2 - r, y2), color, thickness)
        cv2.rectangle(img, (x1, y1 + r), (x2, y2 - r), color, thickness)

def draw_hud(frame, layout, waypoint, preloaded_skin=None, render_log=False, waypoints=None):
    """
    Complete HUD rendering logic used by both CLI and GUI Review.
    Now using Corner-to-Corner Layout Anchor System.
    """
    h_v, w_v = frame.shape[:2]
    hud_skin = layout.get("hud_skin", {})
    
    # --- Universal Scaling Factor (Base 1920px) ---
    design_w = float(layout.get("design_width", 1920))
    res_scale = 1.0 if render_log else (w_v / design_w)
    
    skin_type = hud_skin.get("type", "image")
    skin_opacity = hud_skin.get("opacity", 1.0)
    user_scale = hud_skin.get("scale", 1.0)
    
    # --- 1. Get Scaled HUD Dimensions ---
    if skin_type == "shape":
        w_hud = int(hud_skin.get("width", 400) * res_scale)
        h_hud = int(hud_skin.get("height", 200) * res_scale)
    else:
        # Load or use preloaded skin to get original dimensions
        if preloaded_skin is not None:
            h_hud, w_hud = preloaded_skin.shape[:2]
        else:
            skin_path = hud_skin.get("path")
            if not skin_path: return
            img_temp = cv2.imread(skin_path, cv2.IMREAD_UNCHANGED)
            if img_temp is None: return
            w_hud = int(img_temp.shape[1] * user_scale * res_scale)
            h_hud = int(img_temp.shape[0] * user_scale * res_scale)

    # --- 2. Resolve Anchor Base Coordinates (Screen side) ---
    anchor = hud_skin.get("anchor", "TOP_LEFT")
    base_x, base_y = 0.0, 0.0
    
    if 'CENTER' in anchor: base_x = w_v / 2.0
    elif 'RIGHT' in anchor: base_x = float(w_v)
    
    if 'MIDDLE' in anchor: base_y = h_v / 2.0
    elif 'BOTTOM' in anchor: base_y = float(h_v)
    
    # --- 3. Resolve HUD Pivot Adjustments (HUD side) ---
    # To lock corner-to-corner, we must subtract the HUD's own dimensions
    # if anchored to Center/Right/Bottom.
    pivot_x, pivot_y = 0.0, 0.0
    
    if 'CENTER' in anchor: pivot_x = w_hud / 2.0
    elif 'RIGHT' in anchor: pivot_x = float(w_hud)
    
    if 'MIDDLE' in anchor: pivot_y = h_hud / 2.0
    elif 'BOTTOM' in anchor: pivot_y = float(h_hud)
    
    # --- 4. Apply Reference Offsets (Margin side) ---
    ref_x = hud_skin.get("ref_offset_x", 0.0)
    ref_y = hud_skin.get("ref_offset_y", 0.0)
    
    # Final Top-Left Coordinate
    if render_log:
        skin_x = 0
        skin_y = 0
    else:
        skin_x = int(base_x + (ref_x * res_scale) - pivot_x)
        skin_y = int(base_y + (ref_y * res_scale) - pivot_y)

    if os.environ.get("UW_DEBUG"):
        print(f"HUD Render Debug (Anchor: {anchor}):")
        print(f"  Frame: {w_v}x{h_v} | HUD Size: {w_hud}x{h_hud}")
        print(f"  Base (Screen): ({base_x}, {base_y})")
        print(f"  Pivot (HUD): ({pivot_x}, {pivot_y})")
        print(f"  Final Pos (Top-Left): ({skin_x}, {skin_y})")

    # --- 5. Render HUD Skin ---
    if skin_type == "shape":
        color_hex = hud_skin.get("color", "#000000").lstrip('#')
        color_bgr = tuple(int(color_hex[i:i+2], 16) for i in (4, 2, 0))
        radius = int(hud_skin.get("corner_radius", 20) * res_scale)
        overlay = frame.copy()
        draw_rounded_rect(overlay, (skin_x, skin_y), (skin_x + w_hud, skin_y + h_hud), color_bgr, -1, radius, 1)
        cv2.addWeighted(overlay, skin_opacity, frame, 1 - skin_opacity, 0, frame)
    else:
        img_skin = preloaded_skin
        if img_skin is None:
            # We already loaded it once in step 1, but let's be safe
            img_orig = cv2.imread(hud_skin.get("path"), cv2.IMREAD_UNCHANGED)
            img_skin = cv2.resize(img_orig, (w_hud, h_hud), interpolation=cv2.INTER_AREA)
            if img_skin.shape[2] == 4:
                img_skin[:, :, 3] = (img_skin[:, :, 3] * skin_opacity).astype(np.uint8)

        # Apply Skin Overlay
        tx1, ty1 = max(0, skin_x), max(0, skin_y)
        tx2, ty2 = min(w_v, skin_x + w_hud), min(h_v, skin_y + h_hud)
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

    # --- 6. Draw Telemetry ---
    skin_info = {
        'x': skin_x, 'y': skin_y, 'w': w_hud, 'h': h_hud,
        'res_scale': res_scale, 'user_scale': user_scale if skin_type == "image" else 1.0,
        'render_log': render_log
    }
    draw_telemetry_on_frame(frame, layout, waypoint, skin_info, waypoints=waypoints)

def draw_depth_graph(frame, elem, waypoint, waypoints, skin_info):
    skin_x = skin_info['x']
    skin_y = skin_info['y']
    w_scaled = skin_info['w']
    h_scaled = skin_info['h']
    res_scale = skin_info['res_scale']
    
    rel_x = elem.get("rel_x", 0.0)
    rel_y = elem.get("rel_y", 0.0)
    
    graph_w = int(elem.get("width", 300) * res_scale)
    graph_h = int(elem.get("height", 150) * res_scale)
    
    abs_x = int(skin_x + (rel_x * w_scaled))
    abs_y = int(skin_y + (rel_y * h_scaled))
    
    color_hex = elem.get("color", "#00FF00").lstrip('#')
    color_bgr = tuple(int(color_hex[i:i+2], 16) for i in (4, 2, 0))
    
    # Background
    overlay = frame.copy()
    cv2.rectangle(overlay, (abs_x, abs_y), (abs_x + graph_w, abs_y + graph_h), (0, 0, 0), -1)
    cv2.rectangle(overlay, (abs_x, abs_y), (abs_x + graph_w, abs_y + graph_h), color_bgr, 1)
    cv2.addWeighted(overlay, 0.4, frame, 0.6, 0, frame)
    
    if not waypoints:
        return
        
    max_d = max(wp.depth for wp in waypoints) if waypoints else 1.0
    if max_d <= 0:
        max_d = 1.0
    max_d *= 1.1
    
    n_wps = len(waypoints)
    if n_wps < 2:
        return
        
    dx = graph_w / (n_wps - 1)
    dy = graph_h / max_d
    
    # Fill path
    fill_overlay = frame.copy()
    pts = []
    pts.append([abs_x, abs_y])
    for i in range(n_wps):
        x = int(abs_x + i * dx)
        y = int(abs_y + waypoints[i].depth * dy)
        pts.append([x, y])
    pts.append([abs_x + graph_w, abs_y])
    
    pts = np.array(pts, dtype=np.int32)
    cv2.fillPoly(fill_overlay, [pts], color_bgr)
    cv2.addWeighted(fill_overlay, 0.15, frame, 0.85, 0, frame)
    
    # Outline line
    line_pts = []
    for i in range(n_wps):
        x = int(abs_x + i * dx)
        y = int(abs_y + waypoints[i].depth * dy)
        line_pts.append([x, y])
    line_pts = np.array(line_pts, dtype=np.int32)
    cv2.polylines(frame, [line_pts], False, color_bgr, int(2 * res_scale))
    
    # Cursor
    if waypoint:
        curr_idx = 0
        closest_diff = float('inf')
        for idx, wp in enumerate(waypoints):
            diff = abs((wp.timestamp - waypoint.timestamp).total_seconds())
            if diff < closest_diff:
                closest_diff = diff
                curr_idx = idx
                
        curr_x = int(abs_x + curr_idx * dx)
        curr_y = int(abs_y + waypoints[curr_idx].depth * dy)
        
        cv2.line(frame, (curr_x, abs_y), (curr_x, abs_y + graph_h), color_bgr, 1)
        
        marker_style = elem.get("marker_style", "dot")
        marker_size = elem.get("marker_size", 6)
        scaled_size = int(marker_size * res_scale)
        if marker_style == "dot":
            cv2.circle(frame, (curr_x, curr_y), scaled_size, color_bgr, -1)
            cv2.circle(frame, (curr_x, curr_y), scaled_size, (255, 255, 255), 1)
        elif marker_style == "cross":
            cv2.line(frame, (curr_x - scaled_size, curr_y), (curr_x + scaled_size, curr_y), color_bgr, 1)
            cv2.line(frame, (curr_x, curr_y - scaled_size), (curr_x, curr_y + scaled_size), color_bgr, 1)
        elif marker_style == "bold_cross":
            thickness = max(2, int(3 * res_scale))
            cv2.line(frame, (curr_x - scaled_size, curr_y), (curr_x + scaled_size, curr_y), color_bgr, thickness)
            cv2.line(frame, (curr_x, curr_y - scaled_size), (curr_x, curr_y + scaled_size), color_bgr, thickness)

def draw_telemetry_on_frame(frame, layout, waypoint, skin_info, waypoints=None):
    """
    Renders the HUD telemetry elements using Pillow for TrueType parity.
    """
    linked_elements = layout.get("hud_skin", {}).get("linked_elements", [])
    skin_x = skin_info['x']
    skin_y = skin_info['y']
    w_scaled = skin_info['w']
    h_scaled = skin_info['h']
    res_scale = skin_info['res_scale']
    user_scale = skin_info['user_scale']
    render_log = skin_info.get('render_log', False)

    # Filter out graphs first and draw them using OpenCV directly on the frame
    for elem in linked_elements:
        field = elem.get("field", "")
        if elem.get("type") == "graph" or field == "depth_graph":
            draw_depth_graph(frame, elem, waypoint, waypoints, skin_info)

    pil_img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_img)

    for elem in linked_elements:
        field = elem.get("field", "")
        if elem.get("type") == "graph" or field == "depth_graph":
            continue

        # Get formatted value (same logic)
        if field == "safety_stop":
            from utils.hud_rules_engine import get_safety_stop_text
            manufacturer = layout.get("manufacturer", "Shearwater")
            model = layout.get("model", "Perdix2")
            val = get_safety_stop_text(manufacturer, model, waypoint)
            raw_val = None
        elif field.startswith("custom:"):
            val = field.replace("custom:", "")
            raw_val = None
        elif field.startswith("tank_pressure:"):
            tank_name = field.replace("tank_pressure:", "")
            tank_data = waypoint.tanks.get(tank_name)
            raw_val = tank_data.pressure_bar if tank_data else None
            val = format_telemetry_value(field, raw_val)
        elif field.startswith("tank_name:"):
            tank_name = field.replace("tank_name:", "")
            tank_data = waypoint.tanks.get(tank_name)
            raw_val = tank_data.name if tank_data else tank_name
            val = format_telemetry_value(field, raw_val)
        else:
            raw_val = getattr(waypoint, field, None)
            val = format_telemetry_value(field, raw_val)

        if val is None or str(val) == "":
            continue

        # Positioning relative to skin
        rel_x = elem.get("rel_x", 0.0)
        rel_y = elem.get("rel_y", 0.0)
        
        abs_x = int(skin_x + (rel_x * w_scaled))
        abs_y = int(skin_y + (rel_y * h_scaled))
        
        # Get dynamic color
        from utils.hud_rules_engine import get_dynamic_color
        manufacturer = layout.get("manufacturer", "Shearwater")
        model = layout.get("model", "Perdix2")
        default_color = elem.get("color", "#FFFFFF")
        color_hex = get_dynamic_color(manufacturer, model, field, raw_val, default_color).lstrip('#')
        color_rgb = tuple(int(color_hex[i:i+2], 16) for i in (0, 2, 4))

        base_font_size = elem.get("font_size", 16)
        item_scale = elem.get("scale", 1.0)
        
        # Scaling font
        if render_log:
            final_size = int(base_font_size * user_scale * item_scale)
        else:
            final_size = int(base_font_size * user_scale * res_scale * item_scale)
        if final_size < 1: final_size = 1
        
        font = get_font(final_size)
        
        o_dist = max(1, int(final_size / 20))
        for dx, dy in [(-o_dist, -o_dist), (o_dist, -o_dist), (-o_dist, o_dist), (o_dist, o_dist)]:
            draw.text((abs_x + dx, abs_y + dy), str(val), font=font, fill=(0, 0, 0))
            
        draw.text((abs_x, abs_y), str(val), font=font, fill=color_rgb)

    frame[:] = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
