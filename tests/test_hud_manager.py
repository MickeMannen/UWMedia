import pytest
from PySide6.QtWidgets import QApplication, QGraphicsScene
from gui.hud_manager import HUDManager

@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app

def test_hud_manager_manufacturer_model(qapp):
    scene = QGraphicsScene()
    manager = HUDManager(scene, 1000, 800)
    
    # Default values
    assert manager.manufacturer == "Shearwater"
    assert manager.model == "Perdix2"
    
    # Update values
    manager.manufacturer = "Garmin"
    manager.model = "x50i"
    
    # Retrieve layout JSON
    # First we need a skin item to avoid empty layout dict
    manager.create_shape_skin(width=100, height=100)
    
    layout = manager.get_layout_json()
    assert layout.get("manufacturer") == "Garmin"
    assert layout.get("model") == "x50i"
    
    # Test loading layout
    new_layout = {
        "manufacturer": "Shearwater",
        "model": "Peregrine TX",
        "hud_skin": {
            "type": "shape",
            "width": 100,
            "height": 100,
            "anchor": "TOP_LEFT"
        }
    }
    
    manager.load_layout(new_layout)
    assert manager.manufacturer == "Shearwater"
    assert manager.model == "Peregrine TX"

    # Test loading Generic layout
    generic_layout = {
        "manufacturer": "Generic",
        "model": "",
        "hud_skin": {
            "type": "shape",
            "width": 100,
            "height": 100,
            "anchor": "TOP_LEFT"
        }
    }
    manager.load_layout(generic_layout)
    assert manager.manufacturer == "Generic"
    assert manager.model == ""

def test_hud_manager_marker_style(qapp):
    scene = QGraphicsScene()
    manager = HUDManager(scene, 1000, 800)
    manager.create_shape_skin(width=100, height=100)
    
    # 1. Test adding depth graph and verifying default marker style & size
    graph_item = manager.add_depth_graph(rel_x=0.1, rel_y=0.2)
    assert graph_item is not None
    assert graph_item.marker_style == "dot"
    assert graph_item.marker_size == 6
    
    # 2. Test updating marker style and size
    graph_item.set_marker_style("cross")
    graph_item.set_marker_size(10)
    assert graph_item.marker_style == "cross"
    assert graph_item.marker_size == 10
    
    # 3. Test get_layout_json serialization
    layout = manager.get_layout_json()
    elements = layout.get("hud_skin", {}).get("linked_elements", [])
    graph_elements = [el for el in elements if el.get("type") == "graph"]
    assert len(graph_elements) == 1
    assert graph_elements[0].get("marker_style") == "cross"
    assert graph_elements[0].get("marker_size") == 10
    
    # 4. Test loading layout with custom marker style and size
    new_layout = {
        "manufacturer": "Generic",
        "model": "",
        "hud_skin": {
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
                    "marker_size": 12
                }
            ]
        }
    }
    manager.load_layout(new_layout)
    graph_items = [item for item in manager.linked_elements.values() if item.field == "depth_graph"]
    assert len(graph_items) == 1
    assert graph_items[0].marker_style == "bold_cross"
    assert graph_items[0].marker_size == 12

