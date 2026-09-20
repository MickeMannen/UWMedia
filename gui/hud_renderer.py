import copy
import cv2
import numpy as np
import math
from datetime import timedelta
from PIL import Image, ImageDraw, ImageFont
import os
from pathlib import Path
import platform

from utils.fonts import fallback_font_path, font_path as _registry_font_path

ALIGN_OPTIONS = ("left", "center", "right")
VALIGN_OPTIONS = ("top", "middle", "bottom")
SMALL_SUFFIX_STYLES = ("seconds", "decimals")
SMALL_SUFFIX_DEFAULT_SCALE = 0.35


def split_small_suffix(val_str, style):
    """(main, suffix) for the schema-v2 `small_suffix` text style - the way
    Garmin draws "00:00" as a large "00" with a small, top-aligned ":00" and
    "12.3" as "12" + ".3". "seconds" splits at the first ":", "decimals" at
    the first "." (the separator stays with the suffix). Anything that
    doesn't split returns (val_str, "")."""
    if not val_str or style not in SMALL_SUFFIX_STYLES:
        return val_str, ""
    sep = ":" if style == "seconds" else "."
    index = val_str.find(sep)
    if index <= 0:
        return val_str, ""
    return val_str[:index], val_str[index:]


def text_parts(field, val_str, elem):
    """(main, suffix, suffix_scale) the renderer draws for a text element:
    the NDL "99+" convention (small, top-aligned plus sign) and the
    `small_suffix` element attribute both resolve here so the renderer and
    the Overlay Designer's bounds agree."""
    if field in ("ndl", "ndl_before_clear") and val_str.endswith("+"):
        return val_str[:-1], "+", SMALL_SUFFIX_DEFAULT_SCALE
    style = elem.get("small_suffix")
    if style:
        main, suffix = split_small_suffix(val_str, style)
        if suffix:
            try:
                scale = float(elem.get("small_suffix_scale", SMALL_SUFFIX_DEFAULT_SCALE))
            except (TypeError, ValueError):
                scale = SMALL_SUFFIX_DEFAULT_SCALE
            return main, suffix, max(0.1, min(1.0, scale))
    return val_str, "", SMALL_SUFFIX_DEFAULT_SCALE


def _get_system_arial_font():
    """Kept for callers that still import it - the platform Arial (or best
    stand-in) the renderer has always defaulted to; see utils/fonts.py."""
    return fallback_font_path()

# Cache for loaded fonts to avoid repeated disk I/O - keyed by (path, size)
# now that a template element may pick a font_family/font_weight
# (overlay_rework.md Phase 2); elements without those attributes resolve to
# the same Arial path as before, so their cache entries and rendering are
# unchanged.
_font_cache = {}

def get_font(size, family=None, weight=None):
    """Retrieves or loads a TrueType font at the specified size, for the
    given registry family/weight (None -> the default Arial)."""
    path = _registry_font_path(family, weight)
    key = (path, size)
    if key not in _font_cache:
        try:
            _font_cache[key] = ImageFont.truetype(path, size)
        except Exception as e:
            try:
                _font_cache[key] = ImageFont.truetype(fallback_font_path(), size)
            except Exception:
                try:
                    _font_cache[key] = ImageFont.truetype("arial.ttf", size)
                except Exception:
                    print(f"Warning: Could not load font {path}: {e}")
                    _font_cache[key] = ImageFont.load_default()
    return _font_cache[key]

def text_anchor_shift(font, text, align="left", valign="top"):
    """(dx, dy, bbox) to add to an element's anchor position so the rendered
    text's *ink box* (font.getbbox) is aligned as requested - right/center
    put the ink's right edge/centre on the anchor, bottom/middle its bottom
    edge/centre; left/top is today's unchanged top-left behaviour. Shared by
    the renderer and the Overlay Designer's hit-testing so both agree."""
    left, top, right, bottom = font.getbbox(text)
    dx = 0.0
    if align == "center":
        dx = -(left + right) / 2.0
    elif align == "right":
        dx = -float(right)
    dy = 0.0
    if valign == "middle":
        dy = -(top + bottom) / 2.0
    elif valign == "bottom":
        dy = -float(bottom)
    return dx, dy, (left, top, right, bottom)

def format_telemetry_value(field, raw_val):
    """Unified formatting for telemetry values."""
    if field == "gasmix":
        return str(raw_val) if raw_val is not None else "N/A"
    elif field.startswith("tank_name:"):
        if raw_val:
            return str(raw_val)
        return field.replace("tank_name:", "")
    elif field in ("primary_tank_pressure", "secondary_tank_pressure") or field.startswith("tank_pressure:"):
        if raw_val is None:
            return "--"
        return str(int(float(raw_val)))
    elif field in ("primary_tank_name", "secondary_tank_name"):
        return str(raw_val) if raw_val else "--"
    elif field in ["ndl", "ndl_before_clear", "air_remaining"] and raw_val is not None:
        val_mins = int(raw_val / 60)
        if field in ("ndl", "ndl_before_clear"):
            if val_mins > 99 or val_mins <= 0:
                return "99+"
            return f"{val_mins:02d}"
        else:
            return str(val_mins)
    elif field in ["dive_time", "tts", "next_stop_time"] and raw_val is not None:
        mins = int(raw_val // 60)
        secs = int(raw_val % 60)
        return f"{mins:02d}:{secs:02d}"
    elif field in ["depth", "max_depth"] and raw_val is not None:
        return f"{raw_val:.1f}"
    elif field == "volume_sac" and raw_val is not None:
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
        'res_scale': res_scale, 'user_scale': user_scale,
        'render_log': render_log
    }
    draw_telemetry_on_frame(frame, layout, waypoint, skin_info, waypoints=waypoints)

def resolve_overlay_instance_layout(layout, x, y, scale, frame_w, frame_h):
    """Pass 2 (Color page multi-overlay) helper: turns one overlay instance's
    continuous frame-relative placement (x, y as 0.0-1.0 fractions of the
    *output frame*, top-left of the skin's bounding box; scale as a
    continuous multiplier) into a layout dict draw_hud() can render
    unchanged, by baking an anchor="TOP_LEFT" + ref_offset_x/y (in design
    pixels) into hud_skin - draw_hud() itself is not modified.

    Derivation (see draw_hud): with anchor=TOP_LEFT, base_x=base_y=pivot_x=
    pivot_y=0, so skin_x = ref_offset_x * res_scale where
    res_scale = frame_w / design_w. Solving skin_x = x * frame_w gives
    ref_offset_x = x * design_w; solving skin_y = y * frame_h (res_scale is
    always frame_w/design_w, even for the y axis) gives
    ref_offset_y = y * frame_h * design_w / frame_w.

    scale bakes in exactly the way _compose_hud_layout_path's own
    HUD_SIZE_PRESETS multiplier already does (uwmedia/app.py): shape skins
    get width/height multiplied, every skin type gets hud_skin["scale"]
    multiplied.
    """
    resolved = copy.deepcopy(layout)
    hud_skin = resolved.setdefault("hud_skin", {})
    design_w = float(resolved.get("design_width", 1920))

    hud_skin["anchor"] = "TOP_LEFT"
    hud_skin["ref_offset_x"] = x * design_w
    hud_skin["ref_offset_y"] = y * frame_h * design_w / frame_w

    if hud_skin.get("type") == "shape":
        hud_skin["width"] = hud_skin.get("width", 400) * scale
        hud_skin["height"] = hud_skin.get("height", 200) * scale
    hud_skin["scale"] = hud_skin.get("scale", 1.0) * scale

    return resolved

def overlay_pixel_bbox(layout, x, y, scale, frame_w, frame_h, preloaded_skin=None):
    """Pass 2 (Color page) helper: the on-frame pixel bounding box
    (x0, y0, x1, y1) an overlay instance would occupy, for GUI hit-testing/
    handle-drawing - mirrors draw_hud()'s own Step 1 (Scaled HUD Dimensions)
    sizing math exactly, without actually rendering anything."""
    hud_skin = layout.get("hud_skin", {})
    design_w = float(layout.get("design_width", 1920))
    res_scale = frame_w / design_w
    skin_type = hud_skin.get("type", "image")
    user_scale = hud_skin.get("scale", 1.0) * scale

    if skin_type == "shape":
        w_hud = int(hud_skin.get("width", 400) * scale * res_scale)
        h_hud = int(hud_skin.get("height", 200) * scale * res_scale)
    elif preloaded_skin is not None:
        h_hud, w_hud = preloaded_skin.shape[:2]
    else:
        skin_path = hud_skin.get("path")
        img_temp = cv2.imread(skin_path, cv2.IMREAD_UNCHANGED) if skin_path else None
        if img_temp is None:
            return (0, 0, 0, 0)
        w_hud = int(img_temp.shape[1] * user_scale * res_scale)
        h_hud = int(img_temp.shape[0] * user_scale * res_scale)

    skin_x = int(x * frame_w)
    skin_y = int(y * frame_h)
    return (skin_x, skin_y, skin_x + w_hud, skin_y + h_hud)

def draw_depth_graph(frame, elem, waypoint, waypoints, skin_info):
    skin_x = skin_info['x']
    skin_y = skin_info['y']
    w_scaled = skin_info['w']
    h_scaled = skin_info['h']
    res_scale = skin_info['res_scale']
    # Every other linked_elements type (text fields via final_size, badges,
    # tank icons) scales its own size by user_scale - the per-instance
    # resize factor from the Color page's drag-resize handles - on top of
    # res_scale. This one never did, so resizing a dive-profile overlay
    # moved fine but visibly did nothing (root-caused after the user
    # reported "can move it around but can't resize it at all").
    user_scale = skin_info.get('user_scale', 1.0)

    rel_x = elem.get("rel_x", 0.0)
    rel_y = elem.get("rel_y", 0.0)

    graph_w = int(elem.get("width", 300) * user_scale * res_scale)
    graph_h = int(elem.get("height", 150) * user_scale * res_scale)

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

    # Map by elapsed dive time, not sample index - real logs aren't always
    # evenly sampled, and this graph always plots the *entire* dive (never
    # just the current video clip's slice of it), so index-spacing would
    # visibly distort the profile whenever the sampling rate varies.
    t0 = waypoints[0].time_since_start
    total_t = waypoints[-1].time_since_start - t0
    if total_t <= 0:
        total_t = 1
    dy = graph_h / max_d

    def x_for_time(t):
        frac = min(1.0, max(0.0, (t - t0) / total_t))
        return abs_x + frac * graph_w

    def y_for_depth(d):
        return int(abs_y + d * dy)

    # Fill path
    fill_overlay = frame.copy()
    pts = []
    pts.append([abs_x, abs_y])
    for i in range(n_wps):
        x = int(x_for_time(waypoints[i].time_since_start))
        y = y_for_depth(waypoints[i].depth)
        pts.append([x, y])
    pts.append([abs_x + graph_w, abs_y])

    pts = np.array(pts, dtype=np.int32)
    cv2.fillPoly(fill_overlay, [pts], color_bgr)
    cv2.addWeighted(fill_overlay, 0.15, frame, 0.85, 0, frame)

    # Deco ceiling - a gray "may not ascend above this" band from the
    # surface down to each waypoint's own deco_stop_depth, revealed only up
    # to the current playback position (not the whole dive at once, unlike
    # the profile line/fill above - see rework_hud.md's dive-profile-graph
    # planning notes). Since every rectangle is derived straight from that
    # waypoint's own logged ceiling value and nothing already drawn is ever
    # erased, a stop's shaded patch is permanent once revealed even after it
    # clears and the diver moves on to a shallower one.
    if waypoint is not None:
        reveal_t = waypoint.time_since_start
        ceiling_hex = elem.get("ceiling_color", "#808080").lstrip('#')
        ceiling_bgr = tuple(int(ceiling_hex[i:i + 2], 16) for i in (4, 2, 0))
        ceiling_overlay = frame.copy()
        any_ceiling = False
        for i in range(n_wps):
            wp_i = waypoints[i]
            if wp_i.time_since_start > reveal_t:
                break
            ceiling = getattr(wp_i, "deco_stop_depth", None)
            if not ceiling or ceiling <= 0:
                continue
            next_t = waypoints[i + 1].time_since_start if i + 1 < n_wps else reveal_t
            seg_end_t = min(next_t, reveal_t)
            x_start = int(x_for_time(wp_i.time_since_start))
            x_end = max(x_start + 1, int(x_for_time(seg_end_t)))
            y_bot = y_for_depth(ceiling)
            cv2.rectangle(ceiling_overlay, (x_start, abs_y), (x_end, y_bot), ceiling_bgr, -1)
            any_ceiling = True
        if any_ceiling:
            cv2.addWeighted(ceiling_overlay, 0.45, frame, 0.55, 0, frame)

    # Outline line
    line_pts = []
    for i in range(n_wps):
        x = int(x_for_time(waypoints[i].time_since_start))
        y = y_for_depth(waypoints[i].depth)
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

        curr_x = int(x_for_time(waypoints[curr_idx].time_since_start))
        curr_y = y_for_depth(waypoints[curr_idx].depth)
        
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

def badge_lines(manufacturer, model, elem, waypoint):
    """The (text, color_rgb, is_value) lines a state badge renders for this
    waypoint - None when nothing is drawn ('normal' state, no badge config,
    no waypoint). Shared by _draw_state_badge and the Overlay Designer's
    hit-testing. See rework_hud.md's "State rendering" section."""
    from utils.hud_rules_engine import resolve_state, get_badge_config, resolve_blink_color

    if waypoint is None:
        return None

    state = resolve_state(manufacturer, model, waypoint)
    if state == "normal":
        return None

    badge = get_badge_config(manufacturer, model, state)
    if not badge:
        return None

    label_color_hex = badge.get("color", "#FFFFFF")
    if badge.get("blink"):
        elapsed = waypoint.dive_time if waypoint.dive_time is not None else waypoint.time_since_start
        label_color_hex = resolve_blink_color(label_color_hex, "#FF0000", elapsed)
    label_rgb = tuple(int(label_color_hex.lstrip('#')[i:i + 2], 16) for i in (0, 2, 4))

    # is_value marks lines that use value_font_size (depth/timer) instead of the
    # label's own font_size - Shearwater's badge shows a small cyan title above a
    # much larger white countdown, unlike Garmin's uniformly-sized 3-line badge.
    lines = [(badge.get("label", state.upper()), label_rgb, False)]

    depth_val = getattr(waypoint, "next_stop_depth", None)
    if depth_val:
        depth_color_hex = label_color_hex
        if badge.get("blink_depth"):
            elapsed = waypoint.dive_time if waypoint.dive_time is not None else waypoint.time_since_start
            depth_color_hex = resolve_blink_color(label_color_hex, "#FF0000", elapsed)
        depth_rgb = tuple(int(depth_color_hex.lstrip('#')[i:i + 2], 16) for i in (0, 2, 4))
        lines.append((f"↑{depth_val:.0f}", depth_rgb, True))

    timer_val = getattr(waypoint, "next_stop_time", None)
    if timer_val is not None:
        mins, secs = divmod(max(0, int(timer_val)), 60)
        lines.append((f"{mins:02d}:{secs:02d}", label_rgb, True))
    return lines

def badge_line_sizes(elem, user_scale, res_scale, render_log):
    """(label_px, value_px) final pixel sizes of a badge's two font tiers."""
    base_font_size = elem.get("font_size", 16)
    base_value_font_size = elem.get("value_font_size", base_font_size)
    item_scale = elem.get("scale", 1.0)

    def _scaled(size):
        raw = size * user_scale * item_scale if render_log else size * user_scale * res_scale * item_scale
        return max(1, int(raw))

    return _scaled(base_font_size), _scaled(base_value_font_size)

def _draw_state_badge(draw, elem, waypoint, manufacturer, model, skin_x, skin_y, w_scaled, h_scaled, res_scale, user_scale, render_log):
    """Renders a compound label + ceiling-depth + countdown-timer badge for the
    waypoint's resolved safety_stop/deco state - see rework_hud.md's "State rendering"
    section. Draws nothing for 'normal' state or when no badge_states config exists."""
    lines = badge_lines(manufacturer, model, elem, waypoint)
    if not lines:
        return

    rel_x = elem.get("rel_x", 0.0)
    rel_y = elem.get("rel_y", 0.0)
    abs_x = int(skin_x + (rel_x * w_scaled))
    abs_y = int(skin_y + (rel_y * h_scaled))

    label_size, value_size = badge_line_sizes(elem, user_scale, res_scale, render_log)
    family, weight = elem.get("font_family"), elem.get("font_weight")
    label_font = get_font(label_size, family, weight)
    value_font = get_font(value_size, family, weight)
    outline = elem.get("outline", True)
    align = elem.get("align", "left")
    valign = elem.get("valign", "top")

    y = abs_y
    if valign != "top":
        block_h = sum(int((value_size if is_value else label_size) * 1.2) for _, _, is_value in lines)
        y -= block_h if valign == "bottom" else block_h // 2
    for text, color_rgb, is_value in lines:
        font = value_font if is_value else label_font
        final_size = value_size if is_value else label_size
        x = abs_x
        if align != "left":
            dx, _, _ = text_anchor_shift(font, text, align, "top")
            x = int(round(abs_x + dx))
        o_dist = max(1, int(final_size / 20))
        if outline:
            for dx, dy in [(-o_dist, -o_dist), (o_dist, -o_dist), (-o_dist, o_dist), (o_dist, o_dist)]:
                draw.text((x + dx, y + dy), text, font=font, fill=(0, 0, 0))
        draw.text((x, y), text, font=font, fill=color_rgb)
        y += int(final_size * 1.2)

TANK_OUTLINE_DEFAULT_WIDTH = 2
TANK_OUTLINE_DEFAULT_GAP = 4
TANK_OUTLINE_DEFAULT_COLOR = "#FFFFFF"


def tank_outline_metrics(elem):
    """(gap, stroke, cap_height) in native px for a tank icon's optional
    drawn outline (schema v2 `draw_outline`), or None when it draws none.
    The outline is a rounded rectangle `gap` px outside the fill rectangle
    with a `stroke`-wide line, plus a small centred cap on top - the shape
    Garmin bakes into its own screens."""
    if not elem.get("draw_outline"):
        return None
    try:
        gap = max(0, int(round(float(elem.get("outline_gap", TANK_OUTLINE_DEFAULT_GAP)))))
        stroke = max(1, int(round(float(elem.get("outline_width", TANK_OUTLINE_DEFAULT_WIDTH)))))
    except (TypeError, ValueError):
        gap, stroke = TANK_OUTLINE_DEFAULT_GAP, TANK_OUTLINE_DEFAULT_WIDTH
    cap_h = max(2, gap + stroke)
    return gap, stroke, cap_h


TISSUE_BAR_MAX_PERCENT = 120.0
TISSUE_BAR_DEFAULT_BANDS = [
    {"max": 80, "color": "#00FF00"},
    {"min": 80, "max": 100, "color": "#FFC000"},
    {"min": 100, "color": "#FF0000"},
]


def tissue_bar_geometry(elem):
    """(width, height, marker_radius) in native px for a tissue-load bar."""
    w = max(2, int(round(float(elem.get("width", 12)))))
    h = max(4, int(round(float(elem.get("height", 33)))))
    r = max(1, int(round(float(elem.get("marker_size", 4)))))
    return w, h, r


def tissue_bar_marker_fraction(value):
    """0.0 (bottom) .. 1.0 (top) position of the marker for a tissue load in
    percent - linear up to TISSUE_BAR_MAX_PERCENT, clamped. None -> 0."""
    if value is None:
        return 0.0
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, v / TISSUE_BAR_MAX_PERCENT))


def _draw_tissue_bar(draw, elem, waypoint, manufacturer, model, skin_x, skin_y, w_scaled, h_scaled, res_scale, user_scale, render_log):
    """Garmin-style vertical tissue-load bar (schema v2 element type
    "tissue_bar", field n2_tissue_load): three stacked segments coloured by
    hud_rules.json's `tissue_load` bands (green 0-80 %, yellow 80-100 %, red
    100-120 % of the bar height, small gaps between), plus a white marker dot
    at the bar's left edge at the current load. Drawn even without a value
    (marker at the bottom), like the real device."""
    from utils.hud_rules_engine import get_rule_config

    rel_x = elem.get("rel_x", 0.0)
    rel_y = elem.get("rel_y", 0.0)
    abs_x = int(skin_x + (rel_x * w_scaled))
    abs_y = int(skin_y + (rel_y * h_scaled))
    scale = user_scale if render_log else user_scale * res_scale
    w, h, r = tissue_bar_geometry(elem)
    w_px, h_px = max(2, int(round(w * scale))), max(4, int(round(h * scale)))
    r_px = max(1, int(round(r * scale)))
    gap_px = max(1, int(round(1.5 * scale)))

    bands = get_rule_config(manufacturer, model, "tissue_load")
    if not isinstance(bands, list) or len(bands) < 3:
        bands = TISSUE_BAR_DEFAULT_BANDS
    colors = []
    for band in bands[:3]:
        hex_color = str(band.get("color", "#FFFFFF")).lstrip('#')
        colors.append(tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4)))

    value = getattr(waypoint, elem.get("field", "n2_tissue_load"), None) if waypoint is not None else None
    fraction = tissue_bar_marker_fraction(value)
    bottom = abs_y + h_px

    if elem.get("style") == "fill":
        # Shearwater-style: an outlined frame that fills from the bottom in
        # the band colour of the current value (no marker).
        frame_hex = str(elem.get("outline_color", "#00ADED")).lstrip('#')
        frame_rgb = tuple(int(frame_hex[i:i + 2], 16) for i in (0, 2, 4))
        stroke = max(1, int(round(2 * scale)))
        radius = max(1, int(round(3 * scale)))
        fill_color = colors[0]
        try:
            v = float(value) if value is not None else 0.0
        except (TypeError, ValueError):
            v = 0.0
        for band, color in zip(bands[:3], colors):
            if "min" in band and v < band["min"]:
                continue
            if "max" in band and v >= band["max"]:
                continue
            fill_color = color
            break
        # black interior first (the device's bar sits on its black screen and
        # the icon covers whatever is behind it), then the fill, then the frame
        draw.rounded_rectangle([abs_x, abs_y, abs_x + w_px, bottom], radius=radius, fill=(0, 0, 0))
        fill_h = int(round((h_px - 2 * stroke) * fraction))
        if fill_h > 0:
            draw.rectangle([abs_x + stroke, bottom - stroke - fill_h, abs_x + w_px - stroke, bottom - stroke], fill=fill_color)
        draw.rounded_rectangle([abs_x, abs_y, abs_x + w_px, bottom], radius=radius, outline=frame_rgb, width=stroke)
        return

    # Segment heights follow the percent ranges 0-80 / 80-100 / 100-120.
    fractions = (80.0 / TISSUE_BAR_MAX_PERCENT, 20.0 / TISSUE_BAR_MAX_PERCENT, 20.0 / TISSUE_BAR_MAX_PERCENT)
    cursor = bottom
    for frac, color in zip(fractions, colors):
        seg_h = max(1, int(round(h_px * frac)))
        top = cursor - seg_h
        draw.rectangle([abs_x, top + (gap_px if cursor != bottom else 0), abs_x + w_px, cursor], fill=color)
        cursor = top

    marker_y = bottom - int(round(fraction * h_px))
    marker_y = max(abs_y + r_px, min(bottom, marker_y))
    cx = abs_x
    draw.ellipse([cx - r_px, marker_y - r_px, cx + r_px, marker_y + r_px], fill=(255, 255, 255), outline=(0, 0, 0))


ASCENT_FULL_SCALE_M_PER_MIN = 12.0
ASCENT_DEADBAND_M_PER_MIN = 0.5
ASCENT_DEFAULT_BANDS = [
    {"max": 7.9, "color": "#00FF00"},
    {"min": 7.9, "max": 10.1, "color": "#FFC000"},
    {"min": 10.1, "color": "#FF0000"},
]
CHEVRON_UNLIT = (138, 138, 138)


def ascent_rate_for(waypoint, waypoints=None):
    """Ascent rate in m/min, positive when getting shallower. Uses the
    waypoint's own logged value when present (Garmin), else derives it from
    the previous waypoint's depth in `waypoints` (Shearwater/UDDF/Subsurface
    carry no rate). None when it can't be determined."""
    if waypoint is None:
        return None
    rate = getattr(waypoint, "ascent_rate", None)
    if rate is not None:
        return float(rate)
    if not waypoints or waypoint.depth is None:
        return None
    t = waypoint.time_since_start
    prev = None
    for wp in waypoints:
        if wp.time_since_start >= t:
            break
        prev = wp
    if prev is None or prev.depth is None:
        return None
    dt = t - prev.time_since_start
    if dt <= 0:
        return None
    return (prev.depth - waypoint.depth) / dt * 60.0


def ascent_chevron_geometry(elem):
    """(width, height, up_count, down_count) in native px / counts."""
    w = max(4, int(round(float(elem.get("width", 16)))))
    h = max(8, int(round(float(elem.get("height", 47)))))
    up = max(0, int(elem.get("up_count", 4)))
    down = max(0, int(elem.get("down_count", 1)))
    if up + down == 0:
        up = 1
    return w, h, up, down


def ascent_lit_count(rate, up_count):
    """How many upward chevrons light for `rate` m/min (0 when level or
    descending): one at the deadband, then linearly to all at full scale."""
    if rate is None or rate < ASCENT_DEADBAND_M_PER_MIN or up_count <= 0:
        return 0
    return max(1, min(up_count, int(rate / ASCENT_FULL_SCALE_M_PER_MIN * up_count) + 1))


def _draw_ascent_chevrons(draw, elem, waypoint, waypoints, manufacturer, model, skin_x, skin_y, w_scaled, h_scaled, res_scale, user_scale, render_log):
    """Garmin-style ascent-rate indicator (schema v2 element type
    "ascent_chevrons"): `up_count` upward chevrons stacked above a white bar
    and `down_count` downward chevrons below it. Unlit chevrons are grey; on
    ascent 1..up_count chevrons light in the hud_rules.json `ascent_rate`
    band colour for the current rate, on descent the downward chevrons light
    white. Always drawn (all grey when level or without data)."""
    from utils.hud_rules_engine import get_rule_config

    rel_x = elem.get("rel_x", 0.0)
    rel_y = elem.get("rel_y", 0.0)
    abs_x = int(skin_x + (rel_x * w_scaled))
    abs_y = int(skin_y + (rel_y * h_scaled))
    scale = user_scale if render_log else user_scale * res_scale
    w, h, up, down = ascent_chevron_geometry(elem)
    w_px = max(4, int(round(w * scale)))
    h_px = max(8, int(round(h * scale)))
    bar_h = max(2, int(round(h_px * 0.10)))
    gap = max(1, int(round(1.0 * scale)))
    n = up + down
    chev_h = max(3, int((h_px - bar_h - gap * (n + 1)) / n)) if n else 0
    arrow = max(1, int(round(w_px * 0.45)))          # apex depth of the "^"
    band_t = max(1, chev_h - arrow)                   # band thickness

    rate = ascent_rate_for(waypoint, waypoints)
    lit_up = ascent_lit_count(rate, up)
    lit_down = 1 if (rate is not None and rate <= -ASCENT_DEADBAND_M_PER_MIN and down > 0) else 0

    bands = get_rule_config(manufacturer, model, "ascent_rate")
    if not isinstance(bands, list):
        bands = ASCENT_DEFAULT_BANDS
    lit_color = CHEVRON_UNLIT
    if lit_up:
        for band in bands:
            if "min" in band and rate < band["min"]:
                continue
            if "max" in band and rate >= band["max"]:
                continue
            hex_color = str(band.get("color", "#00FF00")).lstrip('#')
            lit_color = tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
            break

    def chevron(top, pointing_up, color):
        x0, x1, xm = abs_x, abs_x + w_px, abs_x + w_px / 2.0
        if pointing_up:
            pts = [(x0, top + arrow), (xm, top), (x1, top + arrow), (x1, top + arrow + band_t), (xm, top + band_t), (x0, top + arrow + band_t)]
        else:
            bottom = top + arrow + band_t
            pts = [(x0, bottom - arrow), (xm, bottom), (x1, bottom - arrow), (x1, bottom - arrow - band_t), (xm, bottom - band_t), (x0, bottom - arrow - band_t)]
        draw.polygon(pts, fill=color)

    y = abs_y
    # upward chevrons: the lit ones are the lowest (closest to the bar), like the device
    for i in range(up):
        index_from_bar = up - 1 - i
        chevron(y, True, lit_color if index_from_bar < lit_up else CHEVRON_UNLIT)
        y += chev_h + gap
    draw.rectangle([abs_x, y, abs_x + w_px, y + bar_h], fill=(255, 255, 255))
    y += bar_h + gap
    for i in range(down):
        chevron(y, False, (255, 255, 255) if i < lit_down else CHEVRON_UNLIT)
        y += chev_h + gap


TANK_SEGMENTS_DEFAULT = 5
TANK_SEGMENT_GAP_DEFAULT = 2
TANK_FULL_BAR_DEFAULT = 200.0
TANK_SEGMENT_UNLIT = (58, 58, 58)
TANK_SEGMENT_OUTLINE_DEFAULT = "#9A9A9A"


def tank_segments_geometry(elem):
    """(segments, gap, full_bar, pad, stroke, nose, nub) in native px for a
    tank icon in the "segments" style (Shearwater's horizontal cylinder with
    N pressure slots, a rounded shoulder and a valve nub on the right)."""
    n = max(1, int(elem.get("segments", TANK_SEGMENTS_DEFAULT)))
    gap = max(0, int(round(float(elem.get("segment_gap", TANK_SEGMENT_GAP_DEFAULT)))))
    try:
        full_bar = max(1.0, float(elem.get("full_bar", TANK_FULL_BAR_DEFAULT)))
    except (TypeError, ValueError):
        full_bar = TANK_FULL_BAR_DEFAULT
    pad = max(0, int(round(float(elem.get("outline_gap", 3)))))
    stroke = max(1, int(round(float(elem.get("outline_width", 2)))))
    h = max(1, int(elem.get("height", 30)))
    nose = max(2, int(round(h * 0.45)))
    nub = max(2, int(round(h * 0.18)))
    return n, gap, full_bar, pad, stroke, nose, nub


def tank_segments_lit(pressure, full_bar, segments):
    """How many of `segments` light for `pressure` bar (None -> 0)."""
    if pressure is None:
        return 0
    try:
        frac = float(pressure) / full_bar
    except (TypeError, ValueError):
        return 0
    if frac <= 0:
        return 0
    return max(1, min(segments, int(frac * segments + 0.5)))  # round half up (2.5 -> 3)


def _draw_tank_segments(draw, elem, raw_val, fill_hex, abs_x, abs_y, scale):
    n, gap, full_bar, pad, stroke, nose, nub = tank_segments_geometry(elem)
    seg_w = max(1, int(round(int(elem.get("width", 12)) * scale)))
    seg_h = max(1, int(round(int(elem.get("height", 23)) * scale)))
    gap_px = int(round(gap * scale))
    pad_px = int(round(pad * scale))
    stroke_px = max(1, int(round(stroke * scale)))
    nose_px = max(2, int(round(nose * scale)))
    nub_px = max(2, int(round(nub * scale)))
    radius = max(1, int(round(int(elem.get("corner_radius", 2)) * scale)))
    total_w = n * seg_w + (n - 1) * gap_px

    outline_hex = str(elem.get("outline_color", TANK_SEGMENT_OUTLINE_DEFAULT)).lstrip('#')
    outline_rgb = tuple(int(outline_hex[i:i + 2], 16) for i in (0, 2, 4))
    x0, y0 = abs_x - pad_px - stroke_px, abs_y - pad_px - stroke_px
    x1, y1 = abs_x + total_w + pad_px + stroke_px, abs_y + seg_h + pad_px + stroke_px
    body_h = y1 - y0
    # body with a rounded shoulder on the right: rectangle + half ellipse
    draw.rounded_rectangle([x0, y0, x1, y1], radius=max(1, radius + pad_px), outline=outline_rgb, width=stroke_px)
    draw.pieslice([x1 - nose_px, y0, x1 + nose_px, y1], start=270, end=90, fill=(0, 0, 0), outline=outline_rgb, width=stroke_px)
    # re-cover the seam where the shoulder meets the body
    draw.rectangle([x1 - stroke_px, y0 + stroke_px, x1 + stroke_px, y1 - stroke_px], fill=(0, 0, 0))
    draw.line([(x1 - stroke_px, y0), (x1, y0)], fill=outline_rgb, width=stroke_px)
    draw.line([(x1 - stroke_px, y1), (x1, y1)], fill=outline_rgb, width=stroke_px)
    # valve nub
    nub_h = max(2, int(round(body_h * 0.3)))
    cy = (y0 + y1) // 2
    draw.rectangle([x1 + nose_px - 1, cy - nub_h // 2, x1 + nose_px + nub_px, cy + nub_h // 2], fill=outline_rgb)

    lit = tank_segments_lit(raw_val, full_bar, n)
    fill_rgb = tuple(int(fill_hex.lstrip('#')[i:i + 2], 16) for i in (0, 2, 4)) if fill_hex else TANK_SEGMENT_UNLIT
    for i in range(n):
        sx = abs_x + i * (seg_w + gap_px)
        draw.rounded_rectangle([sx, abs_y, sx + seg_w, abs_y + seg_h], radius=radius,
                               fill=fill_rgb if i < lit else TANK_SEGMENT_UNLIT)


def _draw_tank_fill(draw, elem, waypoint, manufacturer, model, skin_x, skin_y, w_scaled, h_scaled, res_scale, user_scale, render_log):
    """Tank-pressure icon: an optional drawn outline (rounded rectangle + cap,
    schema v2 `draw_outline`/`outline_color`/`outline_width`/`outline_gap` -
    for skins whose image carries no outline of its own) and the solid status
    fill (red/yellow/green - see hud_rules_engine.get_tank_fill_color).
    rel_x/rel_y/width/height define the fill rectangle; when the skin image
    has a baked outline the fill is sized to land just inside it. The fill is
    skipped when the tank has no pressure reading yet; the outline is not."""
    from utils.hud_rules_engine import get_tank_fill_color

    rel_x = elem.get("rel_x", 0.0)
    rel_y = elem.get("rel_y", 0.0)
    abs_x = int(skin_x + (rel_x * w_scaled))
    abs_y = int(skin_y + (rel_y * h_scaled))

    scale = user_scale if render_log else user_scale * res_scale
    w = max(1, int(elem.get("width", 20) * scale))
    h = max(1, int(elem.get("height", 30) * scale))
    radius = max(1, int(elem.get("corner_radius", 4) * scale))

    if elem.get("style") == "segments":
        # Shearwater-style horizontal segmented gauge (draws its own outline).
        from utils.hud_rules_engine import get_tank_fill_color as _fill_color
        raw_val = None
        if waypoint is not None:
            field = elem.get("field", "primary_tank_pressure")
            if field.startswith("tank_pressure:"):
                tank_data = waypoint.tanks.get(field.replace("tank_pressure:", ""))
                raw_val = tank_data.pressure_bar if tank_data else None
            else:
                raw_val = getattr(waypoint, field, None)
        _draw_tank_segments(draw, elem, raw_val, _fill_color(manufacturer, model, raw_val), abs_x, abs_y, scale)
        return

    metrics = tank_outline_metrics(elem)
    if metrics is not None:
        gap, stroke, cap_h = metrics
        gap_px = int(round(gap * scale))
        stroke_px = max(1, int(round(stroke * scale)))
        cap_px = max(1, int(round(cap_h * scale)))
        color_hex = elem.get("outline_color", TANK_OUTLINE_DEFAULT_COLOR)
        outline_rgb = tuple(int(color_hex.lstrip('#')[i:i + 2], 16) for i in (0, 2, 4))
        ox0, oy0 = abs_x - gap_px - stroke_px, abs_y - gap_px - stroke_px
        ox1, oy1 = abs_x + w + gap_px + stroke_px, abs_y + h + gap_px + stroke_px
        outer_radius = max(1, radius + gap_px + stroke_px)
        draw.rounded_rectangle([ox0, oy0, ox1, oy1], radius=outer_radius, outline=outline_rgb, width=stroke_px)
        cap_w = max(2, int(round((ox1 - ox0) * 0.45)))
        cx = (ox0 + ox1) // 2
        draw.rounded_rectangle(
            [cx - cap_w // 2, oy0 - cap_px + stroke_px, cx + cap_w // 2, oy0 + stroke_px],
            radius=max(1, cap_px // 2), outline=outline_rgb, width=stroke_px,
        )

    if waypoint is None:
        return

    field = elem.get("field", "primary_tank_pressure")
    if field.startswith("tank_pressure:"):
        tank_name = field.replace("tank_pressure:", "")
        tank_data = waypoint.tanks.get(tank_name)
        raw_val = tank_data.pressure_bar if tank_data else None
    else:
        raw_val = getattr(waypoint, field, None)

    color_hex = get_tank_fill_color(manufacturer, model, raw_val)
    if not color_hex:
        return
    color_rgb = tuple(int(color_hex.lstrip('#')[i:i + 2], 16) for i in (0, 2, 4))

    draw.rounded_rectangle([abs_x, abs_y, abs_x + w, abs_y + h], radius=radius, fill=color_rgb)

def rules_manufacturer(layout):
    """The hud_rules.json manufacturer key a layout's colour/warning rules
    come from: `rules_profile` when set (overlay_rework.md schema v2 - a
    custom template borrowing a brand's scheme), else `manufacturer`."""
    return layout.get("rules_profile") or layout.get("manufacturer", "Shearwater")

def resolve_element_text(layout, field, waypoint, waypoints=None):
    """(display string, raw value) for one text element's field - the exact
    chain draw_telemetry_on_frame() renders with, factored out so the
    Overlay Designer measures the same string it draws. Tolerates a None
    waypoint (every branch then yields "--"/None)."""
    manufacturer = rules_manufacturer(layout)
    model = layout.get("model", "Perdix2")
    if field == "safety_stop":
        from utils.hud_rules_engine import get_safety_stop_text
        return get_safety_stop_text(manufacturer, model, waypoint), None
    if field == "time_of_day":
        val = waypoint.timestamp.strftime("%H:%M") if waypoint is not None and waypoint.timestamp else None
        return val, None
    if field == "ndl_before_clear":
        from utils.hud_rules_engine import get_ndl_before_clear
        raw_val = get_ndl_before_clear(manufacturer, model, waypoint, waypoints)
        return format_telemetry_value(field, raw_val), raw_val
    if field.startswith("custom:"):
        return field.replace("custom:", ""), None
    if field.startswith("tank_pressure:"):
        tank_name = field.replace("tank_pressure:", "")
        tank_data = waypoint.tanks.get(tank_name) if waypoint is not None else None
        raw_val = tank_data.pressure_bar if tank_data else None
        return format_telemetry_value(field, raw_val), raw_val
    if field.startswith("tank_name:"):
        tank_name = field.replace("tank_name:", "")
        tank_data = waypoint.tanks.get(tank_name) if waypoint is not None else None
        raw_val = tank_data.name if tank_data else tank_name
        return format_telemetry_value(field, raw_val), raw_val
    raw_val = getattr(waypoint, field, None)
    return format_telemetry_value(field, raw_val), raw_val

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

        if elem.get("type") == "badge":
            manufacturer = rules_manufacturer(layout)
            model = layout.get("model", "Perdix2")
            _draw_state_badge(draw, elem, waypoint, manufacturer, model, skin_x, skin_y, w_scaled, h_scaled, res_scale, user_scale, render_log)
            continue

        if elem.get("type") == "tank_icon":
            manufacturer = rules_manufacturer(layout)
            model = layout.get("model", "Perdix2")
            _draw_tank_fill(draw, elem, waypoint, manufacturer, model, skin_x, skin_y, w_scaled, h_scaled, res_scale, user_scale, render_log)
            continue

        if elem.get("type") == "tissue_bar":
            manufacturer = rules_manufacturer(layout)
            model = layout.get("model", "Perdix2")
            _draw_tissue_bar(draw, elem, waypoint, manufacturer, model, skin_x, skin_y, w_scaled, h_scaled, res_scale, user_scale, render_log)
            continue

        if elem.get("type") == "ascent_chevrons":
            manufacturer = rules_manufacturer(layout)
            model = layout.get("model", "Perdix2")
            _draw_ascent_chevrons(draw, elem, waypoint, waypoints, manufacturer, model, skin_x, skin_y, w_scaled, h_scaled, res_scale, user_scale, render_log)
            continue

        val, raw_val = resolve_element_text(layout, field, waypoint, waypoints)

        if val is None or str(val) == "":
            continue

        # Positioning relative to skin
        rel_x = elem.get("rel_x", 0.0)
        rel_y = elem.get("rel_y", 0.0)
        
        abs_x = int(skin_x + (rel_x * w_scaled))
        abs_y = int(skin_y + (rel_y * h_scaled))
        
        # Get dynamic color
        from utils.hud_rules_engine import get_dynamic_color
        manufacturer = rules_manufacturer(layout)
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
        
        font = get_font(final_size, elem.get("font_family"), elem.get("font_weight"))
        outline = elem.get("outline", True)

        val_str = str(val)
        main_str, suffix_str, suffix_scale = text_parts(field, val_str, elem)
        suffix_font = None
        if suffix_str:
            suffix_size = max(1, round(final_size * suffix_scale))
            suffix_font = get_font(suffix_size, elem.get("font_family"), elem.get("font_weight"))
        # Alignment (overlay_rework.md schema v2) - only measured when an
        # element asks for it, so default templates render exactly as before.
        align = elem.get("align", "left")
        valign = elem.get("valign", "top")
        if align != "left" or valign != "top":
            dx, dy, (left, top, right, bottom) = text_anchor_shift(font, main_str, align, valign)
            if suffix_font is not None:
                # the whole main+suffix run is what gets aligned horizontally
                total_right = right + draw.textlength(suffix_str, font=suffix_font)
                if align == "center":
                    dx = -(left + total_right) / 2.0
                elif align == "right":
                    dx = -float(total_right)
            abs_x = int(round(abs_x + dx))
            abs_y = int(round(abs_y + dy))
        if suffix_font is not None:
            # Real devices (Garmin) draw the NDL "+" and the seconds / decimal
            # part as a small mark top-aligned with the main digits - not
            # full-size and vertically centered the way a single draw.text()
            # call would render it.
            o_dist = max(1, int(final_size / 20))
            if outline:
                for dx, dy in [(-o_dist, -o_dist), (o_dist, -o_dist), (-o_dist, o_dist), (o_dist, o_dist)]:
                    draw.text((abs_x + dx, abs_y + dy), main_str, font=font, fill=(0, 0, 0))
            draw.text((abs_x, abs_y), main_str, font=font, fill=color_rgb)

            suffix_x = abs_x + draw.textlength(main_str, font=font)
            suffix_y = abs_y
            if elem.get("small_suffix"):
                # Align the suffix's ink top with the main digits' ink top
                # (PIL's text origin is the line top, so a smaller font's
                # glyphs would otherwise sit higher than the big ones). The
                # NDL "+" keeps its legacy raised look.
                suffix_y = abs_y + (font.getbbox(main_str)[1] - suffix_font.getbbox(suffix_str)[1])
            suffix_o = max(1, int(suffix_font.size / 20))
            if outline:
                for dx, dy in [(-suffix_o, -suffix_o), (suffix_o, -suffix_o), (-suffix_o, suffix_o), (suffix_o, suffix_o)]:
                    draw.text((suffix_x + dx, suffix_y + dy), suffix_str, font=suffix_font, fill=(0, 0, 0))
            draw.text((suffix_x, suffix_y), suffix_str, font=suffix_font, fill=color_rgb)
            continue

        o_dist = max(1, int(final_size / 20))
        if outline:
            for dx, dy in [(-o_dist, -o_dist), (o_dist, -o_dist), (-o_dist, o_dist), (o_dist, o_dist)]:
                draw.text((abs_x + dx, abs_y + dy), val_str, font=font, fill=(0, 0, 0))

        draw.text((abs_x, abs_y), val_str, font=font, fill=color_rgb)

    frame[:] = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
