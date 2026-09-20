"""utils/hud_designer.py additions for the Overlay Designer (overlay_rework.md
Phase 2): element kinds/defaults, schema-v2 key carry-through, native-pixel
bounds that mirror the renderer, and bounds hit-testing."""
from gui.hud_renderer import get_font, text_anchor_shift
from utils.hud_designer import (
    build_layout_json,
    element_defaults,
    element_kind,
    element_native_bounds,
    hit_test_bounds,
    measure_element_box,
    parse_layout_elements,
)


def test_element_kind_covers_legacy_graph_and_typed_elements():
    assert element_kind({"field": "depth"}) == "text"
    assert element_kind({"field": "depth_graph"}) == "graph"
    assert element_kind({"field": "x", "type": "graph"}) == "graph"
    assert element_kind({"field": "state_badge", "type": "badge"}) == "badge"
    assert element_kind({"field": "primary_tank_pressure", "type": "tank_icon"}) == "tank_icon"


def test_element_defaults_per_kind_are_centred_and_renderable():
    for kind in ("text", "badge", "tank_icon", "graph"):
        elem = element_defaults(kind, "depth")
        assert (elem["rel_x"], elem["rel_y"]) == (0.5, 0.5)
        assert element_kind(elem) == kind
    assert "type" not in element_defaults("text", "depth")
    assert element_defaults("graph", "depth_graph")["ceiling_color"] == "#808080"


def test_parse_and_build_carry_unknown_keys_through():
    skin = {
        "type": "image", "native_width": 100, "native_height": 50, "scale": 1.0,
        "anchor": "TOP_LEFT", "x": 0.0, "y": 0.0, "path": "skin.png",
        "linked_elements": [
            {"field": "depth", "rel_x": 0.1, "rel_y": 0.2, "align": "right", "font_family": "Roboto", "outline": False},
            {"field": "state_badge", "type": "badge", "rel_x": 0.3, "rel_y": 0.4, "font_size": 20, "value_font_size": 44},
            {"field": "depth_graph", "type": "graph", "rel_x": 0.0, "rel_y": 0.0, "ceiling_color": "#123456"},
        ],
    }
    parsed = parse_layout_elements(skin)
    assert parsed[0]["align"] == "right" and parsed[0]["font_family"] == "Roboto" and parsed[0]["outline"] is False
    assert parsed[0]["color"] == "#FFFFFF"  # default filled in
    assert parsed[1]["value_font_size"] == 44
    assert parsed[2]["ceiling_color"] == "#123456" and parsed[2]["marker_style"] == "dot"

    rebuilt = build_layout_json(skin, parsed, "Generic", "", 1920, 1080)["hud_skin"]["linked_elements"]
    assert rebuilt[0]["align"] == "right" and rebuilt[0]["font_family"] == "Roboto" and rebuilt[0]["outline"] is False
    assert rebuilt[1]["value_font_size"] == 44
    assert rebuilt[2]["ceiling_color"] == "#123456"
    assert "uid" not in rebuilt[0]


def test_graph_and_tank_icon_bounds_are_exact():
    graph = {"field": "depth_graph", "type": "graph", "rel_x": 0.1, "rel_y": 0.5, "width": 300, "height": 150}
    assert element_native_bounds(graph, 1000, 200) == (100.0, 100.0, 400.0, 250.0)
    icon = {"field": "primary_tank_pressure", "type": "tank_icon", "rel_x": 0.0, "rel_y": 0.0, "width": 19, "height": 34}
    assert element_native_bounds(icon, 500, 500) == (0.0, 0.0, 19.0, 34.0)


def test_text_bounds_follow_align_and_font_size():
    elem = {"field": "depth", "rel_x": 0.5, "rel_y": 0.5, "font_size": 60, "scale": 1.0}
    x0, y0, x1, y1 = element_native_bounds(elem, 400, 200, text="24.0")
    font = get_font(60)
    left, top, right, bottom = font.getbbox("24.0")
    assert (x0, y0, x1, y1) == (200 + left, 100 + top, 200 + right, 100 + bottom)

    right_aligned = dict(elem, align="right", valign="bottom")
    rx0, ry0, rx1, ry1 = element_native_bounds(right_aligned, 400, 200, text="24.0")
    assert abs(rx1 - 200) < 0.01 and abs(ry1 - 100) < 0.01  # ink right/bottom edges on the anchor
    assert (rx1 - rx0, ry1 - ry0) == (x1 - x0, y1 - y0)  # same size

    scaled = dict(elem, scale=2.0)
    sx0, _, sx1, _ = element_native_bounds(scaled, 400, 200, text="24.0")
    assert (sx1 - sx0) > (x1 - x0)


def test_badge_bounds_use_lines_and_fall_back_to_placeholder():
    elem = {"field": "state_badge", "type": "badge", "rel_x": 0.0, "rel_y": 0.0, "font_size": 20, "value_font_size": 40}
    lines = [("DECO", (255, 0, 0), False), ("↑6", (255, 0, 0), True), ("03:00", (255, 0, 0), True)]
    x0, y0, x1, y1 = element_native_bounds(elem, 500, 500, badge_lines=lines)
    assert y0 == 0.0 and y1 == int(20 * 1.2) + 2 * int(40 * 1.2)
    assert x1 > x0 > -5
    px0, py0, px1, py1 = element_native_bounds(elem, 500, 500)  # no lines -> placeholder label
    assert py1 - py0 == int(20 * 1.2) and px1 > px0


def test_hit_test_bounds_topmost_with_slack():
    bounds = [(0, 0, 100, 100), (50, 50, 150, 150)]
    assert hit_test_bounds(75, 75, bounds) == 1  # later-drawn wins
    assert hit_test_bounds(10, 10, bounds) == 0
    assert hit_test_bounds(151, 151, bounds, slack=2.0) == 1
    assert hit_test_bounds(160, 160, bounds) is None
    assert hit_test_bounds(10, 10, []) is None


def test_measure_element_box_uses_given_text():
    elem = {"field": "depth", "font_size": 40, "scale": 1.0}
    short_w, _ = measure_element_box(elem, {"type": "shape"}, text="1")
    long_w, _ = measure_element_box(elem, {"type": "shape"}, text="123.4")
    assert long_w > short_w


def test_text_anchor_shift_zero_for_defaults():
    font = get_font(30)
    dx, dy, bbox = text_anchor_shift(font, "12.3", "left", "top")
    assert (dx, dy) == (0.0, 0.0) and len(bbox) == 4
