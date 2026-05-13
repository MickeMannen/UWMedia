from PySide6.QtWidgets import QWidget, QVBoxLayout, QSlider, QLabel, QFormLayout
from PySide6.QtCore import Qt

class HUDControls(QWidget):
    """
    UI Controls for managing the HUD Skin settings.
    """
    def __init__(self, hud_manager):
        super().__init__()
        self.hud_manager = hud_manager
        self.init_ui()

    def init_ui(self):
        layout = QFormLayout(self)

        # Opacity Slider
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(100)
        self.opacity_slider.valueChanged.connect(self.on_opacity_changed)
        
        self.opacity_label = QLabel("1.00")
        
        layout.addRow("HUD Opacity:", self.opacity_slider)
        layout.addRow("", self.opacity_label)

        # Scale Slider (as an extra benefit)
        self.scale_slider = QSlider(Qt.Horizontal)
        self.scale_slider.setRange(1, 200) # 1% to 200%
        self.scale_slider.setValue(100)
        self.scale_slider.valueChanged.connect(self.on_scale_changed)
        
        layout.addRow("HUD Scale:", self.scale_slider)

    def on_opacity_changed(self, value):
        opacity = value / 100.0
        self.opacity_label.setText(f"{opacity:.2f}")
        if self.hud_manager.skin_item:
            self.hud_manager.skin_item.setOpacity(opacity)

    def on_scale_changed(self, value):
        scale = value / 100.0
        if self.hud_manager.skin_item:
            self.hud_manager.skin_item.setScale(scale)
