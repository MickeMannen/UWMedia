"""Suunto's rules in hud_rules.json (EON Core / EON Steel Black at the brand
level, the Nautic as a model block): colours, the safety stop, the deco
window, notices, and the gauges taking the brand's ascent-rate bands. Every
value is cited in hud_rules_sources.md."""
from datetime import datetime, timedelta

import numpy as np

from gui.hud_renderer import draw_hud
from models.dive import TankData, Waypoint
from utils.hud_notices import active_notice, notice_rules, notice_style, notice_timeline
from utils.hud_rules_engine import (
    deco_stop_phase,
    get_dynamic_color,
    get_rule_config,
    safety_stop_timeline,
    tank_pressure_state,
)


def _wp(t, depth, **kw):
    return Waypoint(timestamp=datetime(2026, 1, 1, 10) + timedelta(seconds=t), depth=depth, max_depth=max(depth, kw.pop("max_depth", depth)),
                    time_since_start=t, dive_time=t, **kw)


def test_every_suunto_rule_and_notice_is_sourced():
    for model in ("EON Core", "EON Steel Black", "Nautic"):
        rules = notice_rules("Suunto", model)
        assert rules and all(r.get("_source") for r in rules)


def test_eon_colours():
    assert get_dynamic_color("Suunto", "EON Core", "ndl", 40 * 60, "#FFFFFF") == "#B1CB45"
    assert get_dynamic_color("Suunto", "EON Core", "ndl", 6000, "#FFFFFF") == "#B1CB45"
    assert get_dynamic_color("Suunto", "EON Steel Black", "po2", 1.7, "#FFFFFF") == "#FF0000"
    assert get_dynamic_color("Suunto", "EON Core", "po2", 1.4, "#FFFFFF") == "#FFFFFF"
    # yellow below the diver's own alarm (70 bar assumed), red below the built-in 50
    assert tank_pressure_state("Suunto", "EON Core", 60) == "reserve"
    assert tank_pressure_state("Suunto", "EON Core", 45) == "critical"
    assert get_dynamic_color("Suunto", "EON Core", "primary_tank_pressure", 45, "#79C8DF") == "#FF0000"


def test_nautic_overrides():
    assert get_dynamic_color("Suunto", "Nautic", "ndl", 4 * 60, "#FFFFFF") == "#FEF01D"
    assert get_dynamic_color("Suunto", "Nautic", "ndl", 40 * 60, "#FFFFFF") == "#FFFFFF"
    assert get_dynamic_color("Suunto", "Nautic", "po2", 1.5, "#FFFFFF") == "#FEF01D"
    assert get_rule_config("Suunto", "Nautic", "gf_colors")["gf_high_default"] == 85
    assert notice_style("Suunto", "Nautic")["style"] == "banner"
    assert notice_style("Suunto", "EON Core")["style"] == "box"


def test_safety_stop_counts_between_2_4_and_6_m():
    wps = [_wp(0, 20.0), _wp(60, 12.0), _wp(70, 7.0), _wp(80, 5.0), _wp(140, 5.0), _wp(150, 7.5), _wp(160, 4.0), _wp(300, 4.0)]
    tl = safety_stop_timeline("Suunto", "EON Core", wps)
    assert tl[70] == ("pending", 180)  # shown before it counts, deeper than 6 m
    assert tl[140] == ("counting", 110)  # from t=70, the step in which it entered the window
    assert tl[150][0] == "paused"  # deeper than 6 m: the timer stops
    assert tl[300] == ("complete", 0)
    assert safety_stop_timeline("Suunto", "Nautic", wps)[140] == ("counting", 110)


def test_deco_window_and_violation_follow_the_logged_ceiling():
    stop = dict(next_stop_depth=6.3, deco_stop_depth=6.3, ceiling=6.3)
    assert deco_stop_phase("Suunto", "EON Core", _wp(0, 8.0, **stop)) == "at_stop"  # inside the 3 m window
    assert deco_stop_phase("Suunto", "EON Core", _wp(0, 5.9, **stop)) == "at_stop"  # within the 0.6 m safe margin
    assert deco_stop_phase("Suunto", "EON Core", _wp(0, 5.5, **stop)) == "violation"


def test_notices():
    assert active_notice("Suunto", "EON Core", _wp(0, 30.0, po2=1.7)) is not None
    high = active_notice("Suunto", "EON Core", _wp(0, 30.0, po2=1.7))
    assert high["text"] == "pO2 high" and high["color"] == "#FF0000"
    assert active_notice("Suunto", "EON Core", _wp(0, 20.0, cns=85))["text"] == "CNS 80%"
    tank = active_notice("Suunto", "EON Core", _wp(0, 20.0, tanks={"T1": TankData(pressure_bar=40)}))
    assert tank["text"] == "Tank pressure"
    gas = active_notice("Suunto", "EON Core", _wp(0, 21.0, dive_alerts=["suunto:Gas Available"]))
    assert gas["text"] == "Change gas" and gas["color"] == "#FFFF00"
    assert active_notice("Suunto", "Nautic", _wp(0, 30.0, po2=1.7))["text"] == "PO2 HIGH"
    switch = active_notice("Suunto", "Nautic", _wp(0, 21.0, dive_alerts=["suunto:Gas Switch"]))
    assert switch["text"] == "SWITCH GAS" and switch["color"] == "#3FEBDF"


def test_fast_ascent_needs_five_seconds():
    samples = [_wp(t, 30.0 - max(0, t - 60) * 0.2) for t in range(0, 90, 1)]  # 12 m/min from t=60
    tl = notice_timeline("Suunto", "EON Core", samples)
    assert tl[62] is None
    assert any(tl[t] and tl[t]["text"] == "Ascent speed" for t in range(64, 70))


def test_segment_bar_takes_the_brand_ascent_bands():
    t0 = datetime(2026, 1, 1)
    elem = {"type": "segment_bar", "field": "ascent_rate", "rel_x": 0.0, "rel_y": 0.0, "width": 10, "height": 98,
            "segments": 5, "segment_gap": 2, "range_max": 10, "track_color": "#404040"}
    wps = [Waypoint(timestamp=t0, depth=20.0, time_since_start=0),
           Waypoint(timestamp=t0 + timedelta(seconds=10), depth=20.0 - 9.0 / 6.0, time_since_start=10)]  # 9 m/min
    layout = {"design_width": 400, "design_height": 200, "manufacturer": "Suunto", "model": "EON Core",
              "hud_skin": {"type": "shape", "width": 400, "height": 200, "anchor": "TOP_LEFT", "opacity": 0.0, "linked_elements": [elem]}}
    frame = np.zeros((200, 400, 3), dtype=np.uint8)
    draw_hud(frame, layout, wps[1], waypoints=wps, render_log=True)
    assert tuple(frame[88, 5]) == (0, 255, 255)  # BGR yellow: 8-10 m/min (EON Core manual p.15)
