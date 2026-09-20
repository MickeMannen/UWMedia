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

PERDIX = TemplateRef("shearwater", "perdix_2", "main", "single_tank")


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
