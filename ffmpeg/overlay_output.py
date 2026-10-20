"""Where a telemetry-only render goes: a transparent ProRes 4444 movie, a
PNG sequence with alpha, or the video on black that every render was until
2026-10-17. Shared by the two render loops in cli_main.py (--render-log and
--render-video-log) so they differ only in where their frames' times come
from.

The alpha comes the way ffmpeg/hud_layers.py gets it: the HUD is drawn
twice, on black and on white, and the difference says how much background
shows through (matte()). Frames only change when the dive sample does, so
the caller tells the sink whether a frame is new; a PNG sequence copies the
previous file instead of encoding the same picture again.
"""
import shutil
import subprocess as sp
import threading
from pathlib import Path
from queue import Queue
from typing import Optional

import cv2
import numpy as np

PRORES = "prores"   # transparent .mov, ProRes 4444 with alpha
PNG = "png"         # folder of frame_000001.png ... with alpha
HEVC = "hevc"       # HEVC .mp4 on black (the only output before 2026-10-17)
FORMATS = (PRORES, PNG, HEVC)
DEFAULT_FORMAT = HEVC  # the CLI's default; the Overlay Generator page passes its own
WRITE_QUEUE_SIZE = 8


def has_alpha(fmt: str) -> bool:
    return fmt in (PRORES, PNG)


def output_path_for(fmt: str, path: Path, is_video: bool = True) -> Path:
    """The path a render of `fmt` writes, from the name the run would have
    used: .mov for ProRes, a folder (no suffix) for a PNG sequence, the
    given name for HEVC. A photo rendered with alpha becomes a .png."""
    if fmt == PRORES:
        return path.with_suffix(".mov") if is_video else path.with_suffix(".png")
    if fmt == PNG:
        return path.with_suffix("") if is_video else path.with_suffix(".png")
    return path


def render_frame(layout, wp, draw_hud, black, white=None, **draw_kwargs):
    """Draw one overlay frame into `black` (and `white` for alpha) and
    return what the sink wants: BGR when there is no white canvas, BGRA
    otherwise."""
    black[:] = 0
    draw_hud(black, layout, wp, **draw_kwargs)
    if white is None:
        return black
    white[:] = 255
    draw_hud(white, layout, wp, **draw_kwargs)
    from ffmpeg.hud_layers import matte
    return matte(black, white)


class FrameSink:
    """Takes frames in order and writes them as `fmt`. `put(frame, changed)`
    is called once per output frame; `changed` False means the same picture
    as the last call."""

    def __init__(self, fmt: str, ff, width: int, height: int, fps: float, target: Path, debug: bool = False):
        if fmt not in FORMATS:
            raise ValueError(f"unknown overlay format {fmt!r}")
        self.fmt, self.ff, self.width, self.height, self.fps, self.target, self.debug = fmt, ff, width, height, fps, Path(target), debug
        self.frames = 0
        self._process: Optional[sp.Popen] = None
        self._queue: Optional[Queue] = None
        self._thread: Optional[threading.Thread] = None
        self._error = [None]
        self._last_bytes: Optional[bytes] = None
        self._last_png: Optional[Path] = None

    # -- lifecycle ---------------------------------------------------------

    def start(self):
        if self.fmt == PNG:
            self.target.mkdir(parents=True, exist_ok=True)
            return self
        self._process = sp.Popen(self.command(), stdin=sp.PIPE)
        self._queue = Queue(maxsize=WRITE_QUEUE_SIZE)

        def worker():
            try:
                while True:
                    data = self._queue.get()
                    if data is None:
                        break
                    self._process.stdin.write(data)
            except Exception as e:  # surfaced by close()
                self._error[0] = e

        self._thread = threading.Thread(target=worker, name="ffmpeg-write", daemon=True)
        self._thread.start()
        return self

    def command(self):
        """The ffmpeg command: raw frames on stdin, the format's encoder out."""
        pix_in = "bgra" if has_alpha(self.fmt) else "bgr24"
        cmd = [str(self.ff.get_path()), "-y",
               "-f", "rawvideo", "-vcodec", "rawvideo",
               "-s", f"{self.width}x{self.height}", "-pix_fmt", pix_in, "-r", str(self.fps),
               "-i", "-"]
        if self.fmt == PRORES:
            # ProRes 4444 keeps the alpha; every major editor reads it
            cmd += ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", "-vendor", "ap10"]
        else:
            cmd += ["-vcodec", self.ff.get_encoder(), "-pix_fmt", "yuv420p", "-tag:v", "hvc1", *self.ff.quality_args()]
        cmd.append(str(self.target))
        if not self.debug:
            cmd += ["-nostats", "-loglevel", "error"]
        return cmd

    def put(self, frame: np.ndarray, changed: bool = True):
        self.frames += 1
        if self.fmt == PNG:
            path = self.target / f"frame_{self.frames:06d}.png"
            if changed or self._last_png is None:
                cv2.imwrite(str(path), frame, [cv2.IMWRITE_PNG_COMPRESSION, 3])
            else:
                shutil.copyfile(self._last_png, path)
            self._last_png = path
            return
        if changed or self._last_bytes is None:
            self._last_bytes = np.ascontiguousarray(frame).tobytes()
        self._queue.put(self._last_bytes)

    def close(self):
        if self.fmt == PNG:
            return
        if self._queue is not None:
            self._queue.put(None)
        if self._thread is not None:
            self._thread.join(timeout=10)
        if self._process is not None:
            self._process.stdin.close()
            self._process.wait()
        if self._error[0]:
            raise self._error[0]

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.close()
        elif self._process is not None:
            try:
                self._queue.put(None)
                self._process.stdin.close()
                self._process.wait()
            except Exception:
                pass
        return False
