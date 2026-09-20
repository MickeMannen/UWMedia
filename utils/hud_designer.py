"""
Pure logic for the Overlay Designer (module keeps its original "hud_designer"
name - overlay_rework.md decision Q10): anchor/offset math, layout JSON (de)serialization,
element hit-testing, and alignment - ported from gui/hud_manager.py's HUDManager,
with Qt's QGraphicsScene item state replaced by plain dicts. No Toga/Qt imports here;
uwmedia/app.py owns the canvas widget and file I/O, this module owns the math.

Layout schema matches the existing hud_layout.json format (see gui/hud_manager.py's
get_layout_json/load_layout, and cli_main.py's consumption of it) exactly, so packages
saved here load in the CLI/renderer unchanged, and vice versa.
"""
from typing import Any, Dict, List, Optional, Tuple

from gui.hud_renderer import (
    ascent_chevron_geometry,
    badge_line_sizes,
    get_font,
    tank_outline_metrics,
    tank_segments_geometry,
    text_anchor_shift,
    text_parts,
    tissue_bar_geometry,
)
from models.dive import Waypoint

ANCHORS = [
    "TOP_LEFT", "TOP_CENTER", "TOP_RIGHT",
    "MIDDLE_LEFT", "CENTER", "MIDDLE_RIGHT",
    "BOTTOM_LEFT", "BOTTOM_CENTER", "BOTTOM_RIGHT",
]

MARKER_STYLES = ["dot", "cross", "bold_cross"]


def resolve_anchor_position(
    anchor: str, ref_x: float, ref_y: float, view_w: float, view_h: float, skin_w: float, skin_h: float
) -> Tuple[float, float]:
    """Top-left of the skin, given its anchor + reference offset (ported from
    HUDManager.load_layout's anchor block)."""
    base_x, base_y = 0.0, 0.0
    if "CENTER" in anchor:
        base_x = view_w / 2.0
    elif "RIGHT" in anchor:
        base_x = float(view_w)
    if "MIDDLE" in anchor:
        base_y = view_h / 2.0
    elif "BOTTOM" in anchor:
        base_y = float(view_h)

    pivot_x, pivot_y = 0.0, 0.0
    if "CENTER" in anchor:
        pivot_x = skin_w / 2.0
    elif "RIGHT" in anchor:
        pivot_x = skin_w
    if "MIDDLE" in anchor:
        pivot_y = skin_h / 2.0
    elif "BOTTOM" in anchor:
        pivot_y = skin_h

    return base_x + ref_x - pivot_x, base_y + ref_y - pivot_y


def resolve_skin_position(
    skin_data: Dict[str, Any], skin_w: float, skin_h: float, view_w: float, view_h: float
) -> Tuple[float, float]:
    """Top-left of the skin from a hud_skin JSON dict - anchor+offset if present,
    else the legacy x_pct/y_pct fallback."""
    ref_x = skin_data.get("ref_offset_x")
    ref_y = skin_data.get("ref_offset_y")
    if ref_x is not None and ref_y is not None:
        anchor = skin_data.get("anchor", "TOP_LEFT")
        return resolve_anchor_position(anchor, ref_x, ref_y, view_w, view_h, skin_w, skin_h)
    return skin_data.get("x_pct", 0.0) * view_w, skin_data.get("y_pct", 0.0) * view_h


def compute_ref_offset(
    anchor: str, x: float, y: float, skin_w: float, skin_h: float, view_w: float, view_h: float
) -> Tuple[float, float]:
    """Inverse of resolve_anchor_position (ported from HUDManager.get_layout_json)."""
    if "LEFT" in anchor:
        hud_ref_x = x
    elif "CENTER" in anchor:
        hud_ref_x = x + skin_w / 2.0
    else:  # RIGHT
        hud_ref_x = x + skin_w

    if "TOP" in anchor:
        hud_ref_y = y
    elif "MIDDLE" in anchor:
        hud_ref_y = y + skin_h / 2.0
    else:  # BOTTOM
        hud_ref_y = y + skin_h

    if "LEFT" in anchor:
        screen_ref_x = 0.0
    elif "CENTER" in anchor:
        screen_ref_x = view_w / 2.0
    else:
        screen_ref_x = float(view_w)

    if "TOP" in anchor:
        screen_ref_y = 0.0
    elif "MIDDLE" in anchor:
        screen_ref_y = view_h / 2.0
    else:
        screen_ref_y = float(view_h)

    return hud_ref_x - screen_ref_x, hud_ref_y - screen_ref_y


def skin_pixel_size(skin: Dict[str, Any]) -> Tuple[float, float]:
    """Current skin size in design pixels."""
    if skin.get("type") == "shape":
        return float(skin.get("width", 400)), float(skin.get("height", 200))
    native_w = skin.get("native_width") or 0
    native_h = skin.get("native_height") or 0
    scale = skin.get("scale", 1.0)
    return native_w * scale, native_h * scale


def build_layout_json(
    skin: Dict[str, Any],
    elements: List[Dict[str, Any]],
    manufacturer: str,
    model: str,
    view_w: float,
    view_h: float,
) -> Dict[str, Any]:
    """Ported from HUDManager.get_layout_json, operating on plain dicts."""
    is_shape = skin.get("type") == "shape"
    skin_w, skin_h = skin_pixel_size(skin)
    anchor = skin.get("anchor", "TOP_LEFT")
    x, y = skin.get("x", 0.0), skin.get("y", 0.0)

    ref_x, ref_y = compute_ref_offset(anchor, x, y, skin_w, skin_h, view_w, view_h)

    linked_elements = []
    for elem in elements:
        # Unknown keys (ceiling_color, value_font_size, align, font_family,
        # ... - overlay_rework.md schema v2) are carried through verbatim;
        # only the per-type defaults below are filled in when absent.
        entry = {k: v for k, v in elem.items() if k not in TRANSIENT_ELEMENT_KEYS}
        entry["field"] = elem["field"]
        entry["rel_x"] = elem["rel_x"]
        entry["rel_y"] = elem["rel_y"]
        kind = elem.get("type")
        if kind == "graph":
            entry["type"] = "graph"
            for key, default in (("color", "#00FF00"), ("width", 300), ("height", 150),
                                 ("marker_style", "dot"), ("marker_size", 6)):
                entry.setdefault(key, default)
        elif kind == "badge":
            entry["type"] = "badge"
            entry.setdefault("font_size", 16)
            entry.setdefault("scale", 1.0)
        elif kind == "tank_icon":
            entry["type"] = "tank_icon"
            for key, default in (("width", 20), ("height", 30), ("corner_radius", 4)):
                entry.setdefault(key, default)
        elif kind == "tissue_bar":
            entry["type"] = "tissue_bar"
            for key, default in (("width", 12), ("height", 33), ("marker_size", 4)):
                entry.setdefault(key, default)
        elif kind == "ascent_chevrons":
            entry["type"] = "ascent_chevrons"
            for key, default in (("width", 16), ("height", 47), ("up_count", 4), ("down_count", 1)):
                entry.setdefault(key, default)
        else:
            for key, default in (("color", "#FFFFFF"), ("font_size", 16), ("scale", 1.0)):
                entry.setdefault(key, default)
        linked_elements.append(entry)

    skin_data = {
        "type": "shape" if is_shape else "image",
        "anchor": anchor,
        "ref_offset_x": ref_x,
        "ref_offset_y": ref_y,
        "opacity": skin.get("opacity", 1.0),
        "x_pct": x / view_w if view_w else 0.0,
        "y_pct": y / view_h if view_h else 0.0,
        "linked_elements": linked_elements,
    }
    if is_shape:
        skin_data.update({
            "width": skin.get("width", 400),
            "height": skin.get("height", 200),
            "color": skin.get("color", "#000000"),
            "corner_radius": skin.get("corner_radius", 20),
        })
    else:
        skin_data.update({
            "path": skin.get("path"),
            "scale": skin.get("scale", 1.0),
        })

    return {
        "manufacturer": manufacturer,
        "model": model,
        "hud_skin": skin_data,
        "design_width": view_w,
        "design_height": view_h,
    }


TRANSIENT_ELEMENT_KEYS = frozenset({"uid"})

ELEMENT_KINDS = ("text", "badge", "tank_icon", "graph", "tissue_bar", "ascent_chevrons")


def element_kind(element: Dict[str, Any]) -> str:
    """One of ELEMENT_KINDS - "graph" also for the legacy field-only
    depth_graph form, "text" for anything without a type."""
    kind = element.get("type")
    if kind == "graph" or element.get("field") == "depth_graph":
        return "graph"
    if kind in ("badge", "tank_icon", "tissue_bar", "ascent_chevrons"):
        return kind
    return "text"


def element_defaults(kind: str, field: str) -> Dict[str, Any]:
    """A new element of `kind` for `field`, centred on the skin, with the
    same defaults the renderer would assume for missing keys."""
    base: Dict[str, Any] = {"field": field, "rel_x": 0.5, "rel_y": 0.5}
    if kind == "graph":
        base.update({"type": "graph", "width": 300, "height": 150, "color": "#00FF00",
                     "ceiling_color": "#808080", "marker_style": "dot", "marker_size": 6})
    elif kind == "badge":
        base.update({"type": "badge", "font_size": 16, "value_font_size": 32, "scale": 1.0})
    elif kind == "tank_icon":
        base.update({"type": "tank_icon", "width": 20, "height": 30, "corner_radius": 4})
    elif kind == "tissue_bar":
        base.update({"type": "tissue_bar", "field": "n2_tissue_load", "width": 12, "height": 33, "marker_size": 4})
    elif kind == "ascent_chevrons":
        base.update({"type": "ascent_chevrons", "field": "ascent_rate", "width": 16, "height": 47, "up_count": 4, "down_count": 1})
    else:
        base.update({"color": "#FFFFFF", "font_size": 30, "scale": 1.0})
    return base


def parse_layout_elements(hud_skin: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Element dicts from a hud_skin JSON block (ported from HUDManager.load_layout's
    element loop). Does not touch the skin itself - see resolve_skin_position for that.
    Every key in the file is kept (schema v2 attributes included); per-type
    defaults are filled in for keys that are absent."""
    elements = []
    for element in hud_skin.get("linked_elements", []):
        field = element.get("field", "")
        kind = element_kind(element)
        entry = dict(element)
        entry["rel_x"] = element["rel_x"]
        entry["rel_y"] = element["rel_y"]
        if kind == "graph":
            entry["field"] = field or "depth_graph"
            entry["type"] = "graph"
            for key, default in (("width", 300), ("height", 150), ("color", "#00FF00"),
                                 ("marker_style", "dot"), ("marker_size", 6)):
                entry.setdefault(key, default)
        elif kind == "badge":
            entry["field"] = field or "state_badge"
            entry.setdefault("font_size", 16)
            entry.setdefault("scale", 1.0)
        elif kind == "tank_icon":
            entry["field"] = field or "primary_tank_pressure"
            for key, default in (("width", 20), ("height", 30), ("corner_radius", 4)):
                entry.setdefault(key, default)
        elif kind == "tissue_bar":
            entry["field"] = field or "n2_tissue_load"
            for key, default in (("width", 12), ("height", 33), ("marker_size", 4)):
                entry.setdefault(key, default)
        elif kind == "ascent_chevrons":
            entry["field"] = field or "ascent_rate"
            for key, default in (("width", 16), ("height", 47), ("up_count", 4), ("down_count", 1)):
                entry.setdefault(key, default)
        else:
            entry["field"] = field
            for key, default in (("color", "#FFFFFF"), ("font_size", 16), ("scale", 1.0)):
                entry.setdefault(key, default)
        elements.append(entry)
    return elements


def available_telemetry_fields(dive=None) -> List[str]:
    """Ported from gui_main.py's update_available_fields."""
    standard_fields = list(Waypoint.model_fields.keys())
    standard_fields += [
        "primary_tank_pressure", "primary_tank_name",
        "secondary_tank_pressure", "secondary_tank_name",
        "gasmix", "safety_stop", "time_of_day",
    ]
    fields = sorted(f for f in standard_fields if f != "tanks")

    if dive and dive.waypoints:
        unique_tanks = set()
        for wp in dive.waypoints:
            unique_tanks.update(wp.tanks.keys())
        for tank_name in sorted(unique_tanks):
            fields.append(f"tank_pressure:{tank_name}")
            fields.append(f"tank_name:{tank_name}")
    return fields


def element_display_name(field: str) -> str:
    if field.startswith("custom:"):
        return field.replace("custom:", "")
    if field.startswith("tank_pressure:"):
        return field.replace("tank_pressure:", "") + " (Bar)"
    if field.startswith("tank_name:"):
        return field.replace("tank_name:", "")
    if field == "depth_graph":
        return "Depth Graph"
    if field == "state_badge":
        return "State Badge"
    if field == "time_of_day":
        return "Time of Day"
    return field


def measure_element_box(elem: Dict[str, Any], skin: Dict[str, Any], text: Optional[str] = None) -> Tuple[float, float]:
    """Approximate (width, height) of an element in design pixels - graphs use their
    explicit dimensions; text elements are measured with the same PIL font metrics
    draw_hud itself uses, against `text` when given (the Overlay Designer passes the
    currently rendered value) else the element's display name."""
    if elem.get("type") == "graph":
        return float(elem.get("width", 300)), float(elem.get("height", 150))

    skin_scale = skin.get("scale", 1.0) if skin.get("type") != "shape" else 1.0
    font_size = max(1, int(elem.get("font_size", 16) * skin_scale * elem.get("scale", 1.0)))
    font = get_font(font_size, elem.get("font_family"), elem.get("font_weight"))
    text = text or element_display_name(elem["field"]) or "0"
    left, top, right, bottom = font.getbbox(text)
    return float(right - left) or float(font_size), float(bottom - top) or float(font_size)


def element_native_bounds(
    elem: Dict[str, Any],
    native_w: float,
    native_h: float,
    text: Optional[str] = None,
    badge_lines: Optional[List[Any]] = None,
) -> Tuple[float, float, float, float]:
    """(x0, y0, x1, y1) of an element in the skin's own native pixels - i.e.
    where draw_hud(render_log=True, hud_skin.scale=1) puts it - mirroring the
    renderer's sizing, alignment and font choice exactly (text via the same
    text_anchor_shift(); badges via badge_line_sizes()). `text` is the value
    string being rendered (falls back to the field's display name);
    `badge_lines` the renderer's badge_lines() result (falls back to a single
    placeholder line so an invisible 'normal'-state badge is still selectable)."""
    x = float(elem.get("rel_x", 0.0)) * native_w
    y = float(elem.get("rel_y", 0.0)) * native_h
    kind = element_kind(elem)
    if kind == "graph":
        return x, y, x + float(elem.get("width", 300)), y + float(elem.get("height", 150))
    if kind == "tissue_bar":
        w, h, r = tissue_bar_geometry(elem)
        return x - r, y, x + w, y + h + r
    if kind == "ascent_chevrons":
        w, h, _, _ = ascent_chevron_geometry(elem)
        return x, y, x + w, y + h
    if kind == "tank_icon" and elem.get("style") == "segments":
        n, gap, _, pad, stroke, nose, nub = tank_segments_geometry(elem)
        seg_w, seg_h = float(elem.get("width", 12)), float(elem.get("height", 23))
        total_w = n * seg_w + (n - 1) * gap
        return x - pad - stroke, y - pad - stroke, x + total_w + pad + stroke + nose + nub, y + seg_h + pad + stroke
    if kind == "tank_icon":
        w, h = float(elem.get("width", 20)), float(elem.get("height", 30))
        metrics = tank_outline_metrics(elem)
        if metrics is None:
            return x, y, x + w, y + h
        gap, stroke, cap_h = metrics
        pad = gap + stroke
        return x - pad, y - pad - cap_h + stroke, x + w + pad, y + h + pad

    family, weight = elem.get("font_family"), elem.get("font_weight")
    align = elem.get("align", "left")
    valign = elem.get("valign", "top")

    if kind == "badge":
        label_size, value_size = badge_line_sizes(elem, 1.0, 1.0, True)
        lines = badge_lines or [(element_display_name("state_badge"), None, False)]
        block_h = sum(int((value_size if is_value else label_size) * 1.2) for _, _, is_value in lines)
        y0 = y - (block_h if valign == "bottom" else block_h // 2 if valign == "middle" else 0)
        x0, x1 = float("inf"), float("-inf")
        for line_text, _, is_value in lines:
            size = value_size if is_value else label_size
            font = get_font(size, family, weight)
            dx, _, (left, _, right, _) = text_anchor_shift(font, line_text, align, "top")
            x0 = min(x0, x + dx + left)
            x1 = max(x1, x + dx + right)
        if x0 == float("inf"):
            x0, x1 = x, x + label_size
        return x0, float(y0), x1, float(y0 + block_h)

    size = max(1, int(float(elem.get("font_size", 16)) * float(elem.get("scale", 1.0))))
    font = get_font(size, family, weight)
    value = text if text else (element_display_name(elem.get("field", "")) or "0")
    main, suffix, suffix_scale = text_parts(elem.get("field", ""), value, elem)
    dx, dy, (left, top, right, bottom) = text_anchor_shift(font, main, align, valign)
    if suffix:
        suffix_font = get_font(max(1, round(size * suffix_scale)), family, weight)
        right = right + suffix_font.getlength(suffix)
        if align == "center":
            dx = -(left + right) / 2.0
        elif align == "right":
            dx = -float(right)
    return x + dx + left, y + dy + top, x + dx + right, y + dy + bottom


def hit_test_bounds(x: float, y: float, bounds: List[Tuple[float, float, float, float]], slack: float = 2.0) -> Optional[int]:
    """Index of the topmost (last-drawn) bounds box containing (x, y), with
    `slack` pixels of tolerance so thin text is still grabbable; None if none."""
    for index in range(len(bounds) - 1, -1, -1):
        x0, y0, x1, y1 = bounds[index]
        if x0 - slack <= x <= x1 + slack and y0 - slack <= y <= y1 + slack:
            return index
    return None


def element_position(elem: Dict[str, Any], skin: Dict[str, Any]) -> Tuple[float, float]:
    """Absolute design-pixel top-left of an element (skin position + its rel_x/rel_y)."""
    skin_w, skin_h = skin_pixel_size(skin)
    return skin.get("x", 0.0) + elem["rel_x"] * skin_w, skin.get("y", 0.0) + elem["rel_y"] * skin_h


def hit_test(
    x: float, y: float, skin: Optional[Dict[str, Any]], elements: List[Dict[str, Any]]
) -> Optional[Any]:
    """Returns the index of the topmost element under (x, y) in design-pixel space, the
    string "skin" if only the skin was hit, or None. Elements are tested last-first,
    approximating the draw order's z-index (later-added draws on top)."""
    if not skin:
        return None

    for index in range(len(elements) - 1, -1, -1):
        elem = elements[index]
        ex, ey = element_position(elem, skin)
        ew, eh = measure_element_box(elem, skin)
        if ex <= x <= ex + ew and ey <= y <= ey + eh:
            return index

    skin_w, skin_h = skin_pixel_size(skin)
    sx, sy = skin.get("x", 0.0), skin.get("y", 0.0)
    if sx <= x <= sx + skin_w and sy <= y <= sy + skin_h:
        return "skin"
    return None


def align_elements(elements: List[Dict[str, Any]], indices: List[int], skin: Dict[str, Any], mode: str) -> None:
    """Aligns the given elements (by index into `elements`, mutated in place) - ported
    from HUDManager.align_selected, operating on rel_x/rel_y instead of Qt item pos()."""
    if len(indices) < 2:
        return
    skin_w, skin_h = skin_pixel_size(skin)
    if not skin_w or not skin_h:
        return

    targets = [elements[i] for i in indices]
    boxes = [measure_element_box(e, skin) for e in targets]

    if mode == "h_top":
        target_y = min(e["rel_y"] for e in targets)
        for e in targets:
            e["rel_y"] = target_y
    elif mode == "h_bottom":
        bottoms = [e["rel_y"] + (h / skin_h) for e, (_, h) in zip(targets, boxes)]
        target_bottom = max(bottoms)
        for e, (_, h) in zip(targets, boxes):
            e["rel_y"] = target_bottom - (h / skin_h)
    elif mode == "h_center":
        tops = [e["rel_y"] for e in targets]
        bottoms = [e["rel_y"] + (h / skin_h) for e, (_, h) in zip(targets, boxes)]
        center_y = (min(tops) + max(bottoms)) / 2.0
        for e, (_, h) in zip(targets, boxes):
            e["rel_y"] = center_y - (h / skin_h) / 2.0
    elif mode == "v_left":
        target_x = min(e["rel_x"] for e in targets)
        for e in targets:
            e["rel_x"] = target_x
    elif mode == "v_right":
        rights = [e["rel_x"] + (w / skin_w) for e, (w, _) in zip(targets, boxes)]
        target_right = max(rights)
        for e, (w, _) in zip(targets, boxes):
            e["rel_x"] = target_right - (w / skin_w)
    elif mode == "v_center":
        lefts = [e["rel_x"] for e in targets]
        rights = [e["rel_x"] + (w / skin_w) for e, (w, _) in zip(targets, boxes)]
        center_x = (min(lefts) + max(rights)) / 2.0
        for e, (w, _) in zip(targets, boxes):
            e["rel_x"] = center_x - (w / skin_w) / 2.0
