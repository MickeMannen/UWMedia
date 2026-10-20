"""ffmpeg/overlay_output.py - the path and alpha helpers behind the Overlay
Generator's output formats."""
from pathlib import Path

import numpy as np


def test_overlay_output_paths_and_alpha():
    from ffmpeg.overlay_output import HEVC, PNG, PRORES, output_path_for, render_frame
    assert output_path_for(PRORES, Path("a/dive_perdix.mp4")) == Path("a/dive_perdix.mov")
    assert output_path_for(PNG, Path("a/dive_perdix.mp4")) == Path("a/dive_perdix")
    assert output_path_for(HEVC, Path("a/dive_perdix.mp4")) == Path("a/dive_perdix.mp4")
    assert output_path_for(PRORES, Path("a/IMG_1.jpg"), is_video=False) == Path("a/IMG_1.png")

    def fake_draw(frame, layout, wp, **kw):  # a 50 % grey box blended at half opacity
        frame[10:20, 10:20] = (frame[10:20, 10:20].astype(float) * 0.5 + 64).astype(np.uint8)

    black = np.zeros((30, 30, 3), np.uint8)
    bgr = render_frame({}, None, fake_draw, black)
    assert bgr.shape == (30, 30, 3) and bgr[15, 15, 0] == 64
    bgra = render_frame({}, None, fake_draw, black, np.zeros((30, 30, 3), np.uint8))
    assert bgra.shape == (30, 30, 4)
    assert bgra[5, 5, 3] == 0            # untouched: fully transparent
    assert abs(int(bgra[15, 15, 3]) - 128) <= 1  # half opacity where the box was blended
    assert abs(int(bgra[15, 15, 0]) - 128) <= 2  # un-premultiplied colour: 64 / 0.5
