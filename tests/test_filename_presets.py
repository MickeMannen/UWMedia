"""
The Color page's built-in Output filename presets (color_backend.py's
FILENAME_FORMAT_PRESETS): every pattern distinct, "Original + color" built
from the source name via the CLI's "{filename}" token, and the labels saved
by earlier versions ("Keep original filename", "Date taken") still resolve.
"""
from datetime import datetime

from uwmedia.backends.color_backend import FILENAME_FORMAT_PRESETS, LEGACY_PRESET_LABELS


def test_filename_format_presets_are_pairwise_distinct():
    patterns = [pattern for _, pattern in FILENAME_FORMAT_PRESETS]
    assert len(patterns) == len(set(patterns)), (
        f"FILENAME_FORMAT_PRESETS has duplicate pattern values: {patterns}"
    )


def test_preset_lineup():
    labels = [label for label, _ in FILENAME_FORMAT_PRESETS]
    assert [l.split(" (")[0] for l in labels] == ["Original", "Original + color", "Date + time", "Date + time + color", "Date + time + overlay"]
    presets = dict(FILENAME_FORMAT_PRESETS)
    assert presets[labels[0]] == ""  # --keep-filename
    assert presets[labels[1]] == "{filename}_color"
    fixed = datetime(2026, 9, 5, 14, 30, 0)
    assert fixed.strftime(presets[labels[2]]) == "20260905_143000"
    assert fixed.strftime(presets[labels[3]]) == "20260905_143000_color"
    assert fixed.strftime(presets[labels[4]]) == "20260905_143000_{hud}"


def test_legacy_labels_map_to_current_presets():
    presets = dict(FILENAME_FORMAT_PRESETS)
    for old, new in LEGACY_PRESET_LABELS.items():
        assert old not in presets and new in presets
