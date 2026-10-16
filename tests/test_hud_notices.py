from datetime import datetime, timedelta

import numpy as np
import pytest

from models.dive import TankData, Waypoint
from utils.hud_notices import active_notice, notice_rules, notice_style, notice_timeline


def _wp(t, depth, **kw):
    return Waypoint(timestamp=datetime(2026, 1, 1, 10) + timedelta(seconds=t), depth=depth, max_depth=max(depth, kw.pop("max_depth", depth)),
                    time_since_start=t, dive_time=t, **kw)


def _dive(samples):
    """samples: (t, depth, extra dict) at 1 s or coarser spacing."""
    return [_wp(t, d, **extra) for t, d, extra in samples]


def test_shearwater_notice_table_is_in_priority_order_and_sourced():
    rules = notice_rules("Shearwater", "Perdix 2")
    ids = [r["id"] for r in rules]
    assert ids[:4] == ["low_ppo2", "high_ppo2", "missed_stop", "fast_ascent"]
    assert "time_alert" not in ids  # off by default on the device (manual p.24)
    assert all(r.get("_source") for r in rules)
    style = notice_style("Shearwater", "Perdix 2")
    assert style["style"] == "text" and style["confirm_text"] == "Confirm" and "_source" not in style


def test_high_ppo2_needs_thirty_seconds_then_shows_for_show_seconds():
    # Perdix 2 manual p.22: HIGH PPO2 once the average PPO2 is above the limit
    # for more than 30 s; a log has no button press, so it shows for 10 s.
    samples = [(t, 30.0, {"po2": 1.8 if t >= 100 else 1.2}) for t in range(0, 200, 5)]
    wps = _dive(samples)
    tl = notice_timeline("Shearwater", "Perdix 2", wps)
    assert tl[100] is None and tl[125] is None
    assert tl[130]["text"] == "HIGH PPO2" and tl[130]["caption"] == "Warning" and tl[130]["color"] == "#FFFF00"
    assert tl[135]["id"] == "high_ppo2"
    assert tl[140] is None  # 10 s shown
    assert active_notice("Shearwater", "Perdix 2", wps[26], wps)["id"] == "high_ppo2"


def test_fast_ascent_is_sustained_and_rearms():
    samples = []
    for t in range(0, 120, 2):
        rate = 14.0 if 20 <= t < 40 or 80 <= t < 100 else 2.0
        samples.append((t, 20.0, {"ascent_rate": rate}))
    tl = notice_timeline("Shearwater", "Perdix 2", _dive(samples))
    assert tl[28] is None and tl[30]["text"] == "FAST ASCENT"
    assert tl[50] is None
    assert tl[90]["text"] == "FAST ASCENT"  # the second episode fires again


def test_low_ndl_alert_rearms_three_minutes_above_the_value():
    # Perdix 2 manual p.24: 5 min alert, resets once the NDL reaches 8 min.
    samples = [(0, 20.0, {"ndl": 600}), (10, 20.0, {"ndl": 290}), (30, 20.0, {"ndl": 280}), (40, 10.0, {"ndl": 420}),
               (50, 15.0, {"ndl": 280}), (60, 5.0, {"ndl": 500}), (70, 20.0, {"ndl": 250})]
    tl = notice_timeline("Shearwater", "Perdix 2", _dive(samples))
    assert tl[10]["text"] == "Low NDL Alert" and tl[10]["caption"] == "Alert"
    assert tl[30] is None  # shown 10 s, not re-armed (NDL never reached 8 min)
    assert tl[50] is None
    assert tl[70]["text"] == "Low NDL Alert"  # re-armed by the 500 s NDL (> 8 min) in between


def test_critical_pressure_names_the_tank_and_outranks_low_ndl():
    tanks = {"T1": TankData(pressure_bar=24.0, enabled=True)}
    samples = [(0, 20.0, {"ndl": 600}), (10, 20.0, {"ndl": 200, "tanks": tanks})]
    tl = notice_timeline("Shearwater", "Perdix 2", _dive(samples))
    # both trigger at t=10; Low NDL Alert (p.25 first column) outranks T1 CRITICAL PRES
    assert tl[10]["text"] == "Low NDL Alert"
    wp = _wp(0, 20.0, tanks=tanks)
    assert active_notice("Shearwater", "Perdix 2", wp)["text"] == "T1 CRITICAL PRES"


def test_single_waypoint_evaluation_for_forced_states():
    assert active_notice("Shearwater", "Perdix 2", _wp(0, 20.0, po2=0.15))["text"] == "LOW PPO2"
    assert active_notice("Shearwater", "Perdix 2", _wp(0, 20.0, cns=95))["text"] == "HIGH CNS"
    assert active_notice("Shearwater", "Perdix 2", _wp(0, 20.0, cns=160))["text"] == "VERY HIGH CNS"
    assert active_notice("Shearwater", "Perdix 2", _wp(0, 41.0))["text"] == "Depth Alert"
    assert active_notice("Shearwater", "Perdix 2", _wp(0, 20.0)) is None
    assert active_notice("Garmin", "mk3i", _wp(0, 20.0, dive_alerts=["ndl_reached"]))["text"] == "NDL exceeded. Decompression now required."
    assert active_notice("Garmin", "x50i", _wp(0, 20.0, dive_alerts=["ndl_reached"]))["text"] == "NDL exceeded.\nDeco required."  # two lines on the X50i
    assert active_notice("UnknownMfg", None, _wp(0, 20.0, po2=0.1)) is None


def test_garmin_fit_alerts_drive_the_notices_with_the_manual_wording():
    samples = [(0, 20.0, {}), (10, 20.0, {"dive_alerts": ["approaching_ndl"]}), (15, 20.0, {}),
               (30, 20.0, {"dive_alerts": ["cns_warning", "ascent_critical"], "cns": 80}), (45, 20.0, {})]
    tl = notice_timeline("Garmin", "mk3i", _dive(samples))
    assert tl[10]["text"] == "Approaching NDL" and tl[15]["text"] == "Approaching NDL"
    assert tl[30]["text"] == "Ascending too fast. Slow your ascent."  # listed before the CNS warning
    assert tl[45] is None


def test_teric_info_events_fire_on_state_transitions():
    # Teric manual p.26: "Deco Needed" when deco is required, "Deco Clear" once
    # it is over; p.25: "Safety Stop" when the stop starts counting.
    samples = [(0, 30.0, {"ndl": 300}), (10, 30.0, {"ndl": 60}), (20, 30.0, {"deco_stop_depth": 3.0, "next_stop_depth": 3.0, "next_stop_time": 60, "ndl": None}),
               (40, 20.0, {"deco_stop_depth": 3.0, "next_stop_depth": 3.0, "next_stop_time": 30, "ndl": None}), (60, 5.0, {"ndl": 600})]
    tl = notice_timeline("Shearwater", "Teric", _dive(samples))
    assert tl[20]["text"] == "Deco Needed" and tl[20]["caption"] == "INFO" and tl[20]["color"] == "#00ADED"
    assert tl[40] is None
    assert tl[60]["text"] == "Deco Clear" and tl[60]["color"] == "#00C800"
    assert notice_style("Shearwater", "Teric")["style"] == "banner"


def test_renderer_draws_the_notice_and_hides_covered_elements():
    from gui.hud_renderer import draw_hud
    layout = {
        "manufacturer": "Shearwater", "model": "Perdix 2", "design_width": 1920, "design_height": 1080,
        "hud_skin": {"type": "shape", "anchor": "TOP_LEFT", "ref_offset_x": 0, "ref_offset_y": 0, "width": 600, "height": 300, "scale": 1.0,
                     "color": "#000000", "linked_elements": [
                         {"field": "gasmix", "rel_x": 0.05, "rel_y": 0.6, "font_size": 60, "color": "#00FF00", "hide_when_notice": True},
                         {"field": "notice", "type": "notice", "rel_x": 0.05, "rel_y": 0.5, "width": 500, "font_size": 60, "caption_font_size": 24},
                     ]}}
    quiet = _wp(0, 20.0, po2=1.2)
    loud = _wp(0, 20.0, po2=0.1)
    f_quiet = np.zeros((1080, 1920, 3), dtype=np.uint8)
    f_loud = np.zeros((1080, 1920, 3), dtype=np.uint8)
    draw_hud(f_quiet, layout, quiet, render_log=False)
    draw_hud(f_loud, layout, loud, render_log=False)
    green = lambda f: ((f[:, :, 1] > 180) & (f[:, :, 2] < 80) & (f[:, :, 0] < 80)).sum()
    yellow = lambda f: ((f[:, :, 1] > 180) & (f[:, :, 2] > 180) & (f[:, :, 0] < 80)).sum()  # BGR
    assert green(f_quiet) > 50 and yellow(f_quiet) == 0
    assert green(f_loud) == 0 and yellow(f_loud) > 200  # LOW PPO2 in yellow, the gas hidden


def test_renderer_puts_a_low_tank_pressure_on_a_coloured_box():
    from gui.hud_renderer import draw_hud
    layout = {
        "manufacturer": "Shearwater", "model": "Perdix 2", "design_width": 1920, "design_height": 1080,
        "hud_skin": {"type": "shape", "anchor": "TOP_LEFT", "ref_offset_x": 0, "ref_offset_y": 0, "width": 600, "height": 300, "scale": 1.0,
                     "color": "#000000", "linked_elements": [
                         {"field": "primary_tank_pressure", "rel_x": 0.1, "rel_y": 0.3, "font_size": 80, "color": "#FFFFFF"}]}}
    def frame(bar):
        f = np.zeros((1080, 1920, 3), dtype=np.uint8)
        draw_hud(f, layout, _wp(0, 20.0, tanks={"T1": TankData(pressure_bar=bar, enabled=True)}), render_log=False)
        return f
    yellow = lambda f: ((f[:, :, 1] > 180) & (f[:, :, 2] > 180) & (f[:, :, 0] < 80)).sum()
    red = lambda f: ((f[:, :, 2] > 180) & (f[:, :, 1] < 80) & (f[:, :, 0] < 80)).sum()
    assert yellow(frame(150)) == 0 and red(frame(150)) == 0
    assert yellow(frame(47)) > 2000  # a filled yellow box (Perdix 2 manual p.40), not just yellow digits
    assert red(frame(23)) > 2000


def test_garmin_sidemount_pages_say_which_tank_to_breathe_from():
    """Mk3 EN-US manual p.24 / p.36, X50i p.13 / p.27: when the two sidemount
    tanks differ by more than the Switch Pressure, "Breathe from <tank>."
    appears and that tank is highlighted in blue; nothing while they are
    within the threshold, and the alert re-arms once they are again."""
    from utils.hud_rules_engine import get_rule_config, sidemount_switch_target
    rule = get_rule_config("Garmin", "mk3i", "sidemount_switch")
    assert rule["threshold_bar"] == 30.0 and rule["color"].startswith("#")
    even = {"T1": TankData(pressure_bar=150.0, name="T1", enabled=True), "T2": TankData(pressure_bar=140.0, name="T2", enabled=True)}
    skewed = {"T1": TankData(pressure_bar=100.0, name="T1", enabled=True), "T2": TankData(pressure_bar=140.0, name="T2", enabled=True)}
    assert sidemount_switch_target("Garmin", "mk3i", _wp(0, 20.0, tanks=even)) is None
    assert sidemount_switch_target("Garmin", "x50i", _wp(0, 20.0, tanks=skewed)) == "secondary"
    samples = [(0, 20.0, {"tanks": even}), (10, 20.0, {"tanks": skewed}), (15, 20.0, {"tanks": skewed}),
               (40, 20.0, {"tanks": skewed}), (50, 20.0, {"tanks": even}), (60, 20.0, {"tanks": skewed})]
    tl = notice_timeline("Garmin", "mk3i", _dive(samples))
    assert tl[0] is None
    assert tl[10]["text"] == "Breathe from T2." and tl[15]["text"] == "Breathe from T2."
    assert tl[40] is None  # shown for show_seconds, then gone although the difference remains
    assert tl[60]["text"] == "Breathe from T2."  # re-armed after the tanks were even again
    assert notice_timeline("Garmin", "x50i", _dive(samples))[10]["text"] == "Breathe from T2."  # the X50i's own notice list has it too
