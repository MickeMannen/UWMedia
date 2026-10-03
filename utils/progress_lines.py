"""The UWMEDIA_* progress lines the CLI child prints and the GUI pages read.

Child side, emit(): one write per line under a lock. print() writes the
text and the newline separately, so two worker threads of a parallel batch
could interleave them into one line ("...A.MP4UWMEDIA_FFMPEG_PROGRESS 20.0
B.MP4"), which the Color page then counted as an extra file - its Current
bar went past 100% and the time estimate with it.

GUI side, LineBuffer: QProcess hands over whatever bytes have arrived, which
can end in the middle of a line (or of a UTF-8 character); the rest is kept
until the next read instead of being parsed as a line of its own.
"""
import codecs
import sys
import threading

_lock = threading.Lock()


def emit(line):
    with _lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


class LineBuffer:
    def __init__(self):
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._pending = ""

    def feed(self, data):
        """Complete lines in `data` plus what was left from earlier reads."""
        text = self._pending + self._decoder.decode(bytes(data))
        lines = text.split("\n")
        self._pending = lines.pop()
        return [line.rstrip("\r") for line in lines]

    def flush(self):
        """What is left once the process has ended (a last line with no newline)."""
        text = self._pending + self._decoder.decode(b"", final=True)
        self._pending = ""
        return [text.rstrip("\r")] if text else []


def finished_text(exit_code, crashed):
    """The pages' status once the CLI child has ended. Killed by a signal
    (crashed), Qt passes the signal number as exit_code, so "exit code 13"
    really meant SIGPIPE; say so instead."""
    if crashed:
        return f"Failed - processing stopped (signal {exit_code})"
    if exit_code == 0:
        return "Finished (exit code 0)"
    return f"Failed (exit code {exit_code})"
