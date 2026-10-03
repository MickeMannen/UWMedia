"""uwmedia/__main__.py: a CLI run of the macOS app writes to the real stdout.

The Briefcase macOS launcher installs std-nslog, which swaps sys.stdout and
sys.stderr for writers into the system log. The Color, Overlay Generator and
Convertion pages run the CLI as a child of the same binary and read its
stdout for progress, so in the downloaded app they never left "Starting…".
"""
import io
import sys

import uwmedia.__main__ as entry


class _SystemLogWriter(io.TextIOBase):
    """Stands in for std-nslog's NSLogWriter."""

    def write(self, s):
        return len(s)


def test_cli_run_puts_back_the_original_streams(monkeypatch):
    real_out, real_err = io.StringIO(), io.StringIO()
    monkeypatch.setattr(sys, "__stdout__", real_out)
    monkeypatch.setattr(sys, "__stderr__", real_err)
    monkeypatch.setattr(sys, "stdout", _SystemLogWriter())
    monkeypatch.setattr(sys, "stderr", _SystemLogWriter())

    entry._restore_console_stdio()

    assert sys.stdout is real_out and sys.stderr is real_err


def test_streams_left_alone_without_an_original(monkeypatch):
    # A Windows GUI launch can start with no console streams at all
    replaced = _SystemLogWriter()
    monkeypatch.setattr(sys, "__stdout__", None)
    monkeypatch.setattr(sys, "stdout", replaced)

    entry._restore_console_stdio()

    assert sys.stdout is replaced
