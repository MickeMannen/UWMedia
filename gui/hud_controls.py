from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QSlider, QLabel, QFormLayout, 
    QColorDialog, QPushButton, QSpinBox, QGroupBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

class HUDControls(QWidget):
    """
    UI Controls for managing the HUD Skin settings and selected Telemetry elements.
    """
    def __init__(self, hud_manager):
        super().__init__()
        self.hud_manager = hud_manager
        self.selected_item = None
        self.init_ui()
        
        # Connect to manager selection
        self.hud_manager.item_selected.connect(self.on_item_selected)
        self.hud_manager.skin_loaded.connect(self.sync_skin_controls)

    def init_ui(self):
        self.layout = QVBoxLayout(self)

        # 1. Skin Controls
        skin_group = QGroupBox("1. Skin (Overall HUD)")
        skin_layout = QFormLayout(skin_group)
        
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(100)
        self.opacity_slider.valueChanged.connect(self.on_opacity_changed)
        self.opacity_label = QLabel("1.00")
        
        self.scale_slider = QSlider(Qt.Horizontal)
        self.scale_slider.setRange(1, 500) # Increased to 5x
        self.scale_slider.setValue(100)
        self.scale_slider.valueChanged.connect(self.on_scale_changed)
        self.scale_label = QLabel("1.00")
        
        skin_layout.addRow("Opacity:", self.opacity_slider)
        skin_layout.addRow("", self.opacity_label)
        skin_layout.addRow("Global Scale:", self.scale_slider)
        skin_layout.addRow("", self.scale_label)
        self.layout.addWidget(skin_group)

        # 2. Item Controls (Contextual)
        self.item_group = QGroupBox("2. Selected Item")
        self.item_layout = QFormLayout(self.item_group)
        
        self.color_btn = QPushButton("Select Color")
        self.color_btn.clicked.connect(self.pick_color)
        
        self.font_spin = QSpinBox()
        self.font_spin.setRange(8, 200)
        self.font_spin.valueChanged.connect(self.on_font_size_changed)

        self.item_scale_slider = QSlider(Qt.Horizontal)
        self.item_scale_slider.setRange(10, 500) # 0.1x to 5.0x
        self.item_scale_slider.setValue(100)
        self.item_scale_slider.valueChanged.connect(self.on_item_scale_changed)
        self.item_scale_label = QLabel("1.00")
        
        self.item_layout.addRow("Color:", self.color_btn)
        self.item_layout.addRow("Font Size (px):", self.font_spin)
        self.item_layout.addRow("Item Scale:", self.item_scale_slider)
        self.item_layout.addRow("", self.item_scale_label)
        
        self.item_group.setEnabled(False)
        self.layout.addWidget(self.item_group)

    def sync_skin_controls(self, skin_item):
        """Syncs the sliders with the loaded skin properties."""
        self.opacity_slider.blockSignals(True)
        self.scale_slider.blockSignals(True)
        
        opacity = skin_item.opacity()
        scale = skin_item.scale()
        
        self.opacity_slider.setValue(int(opacity * 100))
        self.opacity_label.setText(f"{opacity:.2f}")
        
        self.scale_slider.setValue(int(scale * 100))
        self.scale_label.setText(f"{scale:.2f}")
        
        self.opacity_slider.blockSignals(False)
        self.scale_slider.blockSignals(False)

    def on_item_selected(self, item):
        self.selected_item = item
        if item:
            self.item_group.setEnabled(True)
            self.item_group.setTitle(f"Selected: {item.field}")
            # Update UI to match item properties
            self.font_spin.blockSignals(True)
            self.font_spin.setValue(item.font().pixelSize())
            self.font_spin.blockSignals(False)
            
            self.item_scale_slider.blockSignals(True)
            self.item_scale_slider.setValue(int(item.scale() * 100))
            self.item_scale_label.setText(f"{item.scale():.2f}")
            self.item_scale_slider.blockSignals(False)
        else:
            self.item_group.setEnabled(False)
            self.item_group.setTitle("Selected Item")

    def pick_color(self):
        if not self.selected_item: return
        color = QColorDialog.getColor(self.selected_item.defaultTextColor(), self, "Choose Text Color")
        if color.isValid():
            self.selected_item.set_color(color.name())

    def on_font_size_changed(self, value):
        if self.selected_item:
            self.selected_item.set_font_size(value)

    def on_item_scale_changed(self, value):
        scale = value / 100.0
        self.item_scale_label.setText(f"{scale:.2f}")
        if self.selected_item:
            self.selected_item.setScale(scale)

    def on_opacity_changed(self, value):
        opacity = value / 100.0
        self.opacity_label.setText(f"{opacity:.2f}")
        if self.hud_manager.skin_item:
            self.hud_manager.skin_item.setOpacity(opacity)

    def on_scale_changed(self, value):
        scale = value / 100.0
        self.scale_label.setText(f"{scale:.2f}")
        if self.hud_manager.skin_item:
            self.hud_manager.skin_item.setScale(scale)
