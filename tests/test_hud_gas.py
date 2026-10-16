"""simulator.md A6: values a computer shows that no log records - GF99 and
SurfGF from the deco engine, the MOD of the breathed gas, a Shearwater's GTR
from the pressure trend, and the persistent notifications built on them."""
from datetime import datetime, timedelta

import numpy as np

from models.dive import Dive, TankData, Waypoint
from utils.deco_engine import BuhlmannEngine, DiveDecompressor, GasDefinition
from utils.hud_gas import gas_time_remaining, mod_metres
from utils.hud_notices import active_persistent_notice


def _wp(t, depth, bar=200.0, o2=32.0, **kw):
    return Waypoint(timestamp=datetime(2026, 1, 1, 10) + timedelta(seconds=t), depth=depth, max_depth=max(depth, kw.pop("max_depth", depth)),
                    time_since_start=t, dive_time=t, tanks={"T1": TankData(pressure_bar=bar, o2_percent=o2, name="T1")}, **kw)


def test_gradient_factor_is_zero_fresh_and_grows_with_loading():
    e = BuhlmannEngine()
    assert e.gradient_factor(e.surface_pressure) == 0.0  # saturated at the surface: tissue tension equals ambient
    e.update(30.0, 20 * 60, 0.21, 0.0)  # 20 min at 30 m on air
    gf99 = e.gradient_factor(e.surface_pressure + 3.0)
    surf = e.gradient_factor(e.surface_pressure)
    assert gf99 == 0.0  # at depth the tissues are still below ambient: on-gassing
    assert 60 < surf < 130  # surfacing now would be a real supersaturation
    e.update(5.0, 3 * 60, 0.21, 0.0)  # a safety stop lowers SurfGF
    assert e.gradient_factor(e.surface_pressure) < surf


def test_deco_pass_fills_gf99_and_surf_gf_instead_of_the_placeholder():
    wps = [{"divetime": t, "datetime": datetime(2026, 1, 1, 10) + timedelta(seconds=t), "depth": 30.0 if 60 <= t <= 1500 else 0.0}
           for t in range(0, 1800, 10)]
    res = DiveDecompressor(simulation_interval=10).process_waypoints(wps, [GasDefinition("AIR", 0.21, 0.0, 56.0)])
    bottom = res[1200]
    assert bottom.gf_current == 0.0 and bottom.surf_gf > 50  # not the old gf_high placeholder (70)
    surface = res[1790]
    assert surface.gf_current > 0 and abs(surface.gf_current - surface.surf_gf) < 0.2  # at the surface the two coincide


def test_mod_from_the_gas_and_the_brand_limit():
    # Perdix 2 manual p.62: OC MOD PPO2 1.40 -> Nx32 MOD 33.75 m, air 56.7 m
    assert abs(mod_metres("Shearwater", "Perdix 2", _wp(0, 20.0, o2=32.0)) - 33.75) < 0.01
    assert abs(mod_metres("Shearwater", "Perdix 2", _wp(0, 20.0, o2=21.0)) - 56.67) < 0.01
    assert mod_metres("Shearwater", "Perdix 2", Waypoint(timestamp=datetime.now(), depth=20.0, time_since_start=0)) is None


def test_persistent_mod_notices_follow_the_depth():
    assert active_persistent_notice("Shearwater", "Perdix 2", _wp(0, 20.0)) is None
    near = active_persistent_notice("Shearwater", "Perdix 2", _wp(0, 32.5))  # within 1.9 m below the 33.75 m MOD
    assert near["id"] == "near_mod" and near["text"] == "MOD\n34m" and near["color"] == "#FFFF00"
    over = active_persistent_notice("Shearwater", "Perdix 2", _wp(0, 35.0))
    assert over["id"] == "mod_exceeded" and over["text"] == "MOD\n34m\n↑" and over["color"] == "#FF0000"
    cns = active_persistent_notice("Shearwater", "Perdix 2", _wp(0, 35.0, cns=101))
    assert cns["id"] == "high_cns_box"  # listed first: it outranks the MOD box


def test_shearwater_gtr_from_the_pressure_trend():
    # Perdix 2 manual p.44-45: SAC over the last two minutes at 1 ATA; gas
    # after the reserve (50 bar) and a 10 m/min ascent, over SAC x Pamb.
    # 1.4 bar/min at 1 ATA at 20 m (3 ATA): the tank drops 4.2 bar/min.
    wps = [_wp(t, 20.0, bar=200.0 - 4.2 * t / 60.0) for t in range(0, 301, 10)]
    assert gas_time_remaining("Shearwater", "Perdix 2", wps[6], wps) is None  # 60 s: still "wait"
    gtr = gas_time_remaining("Shearwater", "Perdix 2", wps[-1], wps)
    pressure = 200.0 - 4.2 * 5
    p_ascent = 1.4 * 2.0 * 2.0  # 2 min of ascent at the mean of 3 and 1 ATA
    expected = (pressure - 50.0 - p_ascent) / (1.4 * 3.0) * 60
    assert abs(gtr - expected) < 60
    # not for a Descent (its ATR is logged), not during deco
    assert gas_time_remaining("Garmin", "mk3i", wps[-1], wps) is None
    deco = [w.model_copy(update={"deco_stop_depth": 6.0}) for w in wps]
    assert gas_time_remaining("Shearwater", "Perdix 2", deco[-1], deco) is None


def test_renderer_shows_gtr_mod_and_gf_colours():
    from gui.hud_renderer import draw_hud, resolve_element_text
    layout = {"manufacturer": "Shearwater", "model": "Perdix 2", "design_width": 1920, "design_height": 1080,
              "hud_skin": {"type": "shape", "anchor": "TOP_LEFT", "ref_offset_x": 0, "ref_offset_y": 0, "width": 600, "height": 300, "scale": 1.0,
                           "color": "#000000", "linked_elements": [
                               {"field": "gf", "rel_x": 0.1, "rel_y": 0.2, "font_size": 60, "color": "#FFFFFF"},
                               {"field": "notice", "type": "notice", "style": "frame", "source": "persistent", "rel_x": 0.6, "rel_y": 0.1, "width": 100, "height": 120, "font_size": 30}]}}
    wps = [_wp(t, 20.0, bar=200.0 - 4.2 * t / 60.0) for t in range(0, 301, 10)]
    assert resolve_element_text(layout, "air_remaining", wps[2], wps) == ("wait", None)
    text, raw = resolve_element_text(layout, "air_remaining", wps[-1], wps)
    assert raw and text == str(int(raw // 60))
    assert resolve_element_text(layout, "mod", wps[-1], wps)[0] == "34"
    assert resolve_element_text(layout, "gf", _wp(0, 20.0, gf=61.4), None)[0] == "61"
    # GF99 above the (default 85) GF high draws yellow, above 100 red; the MOD frame draws red past the MOD
    def colours(wp):
        f = np.zeros((1080, 1920, 3), dtype=np.uint8)
        draw_hud(f, layout, wp, render_log=False)
        yellow = ((f[:, :, 1] > 180) & (f[:, :, 2] > 180) & (f[:, :, 0] < 80)).sum()
        red = ((f[:, :, 2] > 180) & (f[:, :, 1] < 80) & (f[:, :, 0] < 80)).sum()
        return yellow, red
    assert colours(_wp(0, 20.0, gf=90.0))[0] > 50 and colours(_wp(0, 20.0, gf=90.0))[1] == 0
    assert colours(_wp(0, 20.0, gf=101.0))[1] > 50
    assert colours(_wp(0, 35.0, gf=50.0))[1] > 50  # the MOD frame
    assert colours(_wp(0, 20.0, gf=50.0)) == (0, 0)


def test_a_log_with_its_own_gf_high_colours_against_it():
    from gui.hud_renderer import draw_hud
    layout = {"manufacturer": "Shearwater", "model": "Perdix 2", "design_width": 1920, "design_height": 1080,
              "hud_skin": {"type": "shape", "anchor": "TOP_LEFT", "ref_offset_x": 0, "ref_offset_y": 0, "width": 300, "height": 150, "scale": 1.0,
                           "color": "#000000", "linked_elements": [{"field": "gf", "rel_x": 0.1, "rel_y": 0.2, "font_size": 60, "color": "#FFFFFF"}]}}
    wp = _wp(0, 20.0, gf=75.0)
    dive = Dive(start_time=wp.timestamp, end_time=wp.timestamp, waypoints=[wp], gf_low=30, gf_high=70)
    f = np.zeros((1080, 1920, 3), dtype=np.uint8)
    draw_hud(f, layout, dive.waypoints[0], render_log=False)
    assert ((f[:, :, 1] > 180) & (f[:, :, 2] > 180) & (f[:, :, 0] < 80)).sum() > 50  # 75 > the dive's GF high 70: yellow
