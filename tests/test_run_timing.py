"""RunTimer (utils/run_timing.py): the elapsed / remaining line under the
Color, Overlay Generator and Convertion progress bars."""
import pytest

from utils.run_timing import RunTimer, format_duration


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def test_format_duration():
    assert format_duration(0) == "0:00"
    assert format_duration(7.4) == "0:07"
    assert format_duration(252) == "4:12"
    assert format_duration(3825) == "1:03:45"


def test_blank_before_first_run_then_elapsed_only():
    clock = Clock()
    t = RunTimer(clock)
    assert t.text(0.0) == ""
    t.start()
    clock.now += 4
    assert t.text(0.5) == "Elapsed 0:04"  # under MIN_ELAPSED: no estimate yet
    clock.now += 6
    assert t.text(0.01) == "Elapsed 0:10"  # under MIN_FRACTION: no estimate yet


def test_estimate_extrapolates_from_fraction():
    clock = Clock()
    t = RunTimer(clock)
    t.start()
    clock.now += 60
    assert t.remaining(0.25) == 180
    assert t.text(0.25) == "Elapsed 1:00 · about 3:00 left"
    # below a minute the estimate is exact, above it rounds up to 10 s
    clock.now += 100
    assert t.remaining(0.8) == pytest.approx(40)
    assert t.remaining(0.5) == 160
    assert t.remaining(1.0) == 0


def test_stop_freezes_and_names_the_outcome():
    clock = Clock()
    t = RunTimer(clock)
    t.start()
    clock.now += 821
    t.stop()
    clock.now += 500
    assert t.text(1.0) == "Finished in 13:41"
    t.start()
    clock.now += 130
    t.stop(ok=False)
    assert t.text(0.3) == "Stopped after 2:10"
    assert t.remaining(0.3) is None
