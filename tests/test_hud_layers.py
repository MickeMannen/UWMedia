"""ffmpeg/hud_layers.py: the Color page's HUD drawn once per dive sample as
transparent PNGs that FFmpeg overlays, instead of onto every video frame."""
import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import numpy as np
import pytest

from ffmpeg.color import ColorCorrectionEngine
from ffmpeg.hud_layers import (HudLayer, hud_segments, matte, overlay_filter_complex,
                               write_layer_stream)
from gui.hud_renderer import draw_hud, resolve_overlay_instance_layout
from conftest import DJI_CLIP, SONY_CLIP, run_cli
from models.dive import Dive, Waypoint

BASE_DIR = Path(__file__).parent.parent
TEMPLATES = BASE_DIR / "overlays" / "templates"
FRAME_W, FRAME_H = 3840, 2160
START = datetime(2025, 1, 1, 10, 0, 0)
WAYPOINTS = [Waypoint(timestamp=START + timedelta(seconds=s), depth=5 + s * 0.5, temp=24.0, time_since_start=s)
             for s in range(0, 50, 5)]


def _layout(rel_path, x, y, scale):
    path = TEMPLATES / rel_path
    raw = json.loads(path.read_text())
    skin = raw.get("hud_skin", {}).get("path")
    if skin and not Path(skin).is_absolute():
        raw["hud_skin"]["path"] = str(path.parent / skin)
    return resolve_overlay_instance_layout(raw, x, y, scale, FRAME_W, FRAME_H)


def _background():
    rng = np.random.default_rng(0)
    return rng.integers(0, 256, (FRAME_H, FRAME_W, 3), dtype=np.uint8)


def test_matte_recovers_colour_and_alpha():
    colour = np.array([40, 120, 200], dtype=np.float32)
    on_black = np.rint(colour * 0.25).astype(np.uint8)[None, None, :].repeat(2, 0)
    on_white = np.rint(colour * 0.25 + 255 * 0.75).astype(np.uint8)[None, None, :].repeat(2, 0)
    bgra = matte(on_black, on_white)
    assert abs(int(bgra[0, 0, 3]) - 64) <= 1
    assert np.all(np.abs(bgra[0, 0, :3].astype(int) - colour.astype(int)) <= 3)
    empty = matte(np.zeros((2, 2, 3), np.uint8), np.full((2, 2, 3), 255, np.uint8))
    assert not empty[:, :, 3].any()


@pytest.mark.parametrize("rel_path,x,y,scale", [
    ("shearwater/perdix_2/main/normal.json", 0.02, 0.62, 1.0),
    ("shearwater/perdix_2/main/normal.json", 0.9, 0.9, 0.7),   # partly off-frame
    ("generic/dive_profile/main/normal.json", 0.6, 0.05, 1.3),
    ("generic/depth_temp/standard/normal.json", 0.3, 0.4, 1.0),
    ("garmin/x50i/main/normal.json", 0.5, 0.5, 1.2),
])
def test_layer_on_cropped_canvas_matches_drawing_on_the_frame(rel_path, x, y, scale):
    layout = _layout(rel_path, x, y, scale)
    skin = ColorCorrectionEngine(None)._preload_hud_skin(layout, FRAME_W)
    frame = _background()
    expected = frame.copy()
    draw_hud(expected, layout, WAYPOINTS[4], preloaded_skin=skin, waypoints=WAYPOINTS)

    layer = HudLayer(layout, skin, FRAME_W, FRAME_H, resolved=True)
    bgra = layer.render(WAYPOINTS[4], WAYPOINTS)
    x0, y0, x1, y1 = layer.region
    assert (x1 - x0) * (y1 - y0) < FRAME_W * FRAME_H, "layer should be drawn on a cropped canvas"
    out = frame.astype(np.float32)
    a = bgra[:, :, 3:4] / 255.0
    out[y0:y1, x0:x1] = bgra[:, :, :3] * a + out[y0:y1, x0:x1] * (1 - a)

    diff = np.abs(out - expected).max(axis=2)
    # Blending rounding only; the dive profile's line may land 1 px over where
    # int() truncates a value a hair under a whole pixel (frame offset dependent)
    assert (diff > 3).sum() < 400


def test_layer_reaching_the_canvas_edge_widens():
    layout = _layout("shearwater/perdix_2/main/normal.json", 0.3, 0.3, 1.0)
    skin = ColorCorrectionEngine(None)._preload_hud_skin(layout, FRAME_W)
    layer = HudLayer(layout, skin, FRAME_W, FRAME_H, resolved=True)
    first = layer.region
    layer.widen()
    assert layer.region[0] < first[0] and layer.region[2] > first[2]
    layer.widen()
    assert layer.region == (0, 0, FRAME_W, FRAME_H)


def test_hud_segments_group_frames_showing_the_same_sample():
    dive = Dive(start_time=START, end_time=WAYPOINTS[-1].timestamp, waypoints=WAYPOINTS)
    fps, total = 10.0, 120  # 12 s of video over samples every 5 s
    segments = hud_segments(dive, START, fps, total)
    assert sum(n for _wp, _s, n in segments) == total
    assert [wp.time_since_start for wp, _s, _n in segments] == [0, 5, 10]
    for wp, start, n in segments:
        for i in (start, start + n - 1):
            assert dive.get_waypoint_at(START + timedelta(seconds=i / fps)) is wp


def test_layer_stream_concat_times_each_png(tmp_path):
    layout = _layout("generic/depth_temp/standard/normal.json", 0.1, 0.1, 1.0)
    layer = HudLayer(layout, None, FRAME_W, FRAME_H, resolved=True)
    dive = Dive(start_time=START, end_time=WAYPOINTS[-1].timestamp, waypoints=WAYPOINTS)
    segments = hud_segments(dive, START, 50.0, 600)
    concat, x, y = write_layer_stream(layer, segments, WAYPOINTS, 50.0, tmp_path, 0)
    assert (x, y) == layer.region[:2]
    lines = concat.read_text().splitlines()
    assert lines[0] == "ffconcat version 1.0"
    durations = [float(line.split()[1]) for line in lines if line.startswith("duration")]
    assert abs(sum(durations) - 600 / 50.0) < 1e-6
    pngs = [line.split("'")[1] for line in lines if line.startswith("file")]
    assert len(pngs) == len(durations)
    img = cv2.imread(pngs[0], cv2.IMREAD_UNCHANGED)
    assert img.shape[2] == 4 and img[:, :, 3].any()


def test_overlay_filter_complex_overlays_layers_in_order_after_colour():
    graph, out = overlay_filter_complex("lut3d=file='x.cube'", [(10, 20), (30, 40)])
    assert graph == ("[0:v]lut3d=file='x.cube'[v0];"
                     "[1:v]format=rgba[h1];[v0][h1]overlay=x=10:y=20:eof_action=repeat[v1];"
                     "[2:v]format=rgba[h2];[v1][h2]overlay=x=30:y=40:eof_action=repeat[v2]")
    assert out == "[v2]"
    assert overlay_filter_complex(None, []) == ("[0:v]null[v0]", "[v0]")


def test_hw_decodable_rejects_10bit_422_h264():
    # VideoToolbox drops frames of Sony's 10-bit 4:2:2 H.264 instead of
    # falling back to software decoding
    from ffmpeg.ffmpeg_class import FfmpegClass
    ff = FfmpegClass()
    assert ff.hw_decodable(SONY_CLIP) is False
    assert ff.hw_decodable(DJI_CLIP) is True


@pytest.mark.render
def test_overlay_render_keeps_every_frame_and_reports_progress(tmp_path, synthetic_logs):
    video_source = SONY_CLIP
    layout_path = tmp_path / "layout.json"
    layout_path.write_text(json.dumps({
        "design_width": 1920,
        "hud_skin": {"type": "shape", "width": 300, "height": 120, "color": "#808080", "opacity": 1.0,
                     "linked_elements": [{"field": "depth", "rel_x": 0.1, "rel_y": 0.3, "font_size": 24,
                                          "color": "#ffffff"}]},
    }))
    overlays = tmp_path / "overlays.json"
    overlays.write_text(json.dumps([{"layout_path": str(layout_path), "x": 0.1, "y": 0.1, "scale": 1.0}]))
    result = run_cli(video_source, tmp_path, "--logs", synthetic_logs, "--overlays-file", overlays,
                     "--color", "default", "--filename-format", "result", "--tz-adjust", "0", "--hw-accel")
    assert result.returncode == 0, result.stdout[-800:] + result.stderr

    progress = [float(line.split()[1]) for line in result.stdout.splitlines()
                if line.startswith("UWMEDIA_FFMPEG_PROGRESS") and line.endswith(video_source.name)]
    # a 2 s fixture clip reports ~5 updates (a 10 s one reported >10)
    assert len(progress) >= 3 and progress == sorted(progress) and progress[-1] == 100.0
    # No \r-redrawn tqdm bars when piped
    assert "\r" not in result.stdout + result.stderr

    def frames(path):
        return int(subprocess.check_output(
            ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v",
             "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(path)]).decode().strip())
    assert frames(tmp_path / "result.mp4") == frames(video_source)
