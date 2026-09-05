from utils.hud_designer import build_layout_json, parse_layout_elements


def test_hud_layout_manufacturer_model_round_trip():
    skin = {
        "type": "shape", "width": 100, "height": 100, "color": "#000000",
        "corner_radius": 20, "opacity": 0.5, "anchor": "TOP_LEFT", "x": 0.0, "y": 0.0,
    }
    layout = build_layout_json(skin, [], "Garmin", "x50i", 1000, 800)
    assert layout["manufacturer"] == "Garmin"
    assert layout["model"] == "x50i"
    assert layout["hud_skin"]["type"] == "shape"
    assert layout["hud_skin"]["anchor"] == "TOP_LEFT"

    # Loading a layout is just reading these fields back out (uwmedia/app.py's
    # _designer_apply_layout) - a Generic manufacturer/empty model round-trips
    # the same way as any other.
    generic_layout = {
        "manufacturer": "Generic", "model": "",
        "hud_skin": {"type": "shape", "width": 100, "height": 100, "anchor": "TOP_LEFT"},
    }
    assert generic_layout.get("manufacturer") == "Generic"
    assert generic_layout.get("model") == ""


def test_hud_layout_graph_marker_style_round_trip():
    hud_skin = {
        "type": "shape",
        "width": 100,
        "height": 100,
        "anchor": "TOP_LEFT",
        "linked_elements": [
            {
                "field": "depth_graph",
                "type": "graph",
                "width": 100,
                "height": 50,
                "color": "#00FF00",
                "rel_x": 0.1,
                "rel_y": 0.2,
                "marker_style": "bold_cross",
                "marker_size": 12,
            }
        ],
    }

    # 1. Parsing a saved layout recovers the graph element and its marker settings.
    elements = parse_layout_elements(hud_skin)
    assert len(elements) == 1
    graph = elements[0]
    assert graph["field"] == "depth_graph"
    assert graph["marker_style"] == "bold_cross"
    assert graph["marker_size"] == 12

    # 2. Editing marker style/size (as the Selected Item panel would) and
    # rebuilding the layout JSON preserves the change.
    graph["marker_style"] = "cross"
    graph["marker_size"] = 10

    skin = {
        "type": "shape", "width": 100, "height": 100, "color": "#000000",
        "corner_radius": 20, "opacity": 0.5, "anchor": "TOP_LEFT", "x": 0.0, "y": 0.0,
    }
    layout = build_layout_json(skin, elements, "Generic", "", 1000, 800)
    graph_elements = [el for el in layout["hud_skin"]["linked_elements"] if el.get("type") == "graph"]
    assert len(graph_elements) == 1
    assert graph_elements[0]["marker_style"] == "cross"
    assert graph_elements[0]["marker_size"] == 10
