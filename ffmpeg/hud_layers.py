"""HUD layers for ColorCorrectionEngine.process_video's overlay render.

The HUD only changes when the dive sample does (Dive.get_waypoint_at
returns the nearest sample, typically 1-10 s apart), so each layer is drawn
once per sample as a transparent PNG instead of onto every video frame in
Python. FFmpeg reads each layer's PNGs through a concat list (one entry per
run of frames showing the same sample) and overlays them on the colour-
corrected footage itself, so the source never passes through Python.

draw_hud only draws onto an opaque BGR frame; the layer's alpha comes from
drawing it twice, on black and on white (every HUD element is blended
linearly onto the frame, so the difference between the two is exactly how
much of the background shows through).
"""
import copy
import math
from pathlib import Path

import cv2
import numpy as np

from gui.hud_renderer import draw_hud

# Room around a layer's skin for elements drawn past its edge, tried in
# order: a layer whose drawing reaches the canvas edge is redrawn on the
# next one, and finally on the whole frame (HudLayer.render/widen)
CANVAS_PADS = (64, 256)


def hud_segments(dive, creation_date, fps, total_frames):
    """[(waypoint, start_frame, n_frames)]: the runs of consecutive frames
    that show the same dive sample - the same per-frame lookup the HUD used
    when it was drawn onto every frame."""
    from datetime import timedelta
    segments = []
    for i in range(total_frames):
        wp = dive.get_waypoint_at(creation_date + timedelta(seconds=i / fps))
        if segments and segments[-1][0] is wp:
            segments[-1][2] += 1
        else:
            segments.append([wp, i, 1])
    return [tuple(s) for s in segments]


def matte(on_black, on_white):
    """BGRA from the same HUD drawn on black and on white: alpha is how
    little of the background shows through, colour is un-premultiplied."""
    b = on_black.astype(np.float32)
    w = on_white.astype(np.float32)
    alpha = 1.0 - (w - b).mean(axis=2, keepdims=True) / 255.0
    alpha = np.clip(alpha, 0.0, 1.0)
    colour = np.where(alpha > 0, b / np.maximum(alpha, 1e-6), 0.0)
    bgra = np.empty(on_black.shape[:2] + (4,), dtype=np.uint8)
    bgra[:, :, :3] = np.clip(np.rint(colour), 0, 255)
    bgra[:, :, 3] = np.rint(alpha[:, :, 0] * 255.0)
    return bgra


def _canvas_design_width(design_w, canvas_w, res_scale):
    """design_width that makes draw_hud's res_scale (canvas_w / design_width)
    come out exactly the full frame's, so every int() size it takes matches."""
    dw = canvas_w / res_scale
    for _ in range(8):
        got = canvas_w / dw
        if got == res_scale:
            break
        dw = math.nextafter(dw, 0.0 if got < res_scale else math.inf)
    return dw


class HudLayer:
    """One overlay as drawn by draw_hud on a frame_w x frame_h video, kept
    on the smallest canvas that holds it. `resolved` marks a layout from
    resolve_overlay_instance_layout (TOP_LEFT anchor + ref offsets), whose
    skin position is known and can be drawn on a cropped canvas; any other
    layout is drawn full-frame."""

    def __init__(self, layout, preloaded_skin, frame_w, frame_h, resolved):
        self.layout = layout
        self.skin = preloaded_skin
        self.frame_w, self.frame_h = frame_w, frame_h
        self._pad_index = 0
        self.full_frame()
        if resolved:
            self._crop_to_skin(CANVAS_PADS[0])

    def _crop_to_skin(self, pad):
        hud_skin = self.layout.get("hud_skin", {})
        design_w = float(self.layout.get("design_width", 1920))
        res_scale = self.frame_w / design_w
        if hud_skin.get("type", "image") == "shape":
            w_hud = int(hud_skin.get("width", 400) * res_scale)
            h_hud = int(hud_skin.get("height", 200) * res_scale)
        elif self.skin is not None:
            h_hud, w_hud = self.skin.shape[:2]
        else:
            return
        skin_x = int(hud_skin.get("ref_offset_x", 0.0) * res_scale)
        skin_y = int(hud_skin.get("ref_offset_y", 0.0) * res_scale)
        x0, y0 = max(0, skin_x - pad), max(0, skin_y - pad)
        x1 = min(self.frame_w, skin_x + w_hud + pad)
        y1 = min(self.frame_h, skin_y + h_hud + pad)
        if x1 <= x0 or y1 <= y0:
            return
        canvas = copy.deepcopy(self.layout)
        canvas["design_width"] = _canvas_design_width(design_w, x1 - x0, res_scale)
        # +1e-6: int() in draw_hud must land on the shifted pixel, not one short
        canvas["hud_skin"]["ref_offset_x"] = (skin_x - x0 + 1e-6) / res_scale
        canvas["hud_skin"]["ref_offset_y"] = (skin_y - y0 + 1e-6) / res_scale
        self.region = (x0, y0, x1, y1)
        self.canvas_layout = canvas

    def _draw(self, waypoint, waypoints):
        x0, y0, x1, y1 = self.region
        shape = (y1 - y0, x1 - x0, 3)
        on_black = np.zeros(shape, dtype=np.uint8)
        on_white = np.full(shape, 255, dtype=np.uint8)
        for canvas in (on_black, on_white):
            draw_hud(canvas, self.canvas_layout, waypoint, preloaded_skin=self.skin, waypoints=waypoints)
        return matte(on_black, on_white)

    def _reaches_canvas_edge(self, bgra):
        """True if the drawing touches a canvas edge that is not also a frame
        edge, i.e. a full-frame draw might have drawn past it."""
        x0, y0, x1, y1 = self.region
        a = bgra[:, :, 3]
        return bool((x0 > 0 and a[:, 0].any()) or (y0 > 0 and a[0, :].any())
                    or (x1 < self.frame_w and a[:, -1].any()) or (y1 < self.frame_h and a[-1, :].any()))

    def render(self, waypoint, waypoints):
        """The layer for one dive sample as BGRA, the size of self.region."""
        bgra = self._draw(waypoint, waypoints)
        if self.region != (0, 0, self.frame_w, self.frame_h) and self._reaches_canvas_edge(bgra):
            raise _CanvasTooSmall()
        return bgra

    def full_frame(self):
        self.region = (0, 0, self.frame_w, self.frame_h)
        self.canvas_layout = self.layout

    def widen(self):
        """The next bigger canvas after the drawing reached this one's edge."""
        self._pad_index += 1
        self.full_frame()
        if self._pad_index < len(CANVAS_PADS):
            self._crop_to_skin(CANVAS_PADS[self._pad_index])


class _CanvasTooSmall(Exception):
    pass


def write_layer_stream(layer, segments, waypoints, fps, out_dir: Path, index, on_segment=None):
    """Draws `layer` for every segment and writes the PNGs (one per change -
    a segment drawing the same as the one before only extends it) and an
    ffconcat list timing them to their segments into out_dir. Returns
    (concat_path, x, y), x/y being where the PNGs go on the frame, or None
    if the layer draws nothing. on_segment(i) is called after each segment
    for progress reporting."""
    while True:
        try:
            entries = _write_layer_pngs(layer, segments, waypoints, out_dir, index, on_segment)
            break
        except _CanvasTooSmall:
            layer.widen()
    if not entries:
        return None

    lines = ["ffconcat version 1.0"]
    for png, n_frames in entries:
        lines.append(f"file '{_concat_path(png)}'")
        lines.append(f"duration {n_frames / fps:.6f}")
    # The last image's duration is cut short, but the overlay's
    # eof_action=repeat keeps it on screen to the end of the clip (listing it
    # a second time, as usual for concat, made the overlay emit one frame
    # past the source's last)
    concat_path = out_dir / f"hud{index}.ffconcat"
    concat_path.write_text("\n".join(lines) + "\n")

    x0, y0, _x1, _y1 = layer.region
    return concat_path, x0, y0


def _write_layer_pngs(layer, segments, waypoints, out_dir, index, on_segment):
    entries, prev, drew = [], None, False
    for i, (wp, _start, n_frames) in enumerate(segments):
        img = layer.render(wp, waypoints)
        drew = drew or bool(img[:, :, 3].any())
        if prev is not None and np.array_equal(img, prev):
            entries[-1][1] += n_frames
        else:
            png = out_dir / f"hud{index}_{len(entries):05d}.png"
            cv2.imwrite(str(png), img, [cv2.IMWRITE_PNG_COMPRESSION, 1])
            entries.append([png, n_frames])
            prev = img
        if on_segment:
            on_segment(i)
    return entries if drew else []


def _concat_path(path: Path) -> str:
    return path.as_posix().replace("'", "'\\''")


def overlay_filter_complex(color_vf, positions):
    """FFmpeg filter graph: the source (input 0) through the colour
    correction `color_vf` (or untouched when None), then each HUD layer
    (inputs 1..N, at `positions`) overlaid in order - last on top. The HUD
    goes on after the colour correction, so it keeps its own colours."""
    parts = [f"[0:v]{color_vf or 'null'}[v0]"]
    for i, (x, y) in enumerate(positions, start=1):
        parts.append(f"[{i}:v]format=rgba[h{i}]")
        parts.append(f"[v{i - 1}][h{i}]overlay=x={x}:y={y}:eof_action=repeat[v{i}]")
    return ";".join(parts), f"[v{len(positions)}]"
