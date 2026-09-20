"""utils/fonts.py - the bundled/system font registry (overlay_rework.md Phase 2)."""
from utils.fonts import DEFAULT_FAMILY, bundled_fonts_dir, fallback_font_path, font_path, list_families, registry
from gui.hud_renderer import get_font

BUNDLED_FAMILIES = ["DSEG7 Classic", "DejaVu Sans", "Liberation Sans", "Roboto", "Roboto Mono"]


def test_bundled_fonts_dir_found_in_checkout():
    directory = bundled_fonts_dir()
    assert directory is not None and directory.name == "fonts"
    assert (directory / "DejaVuSans.ttf").exists()


def test_registry_lists_arial_first_then_bundled_families_with_both_weights():
    families = list_families()
    assert families[0] == DEFAULT_FAMILY
    for family in BUNDLED_FAMILIES:
        assert family in families
        assert set(registry()[family]) == {"regular", "bold"}


def test_font_path_degrades_gracefully():
    assert font_path(None, None) == fallback_font_path()
    assert font_path("", "") == fallback_font_path()
    assert font_path("No Such Family", "bold") == font_path(DEFAULT_FAMILY, "bold")
    assert font_path("Roboto", "weird-weight") == font_path("Roboto", "regular")
    assert font_path("DSEG7 Classic", "bold").endswith("DSEG7Classic-Bold.ttf")


def test_get_font_caches_per_family_and_size():
    default = get_font(40)
    assert get_font(40) is default
    assert get_font(40, None, None) is default
    assert get_font(40, "Roboto") is not default
    assert get_font(40, "Roboto", "bold") is not get_font(40, "Roboto")
    assert get_font(41) is not default
    assert get_font(40, "No Such Family") is default  # unknown family -> the default path
