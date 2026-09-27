"""Overlay size / full frame for telemetry-only renders (cli_main.overlay_canvas,
the Overlay Generator's "Overlay size" choice) and the per-encoder quality
flags that replaced the -crf VideoToolbox ignored."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from cli_main import overlay_canvas


def _shape_layout():
    return {"design_width": 1920, "design_height": 1080,
            "hud_skin": {"type": "shape", "width": 300, "height": 200, "anchor": "BOTTOM_LEFT", "ref_offset_x": 16.0,
                         "linked_elements": [{"field": "depth", "rel_x": 0.1, "rel_y": 0.1, "font_size": 30}]}}


def test_overlay_canvas_sizes_and_modes():
    w, h, render_log, layout = overlay_canvas(_shape_layout(), SimpleNamespace(overlay_size="1080p", overlay_full_frame=False))
    assert (w, h, render_log) == (300, 200, True)
    assert layout["hud_skin"]["anchor"] == "CENTER" and layout["hud_skin"]["ref_offset_x"] == 0.0  # the skin is the frame
    w, h, render_log, layout = overlay_canvas(_shape_layout(), SimpleNamespace(overlay_size="4k", overlay_full_frame=False))
    assert (w, h, render_log) == (600, 400, True)
    assert layout["hud_skin"]["scale"] == 2.0 and layout["hud_skin"]["width"] == 600  # fonts and skin both double
    w, h, render_log, layout = overlay_canvas(_shape_layout(), SimpleNamespace(overlay_size="4k", overlay_full_frame=True))
    assert (w, h, render_log) == (3840, 2160, False)
    assert layout["hud_skin"]["anchor"] == "BOTTOM_LEFT" and layout["hud_skin"]["ref_offset_x"] == 16.0  # placed as on the footage
    w, h, render_log, _ = overlay_canvas(_shape_layout(), SimpleNamespace(overlay_size="1080p", overlay_full_frame=True))
    assert (w, h, render_log) == (1920, 1080, False)
    # an image skin: the PNG times the template scale, times the size factor
    perdix = json.loads(Path("overlays/templates/shearwater/perdix_2/main/normal.json").read_text())
    perdix["hud_skin"]["path"] = str(Path("overlays/templates/shearwater/perdix_2/main/normal.png").resolve())
    w1, h1, _, _ = overlay_canvas(perdix, SimpleNamespace(overlay_size="1080p", overlay_full_frame=False))
    w2, h2, _, _ = overlay_canvas(perdix, SimpleNamespace(overlay_size="4k", overlay_full_frame=False))
    assert abs(w1 - 688) <= 2 and abs(h1 - 565) <= 2 and abs(w2 - 2 * w1) <= 2 and abs(h2 - 2 * h1) <= 2


def test_quality_flags_follow_the_encoder():
    from ffmpeg.ffmpeg_class import FfmpegClass
    ff = FfmpegClass(hw_accel=False)
    assert ff.quality_args() == ["-crf", "18"]
    ff.hw_accel, ff.os_type = True, "Darwin"
    assert ff.get_encoder() == "hevc_videotoolbox" and ff.quality_args() == ["-q:v", "65"]
    ff.os_type = "Windows"
    assert ff.get_encoder() == "hevc_nvenc" and "-cq" in ff.quality_args()


def test_generator_overlay_size_choice_is_persisted_and_passed_on(isolated_template_roots, settings_file, tmp_path):
    from uwmedia.backends.overlay_generator_backend import OverlayGeneratorBackend, OVERLAY_SIZE_DEFAULT
    gen = OverlayGeneratorBackend()
    gen.sourceText, gen.outputText, gen.logsText = str(tmp_path), str(tmp_path / "out"), str(tmp_path / "logs")
    gen.hwAccel = False
    assert gen.overlaySize == OVERLAY_SIZE_DEFAULT == "4K (2×)" and gen.overlaySizeIndex == 1
    assert gen._build_hud_args(Path("/tmp/l.json"))[-2:] == ["--overlay-size", "4k"]
    gen.overlaySize = "Full frame 4K"
    assert gen._build_hud_args(Path("/tmp/l.json"))[-3:] == ["--overlay-size", "4k", "--overlay-full-frame"]
    gen.overlaySize = "1080p (template size)"
    assert "--overlay-size" not in gen._build_hud_args(Path("/tmp/l.json"))
    gen.overlaySize = "Full frame 1080p"
    assert gen._build_hud_args(Path("/tmp/l.json"))[-1] == "--overlay-full-frame"
    assert json.loads(settings_file.read_text())["fields"]["hudpage_overlay_size"] == "Full frame 1080p"
    gen.overlaySize = "nonsense"  # ignored
    assert gen.overlaySize == "Full frame 1080p"
    assert OverlayGeneratorBackend().overlaySize == "Full frame 1080p"  # restored
