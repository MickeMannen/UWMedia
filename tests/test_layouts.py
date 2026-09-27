from utils.layouts import list_templates, resolve_template_state


def test_list_templates_finds_bundled_shearwater_perdix_2():
    templates = list_templates()
    assert "shearwater" in templates
    perdix_2 = templates["shearwater"]["perdix_2"]
    assert perdix_2["manufacturer"] == "Shearwater"
    assert perdix_2["model"] == "Perdix 2"

    pages = {page["id"]: page for page in perdix_2["pages"]}
    assert pages["main"]["name"] == "Main Screen"
    assert set(pages["main"]["variants"]) == {"single_tank", "sidemount"}
    assert pages["tec"]["variants"] == []


def test_list_templates_finds_bundled_generic_depth_temp():
    templates = list_templates()
    depth_temp = templates["generic"]["depth_temp"]
    assert depth_temp["manufacturer"] == "Generic"

    page_ids = {page["id"] for page in depth_temp["pages"]}
    assert page_ids == {"standard", "compact"}


def test_list_templates_finds_bundled_generic_dive_profile():
    templates = list_templates()
    dive_profile = templates["generic"]["dive_profile"]
    assert dive_profile["manufacturer"] == "Generic"

    page_ids = {page["id"] for page in dive_profile["pages"]}
    assert page_ids == {"main"}

    state_path = resolve_template_state("generic", "dive_profile", "main")
    assert state_path is not None and state_path.exists()


def test_list_templates_finds_bundled_garmin_x50i():
    templates = list_templates()
    assert "garmin" in templates
    x50i = templates["garmin"]["x50i"]
    assert x50i["manufacturer"] == "Garmin"
    assert x50i["model"] == "x50i"

    pages = {page["id"]: page for page in x50i["pages"]}
    assert set(pages["main"]["variants"]) == {"single_tank", "sidemount"}
    assert pages["gases"]["variants"] == []


def test_resolve_template_state_returns_existing_path():
    path = resolve_template_state("shearwater", "perdix_2", "main", variant="single_tank")
    assert path is not None
    assert path.name == "normal.json"
    assert path.exists()


def test_resolve_template_state_missing_combination_returns_none():
    assert resolve_template_state("nonexistent_brand", "x", "y") is None
    assert resolve_template_state("shearwater", "perdix_2", "no_such_page") is None
    assert resolve_template_state("shearwater", "perdix_2", "main", variant="single_tank", state="deco") is None
    # main has no state file directly under the page dir - only under variants
    assert resolve_template_state("shearwater", "perdix_2", "main") is None


def test_resolve_template_state_shearwater_perdix_2_variants():
    single_tank = resolve_template_state("shearwater", "perdix_2", "main", variant="single_tank")
    assert single_tank is not None and single_tank.exists()

    sidemount = resolve_template_state("shearwater", "perdix_2", "main", variant="sidemount")
    assert sidemount is not None and sidemount.exists()

    tec = resolve_template_state("shearwater", "perdix_2", "tec")
    assert tec is not None and tec.exists()


def test_resolve_template_state_garmin_x50i_variants():
    single_tank = resolve_template_state("garmin", "x50i", "main", variant="single_tank")
    assert single_tank is not None and single_tank.exists()

    sidemount = resolve_template_state("garmin", "x50i", "main", variant="sidemount")
    assert sidemount is not None and sidemount.exists()

    gases = resolve_template_state("garmin", "x50i", "gases")
    assert gases is not None and gases.exists()

    # main has no state file directly under the page dir - only under variants
    assert resolve_template_state("garmin", "x50i", "main") is None


# --- overlay_rework.md Phase 3: additive user pages ---------------------------

import json
import shutil

from utils.layouts import page_display_name


def _user_page(user_root, brand, computer, page, source_json, manifest_pages, manufacturer="Shearwater", model="Perdix 2"):
    page_dir = user_root / brand / computer / page
    page_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_json, page_dir / "normal.json")
    (user_root / brand / computer / "manifest.json").write_text(
        json.dumps({"manufacturer": manufacturer, "model": model, "pages": manifest_pages})
    )
    return page_dir / "normal.json"


def test_user_pages_are_added_beside_bundled_pages(isolated_template_roots, capsys):
    roots = isolated_template_roots
    source = roots["bundled"] / "shearwater" / "perdix_2" / "tec" / "normal.json"
    mine = _user_page(roots["user"], "shearwater", "perdix_2", "my_main", source,
                      [{"id": "my_main", "name": "My Main"}, {"id": "main", "name": "Clash"}])
    _user_page(roots["user"], "shearwater", "perdix_2", "main", source,
               [{"id": "my_main", "name": "My Main"}, {"id": "main", "name": "Clash"}])

    templates = list_templates()
    perdix = templates["shearwater"]["perdix_2"]
    pages = {p["id"]: p for p in perdix["pages"]}
    assert list(pages) == ["main", "tec", "my_main"]  # bundled first, user appended, no duplicate
    assert pages["main"]["name"] == "Main Screen" and pages["main"]["origin"] == "bundled"
    assert pages["my_main"]["origin"] == "user" and pages["my_main"]["path"] == mine.parent
    assert perdix["origin"] == "bundled" and perdix["user_path"] == roots["user"] / "shearwater" / "perdix_2"
    assert perdix["manufacturer"] == "Shearwater"
    assert "collides with a bundled page" in capsys.readouterr().out

    assert resolve_template_state("shearwater", "perdix_2", "my_main") == mine
    assert resolve_template_state("shearwater", "perdix_2", "main", variant="single_tank").is_relative_to(roots["bundled"])
    assert page_display_name(pages["my_main"]) == "My Main · yours"
    assert page_display_name(pages["main"]) == "Main Screen"


def test_user_only_computer_and_brand_are_added_whole(isolated_template_roots):
    roots = isolated_template_roots
    source = roots["bundled"] / "generic" / "depth_temp" / "standard" / "normal.json"
    _user_page(roots["user"], "custom", "gopro", "main", source, [{"id": "main", "name": "Main"}], "Custom", "GoPro")
    templates = list_templates()
    assert templates["custom"]["gopro"]["origin"] == "user"
    assert templates["custom"]["gopro"]["pages"][0]["origin"] == "user"
    assert templates["custom"]["gopro"]["user_path"] == roots["user"] / "custom" / "gopro"
    assert "custom" not in {b for b in templates if b != "custom"}
    # bundled brands unaffected
    assert templates["shearwater"]["perdix_2"]["origin"] == "bundled"
    assert "user_path" not in templates["shearwater"]["perdix_2"]


def test_list_templates_finds_bundled_generic_dive_profile_deco():
    templates = list_templates()
    deco = templates["generic"]["dive_profile_deco"]
    assert (deco["manufacturer"], deco["model"]) == ("Generic", "Dive Profile Deco")
    state_path = resolve_template_state("generic", "dive_profile_deco", "main")
    assert state_path is not None and state_path.exists()


# --- variant overlays: one shared base per page plus per-variant blocks ------

import pytest
from pathlib import Path

from utils.layouts import (
    ELEMENT_ORIGIN_KEY,
    LAYOUT_BASE_KEY,
    load_layout_file,
    merge_variant_layout,
    split_variant_layout,
    strip_variant_markers,
)


@pytest.mark.parametrize("computer", ["x50i", "mk3i"])
def test_garmin_main_variants_share_one_base(computer):
    page = Path("overlays/templates/garmin") / computer / "main"
    base = json.loads((page / "normal.json").read_text())
    base_ids = [e["id"] for e in base["hud_skin"]["linked_elements"]]
    assert len(base_ids) == len(set(base_ids))
    assert not any(e["field"].startswith(("primary_tank", "secondary_tank")) for e in base["hud_skin"]["linked_elements"])
    assert (page / "normal.png").exists()
    merged = {}
    for variant in ("single_tank", "sidemount"):
        raw = json.loads((page / variant / "normal.json").read_text())
        assert raw["base"] == "../normal.json" and "hud_skin" not in raw
        assert not (page / variant / "normal.png").exists()
        layout = load_layout_file(page / variant / "normal.json")
        assert layout[LAYOUT_BASE_KEY] == str((page / "normal.json").resolve())
        assert layout["hud_skin"]["path"] == "../normal.png"
        elems = layout["hud_skin"]["linked_elements"]
        assert [e for e in elems if e[ELEMENT_ORIGIN_KEY] == "base"] == [
            {**e, ELEMENT_ORIGIN_KEY: "base"} for e in base["hud_skin"]["linked_elements"]
        ]
        merged[variant] = elems
    # the shared elements are literally the same in both variants; only the tank block differs
    shared = lambda elems: [strip_variant_markers({"hud_skin": {"linked_elements": [e]}})["hud_skin"]["linked_elements"][0]
                            for e in elems if e[ELEMENT_ORIGIN_KEY] == "base"]
    assert shared(merged["single_tank"]) == shared(merged["sidemount"])
    single_block = {e["field"] for e in merged["single_tank"] if e[ELEMENT_ORIGIN_KEY] == "variant"}
    side_block = {e["field"] for e in merged["sidemount"] if e[ELEMENT_ORIGIN_KEY] == "variant"}
    assert single_block == {"primary_tank_name", "primary_tank_pressure"}
    assert {"secondary_tank_name", "secondary_tank_pressure"} <= side_block
    # a page with variants has no state of its own
    assert resolve_template_state("garmin", computer, "main") is None


def test_flat_state_files_load_unchanged():
    path = Path("overlays/templates/garmin/x50i/gases/normal.json")
    assert load_layout_file(path) == json.loads(path.read_text())


def _tiny_base():
    return {
        "manufacturer": "Garmin", "model": "x", "design_width": 1920, "design_height": 1080,
        "hud_skin": {"type": "image", "path": "normal.png", "scale": 0.5, "linked_elements": [
            {"id": "depth", "field": "depth", "rel_x": 0.1, "rel_y": 0.1, "font_size": 20},
            {"id": "ndl", "field": "ndl", "rel_x": 0.2, "rel_y": 0.2, "font_size": 20},
        ]},
    }


def test_merge_applies_overrides_removals_and_adds_variant_elements(tmp_path):
    overlay = {"base": "../normal.json",
               "linked_elements": [{"id": "tank", "field": "primary_tank_pressure", "rel_x": 0.5, "rel_y": 0.5}],
               "overrides": {"depth": {"rel_x": 0.15}},
               "remove": ["ndl"]}
    merged = merge_variant_layout(_tiny_base(), overlay, tmp_path, tmp_path / "sidemount")
    elems = merged["hud_skin"]["linked_elements"]
    assert [(e["id"], e[ELEMENT_ORIGIN_KEY]) for e in elems] == [("depth", "override"), ("tank", "variant")]
    assert elems[0]["rel_x"] == 0.15 and elems[0]["font_size"] == 20
    assert merged["hud_skin"]["path"] == "../normal.png"
    assert merged["hud_skin"]["scale"] == 0.5 and merged["manufacturer"] == "Garmin"


def test_split_puts_shared_edits_in_the_base_and_variant_edits_in_the_overlay(tmp_path):
    base = _tiny_base()
    overlay = {"base": "../normal.json",
               "linked_elements": [{"id": "tank", "field": "primary_tank_pressure", "rel_x": 0.5, "rel_y": 0.5}],
               "overrides": {"depth": {"rel_x": 0.15}}}
    merged = merge_variant_layout(base, overlay, tmp_path, tmp_path / "sidemount")
    elems = merged["hud_skin"]["linked_elements"]
    elems[1]["rel_y"] = 0.25            # ndl (shared) moved -> base
    elems[0]["rel_y"] = 0.12            # depth (overridden) moved -> overrides gain rel_y, base keeps 0.1
    elems[2]["rel_x"] = 0.55            # tank (variant) moved -> overlay
    elems.append({"field": "tts", "rel_x": 0.9, "rel_y": 0.9})  # new while editing -> overlay
    merged["hud_skin"]["scale"] = 0.6   # skin is shared -> base
    new_base, new_overlay = split_variant_layout(merged, base)
    assert LAYOUT_BASE_KEY not in new_base
    assert new_base["hud_skin"]["scale"] == 0.6
    assert [e["id"] for e in new_base["hud_skin"]["linked_elements"]] == ["depth", "ndl"]
    assert new_base["hud_skin"]["linked_elements"][0] == base["hud_skin"]["linked_elements"][0]
    assert new_base["hud_skin"]["linked_elements"][1]["rel_y"] == 0.25
    assert new_overlay["overrides"] == {"depth": {"rel_x": 0.15, "rel_y": 0.12}}
    assert [e.get("id", e["field"]) for e in new_overlay["linked_elements"]] == ["tank", "tts"]
    assert new_overlay["linked_elements"][0]["rel_x"] == 0.55
    assert "remove" not in new_overlay
    assert all(ELEMENT_ORIGIN_KEY not in e for e in new_overlay["linked_elements"])

    del merged["hud_skin"]["linked_elements"][1]  # ndl deleted while editing this variant
    _, new_overlay = split_variant_layout(merged, base)
    assert new_overlay["remove"] == ["ndl"]
