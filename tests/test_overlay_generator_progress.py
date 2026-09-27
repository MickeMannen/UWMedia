"""Overlay Generator's two progress bars: the overlay run in flight (its
videos) and the whole batch (videos × overlays), fed from the CLI's
UWMEDIA_PROGRESS / _ACTIVE / FFMPEG lines."""
import pytest


@pytest.fixture
def gen(isolated_template_roots, settings_file):
    from uwmedia.backends.overlay_generator_backend import OverlayGeneratorBackend
    g = OverlayGeneratorBackend()
    g.process = object()  # "running" for the text properties
    g._run_total, g._run_index, g._log_mode = 2, 1, False
    g._reset_run_progress()
    return g


def test_folder_batch_progress_counts_videos_and_overlays(gen):
    assert not gen.progressKnown and gen.currentProgressText == "" and gen.totalProgressText == ""
    assert gen._handle_output_line("UWMEDIA_PROGRESS 0/12 start -")
    assert gen.progressKnown and gen.currentProgress == 0.0 and gen.totalProgress == 0.0
    assert gen.currentProgressText == "Video 1 of 12"
    assert gen.totalProgressText == "0 of 24 video renders (12 × 2 overlays)"
    assert gen._handle_output_line("UWMEDIA_PROGRESS_ACTIVE clip_a.mp4")
    assert gen.currentProgressText == "Video 1 of 12: clip_a.mp4"
    # with several files rendering in parallel, frame percentages are not attributed to the bar
    assert gen._handle_output_line("UWMEDIA_FFMPEG_PROGRESS 50.0")
    assert gen.currentProgress == 0.0
    assert gen._handle_output_line("UWMEDIA_PROGRESS 3/12 done clip_a.mp4")
    assert gen.currentProgress == pytest.approx(0.25) and gen.totalProgress == pytest.approx(0.125)
    assert gen.statusText == "Done: clip_a.mp4"
    assert not gen._handle_output_line("Matched dive starting at 2026-08-29 12:58")  # ordinary status line
    # second overlay run
    gen._run_index = 2
    gen._reset_run_progress()
    gen._handle_output_line("UWMEDIA_PROGRESS 0/12 start -")
    assert gen.totalProgress == pytest.approx(0.5)
    gen._handle_output_line("UWMEDIA_PROGRESS 12/12 done clip_l.mp4")
    assert gen.currentProgress == 1.0 and gen.totalProgress == 1.0
    assert gen.currentProgressText == "All 12 videos done"
    assert gen.totalProgressText == "24 of 24 video renders (12 × 2 overlays)"


def test_single_file_and_log_mode_use_frame_percentages(gen):
    gen._handle_output_line("UWMEDIA_PROGRESS 0/1 start -")
    gen._handle_output_line("UWMEDIA_PROGRESS_ACTIVE clip.mp4")
    gen._handle_output_line("UWMEDIA_FFMPEG_PROGRESS 40")
    assert gen.currentProgress == pytest.approx(0.4) and gen.totalProgress == pytest.approx(0.2)
    assert gen.currentProgressText == "Rendering clip.mp4 - 40 %"
    gen._handle_output_line("UWMEDIA_PROGRESS 1/1 done clip.mp4")
    assert gen.currentProgress == 1.0
    # log-file mode: one render per overlay, the CLI prints only frame percentages
    gen._log_mode = True
    gen._run_index = 2
    gen.logFileText = "/x/plans/deco_40m.uddf"
    gen._reset_run_progress()
    assert gen.progressKnown and gen.totalProgress == pytest.approx(0.5)
    gen._handle_output_line("UWMEDIA_FFMPEG_PROGRESS 75.0")
    assert gen.currentProgress == pytest.approx(0.75) and gen.totalProgress == pytest.approx(0.875)
    assert gen.currentProgressText == "Rendering deco_40m.uddf - 75 %"
    assert gen.totalProgressText == "1 of 2 renders (1 log × 2 overlays)"
    gen._finish_batch()
    assert not gen.progressKnown and gen.statusText == "Done"


def test_failed_overlay_runs_are_named_in_the_final_status(gen):
    gen.process = None
    gen._run_total, gen._run_index = 3, 1
    gen._overlay_progress_text = "Overlay 1 of 3: garmin x50i main single tank"
    gen._status_text = "Error: Layout garmin_x50i_main_single_tank.json contains unknown fields: state_badge"
    gen._run_queue = []
    gen._on_overlay_finished(1, None)
    assert gen.statusText.startswith("Done - 1 of 3 overlays failed: garmin x50i main single tank (Error: Layout")


def test_cli_validator_accepts_the_bundled_dive_computer_templates(tmp_path):
    import json
    from cli_main import validate_layout
    from models.manager import DiveManager
    from utils.layouts import list_templates, load_layout_file, resolve_template_state, strip_variant_markers
    templates = list_templates()
    checked = 0
    for brand, computers in templates.items():
        for computer, manifest in computers.items():
            for page in manifest["pages"]:
                variants = page.get("variants") or [None]
                for variant in variants:
                    state_path = resolve_template_state(brand, computer, page["id"], variant=variant)
                    if state_path is None:
                        continue
                    layout = strip_variant_markers(load_layout_file(state_path))
                    out = tmp_path / f"{brand}_{computer}_{page['id']}_{variant}.json"
                    out.write_text(json.dumps(layout))
                    validate_layout(out, DiveManager())  # sys.exit(1) on an unknown field
                    checked += 1
    assert checked >= 10
