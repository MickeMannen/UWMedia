from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSlider, QLabel, QFormLayout, 
    QColorDialog, QPushButton, QSpinBox, QGroupBox, QComboBox, QLineEdit
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
        
        # Manufacturer & Model Selection
        self.manufacturer_combo = QComboBox()
        self.manufacturer_combo.addItems(["Shearwater", "Garmin", "Generic"])
        self.manufacturer_combo.currentTextChanged.connect(self.on_manufacturer_changed)
        
        self.model_combo = QComboBox()
        self.model_combo.currentTextChanged.connect(self.on_model_changed)
        
        self.update_model_options()

        # Anchor Selection
        self.anchor_combo = QComboBox()
        self.anchor_combo.addItems([
            'TOP_LEFT', 'TOP_CENTER', 'TOP_RIGHT',
            'MIDDLE_LEFT', 'CENTER', 'MIDDLE_RIGHT',
            'BOTTOM_LEFT', 'BOTTOM_CENTER', 'BOTTOM_RIGHT'
        ])
        self.anchor_combo.currentTextChanged.connect(self.on_anchor_changed)

        # Opacity slider + text input layout
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(100)
        self.opacity_slider.valueChanged.connect(self.on_opacity_changed)
        
        self.opacity_input = QLineEdit("1.00")
        self.opacity_input.setFixedWidth(50)
        self.opacity_input.editingFinished.connect(self.on_opacity_input_changed)
        
        self.opacity_container = QWidget()
        opacity_hbox = QHBoxLayout(self.opacity_container)
        opacity_hbox.setContentsMargins(0, 0, 0, 0)
        opacity_hbox.addWidget(self.opacity_slider)
        opacity_hbox.addWidget(self.opacity_input)
        
        # Scale slider + text input layout
        self.scale_slider = QSlider(Qt.Horizontal)
        self.scale_slider.setRange(1, 500) 
        self.scale_slider.setValue(100)
        self.scale_slider.valueChanged.connect(self.on_scale_changed)
        
        self.scale_input = QLineEdit("1.00")
        self.scale_input.setFixedWidth(50)
        self.scale_input.editingFinished.connect(self.on_scale_input_changed)
        
        self.scale_container = QWidget()
        scale_hbox = QHBoxLayout(self.scale_container)
        scale_hbox.setContentsMargins(0, 0, 0, 0)
        scale_hbox.addWidget(self.scale_slider)
        scale_hbox.addWidget(self.scale_input)
        
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

        self.skin_layout.addRow("Manufacturer:", self.manufacturer_combo)
        self.skin_layout.addRow("Model:", self.model_combo)
        self.skin_layout.addRow("Layout Anchor:", self.anchor_combo)
        self.skin_layout.addRow("Opacity:", self.opacity_container)
        self.skin_layout.addRow("Global Scale:", self.scale_container)
        
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
        
        self.custom_text_edit = QLineEdit()
        self.custom_text_edit.setPlaceholderText("Custom label text...")
        self.custom_text_edit.textChanged.connect(self.on_custom_text_changed)
        
        self.item_layout.addRow("Color:", self.color_btn)
        self.item_layout.addRow("Font Size (px):", self.font_spin)
        self.item_layout.addRow("Item Scale:", self.item_scale_slider)
        self.item_layout.addRow("", self.item_scale_label)
        self.item_layout.addRow("Custom Text:", self.custom_text_edit)
        
        self.item_group.setEnabled(False)
        self.item_layout.setRowVisible(self.custom_text_edit, False)
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
            
            # Custom label text sync and visibility
            is_custom = getattr(item, 'is_custom', False)
            self.item_layout.setRowVisible(self.custom_text_edit, is_custom)
            if is_custom:
                self.custom_text_edit.blockSignals(True)
                self.custom_text_edit.setText(getattr(item, 'custom_text', ''))
                self.custom_text_edit.blockSignals(False)
            
        elif isinstance(item, (HUDSkinItem, HUDShapeItem)):
            self.item_group.setEnabled(False)
            self.skin_group.setEnabled(True)
            self.sync_skin_controls(item)
            self.item_layout.setRowVisible(self.custom_text_edit, False)
        else:
            self.item_group.setEnabled(False)
            # If nothing selected, enable skin group if a skin exists
            self.skin_group.setEnabled(self.hud_manager.skin_item is not None)
            self.item_layout.setRowVisible(self.custom_text_edit, False)

    def sync_skin_controls(self, skin_item):
        from gui.hud_manager import HUDShapeItem
        is_shape = isinstance(skin_item, HUDShapeItem)
        
        self.manufacturer_combo.blockSignals(True)
        mfg = getattr(self.hud_manager, 'manufacturer', 'Shearwater')
        if mfg in ["Shearwater", "Garmin", "Generic"]:
            self.manufacturer_combo.setCurrentText(mfg)
        self.manufacturer_combo.blockSignals(False)

        self.update_model_options()

        self.model_combo.blockSignals(True)
        model = getattr(self.hud_manager, 'model', 'Perdix2')
        self.model_combo.setCurrentText(model)
        self.model_combo.blockSignals(False)
        
        self.anchor_combo.blockSignals(True)
        self.anchor_combo.setCurrentText(getattr(skin_item, 'anchor', 'TOP_LEFT'))
        self.anchor_combo.blockSignals(False)

        self.opacity_slider.blockSignals(True)
        self.opacity_slider.setValue(int(skin_item.opacity() * 100))
        self.opacity_slider.blockSignals(False)
        
        self.opacity_input.blockSignals(True)
        self.opacity_input.setText(f"{skin_item.opacity():.2f}")
        self.opacity_input.blockSignals(False)
        
        # Toggle visibility using the actual widgets in those rows
        self.skin_layout.setRowVisible(self.scale_container, not is_shape)
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
            self.scale_slider.blockSignals(False)
            
            self.scale_input.blockSignals(True)
            self.scale_input.setText(f"{skin_item.scale():.2f}")
            self.scale_input.blockSignals(False)

    def on_anchor_changed(self, text):
        if self.hud_manager.skin_item:
            self.hud_manager.skin_item.anchor = text

    def on_opacity_changed(self, value):
        opacity = value / 100.0
        if self.hud_manager.skin_item:
            self.hud_manager.skin_item.setOpacity(opacity)
            self.opacity_input.blockSignals(True)
            self.opacity_input.setText(f"{opacity:.2f}")
            self.opacity_input.blockSignals(False)

    def on_scale_changed(self, value):
        scale = value / 100.0
        if self.hud_manager.skin_item:
            self.hud_manager.skin_item.setScale(scale)
            self.scale_input.blockSignals(True)
            self.scale_input.setText(f"{scale:.2f}")
            self.scale_input.blockSignals(False)

    def on_opacity_input_changed(self):
        try:
            opacity = float(self.opacity_input.text())
            opacity = max(0.0, min(1.0, opacity))
            self.opacity_slider.blockSignals(True)
            self.opacity_slider.setValue(int(opacity * 100))
            self.opacity_slider.blockSignals(False)
            
            if self.hud_manager.skin_item:
                self.hud_manager.skin_item.setOpacity(opacity)
            self.opacity_input.setText(f"{opacity:.2f}")
        except ValueError:
            if self.hud_manager.skin_item:
                current = self.hud_manager.skin_item.opacity()
                self.opacity_input.setText(f"{current:.2f}")

    def on_scale_input_changed(self):
        try:
            scale = float(self.scale_input.text())
            scale = max(0.01, min(5.0, scale))
            self.scale_slider.blockSignals(True)
            self.scale_slider.setValue(int(scale * 100))
            self.scale_slider.blockSignals(False)
            
            if self.hud_manager.skin_item:
                self.hud_manager.skin_item.setScale(scale)
            self.scale_input.setText(f"{scale:.2f}")
        except ValueError:
            if self.hud_manager.skin_item:
                current = self.hud_manager.skin_item.scale()
                self.scale_input.setText(f"{current:.2f}")

    def on_custom_text_changed(self, text):
        from gui.hud_manager import TelemetryItem
        if isinstance(self.selected_item, TelemetryItem) and getattr(self.selected_item, 'is_custom', False):
            self.selected_item.custom_text = text
            self.selected_item.field = f"custom:{text}"
            self.selected_item.setPlainText(text)

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

    def update_model_options(self):
        self.model_combo.blockSignals(True)
        current_model = self.model_combo.currentText()
        self.model_combo.clear()
        
        mfg = self.manufacturer_combo.currentText()
        if mfg == "Garmin":
            models = ["x50i"]
        elif mfg == "Shearwater":
            models = ["Perdix2", "Peregrine TX"]
        else:
            models = []
            
        self.model_combo.addItems(models)
        self.model_combo.setEnabled(len(models) > 0)
        
        if current_model in models:
            self.model_combo.setCurrentText(current_model)
        else:
            if models:
                self.model_combo.setCurrentIndex(0)
        self.model_combo.blockSignals(False)

    def on_manufacturer_changed(self, text):
        self.hud_manager.manufacturer = text
        self.update_model_options()
        self.hud_manager.model = self.model_combo.currentText() if self.model_combo.isEnabled() else ""

    def on_model_changed(self, text):
        self.hud_manager.model = text
