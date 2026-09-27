"""
Custom output filename patterns: saved on the Advanced page
(uwmedia/backends/advanced_backend.py), offered on the Color page
(uwmedia/backends/color_backend.py) and passed to the CLI as
--filename-format. settings.json is redirected to tmp_path, never the real
Application Support file.
"""
import pytest

from utils import app_settings, filename_formats
from utils.filename_formats import custom_filename_formats, example_filename, pattern_error
from uwmedia.backends.advanced_backend import AdvancedBackend
from uwmedia.backends.color_backend import FILENAME_FORMAT_PRESETS, ColorBackend


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(app_settings, "settings_path", lambda: path)
    # The feature is hidden in the app (CUSTOM_FILENAME_FORMATS_ENABLED is
    # False since 2026-09-28); these tests cover the code behind the flag.
    monkeypatch.setattr(filename_formats, "CUSTOM_FILENAME_FORMATS_ENABLED", True)
    return path


def test_hidden_flag_keeps_custom_patterns_off_the_color_page(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(app_settings, "settings_path", lambda: path)
    app_settings.update_settings(filename_formats=["%Y%m%d_%H%M%S_Bali"])
    assert filename_formats.CUSTOM_FILENAME_FORMATS_ENABLED is False
    assert ColorBackend().filenameFormatList == [label for label, _ in FILENAME_FORMAT_PRESETS]
    assert AdvancedBackend().customFilenameFormatsEnabled is False


def _add(advanced, pattern):
    advanced.newFilenameFormatText = pattern
    advanced.addFilenameFormat()


@pytest.mark.parametrize("pattern, ok", [
    ("%Y%m%d_%H%M%S_Bali", True),
    ("%Y-%m-%d", True),
    ("", False),
    ("   ", False),
    ("dive/%Y", False),
    ("dive\\%Y", False),
    ("no_codes_here", False),
])
def test_pattern_validation(pattern, ok):
    assert (pattern_error(pattern) is None) == ok


def test_example_uses_preset_sample_date():
    assert example_filename("%Y%m%d_%H%M%S_Bali") == "20260905_143000_Bali"


def test_advanced_adds_lists_and_removes(settings_file):
    advanced = AdvancedBackend()
    _add(advanced, "%Y%m%d_Bali")
    assert advanced.filenameFormatError == ""
    assert advanced.filenameFormats == [{"pattern": "%Y%m%d_Bali", "example": "20260905_Bali"}]
    _add(advanced, "%Y%m%d_Bali")  # duplicates are ignored
    assert custom_filename_formats() == ["%Y%m%d_Bali"]

    _add(advanced, "dive/%Y")
    assert "can't contain" in advanced.filenameFormatError
    assert custom_filename_formats() == ["%Y%m%d_Bali"]

    advanced.removeFilenameFormat("%Y%m%d_Bali")
    assert advanced.filenameFormats == []


def test_color_page_offers_custom_patterns_and_passes_them_to_cli(settings_file):
    color = ColorBackend()
    advanced = AdvancedBackend()
    advanced.filenameFormatsChanged.connect(color.reloadFilenameFormats)  # as app.py wires it

    _add(advanced, "%Y%m%d_%H%M%S_Bali")
    labels = color.filenameFormatList
    assert labels[: len(FILENAME_FORMAT_PRESETS)] == [label for label, _ in FILENAME_FORMAT_PRESETS]
    custom_label = labels[-1]
    assert custom_label == "%Y%m%d_%H%M%S_Bali  →  20260905_143000_Bali"

    color.filenameFormat = custom_label
    args = color._build_args()
    assert args[args.index("--filename-format") + 1] == "%Y%m%d_%H%M%S_Bali"

    # Remembered across restarts...
    assert ColorBackend().filenameFormat == custom_label
    # ...and falls back to the first preset once the pattern is removed.
    advanced.removeFilenameFormat("%Y%m%d_%H%M%S_Bali")
    assert color.filenameFormat == FILENAME_FORMAT_PRESETS[0][0]
    assert custom_label not in color.filenameFormatList
    assert "--filename-format" not in color._build_args()


def test_unusable_saved_pattern_is_not_offered(settings_file):
    app_settings.update_settings(filename_formats=["bad/%Y", "%Y%m%d_%H%M%S"])  # the second is already a preset
    labels = ColorBackend().filenameFormatList
    assert labels == [label for label, _ in FILENAME_FORMAT_PRESETS]


def test_keep_original_filename_passes_keep_filename(settings_file):
    color = ColorBackend()
    color.filenameFormat = FILENAME_FORMAT_PRESETS[0][0]  # "Original"
    args = color._build_args()
    assert "--keep-filename" in args and "--filename-format" not in args


def test_original_plus_color_passes_the_filename_token(settings_file):
    color = ColorBackend()
    color.filenameFormat = FILENAME_FORMAT_PRESETS[1][0]  # "Original + color"
    args = color._build_args()
    assert "--keep-filename" not in args
    assert args[args.index("--filename-format") + 1] == "{filename}_color"
