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
