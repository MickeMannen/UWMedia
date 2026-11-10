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
