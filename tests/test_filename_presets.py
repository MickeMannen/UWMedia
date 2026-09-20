"""
Regression test for a latent bug in FILENAME_FORMAT_PRESETS: "Date taken"
and "Date + time" used to map to the identical strftime pattern
("%Y%m%d_%H%M%S"), so picking "Date taken" silently produced a
date+time-stamped filename instead of a date-only one. See ui_rework.md's
"Page: Color" section, "Resolved: unified Output filename preset list".
"""
from datetime import datetime

from uwmedia.backends.color_backend import FILENAME_FORMAT_PRESETS


def test_filename_format_presets_are_pairwise_distinct():
    patterns = [pattern for _, pattern in FILENAME_FORMAT_PRESETS]
    assert len(patterns) == len(set(patterns)), (
        f"FILENAME_FORMAT_PRESETS has duplicate pattern values: {patterns}"
    )


def test_date_taken_differs_from_date_plus_time():
    presets = dict(FILENAME_FORMAT_PRESETS)
    date_taken_pattern = presets["Date taken"]
    date_time_pattern = next(
        pattern for label, pattern in FILENAME_FORMAT_PRESETS if label.startswith("Date + time (")
    )

    fixed_date = datetime(2026, 9, 5, 14, 30, 0)
    assert fixed_date.strftime(date_taken_pattern) != fixed_date.strftime(date_time_pattern)
    assert fixed_date.strftime(date_taken_pattern) == "20260905"
