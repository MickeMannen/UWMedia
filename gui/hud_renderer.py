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
# Text element `orientation` (schema v2): "horizontal" (default, absent),
# "stacked" (upright letters one under the other), "up" (the line turned
# 90° to read bottom-to-top) or "down" (turned to read top-to-bottom).
TEXT_ORIENTATIONS = ("horizontal", "stacked", "up", "down")
VERTICAL_ORIENTATIONS = ("stacked", "up", "down")
STACKED_LINE_ADVANCE = 1.05  # of the font size, per stacked letter
# Depth graph shading (schema v2 element keys, 2026-09-27 per the user - the
# fixed tints read far too strong once composited onto footage):
#   fill_color / fill_opacity        the area under the profile line
#   stops_opacity                    the deco-stop steps (Deco stops mode)
#   ceiling_opacity                  the ceiling area - the smooth one in Deco
#                                    stops mode, else the plain stop band
#   background_color / background_opacity   the graph's box (and its 1 px
#                                    border in the line colour); 0 hides it
GRAPH_BACKGROUND_OPACITY = 0.4
GRAPH_FILL_OPACITY = 0.15
GRAPH_STOPS_OPACITY = 0.5
GRAPH_CEILING_OPACITY = 0.4
GRAPH_BAND_OPACITY = 0.45


def graph_opacity(elem, key, default):
    """A graph element's 0..1 shading opacity for `key`, else `default`."""
    try:
        return max(0.0, min(1.0, float(elem.get(key, default))))
    except (TypeError, ValueError):
        return default


def oriented_text_geometry(font, text, orientation, size, align="left", valign="top"):
    """(dx, dy, w, h) of a vertical text element's ink box relative to its
    anchor - the box the renderer paints and the Overlay Designer hit-tests.
    "stacked": one letter per line, each centred in a column as wide as the
    widest letter; "up"/"down": the horizontal ink box turned on its side.
    align/valign move the box onto the anchor the way text_anchor_shift()
    does for a horizontal line."""
    if orientation == "stacked":
        letters = list(text)
        boxes = [font.getbbox(ch) for ch in letters]
        w = max((r - l for l, _, r, _ in boxes), default=0)
        h = int(size * STACKED_LINE_ADVANCE) * len(letters)
    else:
        left, top, right, bottom = font.getbbox(text)
        w, h = bottom - top, right - left  # turned on its side
    dx = -w / 2.0 if align == "center" else -float(w) if align == "right" else 0.0
    dy = -h / 2.0 if valign == "middle" else -float(h) if valign == "bottom" else 0.0
    return dx, dy, w, h


def draw_oriented_text(pil_img, draw, text, font, orientation, x, y, align, valign, color_rgb, outline, size):
    """Paint a vertical text element (see oriented_text_geometry) at anchor
    (x, y). Stacked letters are drawn one per line; a turned line is
    rendered flat onto a transparent tile, rotated and alpha-pasted."""
    dx, dy, w, h = oriented_text_geometry(font, text, orientation, size, align, valign)
    x0, y0 = int(round(x + dx)), int(round(y + dy))
    o_dist = max(1, int(size / 20))
    offsets = [(-o_dist, -o_dist), (o_dist, -o_dist), (-o_dist, o_dist), (o_dist, o_dist)] if outline else []
    if orientation == "stacked":
        advance = int(size * STACKED_LINE_ADVANCE)
        for index, ch in enumerate(text):
            left, top, right, _ = font.getbbox(ch)
            cx = x0 + (w - (right - left)) / 2.0 - left  # centre the letter in the column
            cy = y0 + index * advance - top  # ink top on the line top
            for ox, oy in offsets:
                draw.text((cx + ox, cy + oy), ch, font=font, fill=(0, 0, 0))
            draw.text((cx, cy), ch, font=font, fill=color_rgb)
        return
    left, top, right, bottom = font.getbbox(text)
    margin = o_dist + 1
    tile = Image.new("RGBA", (right - left + 2 * margin, bottom - top + 2 * margin), (0, 0, 0, 0))
    tile_draw = ImageDraw.Draw(tile)
    tx, ty = margin - left, margin - top
    for ox, oy in offsets:
        tile_draw.text((tx + ox, ty + oy), text, font=font, fill=(0, 0, 0, 255))
    tile_draw.text((tx, ty), text, font=font, fill=(*color_rgb, 255))
    tile = tile.rotate(90 if orientation == "up" else -90, expand=True)
    pil_img.paste(tile, (x0 - margin, y0 - margin), tile)


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
    elif field == "pressure_sac":
        # A Perdix shows "wait" until it has two minutes of data (manual p.41).
        return "wait" if raw_val is None else f"{float(raw_val):.1f}"
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

def _hex_to_bgr(hex_color):
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i + 2], 16) for i in (4, 2, 0))


def stop_depth_of(waypoint):
    """The deco stop a waypoint is logged at, on 3 m levels - the logged
    next stop, else the stop depth rounded up to a level. 0 out of deco."""
    depth = getattr(waypoint, "next_stop_depth", None) or 0.0
    if depth <= 0:
        logged = getattr(waypoint, "deco_stop_depth", None) or 0.0
        depth = math.ceil(logged / 3.0 - 1e-9) * 3.0 if logged > 0 else 0.0
    return depth


def graph_stop_label(waypoint):
    """(text, in_deco) for a graph's stop label - 'STOP 6m 2:00' while a
    stop is pending, else None: out of deco the label shows nothing (it used
    to fall back to 'NDL 12'; dropped 2026-09-27 per the user - the Generic
    Dive Profile Deco overlay is about the stops, not a second NDL readout)."""
    if waypoint is None:
        return None
    stop = stop_depth_of(waypoint)
    if stop > 0:
        seconds = getattr(waypoint, "next_stop_time", None)
        return f"STOP {stop:g}m" + (f" {seconds // 60}:{seconds % 60:02d}" if seconds else ""), True
    return None


def _graph_geometry(elem, waypoints, skin_info):
    """Where a graph element sits and how it maps (time, depth) to frame
    pixels - shared by draw_depth_graph and its stop label, which is drawn
    in the later PIL text pass. None with fewer than two waypoints."""
    if not waypoints or len(waypoints) < 2:
        return None
    user_scale = skin_info.get('user_scale', 1.0)
    res_scale = skin_info['res_scale']
    graph_w = int(elem.get("width", 300) * user_scale * res_scale)
    graph_h = int(elem.get("height", 150) * user_scale * res_scale)
    abs_x = int(skin_info['x'] + (elem.get("rel_x", 0.0) * skin_info['w']))
    abs_y = int(skin_info['y'] + (elem.get("rel_y", 0.0) * skin_info['h']))
    max_d = max((wp.depth or 0.0) for wp in waypoints)
    max_d = (max_d if max_d > 0 else 1.0) * 1.1
    t0 = waypoints[0].time_since_start
    total_t = (waypoints[-1].time_since_start - t0) or 1

    def x_for_time(t):
        return abs_x + min(1.0, max(0.0, (t - t0) / total_t)) * graph_w

    def y_for_depth(d):
        return int(abs_y + d * graph_h / max_d)

    return abs_x, abs_y, graph_w, graph_h, x_for_time, y_for_depth


def draw_graph_stop_label(draw, elem, waypoint, waypoints, skin_info):
    """A graph's optional stop_label: the current stop (or NDL) as text next
    to the playback cursor, in the stops colour while in deco."""
    geometry = _graph_geometry(elem, waypoints, skin_info)
    label = graph_stop_label(waypoint)
    if geometry is None or label is None:
        return
    abs_x, abs_y, graph_w, graph_h, x_for_time, y_for_depth = geometry
    text, in_deco = label
    scale = skin_info['res_scale'] * skin_info.get('user_scale', 1.0)
    font = get_font(max(1, int(elem.get("font_size", 16) * scale)), elem.get("font_family"), elem.get("font_weight"))
    color = elem.get("stops_color") if in_deco and elem.get("stops_color") else elem.get("color", "#00FF00")
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    pad = int(6 * scale)
    x = x_for_time(waypoint.time_since_start) + pad
    if x + (right - left) > abs_x + graph_w:  # flip to the cursor's left near the end
        x = x_for_time(waypoint.time_since_start) - pad - (right - left)
    y = min(max(abs_y, y_for_depth(waypoint.depth or 0.0) - (bottom - top) - pad), abs_y + graph_h - (bottom - top))
    draw.text((x - left, y - top), text, font=font, fill=color,
              stroke_width=max(1, int(2 * scale)), stroke_fill="#000000")


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

    # Background box + border, in background_color at background_opacity
    background_opacity = graph_opacity(elem, "background_opacity", GRAPH_BACKGROUND_OPACITY)
    if background_opacity > 0:
        overlay = frame.copy()
        background_bgr = _hex_to_bgr(elem["background_color"]) if elem.get("background_color") else (0, 0, 0)
        cv2.rectangle(overlay, (abs_x, abs_y), (abs_x + graph_w, abs_y + graph_h), background_bgr, -1)
        cv2.rectangle(overlay, (abs_x, abs_y), (abs_x + graph_w, abs_y + graph_h), color_bgr, 1)
        cv2.addWeighted(overlay, background_opacity, frame, 1 - background_opacity, 0, frame)

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

    # reveal_profile: the line and fill only run up to the playback
    # position, so the dive draws itself as the video plays (the axes still
    # span the whole dive, so nothing rescales on the way).
    reveal_t = waypoint.time_since_start if waypoint is not None else None
    shown = waypoints
    if elem.get("reveal_profile") and reveal_t is not None:
        shown = [wp for wp in waypoints if wp.time_since_start <= reveal_t] or waypoints[:1]
    # The deco shading (stops / ceiling bands below) follows the same
    # switch: with reveal_profile the stops appear as the dive reaches them,
    # without it the whole dive's stops are on the graph from the first
    # frame and only the cursor moves - the Generic "Dive Profile Deco"
    # overlay's own posture, like the plain Dive Profile's line.
    shade_t = reveal_t if elem.get("reveal_profile") else waypoints[-1].time_since_start

    # Fill path - the area under the line, in fill_color (the line colour
    # unless set) at fill_opacity
    fill_opacity = graph_opacity(elem, "fill_opacity", GRAPH_FILL_OPACITY)
    if fill_opacity > 0:
        fill_overlay = frame.copy()
        pts = []
        pts.append([abs_x, abs_y])
        for wp_i in shown:
            x = int(x_for_time(wp_i.time_since_start))
            y = y_for_depth(wp_i.depth)
            pts.append([x, y])
        pts.append([int(x_for_time(shown[-1].time_since_start)), abs_y])

        pts = np.array(pts, dtype=np.int32)
        fill_bgr = _hex_to_bgr(elem["fill_color"]) if elem.get("fill_color") else color_bgr
        cv2.fillPoly(fill_overlay, [pts], fill_bgr)
        cv2.addWeighted(fill_overlay, fill_opacity, frame, 1 - fill_opacity, 0, frame)

    # Deco ceiling - a gray "may not ascend above this" band from the
    # surface down to each waypoint's own deco_stop_depth, drawn up to
    # shade_t (the playback position with reveal_profile, else the end of
    # the dive). Since every rectangle is derived straight from that
    # waypoint's own logged ceiling value and nothing already drawn is ever
    # erased, a stop's shaded patch is permanent once revealed even after it
    # clears and the diver moves on to a shallower one.
    if waypoint is not None and elem.get("stops_color"):
        _draw_deco_history(frame, elem, waypoints, shade_t, x_for_time, y_for_depth, abs_y)
    elif waypoint is not None:
        ceiling_hex = elem.get("ceiling_color", "#808080").lstrip('#')
        ceiling_bgr = tuple(int(ceiling_hex[i:i + 2], 16) for i in (4, 2, 0))
        ceiling_overlay = frame.copy()
        any_ceiling = False
        for i in range(n_wps):
            wp_i = waypoints[i]
            if wp_i.time_since_start > shade_t:
                break
            ceiling = getattr(wp_i, "deco_stop_depth", None)
            if not ceiling or ceiling <= 0:
                continue
            next_t = waypoints[i + 1].time_since_start if i + 1 < n_wps else shade_t
            seg_end_t = min(next_t, shade_t)
            x_start = int(x_for_time(wp_i.time_since_start))
            x_end = max(x_start + 1, int(x_for_time(seg_end_t)))
            y_bot = y_for_depth(ceiling)
            cv2.rectangle(ceiling_overlay, (x_start, abs_y), (x_end, y_bot), ceiling_bgr, -1)
            any_ceiling = True
        band_opacity = graph_opacity(elem, "ceiling_opacity", GRAPH_BAND_OPACITY)
        if any_ceiling and band_opacity > 0:
            cv2.addWeighted(ceiling_overlay, band_opacity, frame, 1 - band_opacity, 0, frame)

    # Outline line
    line_pts = []
    for wp_i in shown:
        x = int(x_for_time(wp_i.time_since_start))
        y = y_for_depth(wp_i.depth)
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

def _draw_deco_history(frame, elem, waypoints, reveal_t, x_for_time, y_for_depth, abs_y):
    """A graph with stops_color: the deco stops and the ceiling as two
    separate shaded areas, both drawn up to `reveal_t` (the playback
    position with reveal_profile, else the end of the dive) and never
    erased afterwards - so every stop the dive picked up stays on the
    graph once it clears. Stops (stop_depth_of) are a stepped area from the
    surface down to each stop level in stops_color; the recomputed ceiling
    (Waypoint.ceiling, GF high) a smooth area on top in ceiling_color."""
    stops_bgr = _hex_to_bgr(elem.get("stops_color"))
    ceiling_bgr = _hex_to_bgr(elem.get("ceiling_color", "#808080"))
    revealed = [wp for wp in waypoints if wp.time_since_start <= reveal_t]
    if not revealed:
        return

    stops_overlay = frame.copy()
    any_stop = False
    for i, wp_i in enumerate(revealed):
        stop = stop_depth_of(wp_i)
        if stop <= 0:
            continue
        next_t = waypoints[i + 1].time_since_start if i + 1 < len(waypoints) else reveal_t
        x_start = int(x_for_time(wp_i.time_since_start))
        x_end = max(x_start + 1, int(x_for_time(min(next_t, reveal_t))))
        cv2.rectangle(stops_overlay, (x_start, abs_y), (x_end, y_for_depth(stop)), stops_bgr, -1)
        any_stop = True
    stops_opacity = graph_opacity(elem, "stops_opacity", GRAPH_STOPS_OPACITY)
    if any_stop and stops_opacity > 0:
        cv2.addWeighted(stops_overlay, stops_opacity, frame, 1 - stops_opacity, 0, frame)

    if any((wp_i.ceiling or 0) > 0 for wp_i in revealed):
        pts = [[int(x_for_time(revealed[0].time_since_start)), abs_y]]
        pts += [[int(x_for_time(wp_i.time_since_start)), y_for_depth(wp_i.ceiling or 0.0)] for wp_i in revealed]
        pts.append([int(x_for_time(revealed[-1].time_since_start)), abs_y])
        ceiling_opacity = graph_opacity(elem, "ceiling_opacity", GRAPH_CEILING_OPACITY)
        if ceiling_opacity > 0:
            ceiling_overlay = frame.copy()
            cv2.fillPoly(ceiling_overlay, [np.array(pts, dtype=np.int32)], ceiling_bgr)
            cv2.addWeighted(ceiling_overlay, ceiling_opacity, frame, 1 - ceiling_opacity, 0, frame)


CHECK_MARK = "✓ "  # prefix badge_lines puts on a title shown with the Perdix's check mark


def _draw_check_mark(draw, x, y, size, color_rgb, outline=True):
    """A check mark the height of a `size` px line at (x, y); returns the x
    where the text after it starts."""
    w = int(size * 0.9)
    h = int(size * 0.8)
    top = y + int(size * 0.15)
    pts = [(x + int(w * 0.05), top + int(h * 0.55)), (x + int(w * 0.38), top + h), (x + w, top + int(h * 0.05))]
    stroke = max(2, int(size / 8))
    if outline:
        draw.line(pts, fill=(0, 0, 0), width=stroke + 2, joint="curve")
    draw.line(pts, fill=color_rgb, width=stroke, joint="curve")
    return x + w + int(size * 0.35)


def badge_title_ink_span(font, text, size):
    """(left, right) of a badge title's ink relative to its draw x - with
    the check mark _draw_check_mark() strokes in front of a CHECK_MARK
    title included, so a value line can be centred under the whole title."""
    if text.startswith(CHECK_MARK):
        w = int(size * 0.9)
        _, _, right, _ = font.getbbox(text[len(CHECK_MARK):])
        return int(w * 0.05), w + int(size * 0.35) + right
    left, _, right, _ = font.getbbox(text)
    return left, right


def _rgb(hex_color):
    return tuple(int(hex_color.lstrip('#')[i:i + 2], 16) for i in (0, 2, 4))


def _format_stop_timer(seconds, fmt):
    """'2:33' (m:ss), '02:33' (mm:ss) or '2min' (min - whole minutes, rounded
    up, as a Perdix shows a deco stop's time)."""
    seconds = max(0, int(seconds))
    if fmt == "min":
        return f"{max(1, -(-seconds // 60)) if seconds else 0}min"
    mins, secs = divmod(seconds, 60)
    return f"{mins}:{secs:02d}" if fmt == "m:ss" else f"{mins:02d}:{secs:02d}"


def badge_lines(manufacturer, model, elem, waypoint, waypoints=None):
    """The (text, color_rgb, is_value) lines a state badge renders for this
    waypoint - None when nothing is drawn ('normal' state, no badge config,
    no waypoint). Shared by _draw_state_badge and the Overlay Designer's
    hit-testing. See rework_hud.md's "State rendering" section.

    What is shown comes from hud_rules_engine.stop_phase() (state, phase,
    seconds, stop depth) and is styled by the manufacturer's badge_states
    entry for the state, plus per-element overrides:
      label / color          title line (a label of "" draws no title)
      value_color            colour of the depth/timer lines (default: color)
      <phase>_color          title colour in that phase (pending, counting,
                             paused, complete, approach, at_stop, violation)
      <phase>_value_color    depth/timer colour in that phase
      <phase>_value_text     text shown instead of the timer in that phase
      <phase>_label          title text in that phase (Perdix 3: "PAUSED")
      title_box              the title sits in a filled box of its colour, in black text (Perdix 3)
      check_mark             "✓ " before the title when at the stop / counting / complete
      show_depth             False: no stop-depth line (a Shearwater safety stop names none)
      inline                 depth and timer on one line: "6m↑ 2min" (Perdix deco stop)
      timer_format           "m:ss" | "mm:ss" | "min"; the element's own key wins
      value_align            "center": the timer (and depth line) centred under
                             the title, as a Perdix centres the safety-stop
                             time under "SAFETY STOP"; the element's key wins
      blink / blink_depth    time-based red flashing (kept for older rule files)
    Element keys: depth_unit, depth_font ("label" draws the depth line at
    the label size), timer_format, style ("box" implies m:ss)."""
    from utils.hud_rules_engine import (
        stop_phase, get_badge_config, resolve_blink_color, ceiling_broken, ceiling_broken_color,
    )

    if waypoint is None:
        return None
    state, phase, seconds, stop_depth = stop_phase(manufacturer, model, waypoint, waypoints)
    if state == "normal":
        return None
    badge = get_badge_config(manufacturer, model, state)
    if not badge:
        return None

    elapsed = waypoint.dive_time if waypoint.dive_time is not None else waypoint.time_since_start
    blink_red = lambda hex_color: resolve_blink_color(hex_color, "#FF0000", elapsed)
    blink_phase = resolve_blink_color("a", "b", elapsed) == "b"  # the "on" half of each second

    title_hex = badge.get("color", "#FFFFFF")
    if phase and badge.get(f"{phase}_color"):
        title_hex = badge[f"{phase}_color"]
    if badge.get("blink"):
        title_hex = blink_red(title_hex)
    value_hex = badge.get("value_color", title_hex)
    if phase and badge.get(f"{phase}_value_color"):
        value_hex = badge[f"{phase}_value_color"]
    value_text = badge.get(f"{phase}_value_text") if phase else None  # e.g. Teric: "CLEAR" once the stop is done
    violating = phase == "violation" or (state in ("deco", "clear") and ceiling_broken(manufacturer, model, waypoint))
    if violating:
        red = badge.get("violation_color") or ceiling_broken_color(manufacturer, model)
        title_hex = resolve_blink_color(badge.get("color", "#FFFFFF"), red, elapsed)
        value_hex = resolve_blink_color(badge.get("value_color", badge.get("color", "#FFFFFF")), red, elapsed)

    label = badge.get("label", state.upper())
    if phase and badge.get(f"{phase}_label"):
        label = badge[f"{phase}_label"]  # e.g. Perdix 3: "PAUSED" in place of "SAFETY"
    if label and badge.get("check_mark") and phase in ("at_stop", "counting", "complete"):
        label = "✓ " + label
    lines = [(label, _rgb(title_hex), False)] if label else []

    timer_format = elem.get("timer_format") or ("m:ss" if elem.get("style") == "box" else badge.get("timer_format", "mm:ss"))
    unit = elem.get("depth_unit", "")
    depth_is_value = elem.get("depth_font") != "label"
    show_depth = badge.get("show_depth", True) and stop_depth
    if show_depth and badge.get("inline"):
        # "6m↑ 2min": the arrow flashes while approaching the stop
        arrow = "↑" if phase != "approach" or blink_phase else " "
        timer = _format_stop_timer(seconds, timer_format) if seconds is not None else ""
        lines.append((f"{stop_depth:.0f}{unit}{arrow} {timer}".rstrip(), _rgb(value_hex), True))
        return lines
    if show_depth:
        depth_hex = value_hex
        if badge.get("blink_depth"):
            depth_hex = blink_red(depth_hex)
        lines.append((f"↑{stop_depth:.0f}{unit}", _rgb(depth_hex), depth_is_value))
    if value_text:
        lines.append((value_text, _rgb(value_hex), True))
    elif seconds is not None:
        lines.append((_format_stop_timer(seconds, timer_format), _rgb(value_hex), True))
    return lines


def badge_box_size(elem, user_scale, res_scale, render_log):
    """(w, h) final pixel size of a `style: "box"` badge."""
    scale = user_scale if render_log else user_scale * res_scale
    return max(1, int(elem.get("width", 80) * scale)), max(1, int(elem.get("height", 44) * scale))


def _draw_badge_box(draw, elem, lines, state, abs_x, abs_y, label_size, value_size, box_w, box_h, scale):
    """Garmin Descent-style stop box (X50i manual p.10): a filled rounded
    box in the state's colour replacing the NDL field - the label and
    "↑depth" on the top row, the stop timer large underneath, in dark text.
    `fill_colors` on the element overrides the badge colour per state."""
    fill_hex = (elem.get("fill_colors") or {}).get(state)
    fill = tuple(int(fill_hex.lstrip('#')[i:i + 2], 16) for i in (0, 2, 4)) if fill_hex else lines[0][1]
    text_rgb = tuple(int(elem.get("text_color", "#000000").lstrip('#')[i:i + 2], 16) for i in (0, 2, 4))
    radius = max(1, int(elem.get("corner_radius", 4) * scale))
    draw.rounded_rectangle([abs_x, abs_y, abs_x + box_w, abs_y + box_h], radius=radius, fill=fill)

    family, weight = elem.get("font_family"), elem.get("font_weight")
    label_font = get_font(label_size, family, weight)
    value_font = get_font(value_size, family, weight)
    pad = max(1, int(elem.get("padding", 4) * scale))
    top_row = [text for text, _, is_value in lines if not is_value or text.startswith("↑")]
    timer = next((text for text, _, is_value in lines if is_value and not text.startswith("↑")), None)

    top_text = "  ".join(top_row)
    draw.text((abs_x + pad, abs_y + pad), top_text, font=label_font, fill=text_rgb)
    if timer:
        left, top, right, bottom = value_font.getbbox(timer)
        x = abs_x + (box_w - (right - left)) / 2 - left
        y = abs_y + box_h - pad - bottom
        draw.text((x, y), timer, font=value_font, fill=text_rgb)

def badge_line_sizes(elem, user_scale, res_scale, render_log):
    """(label_px, value_px) final pixel sizes of a badge's two font tiers."""
    base_font_size = elem.get("font_size", 16)
    base_value_font_size = elem.get("value_font_size", base_font_size)
    item_scale = elem.get("scale", 1.0)

    def _scaled(size):
        raw = size * user_scale * item_scale if render_log else size * user_scale * res_scale * item_scale
        return max(1, int(raw))

    return _scaled(base_font_size), _scaled(base_value_font_size)

def _draw_state_badge(draw, elem, waypoint, manufacturer, model, skin_x, skin_y, w_scaled, h_scaled, res_scale, user_scale, render_log, waypoints=None):
    """Renders a compound label + ceiling-depth + countdown-timer badge for the
    waypoint's resolved safety_stop/deco state - see rework_hud.md's "State rendering"
    section. Draws nothing for 'normal' state or when no badge_states config exists."""
    lines = badge_lines(manufacturer, model, elem, waypoint, waypoints)
    if not lines:
        return

    rel_x = elem.get("rel_x", 0.0)
    rel_y = elem.get("rel_y", 0.0)
    abs_x = int(skin_x + (rel_x * w_scaled))
    abs_y = int(skin_y + (rel_y * h_scaled))

    label_size, value_size = badge_line_sizes(elem, user_scale, res_scale, render_log)
    if elem.get("style") == "box":
        from utils.hud_rules_engine import resolve_state
        box_w, box_h = badge_box_size(elem, user_scale, res_scale, render_log)
        scale = user_scale if render_log else user_scale * res_scale
        state = resolve_state(manufacturer, model, waypoint, waypoints)
        _draw_badge_box(draw, elem, lines, state, abs_x, abs_y, label_size, value_size, box_w, box_h, scale)
        return
    family, weight = elem.get("font_family"), elem.get("font_weight")
    label_font = get_font(label_size, family, weight)
    value_font = get_font(value_size, family, weight)
    outline = elem.get("outline", True)
    align = elem.get("align", "left")
    valign = elem.get("valign", "top")

    from utils.hud_rules_engine import get_badge_config, resolve_state
    badge_cfg = get_badge_config(manufacturer, model, resolve_state(manufacturer, model, waypoint, waypoints)) or {}
    title_box = bool(elem.get("title_box", badge_cfg.get("title_box")))
    # "center": value lines sit centred under the title's ink (a Perdix
    # centres the safety-stop time under "SAFETY STOP") whatever the
    # element's own anchor alignment is.
    value_align = elem.get("value_align") or badge_cfg.get("value_align")
    title_center = None

    y = abs_y
    if valign != "top":
        block_h = sum(int((value_size if is_value else label_size) * 1.2) for _, _, is_value in lines)
        y -= block_h if valign == "bottom" else block_h // 2
    for index, (text, color_rgb, is_value) in enumerate(lines):
        font = value_font if is_value else label_font
        final_size = value_size if is_value else label_size
        x = abs_x
        if align != "left":
            dx, _, _ = text_anchor_shift(font, text, align, "top")
            x = int(round(abs_x + dx))
        if is_value and value_align == "center" and title_center is not None:
            left, _, right, _ = font.getbbox(text)
            x = int(round(title_center - (left + right) / 2.0))
        elif not is_value and title_center is None:
            left, right = badge_title_ink_span(font, text, final_size)
            title_center = x + (left + right) / 2.0
        if index == 0 and not is_value and title_box:
            # Perdix 3 style: the title in a filled box of its colour, black text.
            left, top, right, bottom = font.getbbox(text)
            pad = max(1, int(final_size * 0.12))
            draw.rounded_rectangle([x + left - pad, y + top - pad, x + right + pad, y + bottom + pad],
                                   radius=max(1, int(final_size * 0.1)), fill=color_rgb)
            draw.text((x, y), text, font=font, fill=(0, 0, 0))
            y += int(final_size * 1.2) + pad
            continue
        o_dist = max(1, int(final_size / 20))
        if text.startswith(CHECK_MARK):
            # The bundled fonts have no ✓ glyph - draw the Perdix's check mark
            # as a stroke in the line's colour, then the text after it.
            text = text[len(CHECK_MARK):]
            x = _draw_check_mark(draw, x, y, final_size, color_rgb, outline)
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


def ascent_lit_count(rate, up_count, per_chevron=None):
    """How many upward chevrons light for `rate` m/min (0 when level or
    descending). Garmin (no `per_chevron`): one at the deadband, then
    linearly to all at full scale. `per_chevron` (hud_rules.json
    `ascent_chevrons.m_per_min_per_chevron` - the Perdix 2's "1 arrow per
    3 m/min", manual p.12): one more arrow for every `per_chevron` m/min."""
    if rate is None or rate < ASCENT_DEADBAND_M_PER_MIN or up_count <= 0:
        return 0
    if per_chevron:
        return max(1, min(up_count, int(math.ceil(rate / float(per_chevron)))))
    return max(1, min(up_count, int(rate / ASCENT_FULL_SCALE_M_PER_MIN * up_count) + 1))


def _draw_ascent_chevrons(draw, elem, waypoint, waypoints, manufacturer, model, skin_x, skin_y, w_scaled, h_scaled, res_scale, user_scale, render_log):
    """Garmin-style ascent-rate indicator (schema v2 element type
    "ascent_chevrons"): `up_count` upward chevrons stacked above a white bar
    and `down_count` downward chevrons below it. Unlit chevrons are grey; on
    ascent 1..up_count chevrons light in the hud_rules.json `ascent_rate`
    band colour for the current rate, on descent the downward chevrons light
    white. Always drawn (all grey when level or without data).

    Shearwater style (Perdix 2 manual p.12) is the same element with the
    brand's hud_rules.json: `ascent_chevrons` {up_count 6, down_count 0,
    bar false, m_per_min_per_chevron 3} - six arrows and no divider bar -
    and `ascent_rate` bands white / yellow / flashing red (a band's
    `blink: true` alternates its colour with the unlit grey every second
    of dive time). Element keys `bar` (false hides the divider) and the
    counts override the rule."""
    from utils.hud_rules_engine import get_rule_config, resolve_blink_color

    rel_x = elem.get("rel_x", 0.0)
    rel_y = elem.get("rel_y", 0.0)
    abs_x = int(skin_x + (rel_x * w_scaled))
    abs_y = int(skin_y + (rel_y * h_scaled))
    scale = user_scale if render_log else user_scale * res_scale
    w, h, up, down = ascent_chevron_geometry(elem)
    chevron_rule = get_rule_config(manufacturer, model, "ascent_chevrons")
    chevron_rule = chevron_rule if isinstance(chevron_rule, dict) else {}
    show_bar = bool(elem.get("bar", chevron_rule.get("bar", True)))
    w_px = max(4, int(round(w * scale)))
    h_px = max(8, int(round(h * scale)))
    bar_h = max(2, int(round(h_px * 0.10))) if show_bar else 0
    gap = max(1, int(round(1.0 * scale)))
    n = up + down
    chev_h = max(3, int((h_px - bar_h - gap * (n + (1 if show_bar else -1))) / n)) if n else 0
    arrow = max(1, int(round(w_px * 0.45)))          # apex depth of the "^"
    band_t = max(1, chev_h - arrow)                   # band thickness

    rate = ascent_rate_for(waypoint, waypoints)
    lit_up = ascent_lit_count(rate, up, chevron_rule.get("m_per_min_per_chevron"))
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
            hex_color = str(band.get("color", "#00FF00"))
            if band.get("blink"):
                # The band colour is the "blink" (first-half) colour, like the
                # badges' flashing red, so whole-second waypoints show it.
                elapsed = waypoint.dive_time if waypoint.dive_time is not None else waypoint.time_since_start
                unlit_hex = "#%02X%02X%02X" % CHEVRON_UNLIT
                hex_color = resolve_blink_color(unlit_hex, hex_color, elapsed)
            hex_color = hex_color.lstrip('#')
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
    if show_bar:
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

    # `hide_in_states` elements (e.g. the NDL a stop box replaces) step aside
    # while the HUD is in one of those states.
    hud_state = None
    if any(elem.get("hide_in_states") for elem in linked_elements):
        from utils.hud_rules_engine import resolve_state
        hud_state = resolve_state(rules_manufacturer(layout), layout.get("model", "Perdix2"), waypoint, waypoints)

    for elem in linked_elements:
        field = elem.get("field", "")
        if hud_state is not None and hud_state in (elem.get("hide_in_states") or ()):
            continue
        if elem.get("type") == "graph" or field == "depth_graph":
            if elem.get("stop_label"):
                draw_graph_stop_label(draw, elem, waypoint, waypoints, skin_info)
            continue

        if elem.get("type") == "badge":
            manufacturer = rules_manufacturer(layout)
            model = layout.get("model", "Perdix2")
            _draw_state_badge(draw, elem, waypoint, manufacturer, model, skin_x, skin_y, w_scaled, h_scaled, res_scale, user_scale, render_log, waypoints)
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

        if field == "ndl" and (raw_val is None or (isinstance(raw_val, (int, float)) and raw_val <= 0)):
            # In deco a Perdix shows NDL "0" in red (manual p.33) - for
            # manufacturers with an ndl_zero colour, rather than "99+"/"--".
            from utils.hud_rules_engine import get_rule_config, resolve_state
            if get_rule_config(rules_manufacturer(layout), layout.get("model", "Perdix2"), "ndl_zero") and \
                    resolve_state(rules_manufacturer(layout), layout.get("model", "Perdix2"), waypoint, waypoints) == "deco":
                val, raw_val = "0", 0

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
        color_hex = get_dynamic_color(manufacturer, model, field, raw_val, default_color)
        if field == "depth":
            # Above a deco ceiling by more than the margin: the depth flashes
            # red along with the badge's ceiling line (Descent Mk3 manual p.10).
            from utils.hud_rules_engine import ceiling_broken, ceiling_broken_color, resolve_blink_color, resolve_state
            if resolve_state(manufacturer, model, waypoint, waypoints) in ("deco", "clear") and ceiling_broken(manufacturer, model, waypoint):
                elapsed = waypoint.dive_time if waypoint.dive_time is not None else waypoint.time_since_start
                color_hex = resolve_blink_color(color_hex, ceiling_broken_color(manufacturer, model), elapsed)
        color_hex = color_hex.lstrip('#')
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
        orientation = elem.get("orientation")
        if orientation in VERTICAL_ORIENTATIONS:
            # A small_suffix / NDL "+" is not split for vertical text: the
            # whole string is stacked or turned as one.
            draw_oriented_text(pil_img, draw, val_str, font, orientation, abs_x, abs_y, align, valign, color_rgb, outline, final_size)
            continue
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

        highlight = elem.get("tank_switch_highlight")
        if highlight:
            # Sidemount tank-switch notification (Perdix 2 manual p.42): a
            # filled box behind this tank's label when it is the one to
            # breathe from - the rule's colour, text in its text_color.
            from utils.hud_rules_engine import get_rule_config, sidemount_switch_target
            if sidemount_switch_target(manufacturer, model, waypoint) == highlight:
                rule = get_rule_config(manufacturer, model, "sidemount_switch") or {}
                box_rgb = tuple(int(str(rule.get("color", "#00C800")).lstrip('#')[i:i + 2], 16) for i in (0, 2, 4))
                color_rgb = tuple(int(str(rule.get("text_color", "#000000")).lstrip('#')[i:i + 2], 16) for i in (0, 2, 4))
                left, top, right, bottom = font.getbbox(val_str)
                pad = max(1, int(final_size * 0.15))
                draw.rounded_rectangle(
                    [abs_x + left - pad, abs_y + top - pad, abs_x + right + pad, abs_y + bottom + pad],
                    radius=max(1, int(final_size * 0.15)), fill=box_rgb,
                )
                outline = False

        o_dist = max(1, int(final_size / 20))
        if outline:
            for dx, dy in [(-o_dist, -o_dist), (o_dist, -o_dist), (-o_dist, o_dist), (o_dist, o_dist)]:
                draw.text((abs_x + dx, abs_y + dy), val_str, font=font, fill=(0, 0, 0))

        draw.text((abs_x, abs_y), val_str, font=font, fill=color_rgb)

    frame[:] = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
