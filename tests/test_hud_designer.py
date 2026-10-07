"""utils/hud_designer.py: anchor math for all nine anchors, legacy
x_pct/y_pct positioning, parsing defaults, telemetry field lists and display
names, element boxes/native bounds per kind (tissue bar, chevrons, tank
icons, badges, vertical and suffixed text), hit-testing by bounds and the
six alignment modes. Font-dependent sizes are compared relatively, never
as exact pixel widths, since fonts differ per OS."""
from types import SimpleNamespace

import pytest

from gui.hud_renderer import (
    ascent_chevron_geometry,
    get_font,
    tank_outline_metrics,
    tank_segments_geometry,
    tissue_bar_geometry,
)
from utils.hud_designer import (
    align_elements,
    available_telemetry_fields,
    element_defaults,
    element_display_name,
    element_kind,
    element_native_bounds,
    measure_element_box,
    parse_layout_elements,
    resolve_anchor_position,
    resolve_skin_position,
    skin_pixel_size,
)

VIEW_W, VIEW_H = 1920.0, 1080.0
SKIN_W, SKIN_H = 400.0, 200.0


# --- anchor math -----------------------------------------------------------

@pytest.mark.parametrize("anchor, expected", [
    ("TOP_LEFT", (10.0, 20.0)),
    ("TOP_CENTER", (VIEW_W / 2 + 10 - SKIN_W / 2, 20.0)),
    ("TOP_RIGHT", (VIEW_W + 10 - SKIN_W, 20.0)),
    ("MIDDLE_LEFT", (10.0, VIEW_H / 2 + 20 - SKIN_H / 2)),
    # "CENTER" is centred horizontally only, like the renderer
    # (gui/hud_renderer.py) and utils/overlay_document.py place it
    ("CENTER", (VIEW_W / 2 + 10 - SKIN_W / 2, 20.0)),
    ("MIDDLE_RIGHT", (VIEW_W + 10 - SKIN_W, VIEW_H / 2 + 20 - SKIN_H / 2)),
    ("BOTTOM_LEFT", (10.0, VIEW_H + 20 - SKIN_H)),
    ("BOTTOM_CENTER", (VIEW_W / 2 + 10 - SKIN_W / 2, VIEW_H + 20 - SKIN_H)),
    ("BOTTOM_RIGHT", (VIEW_W + 10 - SKIN_W, VIEW_H + 20 - SKIN_H)),
])
def test_resolve_anchor_position_per_anchor(anchor, expected):
    assert resolve_anchor_position(anchor, 10.0, 20.0, VIEW_W, VIEW_H, SKIN_W, SKIN_H) == pytest.approx(expected)


def test_resolve_skin_position_uses_anchor_offset_or_legacy_percent():
    anchored = {"anchor": "BOTTOM_RIGHT", "ref_offset_x": -5.0, "ref_offset_y": -7.0}
    assert resolve_skin_position(anchored, SKIN_W, SKIN_H, VIEW_W, VIEW_H) == pytest.approx(
        (VIEW_W - 5 - SKIN_W, VIEW_H - 7 - SKIN_H))
    # anchor defaults to TOP_LEFT
    assert resolve_skin_position({"ref_offset_x": 3, "ref_offset_y": 4}, SKIN_W, SKIN_H, VIEW_W, VIEW_H) == (3, 4)
    # only one offset present -> legacy percentages
    legacy = {"ref_offset_x": 3, "x_pct": 0.25, "y_pct": 0.5}
    assert resolve_skin_position(legacy, SKIN_W, SKIN_H, VIEW_W, VIEW_H) == pytest.approx((480.0, 540.0))
    assert resolve_skin_position({}, SKIN_W, SKIN_H, VIEW_W, VIEW_H) == (0.0, 0.0)


def test_skin_pixel_size_for_shape_and_image():
    assert skin_pixel_size({"type": "shape"}) == (400.0, 200.0)
    assert skin_pixel_size({"type": "shape", "width": 50, "height": 60}) == (50.0, 60.0)
    assert skin_pixel_size({"native_width": 100, "native_height": 40, "scale": 1.5}) == (150.0, 60.0)
    assert skin_pixel_size({"native_width": None, "native_height": None}) == (0.0, 0.0)


# --- layout JSON -----------------------------------------------------------

def test_parse_layout_elements_fills_missing_fields_per_kind():
    hud = {"linked_elements": [
        {"type": "graph", "rel_x": 0, "rel_y": 0},
        {"type": "badge", "rel_x": 0, "rel_y": 0},
        {"type": "tank_icon", "rel_x": 0, "rel_y": 0},
        {"type": "tissue_bar", "rel_x": 0, "rel_y": 0},
        {"type": "ascent_chevrons", "rel_x": 0, "rel_y": 0},
        {"rel_x": 0.3, "rel_y": 0.4},
    ]}
    graph, badge, tank, tissue, chev, text = parse_layout_elements(hud)
    assert graph["field"] == "depth_graph" and graph["marker_size"] == 6
    assert badge["field"] == "state_badge"
    assert tank["field"] == "primary_tank_pressure" and tank["corner_radius"] == 4
    assert tissue["field"] == "n2_tissue_load" and tissue["height"] == 33
    assert chev["field"] == "ascent_rate" and chev["down_count"] == 1
    assert text["field"] == "" and text["color"] == "#FFFFFF"
    assert parse_layout_elements({}) == []


def test_element_defaults_for_bar_and_chevrons_pick_their_own_field():
    tissue = element_defaults("tissue_bar", "depth")
    chev = element_defaults("ascent_chevrons", "depth")
    assert (tissue["field"], tissue["type"]) == ("n2_tissue_load", "tissue_bar")
    assert (chev["field"], chev["up_count"]) == ("ascent_rate", 4)
    assert element_kind({"type": "tissue_bar"}) == "tissue_bar"
    assert element_kind({"type": "unknown"}) == "text"


# --- fields and names ------------------------------------------------------

def test_available_telemetry_fields_without_and_with_dive():
    base = available_telemetry_fields()
    assert base == sorted(base)
    assert "tanks" not in base
    for f in ("depth", "gasmix", "time_of_day", "primary_tank_pressure"):
        assert f in base
    dive = SimpleNamespace(waypoints=[SimpleNamespace(tanks={"T2": 1, "T1": 1}), SimpleNamespace(tanks={"T1": 1})])
    fields = available_telemetry_fields(dive)
    assert fields[:len(base)] == base
    assert fields[len(base):] == ["tank_pressure:T1", "tank_name:T1", "tank_pressure:T2", "tank_name:T2"]
    assert available_telemetry_fields(SimpleNamespace(waypoints=[])) == base


@pytest.mark.parametrize("field, name", [
    ("custom:Hello", "Hello"),
    ("tank_pressure:T1", "T1 (Bar)"),
    ("tank_name:Deco", "Deco"),
    ("depth_graph", "Depth Graph"),
    ("state_badge", "State Badge"),
    ("time_of_day", "Time of Day"),
    ("depth", "depth"),
])
def test_element_display_name(field, name):
    assert element_display_name(field) == name


# --- measure_element_box ---------------------------------------------------

def test_measure_element_box_graph_uses_explicit_size():
    assert measure_element_box({"type": "graph", "field": "x"}, {}) == (300.0, 150.0)
    assert measure_element_box({"type": "graph", "field": "x", "width": 10, "height": 20}, {}) == (10.0, 20.0)


def test_measure_element_box_text_scales_with_skin_and_element_scale():
    elem = {"field": "depth", "font_size": 20}
    w1, h1 = measure_element_box(elem, {"type": "image", "scale": 1.0}, text="12.3")
    w2, h2 = measure_element_box(elem, {"type": "image", "scale": 2.0}, text="12.3")
    w3, _ = measure_element_box({**elem, "scale": 2.0}, {"type": "shape", "scale": 5.0}, text="12.3")
    assert w1 > 0 and h1 > 0
    assert w2 == pytest.approx(2 * w1, rel=0.2) and h2 > h1
    # shape skins ignore their own scale
    assert w3 == pytest.approx(w2, rel=0.05)
    # display name is the fallback text
    assert measure_element_box({"field": "custom:abcdefghij"}, {}) > measure_element_box({"field": "custom:a"}, {})


def test_measure_element_box_vertical_and_blank_text():
    flat = measure_element_box({"field": "depth", "font_size": 20}, {}, text="ABCDEF")
    up = measure_element_box({"field": "depth", "font_size": 20, "orientation": "up"}, {}, text="ABCDEF")
    stacked = measure_element_box({"field": "depth", "font_size": 20, "orientation": "stacked"}, {}, text="ABCDEF")
    assert up[1] > up[0] and up[1] == pytest.approx(flat[0], abs=1)
    assert stacked[1] > flat[1] * 4
    # a stacked blank has no ink width -> the font size stands in, never 0
    w, h = measure_element_box({"field": "depth", "font_size": 20, "orientation": "stacked"}, {}, text=" ")
    assert w > 0 and h > 0


# --- element_native_bounds -------------------------------------------------

def test_native_bounds_graph_tissue_bar_and_chevrons():
    assert element_native_bounds({"type": "graph", "rel_x": 0.5, "rel_y": 0.25}, 200, 100) == (100, 25, 400, 175)
    tissue = {"type": "tissue_bar", "rel_x": 0.1, "rel_y": 0.1, "width": 10, "height": 40, "marker_size": 5}
    w, h, r = tissue_bar_geometry(tissue)
    assert element_native_bounds(tissue, 100, 100) == (10 - r, 10, 10 + w, 10 + h + r)
    chev = {"type": "ascent_chevrons", "rel_x": 0.0, "rel_y": 0.5, "width": 16, "height": 47}
    cw, ch, _, _ = ascent_chevron_geometry(chev)
    assert element_native_bounds(chev, 100, 100) == (0, 50, cw, 50 + ch)


def test_native_bounds_tank_icon_plain_outlined_and_segments():
    plain = {"type": "tank_icon", "rel_x": 0.5, "rel_y": 0.5, "width": 20, "height": 30}
    assert element_native_bounds(plain, 100, 100) == (50, 50, 70, 80)

    outlined = {**plain, "draw_outline": True}
    gap, stroke, cap_h = tank_outline_metrics(outlined)
    x0, y0, x1, y1 = element_native_bounds(outlined, 100, 100)
    pad = gap + stroke
    assert (x0, x1, y1) == (50 - pad, 70 + pad, 80 + pad)
    assert y0 == 50 - pad - cap_h + stroke
    assert x0 < 50 and y0 < 50  # the outline grows the box

    seg = {"type": "tank_icon", "style": "segments", "rel_x": 0.0, "rel_y": 0.0, "width": 12, "height": 23,
           "segments": 3, "segment_gap": 2}
    n, sgap, _, spad, sstroke, nose, nub = tank_segments_geometry(seg)
    assert n == 3
    bx0, by0, bx1, by1 = element_native_bounds(seg, 100, 100)
    assert (bx0, by0) == (-spad - sstroke, -spad - sstroke)
    assert bx1 == 3 * 12 + 2 * sgap + spad + sstroke + nose + nub
    assert by1 == 23 + spad + sstroke


def test_native_bounds_badge_box_and_text_badge():
    box = {"type": "badge", "style": "box", "rel_x": 0.0, "rel_y": 0.0}
    assert element_native_bounds(box, 100, 100) == (0, 0, 80, 44)
    assert element_native_bounds({**box, "width": 10, "height": 5}, 100, 100) == (0, 0, 10, 5)

    badge = {"type": "badge", "field": "state_badge", "rel_x": 0.5, "rel_y": 0.5, "font_size": 16, "value_font_size": 32}
    x0, y0, x1, y1 = element_native_bounds(badge, 200, 200)
    assert y0 == 100 and y1 == 100 + int(16 * 1.2)  # one placeholder label line
    assert x0 >= 100 - 2 and x1 > x0

    lines = [("STOP", None, False), ("3:00", None, True)]
    top = element_native_bounds(badge, 200, 200, badge_lines=lines)
    block_h = int(16 * 1.2) + int(32 * 1.2)
    assert (top[1], top[3]) == (100, 100 + block_h)
    mid = element_native_bounds({**badge, "valign": "middle"}, 200, 200, badge_lines=lines)
    assert mid[1] == 100 - block_h // 2
    bottom = element_native_bounds({**badge, "valign": "bottom"}, 200, 200, badge_lines=lines)
    assert bottom[3] == 100
    right = element_native_bounds({**badge, "align": "right"}, 200, 200, badge_lines=lines)
    assert right[2] == pytest.approx(100, abs=1) and right[0] < 100


def test_native_bounds_badge_with_only_blank_lines_falls_back_to_label_size():
    badge = {"type": "badge", "rel_x": 0.0, "rel_y": 0.0, "font_size": 16}
    # An empty line list is falsy -> placeholder; a list of blank strings
    # measures an empty ink box, not inf.
    x0, _, x1, _ = element_native_bounds(badge, 100, 100, badge_lines=[("", None, False)])
    assert x0 != float("inf") and x1 >= x0


def test_native_bounds_text_alignment_moves_box_onto_anchor():
    elem = {"field": "depth", "rel_x": 0.5, "rel_y": 0.5, "font_size": 30}
    left = element_native_bounds(elem, 200, 200, text="12.3")
    right = element_native_bounds({**elem, "align": "right"}, 200, 200, text="12.3")
    center = element_native_bounds({**elem, "align": "center", "valign": "middle"}, 200, 200, text="12.3")
    width = left[2] - left[0]
    assert width > 0
    assert right[2] == pytest.approx(100, abs=0.5)
    assert right[2] - right[0] == pytest.approx(width)
    assert (center[0] + center[2]) / 2 == pytest.approx(100, abs=0.5)
    assert (center[1] + center[3]) / 2 == pytest.approx(100, abs=0.5)
    # display name stands in for a missing value
    named = element_native_bounds({**elem, "field": "custom:LongLabelText"}, 200, 200)
    assert named[2] - named[0] > width


def test_native_bounds_vertical_text():
    elem = {"field": "depth", "rel_x": 0.0, "rel_y": 0.0, "font_size": 20, "orientation": "up"}
    x0, y0, x1, y1 = element_native_bounds(elem, 100, 100, text="ABCDEF")
    assert (x0, y0) == (0, 0)
    assert y1 - y0 > x1 - x0
    bx0, by0, bx1, by1 = element_native_bounds({**elem, "align": "right", "valign": "bottom"}, 100, 100, text="ABCDEF")
    assert (bx1, by1) == pytest.approx((0, 0))


def test_native_bounds_text_suffix_widens_box_and_keeps_alignment():
    elem = {"field": "ndl", "rel_x": 0.5, "rel_y": 0.5, "font_size": 30}
    plain = element_native_bounds(elem, 200, 200, text="99")
    plus = element_native_bounds(elem, 200, 200, text="99+")
    assert plus[2] > plain[2] and plus[0] == pytest.approx(plain[0])
    right = element_native_bounds({**elem, "align": "right"}, 200, 200, text="99+")
    assert right[2] == pytest.approx(100, abs=0.5)
    center = element_native_bounds({**elem, "align": "center"}, 200, 200, text="99+")
    assert (center[0] + center[2]) / 2 == pytest.approx(100, abs=0.5)


# --- hit testing -----------------------------------------------------------

def _skin():
    return {"type": "shape", "width": 400, "height": 200, "x": 100.0, "y": 50.0}


# --- alignment -------------------------------------------------------------

def _graphs():
    # skin 400x200; boxes 40x20 and 80x40 -> 0.1x0.1 and 0.2x0.2 relative
    return [
        {"type": "graph", "field": "a", "rel_x": 0.1, "rel_y": 0.1, "width": 40, "height": 20},
        {"type": "graph", "field": "b", "rel_x": 0.5, "rel_y": 0.6, "width": 80, "height": 40},
        {"type": "graph", "field": "c", "rel_x": 0.9, "rel_y": 0.9, "width": 40, "height": 20},
    ]


@pytest.mark.parametrize("mode, key, expected", [
    ("h_top", "rel_y", (0.1, 0.1)),
    ("h_bottom", "rel_y", (0.7, 0.6)),
    ("h_center", "rel_y", (0.4, 0.35)),
    ("v_left", "rel_x", (0.1, 0.1)),
    ("v_right", "rel_x", (0.6, 0.5)),
    ("v_center", "rel_x", (0.35, 0.3)),
])
def test_align_elements_modes(mode, key, expected):
    elements = _graphs()
    align_elements(elements, [0, 1], _skin(), mode)
    assert (elements[0][key], elements[1][key]) == pytest.approx(expected)
    assert elements[2]["rel_x"] == 0.9 and elements[2]["rel_y"] == 0.9  # not selected


def test_align_elements_noops():
    elements = _graphs()
    before = [dict(e) for e in elements]
    align_elements(elements, [0], _skin(), "h_top")
    align_elements(elements, [0, 1], {"type": "shape", "width": 0, "height": 200}, "h_top")
    align_elements(elements, [0, 1], _skin(), "unknown_mode")
    assert elements == before


def test_get_font_is_cached_per_size():
    assert get_font(17) is get_font(17)


def test_hit_test_bounds_topmost_with_slack():
    from utils.hud_designer import hit_test_bounds
    boxes = [(0, 0, 100, 100), (50, 50, 60, 60)]
    assert hit_test_bounds(55, 55, boxes) == 1
    assert hit_test_bounds(61.5, 55, boxes) == 1        # within the 2 px slack
    assert hit_test_bounds(61.5, 55, boxes, slack=0) == 0
    assert hit_test_bounds(103, 50, boxes) is None
    assert hit_test_bounds(0, 0, []) is None
