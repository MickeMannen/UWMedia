"""
Exercises _handle_progress_line's UWMEDIA_FFMPEG_PROGRESS handling, ported to
the QML backends per qml_development.md's Toga-removal cutover. --render-log/
--render-video-log (cli_main.py) surface live percentage feedback via this
marker - see cli_main.py's two per-frame tqdm loops for where it's emitted.

The old Toga app had one UWMediaApp with a `self.progress` dict keyed by
"process"/"convert". The QML port instead has one backend per page, each
handling only its own role - ColorBackend's _handle_progress_line for
"process" semantics (sequential-only: a multi-file batch runs in parallel,
so a bare percentage is only trusted when at most one file is in play),
ConvertionBackend's for "convert" semantics (always sequential, never
ambiguous). Restoring this method on both was a deliberate cutover decision,
not a pre-existing gap papered over: qml_development.md's dependency audit found
neither backend parsed this marker at all (Phase 1/3 only ever showed the
raw last output line), an undocumented simplification from when those pages
were first built - the user chose to restore the feature rather than accept
the regression when this was raised.

Both backends expose the parsed state as plain instance attributes
(_progress_total/_progress_done/_progress_current_target) and a
_status_text string, not widget-backed labels - checked via .statusText
(a real @Property) instead of a MagicMock's .text.
"""
import pytest
from PySide6.QtCore import QObject

from uwmedia.backends.color_backend import ColorBackend
from uwmedia.backends.convertion_backend import ConvertionBackend


def _make_color_backend(total=0, current_target=None):
    app = ColorBackend.__new__(ColorBackend)
    QObject.__init__(app)  # valid QObject, skips ColorBackend.__init__'s real-settings reads
    app._progress_total = total
    app._progress_done = 0
    app._progress_current_target = current_target
    app._progress_pct = 0.0
    app._active_files = []
    app._file_progress = {}
    app._status_text = ""
    return app


def test_convert_ffmpeg_progress_still_shown_with_current_target():
    # Regression: convert always runs one encode at a time, so this was
    # already trusted before render-log's marker was added.
    app = ConvertionBackend()
    app._progress_total = 1
    app._progress_current_target = "clip.mp4"

    handled = app._handle_progress_line("UWMEDIA_FFMPEG_PROGRESS 42.5")

    assert handled is True
    assert app.statusText == "Processing: clip.mp4 — 42%"


def test_process_ffmpeg_progress_shown_for_render_log_with_no_batch_marker():
    # --render-log never emits a UWMEDIA_PROGRESS batch marker at all, so
    # total stays 0 for its whole run - that's the signal it's a single,
    # unambiguous render, not an unknown/unset state.
    app = _make_color_backend(total=0, current_target=None)

    handled = app._handle_progress_line("UWMEDIA_FFMPEG_PROGRESS 10.0")

    assert handled is True
    assert app.statusText == "Rendering — 10%"


def test_process_ffmpeg_progress_shown_for_single_file_batch():
    # A real UWMEDIA_PROGRESS batch marker with total=1 (render-video-log
    # over a directory containing exactly one file) - still sequential per
    # cli_main.py, so still safe to attribute to that one file.
    app = _make_color_backend(total=1, current_target="dive.mp4")

    handled = app._handle_progress_line("UWMEDIA_FFMPEG_PROGRESS 75.0")

    assert handled is True
    assert app.statusText == "Processing: dive.mp4 — 75%"


def test_process_ffmpeg_progress_ignored_for_multi_file_batch():
    # Multiple files run concurrently (ThreadPoolExecutor) - a bare
    # percentage can't be attributed to any one of them, so it must be
    # ignored rather than shown as if it were the current file's progress.
    app = _make_color_backend(total=3, current_target="dive2.mp4")

    handled = app._handle_progress_line("UWMEDIA_FFMPEG_PROGRESS 50.0")

    assert handled is False
    assert app.statusText == ""  # untouched - the line was never parsed


# --- UWMEDIA_PROGRESS_ACTIVE: real parallel-batch in-flight file tracking --
# cli_main.py's _parallel_worker prints this the moment a worker thread
# actually starts a file (not just "submitted" - ThreadPoolExecutor bounds
# real concurrency to max_workers). Lets the Color page's Progress card
# show e.g. "3 files" instead of a bare indeterminate spinner during a
# real multi-file batch.

def test_active_marker_adds_filename_and_updates_count_and_text():
    app = _make_color_backend(total=4)

    handled = app._handle_progress_line("UWMEDIA_PROGRESS_ACTIVE a.mp4")
    app._handle_progress_line("UWMEDIA_PROGRESS_ACTIVE b.mp4")

    assert handled is True
    assert app.activeFilesCount == 2
    assert app.activeFilesText == "a.mp4, b.mp4"


def test_active_marker_does_not_duplicate_same_filename():
    app = _make_color_backend(total=4)

    app._handle_progress_line("UWMEDIA_PROGRESS_ACTIVE a.mp4")
    app._handle_progress_line("UWMEDIA_PROGRESS_ACTIVE a.mp4")

    assert app.activeFilesCount == 1


def test_completion_marker_removes_file_from_active_set():
    app = _make_color_backend(total=4)
    app._handle_progress_line("UWMEDIA_PROGRESS_ACTIVE a.mp4")
    app._handle_progress_line("UWMEDIA_PROGRESS_ACTIVE b.mp4")

    app._handle_progress_line("UWMEDIA_PROGRESS 1/4 done a.mp4")

    assert app.activeFilesCount == 1
    assert app.activeFilesText == "b.mp4"


def test_final_completion_marker_clears_active_set():
    app = _make_color_backend(total=2)
    app._handle_progress_line("UWMEDIA_PROGRESS_ACTIVE a.mp4")
    app._handle_progress_line("UWMEDIA_PROGRESS_ACTIVE b.mp4")
    app._handle_progress_line("UWMEDIA_PROGRESS 1/2 done a.mp4")

    app._handle_progress_line("UWMEDIA_PROGRESS 2/2 done b.mp4")

    assert app.activeFilesCount == 0


# --- Labeled UWMEDIA_FFMPEG_PROGRESS: real aggregate batch percentage -----
# ffmpeg/color.py's plain color-correction path tags every line with its
# filename (ffmpeg_class.py's progress_label param), so - unlike a bare,
# unattributable percentage - several files' progress can be combined into
# one true "how much of the whole batch is done" number even when they're
# encoding concurrently. The user asked for this directly: "will the
# progress bar for current change... to show the actual progress."

def test_labeled_line_is_always_handled_even_in_a_real_batch():
    # Unlike a bare percentage (test_process_ffmpeg_progress_ignored_for_
    # multi_file_batch above), a labeled one is never "unattributable" -
    # it's tied to a specific file regardless of how many run at once.
    app = _make_color_backend(total=3)

    handled = app._handle_progress_line("UWMEDIA_FFMPEG_PROGRESS 50.0 a.mp4")

    assert handled is True
    assert app.progressCurrentDeterminate is True


def test_aggregate_fraction_averages_labeled_files_across_the_batch():
    app = _make_color_backend(total=4)

    app._handle_progress_line("UWMEDIA_FFMPEG_PROGRESS 100.0 a.mp4")
    app._handle_progress_line("UWMEDIA_FFMPEG_PROGRESS 50.0 b.mp4")
    app._handle_progress_line("UWMEDIA_FFMPEG_PROGRESS 25.0 c.mp4")
    # d.mp4 hasn't started yet - implicitly contributes 0, not tracked at all.

    # (100 + 50 + 25 + 0) / (4 files * 100) = 0.4375
    assert app.progressCurrentFraction == pytest.approx(0.4375)


def test_completion_marker_credits_file_as_100_percent_for_the_aggregate():
    app = _make_color_backend(total=2)
    app._handle_progress_line("UWMEDIA_FFMPEG_PROGRESS 92.0 a.mp4")  # last tick before 100 was throttled away

    app._handle_progress_line("UWMEDIA_PROGRESS 1/2 done a.mp4")

    # a.mp4 counts as fully done (1.0) despite its last reported % being 92,
    # b.mp4 hasn't started (0) -> (1.0 + 0) / 2 = 0.5
    assert app.progressCurrentFraction == pytest.approx(0.5)


def test_unlabeled_ffmpeg_progress_still_falls_back_to_old_single_value_behavior():
    # cli_main.py's HUD render-log frame loops don't pass a filename label -
    # aggregate tracking must stay untouched and the old sequential-only
    # single-value behavior (progress_pct) must still drive the fraction.
    app = _make_color_backend(total=1, current_target="dive.mp4")

    app._handle_progress_line("UWMEDIA_FFMPEG_PROGRESS 75.0")

    assert app.progressCurrentFraction == pytest.approx(0.75)
    assert app.progressCurrentDeterminate is True
