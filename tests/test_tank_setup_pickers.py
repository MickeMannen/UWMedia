"""Tank-setup variants: listed in the number-of-tanks order everywhere, and a
choice in the Overlay Generator and Color pickers (not guessed from the
logs); plus the Generator's render-from-log-file mode."""
import json
from pathlib import Path

import pytest

from utils import app_settings
from utils.layouts import list_templates, sort_variants, variant_display_name


def test_variants_are_ordered_by_tank_count_not_alphabetically():
    assert sort_variants(["sidemount", "single_tank"]) == ["single_tank", "sidemount"]
    assert sort_variants(["multi_tank", "no_tank", "zebra", "sidemount", "alpha"]) == ["no_tank", "sidemount", "multi_tank", "alpha", "zebra"]
    assert [variant_display_name(v) for v in ("no_tank", "single_tank", "sidemount", "multi_tank")] == \
        ["No tank", "Single tank", "Sidemount", "Multi-tank"]
    pages = {p["id"]: p for p in list_templates()["garmin"]["x50i"]["pages"]}
    assert pages["main"]["variants"] == ["single_tank", "sidemount"]


def test_overlay_generator_offers_the_tank_setup_and_names_the_overlay_by_it(isolated_template_roots, settings_file):
    from uwmedia.backends.overlay_generator_backend import OverlayGeneratorBackend
    gen = OverlayGeneratorBackend()
    gen.onBrandSelected("Garmin")
    gen.onComputerSelected(next(c for c in gen.computerList if "X50" in c.upper()))
    gen.onPageSelected("Main Screen")
    assert gen.variantVisible and gen.variantList == ["Single tank", "Sidemount"]
    assert gen.variantIndex == 0  # single tank by default
    gen.onVariantSelected("Sidemount")
    assert gen.variantIndex == 1
    gen.addOverlay()
    assert gen.overlayLabels[-1].endswith("sidemount")
    layout = json.loads(Path(gen.selected_overlays[-1]["layout_path"]).read_text())
    fields = {e["field"] for e in layout["hud_skin"]["linked_elements"]}
    assert "secondary_tank_pressure" in fields  # the sidemount variant, merged flat
    gen.onPageSelected("Gases")
    assert not gen.variantVisible and gen.variantList == []


def test_overlay_generator_builds_render_from_log_arguments(isolated_template_roots, settings_file, tmp_path):
    from uwmedia.backends.overlay_generator_backend import OverlayGeneratorBackend
    gen = OverlayGeneratorBackend()
    gen.outputText = str(tmp_path / "out")
    gen.logFileText = str(tmp_path / "dive.uddf")
    gen.hwAccel = False
    args = gen._build_log_args(Path("/tmp/layout.json"))
    assert args == [str(tmp_path / "out"), "--render-log", str(tmp_path / "dive.uddf"), "--layout", "/tmp/layout.json", "--overlay-size", "4k"]
    # the Log file switch decides what Start runs: on, it refuses to start
    # without a real log file, and says so
    gen.addOverlay()
    gen.logFileMode = True
    gen.onStartClicked()
    assert "not found" in gen.statusText
    fields = json.loads(settings_file.read_text())["fields"]
    assert fields["hudpage_log_file_input"] == str(tmp_path / "dive.uddf")
    assert fields["hudpage_log_file_mode"] is True
    # off, the same Start wants the source and dive-logs folders instead -
    # the two paths are kept apart so flipping the switch loses neither
    gen.logFileMode = False
    gen.onStartClicked()
    assert "dive logs folder" in gen.statusText
    assert gen.logFileText == str(tmp_path / "dive.uddf")


def test_color_add_overlay_picker_offers_the_tank_setup(isolated_template_roots, settings_file):
    from uwmedia.backends.color_backend import ColorBackend
    color = ColorBackend()
    color.onAddHudBrandSelected("Garmin")
    color.onAddHudComputerSelected(next(c for c in color.addHudComputerList if "X50" in c.upper()))
    color.onAddHudPageSelected("Main Screen")
    assert color.addHudVariantVisible and color.addHudVariantList == ["Single tank", "Sidemount"]
    color.onAddHudVariantSelected("Sidemount")
    assert color.addHudVariantIndex == 1
    instance = color._resolve_new_color_overlay("garmin", "x50i", "main", "Bottom Left")
    assert instance is not None and "sidemount" in str(instance.get("layout_path", instance))


def test_cascade_indices_follow_the_selection(isolated_template_roots, settings_file):
    # the combos bind currentIndex to these; selecting Generic must not read
    # back as Garmin (entry 0) once the list model is re-emitted
    from uwmedia.backends.overlay_generator_backend import OverlayGeneratorBackend
    from uwmedia.backends.color_backend import ColorBackend
    gen = OverlayGeneratorBackend()
    gen.onBrandSelected("Generic")
    assert gen.brandList[gen.brandIndex] == "Generic"
    gen.onComputerSelected(gen.computerList[-1])
    assert gen.computerIndex == len(gen.computerList) - 1
    gen.onPageSelected(gen.pageList[-1])
    assert gen.pageIndex == len(gen.pageList) - 1
    gen.addOverlay()
    assert gen.brandList[gen.brandIndex] == "Generic"  # adding keeps the cascade where it was
    gen.onBrandSelected("Custom…")
    assert gen.brandList[gen.brandIndex] == "Custom…"
    color = ColorBackend()
    color.onAddHudBrandSelected("Generic")
    assert color.addHudBrandList[color.addHudBrandIndex] == "Generic"
    color.onAddHudComputerSelected(color.addHudComputerList[-1])
    assert color.addHudComputerIndex == len(color.addHudComputerList) - 1
    color.onAddHudPageSelected(color.addHudPageList[-1])
    assert color.addHudPageIndex == len(color.addHudPageList) - 1
