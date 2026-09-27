"""Elapsed / estimated-remaining time for a long batch (Color, Overlay
Generator, Convertion - 2026-09-28, per the user).

RunTimer is plain Python (a clock callable, no Qt) so it is unit-testable;
RunTiming wraps it in a QObject with a one-second QTimer and the string the
Progress cards show, and each backend owns one. The backend feeds it the
0..1 fraction it already computes for its progress bars (the whole batch,
not the file or overlay in flight - otherwise the estimate would restart
at every file).

The estimate is elapsed / fraction, and it is honest about its limits: it
is hidden until MIN_FRACTION of the work and MIN_ELAPSED seconds are done
(a first file that is much shorter or longer than the rest gives nonsense
before that), it is prefixed "about", and above a minute it is rounded to
ten seconds so it does not flicker every tick.
"""
import math
import time

from PySide6.QtCore import Property, QObject, QTimer, Signal

MIN_FRACTION = 0.03
MIN_ELAPSED = 5.0


def format_duration(seconds):
    """0:07, 4:12, 1:03:45 - the shape of the pages' own time labels."""
    seconds = max(0, int(round(seconds)))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


class RunTimer:
    """Start/stop stopwatch plus a fraction-based remaining-time estimate."""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._start = None
        self._end = None
        self._stopped_ok = True

    def start(self):
        self._start = self._clock()
        self._end = None
        self._stopped_ok = True

    def stop(self, ok=True):
        """Freeze the elapsed time; ok=False marks an abort or failure."""
        if self._start is not None and self._end is None:
            self._end = self._clock()
        self._stopped_ok = ok

    def reset(self):
        self._start = self._end = None

    @property
    def running(self):
        return self._start is not None and self._end is None

    @property
    def started(self):
        return self._start is not None

    @property
    def elapsed(self):
        if self._start is None:
            return 0.0
        return (self._end if self._end is not None else self._clock()) - self._start

    def remaining(self, fraction):
        """Seconds left by extrapolating elapsed / fraction, or None while
        there is too little done to say."""
        if not self.running or fraction is None:
            return None
        fraction = min(1.0, fraction)
        elapsed = self.elapsed
        if fraction < MIN_FRACTION or elapsed < MIN_ELAPSED:
            return None
        left = elapsed * (1.0 - fraction) / fraction
        if left > 60:
            left = math.ceil(left / 10.0) * 10
        return left

    def text(self, fraction):
        """The Progress-card line: "" before the first run, "Elapsed 0:04",
        "Elapsed 4:12 · about 9:30 left", then "Finished in 13:41" or
        "Stopped after 2:10"."""
        if self._start is None:
            return ""
        if not self.running:
            verb = "Finished in" if self._stopped_ok else "Stopped after"
            return f"{verb} {format_duration(self.elapsed)}"
        line = f"Elapsed {format_duration(self.elapsed)}"
        left = self.remaining(fraction)
        if left is not None:
            line += f" · about {format_duration(left)} left"
        return line


class RunTiming(QObject):
    """A RunTimer with a one-second tick and the text as a QML property.
    `fraction` is a callable returning the batch's 0..1 progress."""

    changed = Signal()

    def __init__(self, fraction, parent=None):
        super().__init__(parent)
        self._fraction = fraction
        self.timer = RunTimer()
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self.changed.emit)

    def start(self):
        self.timer.start()
        self._tick.start()
        self.changed.emit()

    def stop(self, ok=True):
        self.timer.stop(ok)
        self._tick.stop()
        self.changed.emit()

    @Property(str, notify=changed)
    def text(self):
        try:
            fraction = self._fraction()
        except Exception:
            fraction = None
        return self.timer.text(fraction)
