"""utils/template_store.py - dev/release write target, ownership rules,
save / save-as / create (overlay_rework.md Phase 3, decisions Q3-Q6, Q9)."""
import json
import os
from pathlib import Path

import pytest
from PIL import Image

from conftest import mark_as_checkout
from utils import template_store as store
from utils.layouts import list_templates, resolve_template_state
from utils.overlay_document import OverlayDocument, TemplateRef
from utils.template_store import (
    ReadOnlyTemplateError,
    TemplateExistsError,
    TemplateStoreError,
    can_save_in_place,
    create_computer,
    is_dev_checkout,
    save_template,
    save_template_as,
    slugify,
    template_origin,
    template_write_root,
)

# A flat (non-overlay) variant page for the plain save tests; the Perdix 2
# main page is a shared base + overlays and has its own tests below.
PERDIX = TemplateRef("shearwater", "peregrine", "main", "single_tank")


def _load(roots, ref=PERDIX):
    path = resolve_template_state(ref.brand, ref.computer, ref.page, variant=ref.variant)
    return OverlayDocument.load(path, ref=ref)


# --- mode -------------------------------------------------------------------

def test_release_mode_without_checkout_markers(isolated_template_roots):
    roots = isolated_template_roots
    assert is_dev_checkout() is False
    assert template_write_root() == (roots["user"], store.TARGET_USER)
    assert store.is_dev_mode() is False


def test_dev_mode_with_git_and_pyproject_beside_overlays(isolated_template_roots):
    roots = isolated_template_roots
    mark_as_checkout(roots)
    assert is_dev_checkout() is True
    assert template_write_root() == (roots["bundled"], store.TARGET_REPO)


def test_frozen_app_is_never_dev(isolated_template_roots, monkeypatch):
    mark_as_checkout(isolated_template_roots)
    monkeypatch.setattr("sys.frozen", True, raising=False)
    assert is_dev_checkout() is False
    assert template_write_root()[1] == store.TARGET_USER


def test_env_override_wins_both_ways(isolated_template_roots, monkeypatch):
    roots = isolated_template_roots
    monkeypatch.setenv(store.ENV_TARGET, "repo")
    assert template_write_root() == (roots["bundled"], store.TARGET_REPO)
    mark_as_checkout(roots)
    monkeypatch.setenv(store.ENV_TARGET, "user")
    assert template_write_root() == (roots["user"], store.TARGET_USER)
    monkeypatch.setenv(store.ENV_TARGET, "garbage")
    assert template_write_root()[1] == store.TARGET_REPO  # falls back to the heuristic


def test_slugify():
    assert slugify("GoPro HUD!! v2") == "gopro_hud_v2"
    assert slugify("  Main Screen ") == "main_screen"
    assert slugify("___") == ""
    assert slugify("") == ""


# --- ownership --------------------------------------------------------------

def test_bundled_pages_are_read_only_in_release_mode(isolated_template_roots):
    roots = isolated_template_roots
    assert template_origin("shearwater", "perdix_2", "main") == "bundled"
    assert template_origin("shearwater", "perdix_2", "nope") == "missing"
    assert can_save_in_place("shearwater", "perdix_2", "main") is False
    doc = _load(roots)
    before = doc.source_path.read_bytes()
    with pytest.raises(ReadOnlyTemplateError):
        save_template(PERDIX, doc.render_layout())
    assert doc.source_path.read_bytes() == before
    assert list(roots["user"].iterdir()) == []


def test_dev_mode_saves_bundled_page_in_place_and_normalises(isolated_template_roots):
    roots = isolated_template_roots
    mark_as_checkout(roots)
    assert can_save_in_place("shearwater", "perdix_2", "main") is True
    doc = _load(roots)
    doc.elements[0]["rel_x"] = 0.123456789
    doc.elements[0]["align"] = "right"
    path = save_template(PERDIX, doc.render_layout())
    assert path == doc.source_path
    saved = json.loads(path.read_text())
    assert saved["hud_skin"]["path"] == "normal.png"  # absolute render path normalised back
    assert saved["hud_skin"]["linked_elements"][0]["rel_x"] == 0.12346
    assert saved["hud_skin"]["linked_elements"][0]["align"] == "right"
    assert (path.parent / "normal.png").exists()
    assert list(roots["user"].iterdir()) == []  # nothing leaked to the user dir


def test_save_in_place_copies_a_replaced_skin_image(isolated_template_roots, tmp_path):
    roots = isolated_template_roots
    mark_as_checkout(roots)
    doc = _load(roots)
    new_skin = tmp_path / "photo.jpg"
    Image.new("RGB", (50, 30), (200, 10, 10)).save(new_skin)
    assert doc.set_skin_image(new_skin)
    save_template(PERDIX, doc.render_layout())
    with Image.open(doc.source_path.parent / "normal.png") as img:
        assert img.size == (50, 30) and img.mode == "RGBA"
    assert json.loads(doc.source_path.read_text())["hud_skin"]["path"] == "normal.png"


# --- save as ----------------------------------------------------------------

def test_save_as_under_bundled_computer_creates_self_contained_user_page(isolated_template_roots):
    roots = isolated_template_roots
    doc = _load(roots)
    doc.elements[0]["rel_x"] = 0.4
    dst = TemplateRef("shearwater", "perdix_2", "my_main")
    path = save_template_as(doc.render_layout(), dst, "My Main")

    assert path == roots["user"] / "shearwater" / "perdix_2" / "my_main" / "normal.json"
    assert (path.parent / "normal.png").read_bytes() == (doc.source_path.parent / "normal.png").read_bytes()
    manifest = json.loads((roots["user"] / "shearwater" / "perdix_2" / "manifest.json").read_text())
    assert manifest == {"manufacturer": "Shearwater", "model": "Perdix 2", "pages": [{"id": "my_main", "name": "My Main"}]}
    saved = json.loads(path.read_text())
    assert saved["manufacturer"] == "Shearwater" and saved["hud_skin"]["path"] == "normal.png"
    assert saved["hud_skin"]["linked_elements"][0]["rel_x"] == 0.4

    templates = list_templates()
    pages = {p["id"]: p for p in templates["shearwater"]["perdix_2"]["pages"]}
    assert set(pages) == {"main", "tec", "my_main"}
    assert pages["my_main"]["origin"] == "user" and pages["main"]["origin"] == "bundled"
    assert templates["shearwater"]["perdix_2"]["origin"] == "bundled"
    assert resolve_template_state("shearwater", "perdix_2", "my_main") == path
    assert template_origin("shearwater", "perdix_2", "my_main") == "user"
    assert can_save_in_place("shearwater", "perdix_2", "my_main") is True

    # and the user page can now be saved in place
    doc2 = OverlayDocument.load(path, ref=dst)
    doc2.elements[0]["rel_x"] = 0.6
    assert save_template(dst, doc2.render_layout()) == path
    assert json.loads(path.read_text())["hud_skin"]["linked_elements"][0]["rel_x"] == 0.6


def test_save_as_rejects_bundled_ids_and_invalid_ids(isolated_template_roots):
    roots = isolated_template_roots
    layout = _load(roots).render_layout()
    with pytest.raises(TemplateExistsError):
        save_template_as(layout, TemplateRef("shearwater", "perdix_2", "main"), "Main")
    with pytest.raises(TemplateStoreError):
        save_template_as(layout, TemplateRef("shearwater", "perdix_2", "My Page"), "My Page")
    with pytest.raises(TemplateStoreError):
        save_template_as(layout, TemplateRef("shearwater", "perdix_2", ""), "")
    assert list(roots["user"].iterdir()) == []


def test_save_as_over_existing_user_page_respects_overwrite_flag(isolated_template_roots):
    roots = isolated_template_roots
    layout = _load(roots).render_layout()
    dst = TemplateRef("shearwater", "perdix_2", "my_main")
    save_template_as(layout, dst, "My Main")
    with pytest.raises(TemplateExistsError):
        save_template_as(layout, dst, "My Main", overwrite_user=False)
    save_template_as(layout, dst, "My Main renamed")  # default overwrites
    manifest = json.loads((roots["user"] / "shearwater" / "perdix_2" / "manifest.json").read_text())
    assert manifest["pages"] == [{"id": "my_main", "name": "My Main renamed"}]


def test_save_as_in_dev_mode_refuses_any_existing_id(isolated_template_roots):
    roots = isolated_template_roots
    mark_as_checkout(roots)
    layout = _load(roots).render_layout()
    with pytest.raises(TemplateExistsError):
        save_template_as(layout, TemplateRef("shearwater", "perdix_2", "tec"), "Tec")
    path = save_template_as(layout, TemplateRef("shearwater", "perdix_2", "extra"), "Extra")
    assert path.is_relative_to(roots["bundled"])  # dev mode writes into the repo tree
    manifest = json.loads((roots["bundled"] / "shearwater" / "perdix_2" / "manifest.json").read_text())
    assert [p["id"] for p in manifest["pages"]] == ["main", "tec", "extra"]


def test_save_as_new_custom_computer(isolated_template_roots):
    roots = isolated_template_roots
    layout = _load(roots).render_layout()
    dst = TemplateRef("custom", "gopro_hud", "main")
    path = save_template_as(layout, dst, "Main", manufacturer="Custom", model="GoPro HUD", rules_profile="Shearwater")
    manifest = json.loads((roots["user"] / "custom" / "gopro_hud" / "manifest.json").read_text())
    assert manifest == {"manufacturer": "Custom", "model": "GoPro HUD", "pages": [{"id": "main", "name": "Main"}], "rules_profile": "Shearwater"}
    saved = json.loads(path.read_text())
    assert (saved["manufacturer"], saved["model"], saved["rules_profile"]) == ("Custom", "GoPro HUD", "Shearwater")
    templates = list_templates()
    assert templates["custom"]["gopro_hud"]["origin"] == "user"
    assert templates["custom"]["gopro_hud"]["pages"][0]["origin"] == "user"


def test_save_as_shape_skin_writes_no_png(isolated_template_roots):
    roots = isolated_template_roots
    ref = TemplateRef("generic", "dive_profile", "main")
    layout = _load(roots, ref).render_layout()
    path = save_template_as(layout, TemplateRef("generic", "dive_profile", "mine"), "Mine")
    assert not (path.parent / "normal.png").exists()
    assert "path" not in json.loads(path.read_text())["hud_skin"]


def test_create_computer(isolated_template_roots):
    roots = isolated_template_roots
    path = create_computer("custom", "my_cam", "Custom", "My Cam", rules_profile="Garmin")
    assert json.loads(path.read_text()) == {"manufacturer": "Custom", "model": "My Cam", "pages": [], "rules_profile": "Garmin"}
    assert list_templates()["custom"]["my_cam"]["pages"] == []
    with pytest.raises(TemplateExistsError):
        create_computer("custom", "my_cam", "Custom", "My Cam")
    with pytest.raises(TemplateExistsError):
        create_computer("shearwater", "perdix_2", "Shearwater", "Perdix 2")
    with pytest.raises(TemplateStoreError):
        create_computer("custom", "Bad Id", "Custom", "Bad")


# --- variant overlays (utils.layouts) save back into base + overlay ----------

def test_dev_mode_save_of_a_variant_splits_into_base_and_overlay(isolated_template_roots):
    from utils.layouts import ELEMENT_ORIGIN_KEY, load_layout_file, resolve_template_state, strip_variant_markers

    roots = isolated_template_roots
    mark_as_checkout(roots)
    ref = TemplateRef("garmin", "x50i", "main", "sidemount")
    path = resolve_template_state("garmin", "x50i", "main", variant="sidemount")
    doc = OverlayDocument.load(path, ref=ref)
    assert doc.variant_base_path == path.parent.parent / "normal.json"
    base_before = json.loads(doc.variant_base_path.read_text())
    overlay_before = json.loads(path.read_text())

    depth = next(e for e in doc.elements if e.get("id") == "depth")
    tank = next(e for e in doc.elements if e.get("id") == "secondary_tank_pressure")
    depth["rel_y"] = 0.41111
    tank["rel_x"] = 0.66666
    doc.elements.append({"field": "custom:NEW", "rel_x": 0.5, "rel_y": 0.5, "color": "#FFFFFF", "font_size": 12, "scale": 1.0})

    saved_path = save_template(ref, doc.render_layout())
    assert saved_path == path
    base_after = json.loads(doc.variant_base_path.read_text())
    overlay_after = json.loads(path.read_text())
    # the shared element moved in the base, nothing else there changed
    assert base_after["hud_skin"]["path"] == "normal.png"
    assert next(e for e in base_after["hud_skin"]["linked_elements"] if e["id"] == "depth")["rel_y"] == 0.41111
    assert [e["id"] for e in base_after["hud_skin"]["linked_elements"]] == [e["id"] for e in base_before["hud_skin"]["linked_elements"]]
    assert {k: v for k, v in base_after.items() if k != "hud_skin"} == {k: v for k, v in base_before.items() if k != "hud_skin"}
    # the tank element and the new element live in the overlay only
    assert overlay_after["base"] == "../normal.json"
    assert next(e for e in overlay_after["linked_elements"] if e["id"] == "secondary_tank_pressure")["rel_x"] == 0.66666
    assert overlay_after["linked_elements"][-1]["field"] == "custom:NEW"
    assert len(overlay_after["linked_elements"]) == len(overlay_before["linked_elements"]) + 1
    assert "overrides" not in overlay_after and "remove" not in overlay_after
    assert not any(ELEMENT_ORIGIN_KEY in e for e in overlay_after["linked_elements"])
    # ...and the other variant follows the shared edit
    single = load_layout_file(resolve_template_state("garmin", "x50i", "main", variant="single_tank"))
    assert next(e for e in single["hud_skin"]["linked_elements"] if e.get("id") == "depth")["rel_y"] == 0.41111
    assert not any(e["field"] == "custom:NEW" for e in single["hud_skin"]["linked_elements"])
    assert not (path.parent / "normal.png").exists() and (path.parent.parent / "normal.png").exists()


def test_save_as_of_a_variant_writes_a_flat_self_contained_page(isolated_template_roots):
    from utils.layouts import ELEMENT_ORIGIN_KEY, LAYOUT_BASE_KEY, resolve_template_state

    roots = isolated_template_roots
    path = resolve_template_state("garmin", "x50i", "main", variant="sidemount")
    doc = OverlayDocument.load(path, ref=TemplateRef("garmin", "x50i", "main", "sidemount"))
    dst = TemplateRef("garmin", "x50i", "my_main")
    out = save_template_as(doc.render_layout(), dst, "My Main")
    saved = json.loads(out.read_text())
    assert "base" not in saved and LAYOUT_BASE_KEY not in saved
    assert saved["hud_skin"]["path"] == "normal.png" and (out.parent / "normal.png").exists()
    assert len(saved["hud_skin"]["linked_elements"]) == len(doc.elements)
    assert not any(ELEMENT_ORIGIN_KEY in e for e in saved["hud_skin"]["linked_elements"])
