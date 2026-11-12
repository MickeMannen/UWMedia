"""The Descent X50i's sidemount tank-switch cue and the display rules its
pages use (real screenshots test_data/dive_computers/screen_shots): the
pressure to breathe from turns blue, triangles march towards it, the SM
label and icons step aside, and the gases page writes % signs and
"On-Gassing"."""
from datetime import datetime, timedelta

import numpy as np

from gui.hud_renderer import (apply_value_format, draw_hud, format_telemetry_value, tank_fill_fraction,
                              tank_switch_arrow_levels, tank_switch_arrows_geometry)
from models.dive import TankData, Waypoint
from utils.hud_designer import element_defaults, element_kind, element_native_bounds, parse_layout_elements
from utils.hud_rules_engine import get_rule_config

BLUE = (0, 170, 255)
START = datetime(2025, 1, 1, 10, 0, 0)


def _wp(p1, p2, t=600):
    return Waypoint(timestamp=START + timedelta(seconds=t), depth=12.0, time_since_start=t, dive_time=t, max_depth=15.0,
                    tanks={"L": TankData(pressure_bar=p1, name="Micke01", enabled=True),
                           "R": TankData(pressure_bar=p2, name="Micke02", enabled=True)})


def _layout(elements):
    return {"manufacturer": "Garmin", "model": "x50i", "design_width": 1920, "design_height": 1080,
            "hud_skin": {"type": "shape", "width": 400, "height": 200, "color": "#000000", "opacity": 1.0,
                         "anchor": "TOP_LEFT", "ref_offset_x": 0, "ref_offset_y": 0, "scale": 1.0,
                         "linked_elements": elements}}


def _render(layout, wp):
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    draw_hud(frame, layout, wp, render_log=True)
    return frame


def _count(frame, rgb):
    r, g, b = rgb
    return int(((frame[:, :, 2] == r) & (frame[:, :, 1] == g) & (frame[:, :, 0] == b)).sum())


def test_switch_text_style_colours_the_pressure_without_a_box():
    elements = [
        {"id": "p1", "field": "primary_tank_pressure", "rel_x": 0.1, "rel_y": 0.2, "font_size": 60, "tank_switch_highlight": "primary", "tank_switch_style": "text"},
        {"id": "p2", "field": "secondary_tank_pressure", "rel_x": 0.6, "rel_y": 0.2, "font_size": 60, "tank_switch_highlight": "secondary", "tank_switch_style": "text"},
    ]
    even = _render(_layout(elements), _wp(150.0, 140.0))
    assert _count(even, BLUE) == 0  # within the switch pressure: both white
    skewed = _render(_layout(elements), _wp(115.0, 146.0))
    blue = _count(skewed, BLUE)
    assert blue > 200  # the right pressure's digits in blue...
    white = _count(skewed, (255, 255, 255))
    assert white > 200  # ...the left one still white
    # the digits, not a filled box: blue pixels are a minority of the text cell
    assert blue < 60 * 60 * 3
    # a boxed highlight (the Perdix way) still fills a box in the rule colour
    boxed = [dict(elements[1], tank_switch_style=None)]
    frame = _render(_layout(boxed), _wp(115.0, 146.0))
    assert _count(frame, BLUE) > blue


def test_hide_when_switch_and_the_arrows_follow_the_target():
    elements = [
        {"id": "sm", "field": "custom:SM", "rel_x": 0.45, "rel_y": 0.1, "font_size": 40, "color": "#999999", "hide_when_switch": True},
        {"id": "arrows", "field": "tank_switch", "type": "tank_switch_arrows", "rel_x": 0.4, "rel_y": 0.3, "width": 30, "height": 50, "gap": 10, "count": 2},
    ]
    even = _render(_layout(elements), _wp(150.0, 140.0, t=602))
    assert _count(even, (153, 153, 153)) > 50  # SM shows
    assert _count(even, BLUE) == 0            # no arrows
    right = _render(_layout(elements), _wp(115.0, 146.0, t=602))  # phase 2: both triangles lit
    assert _count(right, (153, 153, 153)) == 0  # SM steps aside
    blue_cols = np.where((right[:, :, 2] == 0) & (right[:, :, 1] == 170) & (right[:, :, 0] == 255))[1]
    assert len(blue_cols) > 500
    # pointing right: the triangles' bases are on the left, so the leftmost
    # columns are the fullest; pointing left (primary tank) it is the other way round
    left = _render(_layout(elements), _wp(146.0, 115.0, t=602))
    cols_left = np.where((left[:, :, 2] == 0) & (left[:, :, 1] == 170) & (left[:, :, 0] == 255))[1]
    def column_fill(cols, x):
        return int((cols == x).sum())
    x0, x1 = blue_cols.min(), blue_cols.max()
    assert column_fill(blue_cols, x0 + 1) > column_fill(blue_cols, x1 - 1)
    assert column_fill(cols_left, cols_left.min() + 1) < column_fill(cols_left, cols_left.max() - 1)


def test_arrow_levels_march_second_by_second():
    seen = {tuple(tank_switch_arrow_levels(t, 2)) for t in range(8)}
    assert (1.0, 0.0) in seen and (1.0, 1.0) in seen and (0.6, 0.38) in seen and (1.0, 0.6) in seen
    assert tank_switch_arrow_levels(None, 3) == [1.0, 1.0, 1.0]
    assert tank_switch_arrows_geometry({}) == (23, 44, 13, 2)


def test_designer_knows_the_arrows_element():
    elem = element_defaults("tank_switch_arrows", "depth")
    assert (elem["type"], elem["field"], elem["count"]) == ("tank_switch_arrows", "tank_switch", 2)
    assert element_kind({"type": "tank_switch_arrows"}) == "tank_switch_arrows"
    parsed, = parse_layout_elements({"linked_elements": [{"type": "tank_switch_arrows", "rel_x": 0.5, "rel_y": 0.5}]})
    assert parsed["width"] == 23 and parsed["gap"] == 13
    x0, y0, x1, y1 = element_native_bounds({"type": "tank_switch_arrows", "rel_x": 0.5, "rel_y": 0.5, "width": 20, "height": 40, "gap": 10, "count": 2}, 400, 200)
    assert (x0, y0, x1, y1) == (200, 100, 250, 140)


def test_x50i_display_rule_percent_signs_and_on_gassing():
    display = get_rule_config("Garmin", "x50i", "display")
    assert format_telemetry_value("surf_gf", 33.4, display) == "33%"
    assert format_telemetry_value("cns", 2, display) == "2%"
    assert format_telemetry_value("gf", 7.0, display) == "7%"
    assert format_telemetry_value("gf", -12.0, display) == "On-Gassing"
    assert format_telemetry_value("gf", 0, display) == "On-Gassing"
    assert format_telemetry_value("gf", None, display) == "--"
    # the Mk3i's display rule has none of it
    mk3i = get_rule_config("Garmin", "mk3i", "display")
    assert format_telemetry_value("surf_gf", 33.4, mk3i) == "33"
    assert format_telemetry_value("gf", -12.0, mk3i) == "-12"


def test_m_ss_and_the_volume_rate_formats():
    assert apply_value_format({"value_format": "m:ss", "field": "tts"}, "01:16", 76) == "1:16"
    assert apply_value_format({"value_format": "m:ss", "field": "dive_time"}, "00:00", 0) == "0:00"
    assert apply_value_format({"value_format": "m:ss", "field": "dive_time"}, "--", None) == "--"
    assert apply_value_format({"value_format": "decimal1", "field": "volume_sac"}, "11", 11.94) == "11.9"


def test_tank_icon_fill_level_follows_the_pressure():
    """Real screenshots: 117 bar fills about half the X50i's icon, 179 bar
    most of it - linear from the critical pressure to the rated one."""
    elem = {"fill_level": True, "full_bar": 207, "empty_bar": 21}
    assert abs(tank_fill_fraction(117, elem) - 20 / 39) < 0.03
    assert abs(tank_fill_fraction(179, elem) - 33 / 39) < 0.03
    assert tank_fill_fraction(207, elem) == 1.0 and tank_fill_fraction(300, elem) == 1.0
    assert tank_fill_fraction(21, elem) == 0.0 and tank_fill_fraction(5, elem) == 0.0
    assert tank_fill_fraction(None, elem) == 0.0
    assert tank_fill_fraction(100, {}) == 0.5  # defaults: 0..200 bar
    icon = {"id": "i", "field": "primary_tank_pressure", "type": "tank_icon", "rel_x": 0.2, "rel_y": 0.2, "width": 20, "height": 100, **elem}
    full = _count(_render(_layout([icon]), _wp(207.0, 207.0)), BLUE)
    half = _count(_render(_layout([icon]), _wp(114.0, 114.0)), BLUE)
    assert 0.45 * full < half < 0.55 * full
    assert _count(_render(_layout([dict(icon, fill_level=False)]), _wp(114.0, 114.0)), BLUE) == full


def test_long_alert_wraps_onto_two_lines():
    """5831.bmp: 'Breathe from Left Tank' / '(Micke01).' - as many words as
    fit on the first line, the rest on the second."""
    from PIL import Image, ImageDraw

    from gui.hud_renderer import get_font, wrap_two_lines
    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    font = get_font(45, "Roboto Condensed", "bold")
    assert wrap_two_lines(draw, "Breathe from Left Tank (Micke01).", font, 419) == ["Breathe from Left Tank", "(Micke01)."]
    assert wrap_two_lines(draw, "Low battery.", font, 419) == ["Low battery."]
    assert wrap_two_lines(draw, "Supercalifragilistic", font, 50) == ["Supercalifragilistic"]


def test_alert_box_fits_the_widest_line_not_the_longest():
    """The X50i alert box fits its font to every line in pixels: "SLOW YOUR
    ASCENT" has fewer characters than "Ascending too fast." but is wider, and
    a fit to the longest string alone ran the capitals past the border."""
    from PIL import Image, ImageDraw

    from gui.hud_renderer import _fit_font, fit_font_lines
    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    lines = ["SLOW YOUR ASCENT", "Ascending too fast."]
    width = 300
    only_longest, _ = _fit_font(draw, max(lines, key=len), 46, width, None, "bold")
    assert draw.textlength(lines[0], font=only_longest) > width  # the bug: capitals overflow
    font, size = fit_font_lines(draw, lines, 46, width, None, "bold")
    assert all(draw.textlength(line, font=font) <= width for line in lines)
    assert size < 46


def _bars_wp(load=60.0, rate=0.0):
    return Waypoint(timestamp=START, depth=12.0, time_since_start=600, dive_time=600, n2_tissue_load=load, ascent_rate=rate)


def test_tissue_bar_has_black_between_its_colours_and_a_pointer_marker():
    """Real screenshots: black space between the red, yellow and green
    segments, and a white tab pointing into the bar, ringed in black."""
    bar = {"id": "t", "field": "n2_tissue_load", "type": "tissue_bar", "rel_x": 0.25, "rel_y": 0.1, "width": 24, "height": 120,
           "marker_size": 7, "segment_gap": 4, "marker_style": "pointer"}
    frame = _render(_layout([bar]), _bars_wp(load=60.0))
    column = frame[21:141, 120].astype(int)  # down the bar's right side, clear of the marker
    kinds = []
    for b, g, r in column:
        kind = "black" if r + g + b < 60 else "red" if g < 80 else "yellow" if r > 200 else "green"
        if not kinds or kinds[-1] != kind:
            kinds.append(kind)
    assert kinds == ["red", "black", "yellow", "black", "green"]
    assert int((column.sum(axis=1) < 60).sum()) == 8  # two gaps of 4 px
    # the marker at half height (60 of 120 %): white from left of the bar to
    # its point, then the black ring, then the bar's green again
    row = frame[80, 90:124].astype(int)
    assert tuple(row[100 - 90 - 3]) == (255, 255, 255) and tuple(row[100 - 90 + 6]) == (255, 255, 255)
    assert tuple(row[100 - 90 + 11]) == (0, 0, 0)
    assert tuple(row[100 - 90 + 20]) == (0, 255, 0)
    # the old look stays the default: a dot, no pointer
    dot = _render(_layout([{k: v for k, v in bar.items() if k not in ("segment_gap", "marker_style")}]), _bars_wp(load=60.0))
    assert tuple(dot[80, 100 + 6]) == (255, 255, 255) and tuple(dot[80, 100 + 9]) != (0, 0, 0)


def test_solid_chevrons_nest_and_the_ones_at_the_bar_are_flat():
    """Real screenshots: thick grey chevrons with a thin black line between
    them, the lowest one and the descent one flat against the white bar."""
    from gui.hud_renderer import CHEVRON_SOLID_UNLIT, solid_chevron_layout
    shapes, total = solid_chevron_layout(4, 1, True)
    assert [(d, k) for d, k, _, _ in shapes] == [("up", "chevron")] * 3 + [("up", "flat"), ("bar", "bar"), ("down", "flat")]
    assert total == 95.5
    assert [(d, k) for d, k, _, _ in solid_chevron_layout(6, 0, False)[0]] == [("up", "chevron")] * 6

    chevrons = {"id": "a", "field": "ascent_rate", "type": "ascent_chevrons", "style": "solid", "rel_x": 0.25, "rel_y": 0.1,
                "width": 24, "height": 96, "up_count": 4, "down_count": 1}
    level = _render(_layout([chevrons]), _bars_wp(rate=0.0))
    grey = _count(level, CHEVRON_SOLID_UNLIT)
    box = 24 * 96
    assert grey > 0.6 * box  # mostly filled: thick chevrons, thin gaps
    thin = _count(_render(_layout([dict(chevrons, style=None)]), _bars_wp(rate=0.0)), (138, 138, 138))
    assert thin < 0.75 * grey
    # flat against the bar: the grey just above and below it spans the full width
    bar_rows = np.where(np.all(level[20:117, 100:124] == 255, axis=(1, 2)))[0] + 20
    assert len(bar_rows) >= 4
    for y in (bar_rows[0] - 5, bar_rows[-1] + 5):
        assert np.all(level[y, 101:124] == CHEVRON_SOLID_UNLIT[0])
    # ascending: the chevron next to the bar lights, in the rate's colour
    rising = _render(_layout([chevrons]), _bars_wp(rate=3.0))
    assert tuple(rising[bar_rows[0] - 5, 112]) == (0, 255, 0)
    assert _count(rising, CHEVRON_SOLID_UNLIT) < grey
    # descending: the one under the bar turns white
    sinking = _render(_layout([chevrons]), _bars_wp(rate=-5.0))
    assert tuple(sinking[bar_rows[-1] + 5, 112]) == (255, 255, 255)


def test_x50i_writes_air_in_lower_case_and_other_brands_keep_capitals():
    rule = get_rule_config("Garmin", "x50i", "display")
    assert format_telemetry_value("gasmix", "AIR", rule) == "Air"
    assert format_telemetry_value("gasmix", "Nx32", rule) == "Nx32"
    assert format_telemetry_value("gasmix", "AIR", get_rule_config("Shearwater", "Perdix 2", "display")) == "AIR"
    assert format_telemetry_value("gasmix", "AIR") == "AIR"


def test_ndl_plus_sign_takes_the_elements_scale_and_offset():
    """Real screenshots: the "+" after 99 is about half the digits' size,
    level with their top and a little clear of them."""
    from gui.hud_renderer import SMALL_SUFFIX_DEFAULT_SCALE, text_parts
    assert text_parts("ndl", "99+", {}) == ("99", "+", SMALL_SUFFIX_DEFAULT_SCALE)
    assert text_parts("ndl", "99+", {"small_suffix_scale": 0.47}) == ("99", "+", 0.47)
    ndl = {"id": "n", "field": "ndl", "rel_x": 0.1, "rel_y": 0.2, "font_size": 80, "font_weight": "bold", "outline": False}
    wp = Waypoint(timestamp=START, depth=12.0, time_since_start=600, dive_time=600, ndl=7000)

    def plus_box(elem):
        frame = _render(_layout([elem]), wp)
        digits = np.where(np.all(_render(_layout([dict(elem, field="custom:99")]), wp) > 200, axis=2))
        ys, xs = np.where(np.all(frame[:, digits[1].max() + 2:] > 200, axis=2))
        return xs.min(), ys.min(), xs.max() - xs.min() + 1, digits[0].min()

    _, small_top, small_w, digits_top = plus_box(ndl)
    x, top, width, digits_top = plus_box(dict(ndl, small_suffix_scale=0.5))
    assert width > 1.25 * small_w
    assert abs(int(top) - int(digits_top)) <= 2  # level with the top of the digits
    moved_x, *_ = plus_box(dict(ndl, small_suffix_scale=0.5, small_suffix_dx=6))
    assert moved_x == x + 6


def test_stop_box_draws_its_arrow_and_right_aligns_the_depth():
    """4570.bmp: STOP at the left, a bar over an arrow and the stop depth at
    the right - the arrow drawn, so a face without the glyph shows no box."""
    from gui.hud_renderer import stop_arrow_shapes
    bar, head, stem = stop_arrow_shapes(100.0, 10.0, 30.0)
    assert max(x for x, _ in bar) == 100.0 and min(y for _, y in bar) == 10.0
    assert max(y for _, y in stem) == 40.0  # as tall as the digits
    assert min(x for x, _ in head) == min(x for x, _ in bar)

    badge = {"id": "b", "field": "state_badge", "type": "badge", "style": "box", "rel_x": 0.1, "rel_y": 0.1, "width": 212, "height": 86,
             "font_size": 34, "font_family": "Roboto Condensed", "value_font_size": 50, "depth_font_size": 46, "font_weight": "bold",
             "depth_unit": "m", "fill_colors": {"safety_stop": "#00FA00"}, "text_color": "#000000", "padding": 5}
    stop = Waypoint(timestamp=START, depth=5.0, time_since_start=1200, dive_time=1200, max_depth=20.0)
    frame = _render(_layout([badge]), stop)
    box = frame[20:106, 40:252]
    assert (box[:, :, 1] > 200).mean() > 0.5  # the green box
    dark = np.where(box.sum(axis=2) < 120)
    assert dark[1].max() > 212 - 12  # the depth reaches the right edge...
    assert dark[1].min() < 20        # ...and the label the left
    top_row = box[:40].sum(axis=2) < 120
    gap = np.where(~top_row.any(axis=0)[20:192])[0]
    assert len(gap) > 30  # with clear green between them
