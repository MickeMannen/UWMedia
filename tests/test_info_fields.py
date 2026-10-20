"""Values the info-screen and gauge pages show that no log records as such
(gui/hud_renderer.resolve_element_text): the running average depth, the GF
setting, the date and the ambient / surface pressure in mbar. Values are
invented."""
from datetime import datetime, timedelta

from gui.hud_renderer import resolve_element_text
from models.dive import Dive, Waypoint
from utils.hud_rules_engine import average_depth_at

LAYOUT = {"manufacturer": "Shearwater", "model": "Perdix 2"}
START = datetime(2026, 3, 1, 9, 5)


def _dive(depths, step=60, **kw):
    wps = [Waypoint(timestamp=START + timedelta(seconds=i * step), depth=d, time_since_start=i * step, dive_time=i * step)
           for i, d in enumerate(depths)]
    return Dive(start_time=wps[0].timestamp, end_time=wps[-1].timestamp, waypoints=wps, **kw)


def test_running_average_depth_is_time_weighted():
    dive = _dive([0.0, 20.0, 20.0, 10.0])
    w = dive.waypoints
    assert average_depth_at(w[0], w) == 0.0
    assert average_depth_at(w[1], w) == 10.0           # 0 -> 20 m over a minute
    assert average_depth_at(w[2], w) == 15.0           # then a minute at 20 m
    assert round(average_depth_at(w[3], w), 2) == 15.0  # 20 -> 10: 15 on that minute too
    assert average_depth_at(w[2], None) == 20.0         # no dive at hand: the depth itself
    assert resolve_element_text(LAYOUT, "avg_depth", w[2], w) == ("15.0", 15.0)


def test_gf_setting_date_and_pressure():
    dive = _dive([0.0, 10.0], gf_low=40, gf_high=85)
    wp = dive.waypoints[1]
    assert resolve_element_text(LAYOUT, "gf_setting", wp, dive.waypoints)[0] == "40/85"
    assert resolve_element_text(LAYOUT, "gf_setting", _dive([0.0]).waypoints[0])[0] == "--"
    assert resolve_element_text(LAYOUT, "date", wp)[0] == "01-Mar-26"
    assert resolve_element_text(LAYOUT, "surface_mbar", wp)[0] == "1013"
    assert resolve_element_text(LAYOUT, "ambient_mbar", wp)[0] == "2018"
