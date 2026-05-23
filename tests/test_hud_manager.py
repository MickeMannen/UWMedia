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
