from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QSlider, QLabel, QFormLayout, 
    QColorDialog, QPushButton, QSpinBox, QGroupBox, QComboBox
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
        self.skin_group = QGroupBox("1. Skin (Overall HUD)")
        self.skin_layout = QFormLayout(self.skin_group)
        
        # Anchor Selection
        self.anchor_combo = QComboBox()
        self.anchor_combo.addItems([
            'TOP_LEFT', 'TOP_CENTER', 'TOP_RIGHT',
            'MIDDLE_LEFT', 'CENTER', 'MIDDLE_RIGHT',
            'BOTTOM_LEFT', 'BOTTOM_CENTER', 'BOTTOM_RIGHT'
        ])
        self.anchor_combo.currentTextChanged.connect(self.on_anchor_changed)

        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(100)
        self.opacity_slider.valueChanged.connect(self.on_opacity_changed)
        self.opacity_label = QLabel("1.00")
        
        self.scale_slider = QSlider(Qt.Horizontal)
        self.scale_slider.setRange(1, 500) 
        self.scale_slider.setValue(100)
        self.scale_slider.valueChanged.connect(self.on_scale_changed)
        self.scale_label = QLabel("1.00")
        
        # Shape specific controls
        self.width_spin = QSpinBox()
        self.width_spin.setRange(10, 2000)
        self.width_spin.valueChanged.connect(self.on_shape_dim_changed)
        
        self.height_spin = QSpinBox()
        self.height_spin.setRange(10, 2000)
        self.height_spin.valueChanged.connect(self.on_shape_dim_changed)
        
        self.radius_spin = QSpinBox()
        self.radius_spin.setRange(0, 500)
        self.radius_spin.valueChanged.connect(self.on_shape_dim_changed)

        self.shape_color_btn = QPushButton("Select BG Color")
        self.shape_color_btn.clicked.connect(self.pick_shape_color)

        self.skin_layout.addRow("Layout Anchor:", self.anchor_combo)
        self.skin_layout.addRow("Opacity:", self.opacity_slider)
        self.skin_layout.addRow("", self.opacity_label)
        
        # We store these to toggle visibility by widget reference
        self.skin_layout.addRow("Global Scale:", self.scale_slider)
        self.skin_layout.addRow("", self.scale_label)
        
        self.skin_layout.addRow("Width:", self.width_spin)
        self.skin_layout.addRow("Height:", self.height_spin)
        self.skin_layout.addRow("Corner Radius:", self.radius_spin)
        self.skin_layout.addRow("BG Color:", self.shape_color_btn)
        
        self.layout.addWidget(self.skin_group)

        # 2. Item Controls
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

    def on_item_selected(self, item):
        from gui.hud_manager import TelemetryItem, HUDSkinItem, HUDShapeItem
        self.selected_item = item
        
        if isinstance(item, TelemetryItem):
            self.item_group.setEnabled(True)
            self.skin_group.setEnabled(False)
            
            # Sync values
            self.font_spin.blockSignals(True)
            self.font_spin.setValue(item.font().pixelSize())
            self.font_spin.blockSignals(False)
            
            self.item_scale_slider.blockSignals(True)
            self.item_scale_slider.setValue(int(item.scale() * 100))
            self.item_scale_label.setText(f"{item.scale():.2f}")
            self.item_scale_slider.blockSignals(False)
            
        elif isinstance(item, (HUDSkinItem, HUDShapeItem)):
            self.item_group.setEnabled(False)
            self.skin_group.setEnabled(True)
            self.sync_skin_controls(item)
        else:
            self.item_group.setEnabled(False)
            # If nothing selected, enable skin group if a skin exists
            self.skin_group.setEnabled(self.hud_manager.skin_item is not None)

    def sync_skin_controls(self, skin_item):
        from gui.hud_manager import HUDShapeItem
        is_shape = isinstance(skin_item, HUDShapeItem)
        
        self.anchor_combo.blockSignals(True)
        self.anchor_combo.setCurrentText(getattr(skin_item, 'anchor', 'TOP_LEFT'))
        self.anchor_combo.blockSignals(False)

        self.opacity_slider.blockSignals(True)
        self.opacity_slider.setValue(int(skin_item.opacity() * 100))
        self.opacity_label.setText(f"{skin_item.opacity():.2f}")
        self.opacity_slider.blockSignals(False)
        
        # Toggle visibility using the actual widgets in those rows
        self.skin_layout.setRowVisible(self.scale_slider, not is_shape)
        self.skin_layout.setRowVisible(self.scale_label, not is_shape)
        self.skin_layout.setRowVisible(self.width_spin, is_shape)
        self.skin_layout.setRowVisible(self.height_spin, is_shape)
        self.skin_layout.setRowVisible(self.radius_spin, is_shape)
        self.skin_layout.setRowVisible(self.shape_color_btn, is_shape)

        if is_shape:
            self.width_spin.blockSignals(True)
            self.width_spin.setValue(skin_item.width)
            self.width_spin.blockSignals(False)
            
            self.height_spin.blockSignals(True)
            self.height_spin.setValue(skin_item.height)
            self.height_spin.blockSignals(False)
            
            self.radius_spin.blockSignals(True)
            self.radius_spin.setValue(skin_item.corner_radius)
            self.radius_spin.blockSignals(False)
        else:
            self.scale_slider.blockSignals(True)
            self.scale_slider.setValue(int(skin_item.scale() * 100))
            self.scale_label.setText(f"{skin_item.scale():.2f}")
            self.scale_slider.blockSignals(False)

    def on_anchor_changed(self, text):
        if self.hud_manager.skin_item:
            self.hud_manager.skin_item.anchor = text

    def on_opacity_changed(self, value):
        opacity = value / 100.0
        if self.hud_manager.skin_item:
            self.hud_manager.skin_item.setOpacity(opacity)
            self.opacity_label.setText(f"{opacity:.2f}")

    def on_scale_changed(self, value):
        scale = value / 100.0
        if self.hud_manager.skin_item:
            self.hud_manager.skin_item.setScale(scale)
            self.scale_label.setText(f"{scale:.2f}")

    def on_shape_dim_changed(self):
        from gui.hud_manager import HUDShapeItem
        if isinstance(self.hud_manager.skin_item, HUDShapeItem):
            self.hud_manager.skin_item.width = self.width_spin.value()
            self.hud_manager.skin_item.height = self.height_spin.value()
            self.hud_manager.skin_item.corner_radius = self.radius_spin.value()
            self.hud_manager.skin_item.update_path()

    def pick_shape_color(self):
        from gui.hud_manager import HUDShapeItem
        if not isinstance(self.hud_manager.skin_item, HUDShapeItem): return
        current_color = QColor(self.hud_manager.skin_item.color_hex)
        color = QColorDialog.getColor(current_color, self, "Choose Background Color")
        if color.isValid():
            self.hud_manager.skin_item.color_hex = color.name()
            self.hud_manager.skin_item.update_path()

    def on_font_size_changed(self, value):
        from gui.hud_manager import TelemetryItem
        if isinstance(self.selected_item, TelemetryItem):
            self.selected_item.set_font_size(value)

    def on_item_scale_changed(self, value):
        from gui.hud_manager import TelemetryItem
        if isinstance(self.selected_item, TelemetryItem):
            scale = value / 100.0
            self.selected_item.setScale(scale)
            self.item_scale_label.setText(f"{scale:.2f}")

    def pick_color(self):
        from gui.hud_manager import TelemetryItem
        if isinstance(self.selected_item, TelemetryItem):
            color = QColorDialog.getColor(self.selected_item.defaultTextColor(), self, "Choose Text Color")
            if color.isValid():
                self.selected_item.set_color(color.name())
