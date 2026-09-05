"""
Pure logic for the HUD Designer: anchor/offset math, layout JSON (de)serialization,
element hit-testing, and alignment - ported from gui/hud_manager.py's HUDManager,
with Qt's QGraphicsScene item state replaced by plain dicts. No Toga/Qt imports here;
uwmedia/app.py owns the canvas widget and file I/O, this module owns the math.

Layout schema matches the existing hud_layout.json format (see gui/hud_manager.py's
get_layout_json/load_layout, and cli_main.py's consumption of it) exactly, so packages
saved here load in the CLI/renderer unchanged, and vice versa.
"""
from typing import Any, Dict, List, Optional, Tuple

from gui.hud_renderer import get_font
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
        entry = {
            "field": elem["field"],
            "rel_x": elem["rel_x"],
            "rel_y": elem["rel_y"],
        }
        if elem.get("type") == "graph":
            entry.update({
                "type": "graph",
                "color": elem.get("color", "#00FF00"),
                "width": elem.get("width", 300),
                "height": elem.get("height", 150),
                "marker_style": elem.get("marker_style", "dot"),
                "marker_size": elem.get("marker_size", 6),
            })
        else:
            entry.update({
                "color": elem.get("color", "#FFFFFF"),
                "font_size": elem.get("font_size", 16),
                "scale": elem.get("scale", 1.0),
            })
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


def parse_layout_elements(hud_skin: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Element dicts from a hud_skin JSON block (ported from HUDManager.load_layout's
    element loop). Does not touch the skin itself - see resolve_skin_position for that."""
    elements = []
    for element in hud_skin.get("linked_elements", []):
        field = element.get("field", "")
        if element.get("type") == "graph" or field == "depth_graph":
            elements.append({
                "field": field or "depth_graph",
                "type": "graph",
                "rel_x": element["rel_x"],
                "rel_y": element["rel_y"],
                "width": element.get("width", 300),
                "height": element.get("height", 150),
                "color": element.get("color", "#00FF00"),
                "marker_style": element.get("marker_style", "dot"),
                "marker_size": element.get("marker_size", 6),
            })
        else:
            elements.append({
                "field": field,
                "rel_x": element["rel_x"],
                "rel_y": element["rel_y"],
                "color": element.get("color", "#FFFFFF"),
                "font_size": element.get("font_size", 16),
                "scale": element.get("scale", 1.0),
            })
    return elements


def available_telemetry_fields(dive=None) -> List[str]:
    """Ported from gui_main.py's update_available_fields."""
    standard_fields = list(Waypoint.model_fields.keys())
    standard_fields += ["primary_tank_pressure", "gasmix", "safety_stop"]
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
    return field


def measure_element_box(elem: Dict[str, Any], skin: Dict[str, Any]) -> Tuple[float, float]:
    """Approximate (width, height) of an element in design pixels - graphs use their
    explicit dimensions; text elements are measured with the same PIL font metrics
    draw_hud itself uses, against the element's display name (not a live value, so the
    hit box doesn't jitter as telemetry data changes)."""
    if elem.get("type") == "graph":
        return float(elem.get("width", 300)), float(elem.get("height", 150))

    skin_scale = skin.get("scale", 1.0) if skin.get("type") != "shape" else 1.0
    font_size = max(1, int(elem.get("font_size", 16) * skin_scale * elem.get("scale", 1.0)))
    font = get_font(font_size)
    text = element_display_name(elem["field"]) or "0"
    left, top, right, bottom = font.getbbox(text)
    return float(right - left) or float(font_size), float(bottom - top) or float(font_size)


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
