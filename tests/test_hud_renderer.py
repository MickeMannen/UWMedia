import copy
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import numpy as np
from datetime import datetime, timedelta
from models.dive import Waypoint, TankData
from gui.hud_renderer import draw_hud
from utils.layouts import load_layout_file, resolve_template_state, strip_variant_markers

def test_hud_renderer_text_scaling():
    # Design width is 1000, frame width is 1920 (w_v = 1920)
    # res_scale = 1920 / 1000 = 1.92
    layout = {
        "design_width": 1000,
        "design_height": 800,
        "hud_skin": {
            "type": "shape",
            "width": 200,
            "height": 100,
            "anchor": "TOP_LEFT",
            "linked_elements": [
                {
                    "field": "depth",
                    "font_size": 20,
                    "scale": 1.5,
                    "rel_x": 0.1,
                    "rel_y": 0.2
                }
            ]
        }
    }
    
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    wp = Waypoint(timestamp=datetime.now(), depth=12.5, time_since_start=0)
    
    # 1. Test with render_log=False (should scale the text)
    # Expected final_size: int(20 * 1.92 * 1.5) = 57
    with patch("gui.hud_renderer.get_font") as mock_get_font:
        mock_font = MagicMock()
        from PIL import Image
        dummy_mask = Image.new("L", (10, 10)).im
        mock_font.getmask2.return_value = (dummy_mask, (0, 0))
        mock_font.getmask.return_value = dummy_mask
        mock_get_font.return_value = mock_font
        
        draw_hud(frame, layout, wp, render_log=False)
        
        # Verify that get_font was called with the scaled size
        called_sizes = [args[0] for args, kwargs in mock_get_font.call_args_list]
        assert 57 in called_sizes
        
    # 2. Test with render_log=True (should NOT scale the text)
    # Expected final_size: int(20 * 1.5) = 30
    with patch("gui.hud_renderer.get_font") as mock_get_font:
        mock_font = MagicMock()
        mock_font.getmask2.return_value = (dummy_mask, (0, 0))
        mock_font.getmask.return_value = dummy_mask
        mock_get_font.return_value = mock_font
        
        draw_hud(frame, layout, wp, render_log=True)
        
        # Verify that get_font was called with the unscaled size
        called_sizes = [args[0] for args, kwargs in mock_get_font.call_args_list]
        assert 30 in called_sizes


def test_hud_renderer_user_scale():
    layout = {
        "design_width": 1000,
        "design_height": 800,
        "hud_skin": {
            "type": "image",
            "path": "dummy_path.png",
            "scale": 0.5,
            "anchor": "TOP_LEFT",
            "linked_elements": [
                {
                    "field": "depth",
                    "font_size": 20,
                    "scale": 1.5,
                    "rel_x": 0.1,
                    "rel_y": 0.2
                }
            ]
        }
    }
    
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    wp = Waypoint(timestamp=datetime.now(), depth=12.5, time_since_start=0)
    
    # Mock cv2.imread and get_font to avoid loading actual image
    with patch("cv2.imread") as mock_imread, patch("gui.hud_renderer.get_font") as mock_get_font:
        # Mock image to return a dummy image (e.g. 100x100 shape)
        dummy_img = np.zeros((100, 100, 4), dtype=np.uint8)
        mock_imread.return_value = dummy_img
        
        mock_font = MagicMock()
        from PIL import Image
        dummy_mask = Image.new("L", (10, 10)).im
        mock_font.getmask2.return_value = (dummy_mask, (0, 0))
        mock_font.getmask.return_value = dummy_mask
        mock_get_font.return_value = mock_font
        
        # Test render_log=False:
        # res_scale = 1920 / 1000 = 1.92
        # user_scale = 0.5
        # Expected final_size: int(20 * 0.5 * 1.92 * 1.5) = 28
        draw_hud(frame, layout, wp, render_log=False)
        called_sizes = [args[0] for args, kwargs in mock_get_font.call_args_list]
        assert 28 in called_sizes

    with patch("cv2.imread") as mock_imread, patch("gui.hud_renderer.get_font") as mock_get_font:
        dummy_img = np.zeros((100, 100, 4), dtype=np.uint8)
        mock_imread.return_value = dummy_img
        
        mock_font = MagicMock()
        from PIL import Image
        dummy_mask = Image.new("L", (10, 10)).im
        mock_font.getmask2.return_value = (dummy_mask, (0, 0))
        mock_font.getmask.return_value = dummy_mask
        mock_get_font.return_value = mock_font
        
        # Test render_log=True:
        # res_scale = 1.0 (since render_log=True bypasses res scaling)
        # user_scale = 0.5
        # Expected final_size: int(20 * 0.5 * 1.5) = 15
        draw_hud(frame, layout, wp, render_log=True)
        called_sizes = [args[0] for args, kwargs in mock_get_font.call_args_list]
        assert 15 in called_sizes

def test_hud_renderer_depth_graph():
    waypoints = [
        Waypoint(timestamp=datetime.now(), depth=0.0, time_since_start=0),
        Waypoint(timestamp=datetime.now(), depth=10.0, time_since_start=10),
        Waypoint(timestamp=datetime.now(), depth=15.0, time_since_start=20),
        Waypoint(timestamp=datetime.now(), depth=12.5, time_since_start=30)
    ]
    wp = Waypoint(timestamp=datetime.now(), depth=12.5, time_since_start=30)

    for marker_style in ["dot", "cross", "bold_cross"]:
        layout = {
            "design_width": 1000,
            "design_height": 800,
            "hud_skin": {
                "type": "shape",
                "width": 200,
                "height": 100,
                "anchor": "TOP_LEFT",
                "linked_elements": [
                    {
                        "field": "depth_graph",
                        "type": "graph",
                        "width": 100,
                        "height": 50,
                        "color": "#00FF00",
                        "rel_x": 0.1,
                        "rel_y": 0.2,
                        "marker_style": marker_style,
                        "marker_size": 10
                    }
                ]
            }
        }
        
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        draw_hud(frame, layout, wp, render_log=False, waypoints=waypoints)
        assert not np.all(frame == 0)


def test_depth_graph_deco_ceiling_reveals_progressively_and_never_retracts():
    # Descent, then a stop that deepens (10m -> 15m) while the diver is still
    # at the bottom, then an ascent that re-visits 10m before finally
    # clearing - see the dive-profile-graph planning notes in rework_hud.md.
    from gui.hud_renderer import draw_depth_graph

    def wp(t, d, ceiling=None):
        return Waypoint(timestamp=datetime.now(), depth=d, time_since_start=t, deco_stop_depth=ceiling)

    waypoints = [
        wp(0, 0), wp(10, 10), wp(20, 20),
        wp(30, 20, 10.0), wp(40, 20, 15.0), wp(50, 15, 10.0), wp(60, 10, 10.0), wp(70, 0, None),
    ]
    # The progressive reveal is the graph's reveal_profile mode; without it
    # the whole dive's ceiling is on the graph from the first frame (below).
    elem = {"width": 100, "height": 50, "rel_x": 0.0, "rel_y": 0.0, "color": "#FF0000", "reveal_profile": True}
    skin_info = {"x": 0, "y": 0, "w": 1, "h": 1, "res_scale": 1.0}
    # Blue channel is 0 wherever only the red line/fill has been drawn, and a
    # distinctly nonzero flat gray tint wherever the ceiling band has been
    # blended in - see the "Deco ceiling" block in draw_depth_graph.
    early_stop_px = (45, 15)   # under the t=30-40 (10m) ceiling
    deep_stop_px = (58, 30)    # under the t=40-45 (15m) ceiling
    later_hold_px = (85, 15)   # under the t=50-70 (10m again) ceiling

    whole = np.zeros((50, 100, 3), dtype=np.uint8)
    draw_depth_graph(whole, {**elem, "reveal_profile": False}, wp(25, 20), waypoints, skin_info)
    assert all(whole[y, x][0] > 0 for x, y in (early_stop_px, deep_stop_px, later_hold_px))  # all there at t=25

    frame = np.zeros((50, 100, 3), dtype=np.uint8)
    draw_depth_graph(frame, elem, wp(25, 20), waypoints, skin_info)
    assert frame[early_stop_px[1], early_stop_px[0]][0] == 0  # no ceiling exists yet
    assert frame[deep_stop_px[1], deep_stop_px[0]][0] == 0
    assert frame[later_hold_px[1], later_hold_px[0]][0] == 0

    frame = np.zeros((50, 100, 3), dtype=np.uint8)
    draw_depth_graph(frame, elem, wp(45, 20), waypoints, skin_info)
    assert frame[early_stop_px[1], early_stop_px[0]][0] > 0   # revealed
    assert frame[deep_stop_px[1], deep_stop_px[0]][0] > 0     # revealed
    assert frame[later_hold_px[1], later_hold_px[0]][0] == 0  # not reached yet

    frame = np.zeros((50, 100, 3), dtype=np.uint8)
    draw_depth_graph(frame, elem, wp(70, 0), waypoints, skin_info)
    assert frame[early_stop_px[1], early_stop_px[0]][0] > 0   # still there
    assert frame[deep_stop_px[1], deep_stop_px[0]][0] > 0     # still there - never retracted
    assert frame[later_hold_px[1], later_hold_px[0]][0] > 0   # now revealed too


def _shape_layout(linked_elements, manufacturer="Garmin", model="x50i"):
    return {
        "design_width": 1000,
        "design_height": 800,
        "manufacturer": manufacturer,
        "model": model,
        "hud_skin": {
            "type": "shape",
            "width": 200,
            "height": 100,
            "anchor": "TOP_LEFT",
            "linked_elements": linked_elements,
        },
    }


def test_hud_renderer_badge_normal_state_draws_nothing():
    layout = _shape_layout([{"type": "badge", "field": "state_badge", "font_size": 20, "rel_x": 0.1, "rel_y": 0.1}])
    wp_normal = Waypoint(timestamp=datetime.now(), depth=5.0, time_since_start=0, deco_stop_depth=0.0)

    frame_with_badge = np.zeros((1080, 1920, 3), dtype=np.uint8)
    draw_hud(frame_with_badge, layout, wp_normal, render_log=False)

    frame_skin_only = np.zeros((1080, 1920, 3), dtype=np.uint8)
    draw_hud(frame_skin_only, _shape_layout([]), wp_normal, render_log=False)

    assert np.array_equal(frame_with_badge, frame_skin_only)


def test_hud_renderer_badge_deco_state_draws_badge():
    layout = _shape_layout([{"type": "badge", "field": "state_badge", "font_size": 20, "rel_x": 0.1, "rel_y": 0.1}])
    wp_deco = Waypoint(
        timestamp=datetime.now(), depth=20.0, time_since_start=0,
        deco_stop_depth=6.0, next_stop_depth=6.0, next_stop_time=120,
    )

    frame_deco = np.zeros((1080, 1920, 3), dtype=np.uint8)
    draw_hud(frame_deco, layout, wp_deco, render_log=False)

    frame_skin_only = np.zeros((1080, 1920, 3), dtype=np.uint8)
    draw_hud(frame_skin_only, _shape_layout([]), wp_deco, render_log=False)

    assert not np.array_equal(frame_deco, frame_skin_only)


def test_hud_renderer_badge_safety_stop_from_alert_event():
    layout = _shape_layout([{"type": "badge", "field": "state_badge", "font_size": 20, "rel_x": 0.1, "rel_y": 0.1}])
    wp = Waypoint(
        timestamp=datetime.now(), depth=5.0, time_since_start=0,
        dive_alerts=["safety_stop_started"],
    )

    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    draw_hud(frame, layout, wp, render_log=False)

    frame_skin_only = np.zeros((1080, 1920, 3), dtype=np.uint8)
    draw_hud(frame_skin_only, _shape_layout([]), wp, render_log=False)

    assert not np.array_equal(frame, frame_skin_only)


def _load_garmin_layout(page, variant=None):
    state_path = resolve_template_state("garmin", "x50i", page, variant=variant)
    assert state_path is not None
    layout = strip_variant_markers(load_layout_file(state_path))
    layout["hud_skin"]["path"] = str((state_path.parent / layout["hud_skin"]["path"]).resolve())
    return layout


def test_garmin_x50i_main_single_tank_renders():
    layout = _load_garmin_layout("main", variant="single_tank")
    wp = Waypoint(
        timestamp=datetime.now(), depth=18.4, max_depth=22.1, temp=27.0,
        dive_time=754, time_since_start=754, ndl=1380, air_remaining=1620,
        volume_sac=14.2,
        tanks={"Micke01": TankData(pressure_bar=142, o2_percent=21.0, name="Micke01")},
    )
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    draw_hud(frame, layout, wp, render_log=False)
    assert not np.all(frame == 0)


def test_garmin_x50i_main_sidemount_renders():
    layout = _load_garmin_layout("main", variant="sidemount")
    wp = Waypoint(
        timestamp=datetime.now(), depth=18.4, max_depth=22.1, temp=27.0,
        dive_time=754, time_since_start=754, ndl=1380, tts=95,
        air_remaining=1620, volume_sac=14.2,
        tanks={
            "Micke01": TankData(pressure_bar=142, o2_percent=21.0, name="Micke01"),
            "Micke02": TankData(pressure_bar=138, o2_percent=21.0, name="Micke02"),
        },
    )
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    draw_hud(frame, layout, wp, render_log=False)
    assert not np.all(frame == 0)


def test_garmin_x50i_gases_renders():
    layout = _load_garmin_layout("gases")
    wp = Waypoint(
        timestamp=datetime.now(), depth=18.4, max_depth=22.1, temp=27.0,
        dive_time=754, time_since_start=754, po2=1.12, gf=0.62, cns=18,
        tanks={"Micke01": TankData(pressure_bar=142, o2_percent=21.0, name="Micke01")},
    )
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    draw_hud(frame, layout, wp, render_log=False)
    assert not np.all(frame == 0)


def test_hud_renderer_time_of_day_field():
    layout = _shape_layout([{"field": "time_of_day", "font_size": 20, "rel_x": 0.1, "rel_y": 0.1}])
    wp = Waypoint(timestamp=datetime(2024, 1, 1, 14, 30), depth=5.0, time_since_start=0)

    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    draw_hud(frame, layout, wp, render_log=False)

    frame_skin_only = np.zeros((1080, 1920, 3), dtype=np.uint8)
    draw_hud(frame_skin_only, _shape_layout([]), wp, render_log=False)

    assert not np.array_equal(frame, frame_skin_only)


def test_hud_renderer_tank_icon_fill_color_by_pressure():
    layout = _shape_layout([
        {"type": "tank_icon", "field": "primary_tank_pressure", "rel_x": 0.3, "rel_y": 0.3, "width": 30, "height": 40}
    ])

    def frame_for_pressure(pressure):
        wp = Waypoint(
            timestamp=datetime.now(), depth=5.0, time_since_start=0,
            tanks={"Back": TankData(pressure_bar=pressure, o2_percent=21.0)} if pressure is not None else {},
        )
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        draw_hud(frame, layout, wp, render_log=False)
        return frame

    frame_skin_only = np.zeros((1080, 1920, 3), dtype=np.uint8)
    draw_hud(frame_skin_only, _shape_layout([]), Waypoint(timestamp=datetime.now(), time_since_start=0), render_log=False)

    # No pressure reading -> nothing drawn beyond the bare skin
    assert np.array_equal(frame_for_pressure(None), frame_skin_only)

    # Low pressure -> red fill somewhere in the frame
    red_frame = frame_for_pressure(30)
    assert not np.array_equal(red_frame, frame_skin_only)
    assert (red_frame[:, :, 2] == 255).any() and not (red_frame[:, :, 1] == 255).any()

    # Healthy pressure -> green fill (BGR: green channel, not red)
    green_frame = frame_for_pressure(180)
    assert not np.array_equal(green_frame, frame_skin_only)
    assert (green_frame[:, :, 1] == 255).any() and not (green_frame[:, :, 2] == 255).any()


def test_hud_renderer_badge_value_font_size_independent_of_label():
    # Shearwater's badge shows a small title above a much larger countdown - the
    # value lines (depth/timer) should scale off value_font_size, not font_size.
    from gui.hud_renderer import get_font

    layout_small_value = _shape_layout([{
        "type": "badge", "field": "state_badge", "rel_x": 0.1, "rel_y": 0.1,
        "font_size": 20, "value_font_size": 20,
    }])
    layout_big_value = _shape_layout([{
        "type": "badge", "field": "state_badge", "rel_x": 0.1, "rel_y": 0.1,
        "font_size": 20, "value_font_size": 80,
    }])
    wp = Waypoint(
        timestamp=datetime.now(), depth=20.0, time_since_start=0,
        deco_stop_depth=6.0, next_stop_depth=6.0, next_stop_time=120,
    )

    with patch("gui.hud_renderer.get_font", wraps=get_font) as mock_get_font:
        draw_hud(np.zeros((1080, 1920, 3), dtype=np.uint8), layout_small_value, wp, render_log=False)
        small_sizes = {call.args[0] for call in mock_get_font.call_args_list}

    with patch("gui.hud_renderer.get_font", wraps=get_font) as mock_get_font:
        draw_hud(np.zeros((1080, 1920, 3), dtype=np.uint8), layout_big_value, wp, render_log=False)
        big_sizes = {call.args[0] for call in mock_get_font.call_args_list}

    # The label size (20, scaled) is requested in both cases; the big-value layout
    # additionally requests a much larger size for its depth/timer lines.
    assert small_sizes & big_sizes  # label size shared
    assert max(big_sizes) > max(small_sizes)


def _load_perdix3_layout(page):
    state_path = resolve_template_state("shearwater", "perdix_3", page)
    assert state_path is not None
    layout = strip_variant_markers(load_layout_file(state_path))
    layout["hud_skin"]["path"] = str((state_path.parent / layout["hud_skin"]["path"]).resolve())
    return layout


def test_perdix3_main_renders():
    layout = _load_perdix3_layout("main")
    wp = Waypoint(
        timestamp=datetime.now(), depth=18.2, max_depth=33.5, temp=23.0,
        dive_time=33 * 60 + 58, time_since_start=33 * 60 + 58, ndl=12 * 60,
        tanks={"T1": TankData(pressure_bar=125, o2_percent=21.0)},
    )
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    draw_hud(frame, layout, wp, render_log=False)
    assert not np.all(frame == 0)


def test_perdix3_standard_renders():
    # Standard shares Big's exact field positions (same skin/photo) with a
    # smaller depth/NDL font - see overlays/templates/shearwater/perdix_3/
    # standard/normal.json and the Perdix 3 manual's own "Big and Standard
    # screen layouts are similar... Big layout providing depth and NDL in a
    # larger font size" (section 4.3).
    layout = _load_perdix3_layout("standard")
    wp = Waypoint(
        timestamp=datetime.now(), depth=24.3, max_depth=33.5, temp=23.0,
        dive_time=24 * 60 + 31, time_since_start=24 * 60 + 31, ndl=10 * 60,
        tanks={"T1": TankData(pressure_bar=82, o2_percent=21.0)},
    )
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    draw_hud(frame, layout, wp, render_log=False)
    assert not np.all(frame == 0)

    main_layout = _load_perdix3_layout("main")
    main_depth = next(e for e in main_layout["hud_skin"]["linked_elements"] if e["field"] == "depth")
    std_depth = next(e for e in layout["hud_skin"]["linked_elements"] if e["field"] == "depth")
    assert std_depth["font_size"] < main_depth["font_size"]


def test_perdix3_tec_renders_ndl_state():
    layout = _load_perdix3_layout("tec")
    wp = Waypoint(
        timestamp=datetime.now(), depth=59.3, max_depth=59.3, temp=20.0,
        dive_time=21 * 60 + 27, time_since_start=21 * 60 + 27,
        ndl=18 * 60, po2=0.94, gf=48.0, tts=0,
        divemode="OC",
        tanks={"T1": TankData(pressure_bar=248, o2_percent=18.0, he_percent=45.0)},
    )
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    draw_hud(frame, layout, wp, render_log=False)
    assert not np.all(frame == 0)


def test_perdix3_tec_renders_deco_state():
    layout = _load_perdix3_layout("tec")
    wp = Waypoint(
        timestamp=datetime.now(), depth=27.0, max_depth=59.3, temp=18.0,
        dive_time=34 * 60, time_since_start=34 * 60,
        deco_stop_depth=27.0, next_stop_depth=27.0, next_stop_time=60,
        po2=1.24, gf=231.0, tts=48 * 60,
        divemode="OC",
        tanks={"T1": TankData(pressure_bar=180, o2_percent=18.0, he_percent=45.0)},
    )
    frame_deco = np.zeros((1080, 1920, 3), dtype=np.uint8)
    draw_hud(frame_deco, layout, wp, render_log=False)

    frame_ndl = np.zeros((1080, 1920, 3), dtype=np.uint8)
    draw_hud(
        frame_ndl, layout,
        Waypoint(timestamp=datetime.now(), depth=27.0, time_since_start=34 * 60, ndl=5 * 60),
        render_log=False,
    )
    assert not np.array_equal(frame_deco, frame_ndl)


def test_perdix3_tec_renders_clear_state():
    # 0 < (deco_stop_depth - depth) < Shearwater's 1.0m clear margin.
    layout = _load_perdix3_layout("tec")
    wp = Waypoint(
        timestamp=datetime.now(), depth=26.6, max_depth=59.3, temp=18.0,
        dive_time=40 * 60, time_since_start=40 * 60,
        deco_stop_depth=27.0, next_stop_depth=0.0, next_stop_time=0,
        po2=1.1, gf=90.0, tts=5 * 60,
        divemode="OC",
        tanks={"T1": TankData(pressure_bar=140, o2_percent=18.0, he_percent=45.0)},
    )
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    draw_hud(frame, layout, wp, render_log=False)
    assert not np.all(frame == 0)


def test_perdix3_tec_renders_safety_stop_state():
    layout = _load_perdix3_layout("tec")
    wp = Waypoint(
        timestamp=datetime.now(), depth=5.0, max_depth=27.0, temp=22.0,
        dive_time=44 * 60, time_since_start=44 * 60,
        dive_alerts=["safety_stop_started"], next_stop_depth=5.0, next_stop_time=180,
        po2=0.5, gf=10.0, tts=3 * 60,
        divemode="OC",
        tanks={"T1": TankData(pressure_bar=110, o2_percent=21.0)},
    )
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    draw_hud(frame, layout, wp, render_log=False)
    assert not np.all(frame == 0)


def _load_perdix2_layout(page, variant=None):
    state_path = resolve_template_state("shearwater", "perdix_2", page, variant=variant)
    assert state_path is not None
    layout = strip_variant_markers(load_layout_file(state_path))
    layout["hud_skin"]["path"] = str((state_path.parent / layout["hud_skin"]["path"]).resolve())
    return layout


def test_perdix2_main_single_tank_renders():
    layout = _load_perdix2_layout("main", variant="single_tank")
    wp = Waypoint(
        timestamp=datetime.now(), depth=15.7, max_depth=15.7, temp=27.0,
        dive_time=35 * 60 + 51, time_since_start=35 * 60 + 51, ndl=22 * 60,
        air_remaining=21 * 60,
        tanks={"T1": TankData(pressure_bar=210, o2_percent=21.0)},
    )
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    draw_hud(frame, layout, wp, render_log=False)
    assert not np.all(frame == 0)


def test_perdix2_main_single_tank_safety_stop_badge_and_tank_fill():
    # Low pressure (< 50 bar) should turn the tank icon red; a safety-stop alert
    # should draw the SAFETY STOP/countdown badge on top of the persistent NDL line.
    layout = _load_perdix2_layout("main", variant="single_tank")
    wp = Waypoint(
        timestamp=datetime.now(), depth=5.0, max_depth=15.7, temp=27.0,
        dive_time=35 * 60 + 51, time_since_start=35 * 60 + 51, ndl=22 * 60,
        air_remaining=21 * 60, next_stop_time=180,
        tanks={"T1": TankData(pressure_bar=45, o2_percent=21.0)},
    )
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    draw_hud(frame, layout, wp, render_log=False)
    # red tank fill present
    assert (frame[:, :, 2] == 255).any()


def test_perdix2_main_sidemount_renders():
    layout = _load_perdix2_layout("main", variant="sidemount")
    wp = Waypoint(
        timestamp=datetime.now(), depth=15.7, max_depth=15.7, temp=27.0,
        dive_time=35 * 60 + 51, time_since_start=35 * 60 + 51, ndl=22 * 60,
        air_remaining=45 * 60,
        tanks={
            "T1": TankData(pressure_bar=210, o2_percent=21.0),
            "T2": TankData(pressure_bar=207, o2_percent=21.0),
        },
    )
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    draw_hud(frame, layout, wp, render_log=False)
    assert not np.all(frame == 0)


def test_perdix2_tec_renders():
    layout = _load_perdix2_layout("tec")
    wp = Waypoint(
        timestamp=datetime.now(), depth=67.0, max_depth=67.0, temp=20.0,
        dive_time=22 * 60, time_since_start=22 * 60,
        deco_stop_depth=39.0, next_stop_time=60,
        po2=1.15, gf=164.0, ndl=8 * 60, tts=56 * 60,
        divemode="OC",
        tanks={"T1": TankData(pressure_bar=153, o2_percent=15.0, he_percent=40.0)},
    )
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    draw_hud(frame, layout, wp, render_log=False)
    assert not np.all(frame == 0)





# --- overlay_rework.md Phase 2: schema v2 text attributes ------------------

def _ink_bbox(align="left", valign="top", family=None, outline=False, extra=None):
    """Render one 60px depth value at the centre of a 400x200 shape skin
    (render_log mode) and return the ink bounding box (xmin, xmax, ymin, ymax)."""
    elem = {"field": "depth", "font_size": 60, "rel_x": 0.5, "rel_y": 0.5, "color": "#FFFFFF",
            "align": align, "valign": valign, "outline": outline}
    if family:
        elem["font_family"] = family
    if extra:
        elem.update(extra)
    layout = {"design_width": 1920, "design_height": 1080,
              "hud_skin": {"type": "shape", "width": 400, "height": 200, "anchor": "TOP_LEFT",
                           "opacity": 0.0, "linked_elements": [elem]}}
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    wp = Waypoint(timestamp=datetime.now(), depth=12.5, time_since_start=0)
    draw_hud(frame, layout, wp, render_log=True)
    ys, xs = np.where(frame[:, :, 0] > 128)
    return int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max()), frame


def test_align_and_valign_move_the_ink_box_onto_the_anchor():
    # anchor = (200, 100)
    lx0, lx1, ly0, ly1, _ = _ink_bbox("left", "top")
    assert lx0 >= 200 and ly0 >= 100  # default: ink hangs right/below the anchor as always

    cx0, cx1, _, _, _ = _ink_bbox("center", "top")
    assert abs((cx0 + cx1) / 2 - 200) <= 3
    rx0, rx1, _, _, _ = _ink_bbox("right", "top")
    assert abs(rx1 - 200) <= 6 and rx0 < 200
    _, _, my0, my1, _ = _ink_bbox("left", "middle")
    assert abs((my0 + my1) / 2 - 100) <= 3
    _, _, by0, by1, _ = _ink_bbox("left", "bottom")
    assert abs(by1 - 100) <= 3 and by0 < 100
    # width/height are preserved by alignment
    assert (cx1 - cx0) == (lx1 - lx0) and (by1 - by0) == (ly1 - ly0)


def test_font_family_changes_rendering_and_unknown_family_falls_back():
    *_, default_frame = _ink_bbox()
    *_, roboto_frame = _ink_bbox(family="Roboto")
    *_, dseg_frame = _ink_bbox(family="DSEG7 Classic")
    *_, unknown_frame = _ink_bbox(family="No Such Family")
    assert not np.array_equal(default_frame, roboto_frame)
    assert not np.array_equal(default_frame, dseg_frame)
    assert np.array_equal(default_frame, unknown_frame)
    *_, bold_frame = _ink_bbox(extra={"font_weight": "bold"})
    assert not np.array_equal(default_frame, bold_frame)


def test_outline_false_draws_no_black_halo():
    layout_base = {"design_width": 1920, "design_height": 1080,
                   "hud_skin": {"type": "shape", "width": 400, "height": 200, "anchor": "TOP_LEFT",
                                "opacity": 1.0, "color": "#808080", "linked_elements": []}}
    wp = Waypoint(timestamp=datetime.now(), depth=12.5, time_since_start=0)
    frames = {}
    for outline in (True, False):
        layout = copy.deepcopy(layout_base)
        layout["hud_skin"]["linked_elements"] = [
            {"field": "depth", "font_size": 60, "rel_x": 0.2, "rel_y": 0.2, "color": "#FFFFFF", "outline": outline}
        ]
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        draw_hud(frame, layout, wp, render_log=True)
        # inside the rounded rectangle (its corners are outside the shape and
        # therefore frame-black regardless of the outline setting)
        skin_area = frame[30:170, 30:370]
        frames[outline] = int(np.sum(np.all(skin_area == 0, axis=2)))
    assert frames[True] > 0
    assert frames[False] == 0


def test_resolve_element_text_matches_renderer_paths():
    from gui.hud_renderer import resolve_element_text
    layout = {"manufacturer": "Garmin", "model": "x50i"}
    wp = Waypoint(timestamp=datetime(2026, 1, 1, 14, 5), depth=12.34, time_since_start=0,
                  tanks={"T1": TankData(pressure_bar=150.4, name="Left")})
    assert resolve_element_text(layout, "depth", wp) == ("12.3", 12.34)
    assert resolve_element_text(layout, "custom:BAR", wp) == ("BAR", None)
    assert resolve_element_text(layout, "time_of_day", wp) == ("14:05", None)
    assert resolve_element_text(layout, "tank_pressure:T1", wp) == ("150", 150.4)
    assert resolve_element_text(layout, "tank_name:T1", wp) == ("Left", "Left")
    # None waypoint never raises
    assert resolve_element_text(layout, "tank_pressure:T1", None)[0] == "--"
    assert resolve_element_text(layout, "depth", None) == ("--", None)
    assert resolve_element_text(layout, "time_of_day", None) == (None, None)


def test_badge_lines_none_for_normal_and_three_lines_for_deco():
    from gui.hud_renderer import badge_lines
    elem = {"field": "state_badge", "type": "badge", "rel_x": 0, "rel_y": 0}
    normal = Waypoint(timestamp=datetime.now(), depth=20.0, time_since_start=0)
    assert badge_lines("Shearwater", "Perdix 2", elem, normal) is None
    assert badge_lines("Shearwater", "Perdix 2", elem, None) is None
    deco = Waypoint(timestamp=datetime.now(), depth=12.0, time_since_start=0,
                    deco_stop_depth=6.0, next_stop_depth=6.0, next_stop_time=180)
    lines = badge_lines("Shearwater", "Perdix 2", {**elem, "depth_unit": "m"}, deco)
    # Perdix 2 manual p.33: "DECO STOP" in red, then "6m↑ 3min" in white on one line
    assert [t for t, _, _ in lines] == ["DECO STOP", "6m↑ 3min"]
    assert [v for _, _, v in lines] == [False, True]
    assert [c for _, c, _ in lines] == [(255, 0, 0), (255, 255, 255)]
    # Garmin keeps its three lines
    lines = badge_lines("Garmin", "x50i", elem, deco)
    assert [t for t, _, _ in lines] == ["DECO", "↑6", "03:00"]


def test_rules_profile_borrows_another_brands_rules():
    from gui.hud_renderer import rules_manufacturer
    assert rules_manufacturer({"manufacturer": "Custom", "rules_profile": "Shearwater"}) == "Shearwater"
    assert rules_manufacturer({"manufacturer": "Garmin"}) == "Garmin"
    assert rules_manufacturer({}) == "Shearwater"

    def render(layout_extra):
        layout = {"design_width": 1920, "design_height": 1080, "model": "",
                  "hud_skin": {"type": "shape", "width": 400, "height": 200, "anchor": "TOP_LEFT", "opacity": 0.0,
                               "linked_elements": [{"field": "state_badge", "type": "badge", "rel_x": 0.1, "rel_y": 0.1,
                                                    "font_size": 30, "value_font_size": 50}]}}
        layout.update(layout_extra)
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        deco = Waypoint(timestamp=datetime.now(), depth=12.0, time_since_start=0,
                        deco_stop_depth=6.0, next_stop_depth=6.0, next_stop_time=180)
        draw_hud(frame, layout, deco, render_log=True)
        return frame

    custom_default = render({"manufacturer": "Custom"})
    custom_shearwater = render({"manufacturer": "Custom", "rules_profile": "Shearwater"})
    real_shearwater = render({"manufacturer": "Shearwater"})
    assert np.array_equal(custom_shearwater, real_shearwater)
    assert not np.array_equal(custom_default, custom_shearwater)  # default DECO badge is orange, Shearwater's red


def test_small_suffix_splits_and_renders_smaller_top_aligned_suffix():
    from gui.hud_renderer import split_small_suffix, text_parts
    assert split_small_suffix("12:34", "seconds") == ("12", ":34")
    assert split_small_suffix("24.0", "decimals") == ("24", ".0")
    assert split_small_suffix("24.0", "seconds") == ("24.0", "")
    assert split_small_suffix("--", "decimals") == ("--", "")
    assert split_small_suffix("", "seconds") == ("", "")
    assert text_parts("ndl", "99+", {}) == ("99", "+", 0.35)
    assert text_parts("dive_time", "12:34", {"small_suffix": "seconds", "small_suffix_scale": 0.33}) == ("12", ":34", 0.33)
    assert text_parts("dive_time", "12:34", {}) == ("12:34", "", 0.35)

    def render(elem_extra):
        elem = {"field": "dive_time", "font_size": 60, "rel_x": 0.1, "rel_y": 0.2, "color": "#FFFFFF", "outline": False}
        elem.update(elem_extra)
        layout = {"design_width": 1920, "design_height": 1080,
                  "hud_skin": {"type": "shape", "width": 600, "height": 200, "anchor": "TOP_LEFT", "opacity": 0.0,
                               "linked_elements": [elem]}}
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        wp = Waypoint(timestamp=datetime.now(), depth=12.5, time_since_start=754, dive_time=754)
        draw_hud(frame, layout, wp, render_log=True)
        return frame

    plain = render({})
    small = render({"small_suffix": "seconds", "small_suffix_scale": 0.33})
    assert not np.array_equal(plain, small)
    # the suffix run is narrower and shorter than the plain "12:34"
    ys_p, xs_p = np.where(plain[:, :, 0] > 128)
    ys_s, xs_s = np.where(small[:, :, 0] > 128)
    assert xs_s.max() < xs_p.max()
    assert ys_s.min() == ys_p.min()  # top edges align (main digits unchanged)
    # right-aligned: the whole run's right edge lands on the anchor (x = 60 + 0.5*600? no: rel_x 0.1 -> 60)
    right = render({"small_suffix": "seconds", "align": "right", "rel_x": 0.5})
    _, xs_r = np.where(right[:, :, 0] > 128)
    assert abs(xs_r.max() - 300) <= 6


def test_small_suffix_bounds_include_the_suffix():
    from utils.hud_designer import element_native_bounds
    elem = {"field": "dive_time", "rel_x": 0.1, "rel_y": 0.1, "font_size": 60, "scale": 1.0}
    x0, y0, x1, y1 = element_native_bounds(elem, 600, 200, text="12:34")
    sx0, sy0, sx1, sy1 = element_native_bounds(dict(elem, small_suffix="seconds"), 600, 200, text="12:34")
    assert sx0 == x0 and sy0 == y0
    assert x1 > sx1 > x0 + 30  # narrower than full-size "12:34", wider than "12" alone


def test_tank_icon_drawn_outline_is_optional_and_independent_of_pressure():
    from gui.hud_renderer import tank_outline_metrics
    assert tank_outline_metrics({"type": "tank_icon"}) is None
    assert tank_outline_metrics({"type": "tank_icon", "draw_outline": True}) == (4, 2, 6)
    assert tank_outline_metrics({"type": "tank_icon", "draw_outline": True, "outline_gap": 0, "outline_width": 3}) == (0, 3, 3)

    def render(elem_extra, waypoint):
        elem = {"field": "primary_tank_pressure", "type": "tank_icon", "rel_x": 0.25, "rel_y": 0.25, "width": 20, "height": 40}
        elem.update(elem_extra)
        layout = {"design_width": 1920, "design_height": 1080, "manufacturer": "Garmin", "model": "mk3i",
                  "hud_skin": {"type": "shape", "width": 200, "height": 200, "anchor": "TOP_LEFT", "opacity": 0.0,
                               "linked_elements": [elem]}}
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        draw_hud(frame, layout, waypoint, render_log=True)
        return frame

    no_tank = Waypoint(timestamp=datetime.now(), depth=10.0, time_since_start=0)
    full = Waypoint(timestamp=datetime.now(), depth=10.0, time_since_start=0, tanks={"T1": TankData(pressure_bar=180.0)})

    assert render({}, no_tank).sum() == 0                       # nothing: no fill, no outline
    assert render({}, full).sum() > 0                            # fill only
    outline_only = render({"draw_outline": True}, no_tank)       # outline even without a reading
    assert outline_only.sum() > 0
    ys, xs = np.where(outline_only.max(axis=2) > 128)
    # fill rect is (50,50)-(70,90); outline sits 4 gap + 2 stroke outside it, cap above
    assert xs.min() <= 45 and xs.max() >= 75 and ys.min() < 44 and ys.max() >= 95
    assert np.all(outline_only[ys, xs] >= 200)                   # white
    red = render({"draw_outline": True, "outline_color": "#FF0000"}, no_tank)
    ys, xs = np.where(red.max(axis=2) > 128)
    assert red[ys, xs][:, 2].max() > 200 and red[ys, xs][:, 1].max() == 0  # BGR: red channel only
    both = render({"draw_outline": True}, full)
    assert both.sum() > outline_only.sum()                       # outline + fill


def test_tank_icon_bounds_include_the_drawn_outline():
    from utils.hud_designer import element_native_bounds
    elem = {"field": "primary_tank_pressure", "type": "tank_icon", "rel_x": 0.5, "rel_y": 0.5, "width": 20, "height": 40}
    assert element_native_bounds(elem, 200, 200) == (100.0, 100.0, 120.0, 140.0)
    x0, y0, x1, y1 = element_native_bounds(dict(elem, draw_outline=True), 200, 200)
    assert (x0, x1) == (94.0, 126.0) and y1 == 146.0 and y0 == 100 - 6 - 6 + 2


def test_tissue_bar_draws_bands_and_moves_marker_with_load():
    from gui.hud_renderer import tissue_bar_geometry, tissue_bar_marker_fraction
    assert tissue_bar_geometry({"type": "tissue_bar"}) == (12, 33, 4)
    assert tissue_bar_marker_fraction(None) == 0.0
    assert tissue_bar_marker_fraction(60) == pytest.approx(0.5)
    assert tissue_bar_marker_fraction(500) == 1.0

    def render(load):
        elem = {"field": "n2_tissue_load", "type": "tissue_bar", "rel_x": 0.5, "rel_y": 0.25, "width": 12, "height": 40, "marker_size": 4}
        layout = {"design_width": 1920, "design_height": 1080, "manufacturer": "Garmin", "model": "x50i",
                  "hud_skin": {"type": "shape", "width": 200, "height": 200, "anchor": "TOP_LEFT", "opacity": 0.0,
                               "linked_elements": [elem]}}
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        wp = Waypoint(timestamp=datetime.now(), depth=10.0, time_since_start=0, n2_tissue_load=load)
        draw_hud(frame, layout, wp, render_log=True)
        return frame

    zero = render(0.0)
    # bar at x 100..112, y 50..90: green bottom, yellow, red top (BGR)
    assert tuple(zero[88, 106]) == (0, 255, 0)
    assert tuple(zero[52, 106]) == (0, 0, 255)
    assert zero[int(50 + 40 * (1 - 90 / 120)) + 1, 106][1] > 150 and zero[int(50 + 40 * (1 - 90 / 120)) + 1, 106][2] > 150  # yellow band
    # white marker at the bottom-left for 0 %, higher for 60 %
    def marker_y(frame):
        ys, xs = np.where(np.all(frame[:, 90:104] > 240, axis=2))
        return ys.mean()
    assert marker_y(zero) > marker_y(render(60.0)) > marker_y(render(119.0))
    assert render(None).sum() > 0  # drawn even without a value


def test_tissue_bar_bounds_and_defaults():
    from utils.hud_designer import element_defaults, element_kind, element_native_bounds, parse_layout_elements
    elem = element_defaults("tissue_bar", "n2_tissue_load")
    assert element_kind(elem) == "tissue_bar" and elem["type"] == "tissue_bar" and elem["field"] == "n2_tissue_load"
    x0, y0, x1, y1 = element_native_bounds(dict(elem, rel_x=0.5, rel_y=0.5), 200, 200)
    assert (x0, y0, x1, y1) == (96.0, 100.0, 112.0, 137.0)
    parsed = parse_layout_elements({"linked_elements": [{"field": "n2_tissue_load", "type": "tissue_bar", "rel_x": 0.1, "rel_y": 0.1}]})
    assert parsed[0]["width"] == 12 and parsed[0]["height"] == 33 and parsed[0]["marker_size"] == 4


def test_ascent_chevrons_light_with_rate_and_derive_rate_when_missing():
    from gui.hud_renderer import ascent_chevron_geometry, ascent_lit_count, ascent_rate_for
    assert ascent_chevron_geometry({"type": "ascent_chevrons"}) == (16, 47, 4, 1)
    assert ascent_lit_count(None, 4) == 0 and ascent_lit_count(0.2, 4) == 0
    assert ascent_lit_count(1.0, 4) == 1 and ascent_lit_count(6.0, 4) == 3 and ascent_lit_count(11.0, 4) == 4 and ascent_lit_count(40.0, 4) == 4
    assert ascent_lit_count(-5.0, 4) == 0

    # derived from depth change when the log carries no rate
    t0 = datetime.now()
    wps = [Waypoint(timestamp=t0, depth=20.0, time_since_start=0),
           Waypoint(timestamp=t0, depth=17.0, time_since_start=30),
           Waypoint(timestamp=t0, depth=18.0, time_since_start=60)]
    assert ascent_rate_for(wps[1], wps) == pytest.approx(6.0)     # 3 m shallower in 30 s
    assert ascent_rate_for(wps[2], wps) == pytest.approx(-2.0)    # deeper
    assert ascent_rate_for(wps[0], wps) is None
    logged = Waypoint(timestamp=t0, depth=10.0, time_since_start=0, ascent_rate=9.0)
    assert ascent_rate_for(logged, wps) == 9.0

    def render(rate):
        elem = {"field": "ascent_rate", "type": "ascent_chevrons", "rel_x": 0.25, "rel_y": 0.25, "width": 16, "height": 48}
        layout = {"design_width": 1920, "design_height": 1080, "manufacturer": "Garmin", "model": "x50i",
                  "hud_skin": {"type": "shape", "width": 200, "height": 200, "anchor": "TOP_LEFT", "opacity": 0.0,
                               "linked_elements": [elem]}}
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        wp = Waypoint(timestamp=t0, depth=10.0, time_since_start=0, ascent_rate=rate)
        draw_hud(frame, layout, wp, render_log=True)
        return frame[50:98, 50:66]

    def count(frame, bgr):
        return int(np.all(frame == np.array(bgr, dtype=np.uint8), axis=2).sum())

    level = render(0.0)
    assert count(level, (138, 138, 138)) > 100 and count(level, (0, 255, 0)) == 0 and count(level, (255, 255, 255)) > 10  # grey + white bar
    slow = render(3.0)
    fast = render(12.0)
    assert 0 < count(slow, (0, 255, 0)) < count(fast, (0, 0, 255))     # one green vs four red chevrons
    assert count(slow, (138, 138, 138)) > count(fast, (138, 138, 138))
    warn = render(9.0)
    assert count(warn, (0, 192, 255)) > 0                              # yellow band (#FFC000 -> BGR 0,192,255)
    descending = render(-3.0)
    assert count(descending, (255, 255, 255)) > count(level, (255, 255, 255))  # the down chevron lit white
    assert render(None).sum() > 0


def test_ascent_chevron_defaults_and_bounds():
    from utils.hud_designer import element_defaults, element_kind, element_native_bounds, parse_layout_elements
    elem = element_defaults("ascent_chevrons", "ascent_rate")
    assert element_kind(elem) == "ascent_chevrons" and elem["field"] == "ascent_rate" and elem["up_count"] == 4
    assert element_native_bounds(dict(elem, rel_x=0.5, rel_y=0.5), 200, 200) == (100.0, 100.0, 116.0, 147.0)
    parsed = parse_layout_elements({"linked_elements": [{"field": "ascent_rate", "type": "ascent_chevrons", "rel_x": 0.1, "rel_y": 0.1}]})
    assert (parsed[0]["width"], parsed[0]["height"], parsed[0]["up_count"], parsed[0]["down_count"]) == (16, 47, 4, 1)


def test_tissue_bar_fill_style_frames_and_fills_by_value():
    def render(value, field="gf"):
        elem = {"field": field, "type": "tissue_bar", "style": "fill", "rel_x": 0.25, "rel_y": 0.25,
                "width": 20, "height": 60, "outline_color": "#00ADED"}
        layout = {"design_width": 1920, "design_height": 1080, "manufacturer": "Shearwater", "model": "Perdix 2",
                  "hud_skin": {"type": "shape", "width": 200, "height": 200, "anchor": "TOP_LEFT", "opacity": 0.0,
                               "linked_elements": [elem]}}
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        wp = Waypoint(timestamp=datetime.now(), depth=10.0, time_since_start=0, gf=value)
        draw_hud(frame, layout, wp, render_log=True)
        return frame[48:112, 48:72]

    def count(frame, bgr):
        return int(np.all(frame == np.array(bgr, dtype=np.uint8), axis=2).sum())

    empty = render(0.0)
    assert count(empty, (237, 173, 0)) > 40           # blue frame (#00ADED -> BGR 237,173,0)
    assert count(empty, (0, 255, 0)) == 0
    half = render(60.0)
    assert 0 < count(half, (0, 255, 0)) < count(render(75.0), (0, 255, 0))
    assert count(render(90.0), (0, 192, 255)) > 0     # yellow band
    assert count(render(110.0), (0, 0, 255)) > 0      # red band
    ys, _ = np.where(np.all(half == (0, 255, 0), axis=2))
    assert ys.max() > 40 and ys.min() > 20            # fills from the bottom
    assert render(None).sum() > 0                     # frame drawn without a value


def test_tank_icon_segments_style_lights_by_pressure_and_draws_its_outline():
    from gui.hud_renderer import tank_segments_geometry, tank_segments_lit
    assert tank_segments_geometry({"type": "tank_icon", "height": 23})[:3] == (5, 2, 200.0)
    assert tank_segments_lit(None, 200, 5) == 0 and tank_segments_lit(0, 200, 5) == 0
    assert tank_segments_lit(10, 200, 5) == 1 and tank_segments_lit(100, 200, 5) == 3 and tank_segments_lit(200, 200, 5) == 5 and tank_segments_lit(500, 200, 5) == 5

    def render(pressure, manufacturer="Shearwater", model="Perdix 2"):
        elem = {"field": "primary_tank_pressure", "type": "tank_icon", "style": "segments", "rel_x": 0.1, "rel_y": 0.25,
                "width": 12, "height": 23, "segments": 5, "segment_gap": 2, "full_bar": 200}
        layout = {"design_width": 1920, "design_height": 1080, "manufacturer": manufacturer, "model": model,
                  "hud_skin": {"type": "shape", "width": 200, "height": 100, "anchor": "TOP_LEFT", "opacity": 0.0,
                               "linked_elements": [elem]}}
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        tanks = {"T1": TankData(pressure_bar=pressure)} if pressure is not None else {}
        wp = Waypoint(timestamp=datetime.now(), depth=10.0, time_since_start=0, tanks=tanks)
        draw_hud(frame, layout, wp, render_log=True)
        return frame[10:60, 10:130]

    def count(frame, bgr):
        return int(np.all(frame == np.array(bgr, dtype=np.uint8), axis=2).sum())

    empty = render(None)
    assert count(empty, (58, 58, 58)) > 5 * 200        # five unlit segments
    assert count(empty, (154, 154, 154)) > 50          # grey outline (#9A9A9A)
    full = render(200.0)
    assert count(full, (255, 255, 255)) > 5 * 200      # Shearwater: white when comfortable
    assert count(full, (58, 58, 58)) == 0
    half = render(100.0)  # 2.5 of 5 segments -> rounds half up to 3 (each segment ~12x23 = 276 px)
    assert 2 * 276 < count(half, (255, 255, 255)) < 4 * 276 and count(half, (58, 58, 58)) > 300
    low = render(40.0)
    assert count(low, (0, 0, 255)) > 100 and count(low, (255, 255, 255)) == 0   # red band, one segment
    garmin = render(200.0, "Garmin", "x50i")
    assert count(garmin, (0, 255, 0)) > 5 * 200        # Garmin keeps green


def test_tank_icon_segments_bounds_span_all_segments_and_nose():
    from utils.hud_designer import element_native_bounds
    elem = {"field": "primary_tank_pressure", "type": "tank_icon", "style": "segments", "rel_x": 0.5, "rel_y": 0.5,
            "width": 12, "height": 23, "segments": 5, "segment_gap": 2, "outline_gap": 3, "outline_width": 2}
    x0, y0, x1, y1 = element_native_bounds(elem, 200, 200)
    assert (x0, y0) == (95.0, 95.0)
    assert x1 == 100 + 5 * 12 + 4 * 2 + 3 + 2 + 10 + 4   # segments + padding + stroke + nose + nub
    assert y1 == 100 + 23 + 3 + 2


# --- Graph deco mode (stops_color), reveal_profile, stop_label --------------

def _deco_waypoints():
    def wp(t, d, stop=None, ceiling=None, stop_time=None, ndl=None):
        return Waypoint(timestamp=datetime(2026, 1, 1) + timedelta(seconds=t), depth=d, time_since_start=t,
                        next_stop_depth=stop, ceiling=ceiling, next_stop_time=stop_time, ndl=ndl)
    return [
        wp(0, 0, ndl=5940), wp(10, 20, ndl=600), wp(20, 20, 3.0, 1.0, 60), wp(30, 20, 6.0, 4.0, 120),
        wp(40, 12, 6.0, 3.0, 60), wp(50, 6, 3.0, 1.0, 60), wp(60, 3, 3.0, 0.5, 30), wp(70, 0, ndl=5940),
    ]


DECO_ELEM = {"width": 100, "height": 50, "rel_x": 0.0, "rel_y": 0.0, "color": "#0000FF",
             "stops_color": "#00FF00", "ceiling_color": "#FF0000"}
GRAPH_SKIN = {"x": 0, "y": 0, "w": 1, "h": 1, "res_scale": 1.0}


def test_deco_graph_shades_stops_and_ceiling_separately_and_keeps_cleared_stops():
    from gui.hud_renderer import draw_depth_graph

    wps = _deco_waypoints()
    # x = 100 * t / 70; y = depth * 50 / 22
    six_m_stop_only = (47, 10)  # t~33, ~4.4m: under the 6m stop, below the ~3m ceiling
    ceiling_px = (44, 4)        # t~31, ~1.8m: under both

    # without reveal_profile the whole dive's stops are shaded from the start
    frame = np.zeros((50, 100, 3), dtype=np.uint8)
    draw_depth_graph(frame, DECO_ELEM, wps[3], wps, GRAPH_SKIN)
    assert frame[six_m_stop_only[1], six_m_stop_only[0]][1] > 0  # t=30: the later stop already on the graph
    # with it, a stop appears only once the dive reaches it
    frame = np.zeros((50, 100, 3), dtype=np.uint8)
    draw_depth_graph(frame, {**DECO_ELEM, "reveal_profile": True}, wps[3], wps, GRAPH_SKIN)
    assert frame[six_m_stop_only[1], six_m_stop_only[0]][1] == 0  # t=30: not revealed yet

    frame = np.zeros((50, 100, 3), dtype=np.uint8)
    draw_depth_graph(frame, DECO_ELEM, wps[-1], wps, GRAPH_SKIN)
    b, g, r = frame[six_m_stop_only[1], six_m_stop_only[0]]
    assert g > 0 and r == 0  # stops colour only, kept after the stop cleared
    b, g, r = frame[ceiling_px[1], ceiling_px[0]]
    assert g > 0 and r > 0  # ceiling blended on top of the stop


def test_reveal_profile_draws_line_only_up_to_the_cursor():
    from gui.hud_renderer import draw_depth_graph

    wps = _deco_waypoints()
    elem = {"width": 100, "height": 50, "rel_x": 0.0, "rel_y": 0.0, "color": "#0000FF", "marker_size": 1}
    late_bottom_px = (40, 45)  # t~28 on the 20m line (y ~45)

    frame = np.zeros((50, 100, 3), dtype=np.uint8)
    draw_depth_graph(frame, {**elem, "reveal_profile": True}, wps[1], wps, GRAPH_SKIN)
    assert frame[late_bottom_px[1], late_bottom_px[0]][0] == 0  # blue is channel 0 (BGR)

    frame = np.zeros((50, 100, 3), dtype=np.uint8)
    draw_depth_graph(frame, elem, wps[1], wps, GRAPH_SKIN)
    assert frame[late_bottom_px[1], late_bottom_px[0]][0] > 0  # the default still draws the whole dive


def test_graph_stop_label_text():
    from gui.hud_renderer import graph_stop_label

    wps = _deco_waypoints()
    assert graph_stop_label(wps[3]) == ("STOP 6m 2:00", True)
    assert graph_stop_label(wps[1]) is None  # out of deco: nothing (no NDL fallback)
    legacy = Waypoint(timestamp=datetime.now(), depth=10, time_since_start=0, deco_stop_depth=4.2)
    assert graph_stop_label(legacy) == ("STOP 6m", True)  # stop depth rounded up to a 3m level


def test_stop_label_is_drawn_in_the_text_pass():
    wps = _deco_waypoints()
    layout = _shape_layout([{**DECO_ELEM, "type": "graph", "field": "depth_graph", "width": 180, "height": 90}])
    without = np.zeros((1080, 1920, 3), dtype=np.uint8)
    draw_hud(without, layout, wps[3], render_log=False, waypoints=wps)
    layout["hud_skin"]["linked_elements"][0]["stop_label"] = True
    with_label = np.zeros((1080, 1920, 3), dtype=np.uint8)
    draw_hud(with_label, layout, wps[3], render_log=False, waypoints=wps)
    assert not np.array_equal(without, with_label)


def test_mk3i_badge_is_label_less_ceiling_over_short_timer():
    # Descent Mk3 manual p.10: the NDL slot shows "↑ceiling" small over the
    # stop timer as 2:33 - no STOP/DECO word, white text.
    from gui.hud_renderer import badge_lines
    elem = {"field": "state_badge", "type": "badge", "rel_x": 0, "rel_y": 0,
            "depth_font": "label", "depth_unit": "m", "timer_format": "m:ss"}
    deco = Waypoint(timestamp=datetime.now(), depth=6.2, time_since_start=0,
                    deco_stop_depth=6.0, next_stop_depth=6.0, next_stop_time=153)
    lines = badge_lines("Garmin", "mk3i", elem, deco)
    assert [t for t, _, _ in lines] == ["↑6m", "2:33"]
    assert [v for _, _, v in lines] == [False, True]
    assert all(rgb == (255, 255, 255) for _, rgb, _ in lines)


def test_ceiling_broken_flashes_depth_line_red_on_garmin_only():
    from gui.hud_renderer import badge_lines
    from utils.hud_rules_engine import ceiling_broken
    elem = {"field": "state_badge", "type": "badge", "rel_x": 0, "rel_y": 0}
    within = Waypoint(timestamp=datetime.now(), depth=5.5, time_since_start=0, dive_time=0,
                      deco_stop_depth=6.0, next_stop_depth=6.0, next_stop_time=60)
    above = Waypoint(timestamp=datetime.now(), depth=5.0, time_since_start=0, dive_time=0,
                     deco_stop_depth=6.0, next_stop_depth=6.0, next_stop_time=60)
    assert not ceiling_broken("Garmin", "mk3i", within)
    assert ceiling_broken("Garmin", "mk3i", above)
    assert not ceiling_broken("Shearwater", "Perdix 2", above)  # no such rule there
    # dive_time 0 -> first half of the blink period -> the red phase
    assert badge_lines("Garmin", "mk3i", elem, above)[0][1] == (255, 0, 0)
    assert badge_lines("Garmin", "mk3i", elem, within)[0][1] == (255, 255, 255)


@pytest.mark.parametrize("variant", ["single_tank", "sidemount"])
def test_garmin_mk3i_main_renders_stop_states_in_the_ndl_slot(variant):
    from utils.layouts import resolve_template_state
    state_path = resolve_template_state("garmin", "mk3i", "main", variant=variant)
    layout = strip_variant_markers(load_layout_file(state_path))
    layout["hud_skin"]["path"] = str((state_path.parent / layout["hud_skin"]["path"]).resolve())
    elems = layout["hud_skin"]["linked_elements"]
    badge = next(e for e in elems if e.get("type") == "badge")
    assert badge["depth_font"] == "label" and badge["timer_format"] == "m:ss"
    for field in ("ndl", "custom:N\nD\nL"):
        assert set(next(e for e in elems if e["field"] == field)["hide_in_states"]) == {"safety_stop", "deco", "clear"}
    tanks = {"T1": TankData(pressure_bar=150, o2_percent=32.0), "T2": TankData(pressure_bar=140, o2_percent=32.0)}
    deco = Waypoint(timestamp=datetime.now(), depth=12.0, max_depth=40.0, temp=27.0, time_since_start=1500,
                    dive_time=1500, deco_stop_depth=6.0, next_stop_depth=6.0, next_stop_time=180, ndl=0, tanks=tanks)
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    draw_hud(frame, layout, deco, render_log=False)
    assert not np.all(frame == 0)



def test_perdix_badge_phases_from_the_manual():
    from gui.hud_renderer import badge_lines
    from models.dive import Waypoint
    elem = {"field": "state_badge", "type": "badge", "rel_x": 0, "rel_y": 0, "depth_unit": "m"}
    at_stop = Waypoint(timestamp=datetime.now(), depth=6.8, time_since_start=0, dive_time=0,
                       deco_stop_depth=6.0, next_stop_depth=6.0, next_stop_time=120)
    lines = badge_lines("Shearwater", "Perdix 2", elem, at_stop)
    assert lines[0] == ("✓ DECO STOP", (0, 200, 0), False)       # green title with a check at the stop
    assert lines[1][0] == "6m↑ 2min"
    approaching = Waypoint(timestamp=datetime.now(), depth=9.0, time_since_start=0, dive_time=0,
                           deco_stop_depth=6.0, next_stop_depth=6.0, next_stop_time=120)
    assert badge_lines("Shearwater", "Perdix 2", elem, approaching)[0][1] == (255, 255, 0)  # yellow while approaching
    # the safety stop shows its planned time with no depth line; the Garmin box keeps its ↑5m
    counting = Waypoint(timestamp=datetime.now(), depth=5.0, max_depth=20.0, time_since_start=0, dive_time=0,
                        dive_alerts=["safety_stop_started"], next_stop_depth=5.0, next_stop_time=150)
    sw = badge_lines("Shearwater", "Perdix 2", elem, counting)
    assert [t for t, _, _ in sw] == ["✓ SAFETY STOP", "2:30"]
    assert sw[1][1] == (255, 255, 255)
    garmin = badge_lines("Garmin", "x50i", elem, counting)
    assert [t for t, _, _ in garmin] == ["STOP", "↑5m", "02:30"]
    cleared = Waypoint(timestamp=datetime.now(), depth=4.5, time_since_start=0, dive_time=0,
                       deco_stop_depth=0.0, next_stop_depth=0.0, next_stop_time=0, dive_alerts=["deco_stop_cleared"])
    assert [t for t, _, _ in badge_lines("Shearwater", "Perdix 2", elem, cleared)] == ["CLEAR", "0:00"]


def test_sac_formats_like_the_perdix():
    from gui.hud_renderer import format_telemetry_value
    assert format_telemetry_value("pressure_sac", None) == "wait"
    assert format_telemetry_value("pressure_sac", 1.06) == "1.1"


def test_perdix2_main_variants_share_a_base_and_the_sidemount_row_highlights_the_tank_to_switch_to():
    from utils.layouts import ELEMENT_ORIGIN_KEY, load_layout_file
    page = Path("overlays/templates/shearwater/perdix_2/main")
    base = json.load(open(page / "normal.json"))
    assert [e["id"] for e in base["hud_skin"]["linked_elements"]] == [
        "depth", "label_m", "label_time", "dive_time", "state_badge", "label_ndl", "ndl", "n2_bar", "ascent_rate"]
    single = load_layout_file(page / "single_tank/normal.json")
    side = load_layout_file(page / "sidemount/normal.json")
    single_row = [e["field"] for e in single["hud_skin"]["linked_elements"] if e[ELEMENT_ORIGIN_KEY] == "variant"]
    side_row = [e["field"] for e in side["hud_skin"]["linked_elements"] if e[ELEMENT_ORIGIN_KEY] == "variant"]
    assert single_row[0] == "gasmix" and "air_remaining" in single_row
    assert {"pressure_sac", "custom:SM", "secondary_tank_pressure"} <= set(side_row)
    assert not (page / "sidemount/normal.png").exists() and (page / "normal.png").exists()

    layout = _load_perdix2_layout("main", variant="sidemount")
    tanks = {"T1": TankData(pressure_bar=175, o2_percent=21.0), "T2": TankData(pressure_bar=153, o2_percent=21.0)}
    wp = Waypoint(timestamp=datetime.now(), depth=15.7, max_depth=15.7, temp=23.0, dive_time=2151,
                  time_since_start=2151, ndl=22 * 60, air_remaining=45 * 60, pressure_sac=1.1, tanks=tanks, gf=40.0)
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    draw_hud(frame, layout, wp, render_log=False)
    green = (frame[:, :, 1] > 180) & (frame[:, :, 0] < 60) & (frame[:, :, 2] < 60)
    # the switch highlight (#00C800 box behind T1) adds a green patch in the info row's left cell
    even = {"T1": TankData(pressure_bar=170, o2_percent=21.0), "T2": TankData(pressure_bar=165, o2_percent=21.0)}
    frame_even = np.zeros((1080, 1920, 3), dtype=np.uint8)
    draw_hud(frame_even, layout, wp.model_copy(update={"tanks": even}), render_log=False)
    green_even = (frame_even[:, :, 1] > 180) & (frame_even[:, :, 0] < 60) & (frame_even[:, :, 2] < 60)
    assert green.sum() > green_even.sum() + 50


def test_teric_badge_lines_follow_its_manual():
    from gui.hud_renderer import badge_lines
    elem = {"field": "state_badge", "type": "badge", "rel_x": 0, "rel_y": 0, "depth_unit": "m"}
    counting = Waypoint(timestamp=datetime.now(), depth=5.0, max_depth=20.0, time_since_start=0, dive_time=0,
                        dive_alerts=["safety_stop_started"], next_stop_depth=5.0, next_stop_time=202)
    lines = badge_lines("Shearwater", "Teric", elem, counting)
    assert lines == [("SAFETY", (0, 200, 0), False), ("3:22", (0, 200, 0), True)]
    deco = Waypoint(timestamp=datetime.now(), depth=20.0, time_since_start=0, dive_time=0,
                    deco_stop_depth=15.0, next_stop_depth=15.0, next_stop_time=120)
    lines = badge_lines("Shearwater", "Tern", elem, deco)
    assert lines == [("DECO", (255, 0, 0), False), ("15m↑ 2min", (255, 255, 255), True)]


@pytest.mark.parametrize("computer", ["teric", "tern"])
def test_watch_templates_replace_the_ndl_with_the_stop_badge(computer):
    state_path = resolve_template_state("shearwater", computer, "main")
    layout = strip_variant_markers(load_layout_file(state_path))
    layout["hud_skin"]["path"] = str((state_path.parent / layout["hud_skin"]["path"]).resolve())
    elems = layout["hud_skin"]["linked_elements"]
    assert any(e.get("type") == "badge" for e in elems)
    for field in ("ndl", "custom:NDL"):
        assert set(next(e for e in elems if e["field"] == field)["hide_in_states"]) == {"safety_stop", "deco", "clear"}
    deco = Waypoint(timestamp=datetime.now(), depth=12.0, max_depth=30.0, temp=27.0, time_since_start=1500,
                    dive_time=1500, deco_stop_depth=9.0, next_stop_depth=9.0, next_stop_time=120, ndl=0, tts=600,
                    tanks={"T1": TankData(pressure_bar=150, o2_percent=32.0)})
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    draw_hud(frame, layout, deco, render_log=False)
    assert not np.all(frame == 0)


def test_petrel_main_variants_share_a_base_like_the_perdix():
    from utils.layouts import ELEMENT_ORIGIN_KEY, load_layout_file
    page = Path("overlays/templates/shearwater/petrel/main")
    assert json.load(open(page / "single_tank/normal.json"))["base"] == "../normal.json"
    side = load_layout_file(page / "sidemount/normal.json")
    row = [e["field"] for e in side["hud_skin"]["linked_elements"] if e[ELEMENT_ORIGIN_KEY] == "variant"]
    assert {"pressure_sac", "custom:SM", "secondary_tank_pressure", "primary_tank_pressure"} <= set(row)
    assert (page / "normal.png").exists() and not (page / "sidemount/normal.png").exists()


def test_perdix_3_badge_lines_and_boxed_title():
    from gui.hud_renderer import badge_lines
    elem = {"field": "state_badge", "type": "badge", "rel_x": 0, "rel_y": 0, "depth_unit": "m"}
    counting = Waypoint(timestamp=datetime.now(), depth=5.0, max_depth=20.0, time_since_start=0, dive_time=0,
                        dive_alerts=["safety_stop_started"], next_stop_depth=5.0, next_stop_time=202)
    assert badge_lines("Shearwater", "Perdix 3", elem, counting) == [("SAFETY", (0, 200, 0), False), ("3:22", (0, 200, 0), True)]
    deco = Waypoint(timestamp=datetime.now(), depth=23.6, time_since_start=0, dive_time=0,
                    deco_stop_depth=18.0, next_stop_depth=18.0, next_stop_time=60)
    assert badge_lines("Shearwater", "Perdix 3", elem, deco) == [("DECO", (0, 173, 237), False), ("18m↑ 1min", (255, 255, 255), True)]
    # the boxed title paints a green block behind "SAFETY" on the rendered page
    layout = _load_perdix3_layout("main")
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    draw_hud(frame, layout, counting, render_log=False)
    green_block = ((frame[:, :, 1] > 180) & (frame[:, :, 0] < 60) & (frame[:, :, 2] < 60)).sum()
    frame_normal = np.zeros((1080, 1920, 3), dtype=np.uint8)
    draw_hud(frame_normal, layout, Waypoint(timestamp=datetime.now(), depth=18.0, time_since_start=0, ndl=12 * 60), render_log=False)
    green_normal = ((frame_normal[:, :, 1] > 180) & (frame_normal[:, :, 0] < 60) & (frame_normal[:, :, 2] < 60)).sum()
    assert green_block > green_normal + 200


@pytest.mark.parametrize("page", ["main", "standard", "tec"])
def test_perdix_3_pages_hide_the_ndl_while_a_stop_shows(page):
    layout = _load_perdix3_layout(page)
    elems = layout["hud_skin"]["linked_elements"]
    assert any(e.get("type") == "badge" for e in elems)
    for field in ("ndl", "custom:NDL"):
        assert set(next(e for e in elems if e["field"] == field)["hide_in_states"]) == {"safety_stop", "deco", "clear"}


def test_shearwater_safety_stop_time_is_centred_under_the_title():
    # hud_rules.json gives the Shearwater safety stop value_align "center":
    # the timer's ink is centred under "✓ SAFETY STOP" (check mark included),
    # while the Garmin-style badge keeps every line on the left anchor.
    from gui.hud_renderer import badge_title_ink_span, get_font
    layout = _shape_layout([{"type": "badge", "field": "state_badge", "font_size": 28, "value_font_size": 38,
                             "rel_x": 0.1, "rel_y": 0.1, "outline": False}], "Shearwater", "Perdix 2")
    counting = Waypoint(timestamp=datetime.now(), depth=5.0, max_depth=20.0, time_since_start=0, dive_time=0,
                        dive_alerts=["safety_stop_started"], next_stop_depth=5.0, next_stop_time=150)
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    draw_hud(frame, layout, counting, render_log=False)
    green = (frame[:, :, 1] > 150) & (frame[:, :, 0] < 80) & (frame[:, :, 2] < 80)   # "✓ SAFETY STOP" in #00C800
    white = (frame[:, :, 0] > 200) & (frame[:, :, 1] > 200) & (frame[:, :, 2] > 200)  # "2:30"
    assert green.any() and white.any()
    title_cols = np.where(green.any(axis=0))[0]
    timer_cols = np.where(white.any(axis=0))[0]
    title_center = (title_cols.min() + title_cols.max()) / 2
    timer_center = (timer_cols.min() + timer_cols.max()) / 2
    assert abs(title_center - timer_center) <= 3
    assert timer_cols.min() > title_cols.min() + 20  # not left-anchored any more
    # the span helper counts the drawn check mark in front of the title
    font = get_font(28)
    plain = badge_title_ink_span(font, "SAFETY STOP", 28)
    checked = badge_title_ink_span(font, "✓ SAFETY STOP", 28)
    assert checked[1] - checked[0] > plain[1] - plain[0]


def _ink_box(frame):
    ink = frame.max(axis=2) > 40
    rows = np.where(ink.any(axis=1))[0]
    cols = np.where(ink.any(axis=0))[0]
    return cols.min(), rows.min(), cols.max(), rows.max()


def test_vertical_text_orientations_stack_or_turn_the_label():
    # `orientation` on a text element: "stacked" draws the letters one under
    # another, "up"/"down" turn the line on its side - all taller than wide
    # for a word, and the designer's bounds follow the painted ink.
    def render(orientation, **extra):
        elem = {"field": "custom:SAFETY", "font_size": 40, "rel_x": 0.3, "rel_y": 0.2, "outline": False, "orientation": orientation}
        elem.update(extra)
        layout = _shape_layout([elem])
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        wp = Waypoint(timestamp=datetime.now(), depth=5.0, time_since_start=0)
        draw_hud(frame, layout, wp, render_log=False)
        return frame
    flat = _ink_box(render("horizontal"))
    assert flat[2] - flat[0] > flat[3] - flat[1]
    for orientation in ("stacked", "up", "down"):
        x0, y0, x1, y1 = _ink_box(render(orientation))
        assert y1 - y0 > x1 - x0, orientation
    up, down = render("up"), render("down")
    assert not np.array_equal(up, down)  # mirrored reading directions
    # "up" reads bottom-to-top: the S (first letter) ends up at the bottom, so
    # flipping "up" twice (180°) is "down" apart from anchor placement -
    # the ink boxes have the same shape
    bu, bd = _ink_box(up), _ink_box(down)
    assert abs((bu[2] - bu[0]) - (bd[2] - bd[0])) <= 2 and abs((bu[3] - bu[1]) - (bd[3] - bd[1])) <= 2
    # outline adds a halo but keeps it vertical
    hx0, hy0, hx1, hy1 = _ink_box(render("stacked", outline=True))
    assert hy1 - hy0 > hx1 - hx0


def test_vertical_text_bounds_match_the_ink_in_the_designer():
    from gui.hud_renderer import get_font, oriented_text_geometry
    font = get_font(40)
    for orientation in ("stacked", "up", "down"):
        dx, dy, w, h = oriented_text_geometry(font, "SAFETY", orientation, 40)
        assert h > w and dx == 0 and dy == 0
        cdx, cdy, _, _ = oriented_text_geometry(font, "SAFETY", orientation, 40, "center", "middle")
        assert cdx == -w / 2 and cdy == -h / 2


def test_shearwater_ascent_arrows_follow_the_perdix_manual():
    # Perdix 2 manual p.12: 1 arrow per 3 m/min, white < 9, yellow 9-18,
    # flashing red > 18; six arrows and no divider bar (hud_rules.json).
    from gui.hud_renderer import ascent_lit_count
    assert ascent_lit_count(2.0, 6, 3.0) == 1 and ascent_lit_count(3.0, 6, 3.0) == 1
    assert ascent_lit_count(8.0, 6, 3.0) == 3 and ascent_lit_count(10.0, 6, 3.0) == 4 and ascent_lit_count(25.0, 6, 3.0) == 6
    t0 = datetime.now()

    def render(rate, elapsed=0, **extra):
        elem = {"field": "ascent_rate", "type": "ascent_chevrons", "rel_x": 0.25, "rel_y": 0.25, "width": 16, "height": 48,
                "up_count": 6, "down_count": 0}
        elem.update(extra)
        layout = {"design_width": 1920, "design_height": 1080, "manufacturer": "Shearwater", "model": "Perdix 2",
                  "hud_skin": {"type": "shape", "width": 200, "height": 200, "anchor": "TOP_LEFT", "opacity": 0.0,
                               "linked_elements": [elem]}}
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        wp = Waypoint(timestamp=t0, depth=10.0, time_since_start=elapsed, ascent_rate=rate)
        draw_hud(frame, layout, wp, render_log=True)
        return frame[50:98, 50:66]

    def count(frame, bgr):
        return int(np.all(frame == np.array(bgr, dtype=np.uint8), axis=2).sum())

    level = render(0.0)
    assert count(level, (138, 138, 138)) > 100 and count(level, (255, 255, 255)) == 0  # six grey arrows, no bar
    slow = render(5.0)
    assert count(slow, (255, 255, 255)) > 0 and count(slow, (0, 255, 255)) == 0          # two white arrows
    warn = render(12.0)
    assert count(warn, (0, 255, 255)) > count(slow, (255, 255, 255))                     # four yellow
    fast = render(20.0)
    assert count(fast, (0, 0, 255)) > 0 and count(fast, (0, 255, 255)) == 0                # all six red
    # the red is the blink colour (shown in the first half of each second, so
    # at whole-second waypoints), the unlit grey the other half
    from utils.hud_rules_engine import resolve_blink_color
    assert resolve_blink_color("#8A8A8A", "#FF0000", 3.0) == "#FF0000" and resolve_blink_color("#8A8A8A", "#FF0000", 3.75) == "#8A8A8A"
    # the brand rule supplies the missing bar/count defaults; an element can put the bar back
    assert count(render(0.0, bar=True), (255, 255, 255)) > 10


def test_graph_shading_colour_and_opacity_are_element_keys():
    # fill_color / fill_opacity (under the line), ceiling_opacity (band or
    # deco ceiling) and stops_opacity (deco steps) - 0 hides the area
    from gui.hud_renderer import draw_depth_graph
    wps = _deco_waypoints()
    under_line = (30, 40)      # t~21, ~17.6 m: under the 20 m bottom, below every stop
    six_m_stop_only = (47, 10)
    ceiling_px = (44, 4)
    plain = {"width": 100, "height": 50, "rel_x": 0.0, "rel_y": 0.0, "color": "#0000FF"}

    frame = np.zeros((50, 100, 3), dtype=np.uint8)
    draw_depth_graph(frame, plain, wps[-1], wps, GRAPH_SKIN)
    assert frame[under_line[1], under_line[0]][0] > 0                       # default fill: a faint blue tint

    frame = np.zeros((50, 100, 3), dtype=np.uint8)
    draw_depth_graph(frame, {**plain, "fill_opacity": 0}, wps[-1], wps, GRAPH_SKIN)
    assert tuple(frame[under_line[1], under_line[0]]) == (0, 0, 0)          # no fill at all

    frame = np.zeros((50, 100, 3), dtype=np.uint8)
    draw_depth_graph(frame, {**plain, "fill_color": "#00FF00", "fill_opacity": 1.0}, wps[-1], wps, GRAPH_SKIN)
    assert tuple(frame[under_line[1], under_line[0]]) == (0, 255, 0)        # solid, in the fill colour (BGR)

    frame = np.zeros((50, 100, 3), dtype=np.uint8)
    draw_depth_graph(frame, {**DECO_ELEM, "stops_opacity": 0, "ceiling_opacity": 0}, wps[-1], wps, GRAPH_SKIN)
    assert frame[six_m_stop_only[1], six_m_stop_only[0]][1] == 0 and frame[ceiling_px[1], ceiling_px[0]][2] == 0

    frame = np.zeros((50, 100, 3), dtype=np.uint8)
    draw_depth_graph(frame, {**DECO_ELEM, "fill_opacity": 0, "stops_opacity": 1.0, "ceiling_opacity": 0}, wps[-1], wps, GRAPH_SKIN)
    assert tuple(frame[six_m_stop_only[1], six_m_stop_only[0]]) == (0, 255, 0)  # solid stops colour


def test_graph_background_box_colour_and_opacity():
    from gui.hud_renderer import draw_depth_graph
    wps = _deco_waypoints()
    plain = {"width": 100, "height": 50, "rel_x": 0.0, "rel_y": 0.0, "color": "#0000FF", "fill_opacity": 0}
    corner = (30, 10)  # inside the box, well above the 20 m bottom at t=20-30, no ceiling band there
    frame = np.full((50, 100, 3), 200, dtype=np.uint8)
    draw_depth_graph(frame, plain, wps[-1], wps, GRAPH_SKIN)
    assert 100 < frame[corner[1], corner[0]][0] < 140                       # default: black box at 0.4 over grey
    frame = np.full((50, 100, 3), 200, dtype=np.uint8)
    draw_depth_graph(frame, {**plain, "background_opacity": 0}, wps[-1], wps, GRAPH_SKIN)
    assert tuple(frame[corner[1], corner[0]]) == (200, 200, 200)            # no box at all
    frame = np.full((50, 100, 3), 200, dtype=np.uint8)
    draw_depth_graph(frame, {**plain, "background_color": "#FF0000", "background_opacity": 1.0}, wps[-1], wps, GRAPH_SKIN)
    assert tuple(frame[corner[1], corner[0]]) == (0, 0, 255)                # solid, in the box colour (BGR)
