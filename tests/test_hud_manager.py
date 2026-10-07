from utils.hud_designer import parse_layout_elements


def test_hud_layout_graph_marker_style_is_read_back():
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

    # Parsing a saved layout recovers the graph element and its marker settings.
    elements = parse_layout_elements(hud_skin)
    assert len(elements) == 1
    graph = elements[0]
    assert graph["field"] == "depth_graph"
    assert graph["marker_style"] == "bold_cross"
    assert graph["marker_size"] == 12
