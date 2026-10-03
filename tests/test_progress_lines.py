"""utils/progress_lines.py and the Color page's use of it.

A Color batch with overlays showed Current above 100% and a far-off time
estimate: progress lines reached the page broken in two (a QProcess read
ending mid-line) or merged (two worker threads printing at once), and the
broken label counted as one more file. The run then ended as "Failed (exit
code 13)" - Qt's report of a child killed by SIGPIPE.
"""
import io
import signal
import sys
import threading

from PySide6.QtCore import QObject, QProcess

import uwmedia.__main__ as entry
from utils.progress_lines import LineBuffer, emit, finished_text
from uwmedia.backends.color_backend import ColorBackend


def test_line_split_across_reads_comes_out_whole():
    buf = LineBuffer()
    assert buf.feed(b"UWMEDIA_FFMPEG_PROGRESS 99.1 DSC") == []
    assert buf.feed(b"0123.MP4\nUWMEDIA_PRO") == ["UWMEDIA_FFMPEG_PROGRESS 99.1 DSC0123.MP4"]
    assert buf.feed(b"GRESS 1/2 done DSC0123.MP4\r\n") == ["UWMEDIA_PROGRESS 1/2 done DSC0123.MP4"]


def test_utf8_character_split_across_reads():
    data = "UWMEDIA_PROGRESS_ACTIVE Dyk_Åre.MP4\n".encode()
    cut = data.index("Å".encode()) + 1
    buf = LineBuffer()
    assert buf.feed(data[:cut]) == []
    assert buf.feed(data[cut:]) == ["UWMEDIA_PROGRESS_ACTIVE Dyk_Åre.MP4"]


def test_flush_returns_a_last_line_without_newline():
    buf = LineBuffer()
    buf.feed(b"one\ntwo")
    assert buf.flush() == ["two"]
    assert buf.flush() == []


def test_emit_from_many_threads_never_merges_lines(monkeypatch):
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)

    def worker(name):
        for i in range(300):
            emit(f"UWMEDIA_FFMPEG_PROGRESS {i}.0 {name}.MP4")

    threads = [threading.Thread(target=worker, args=(f"F{n}",)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    lines = out.getvalue().splitlines()
    assert len(lines) == 1800
    assert all(line.count("UWMEDIA_") == 1 for line in lines)


def test_finished_text():
    assert finished_text(0, False) == "Finished (exit code 0)"
    assert finished_text(1, False) == "Failed (exit code 1)"
    assert "signal 13" in finished_text(13, True)


def test_cli_run_ignores_sigpipe():
    previous = signal.getsignal(signal.SIGPIPE)
    try:
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
        entry._ignore_sigpipe()
        assert signal.getsignal(signal.SIGPIPE) == signal.SIG_IGN
    finally:
        signal.signal(signal.SIGPIPE, previous)


def _color_backend(total):
    app = ColorBackend.__new__(ColorBackend)
    QObject.__init__(app)
    app._progress_total = total
    app._progress_done = 0
    app._progress_current_target = None
    app._progress_pct = 0.0
    app._active_files = []
    app._file_progress = {}
    app._status_text = ""
    app._line_buffer = LineBuffer()
    return app


def _feed(app, data):
    for line in app._line_buffer.feed(data):
        app._handle_progress_line(line)


def test_color_current_stays_within_100_percent_on_split_reads():
    app = _color_backend(total=2)
    _feed(app, b"UWMEDIA_FFMPEG_PROGRESS 100.0 A.MP4\nUWMEDIA_FFMPEG_PROGRESS 100.0 B")
    _feed(app, b".MP4\nUWMEDIA_PROGRESS 1/2 done A.MP4\n")
    assert set(app._file_progress) == {"A.MP4", "B.MP4"}
    assert app.progressCurrentFraction == 1.0


def test_color_current_fraction_is_capped():
    app = _color_backend(total=1)
    app._file_progress = {"A.MP4": 100.0, "stray": 50.0}
    assert app.progressCurrentFraction == 1.0


def test_color_crash_says_signal():
    app = _color_backend(total=2)
    app.process = None

    class _Timing:
        def stop(self, ok=True):
            self.ok = ok

    app.timing = _Timing()
    app._on_process_finished(13, QProcess.ExitStatus.CrashExit)
    assert "signal 13" in app.statusText
    assert app.timing.ok is False
