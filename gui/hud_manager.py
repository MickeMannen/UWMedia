import json
from pathlib import Path
from PySide6.QtWidgets import (
    QGraphicsPixmapItem, QGraphicsTextItem, QGraphicsItem, 
    QGraphicsScene, QGraphicsView
)
from PySide6.QtCore import Qt, QPointF, Signal, QObject
from PySide6.QtGui import QPixmap, QColor, QFont

from gui.hud_renderer import format_telemetry_value

class HUDManager(QObject):
    """
    Manages the HUD Skin and linked telemetry elements in a PySide6 QGraphicsScene.
    """
    layout_changed = Signal(dict)
    item_selected = Signal(object) # Emits the selected item (TelemetryItem or None)
    skin_loaded = Signal(object) # Emits the skin item when loaded
    skin_updated = Signal(object) # Emits when skin opacity or scale changes

    def __init__(self, scene: QGraphicsScene, view_width: int, view_height: int):
        super().__init__()
        self.scene = scene
        self.view_width = view_width
        self.view_height = view_height
        self.skin_item = None
        self.linked_elements = {} # field -> TelemetryItem
        
        self.scene.selectionChanged.connect(self.on_selection_changed)

    def on_selection_changed(self):
        items = self.scene.selectedItems()
        # Filter to only TelemetryItems
        telemetry_items = [i for i in items if isinstance(i, TelemetryItem)]
        
        if telemetry_items:
            self.item_selected.emit(telemetry_items[0])
        else:
            self.item_selected.emit(None)

    def align_selected_horizontally(self):
        """Aligns selected telemetry items to the Y-coordinate of the first selected item."""
        items = [i for i in self.scene.selectedItems() if isinstance(i, TelemetryItem)]
        if len(items) < 2:
            return
            
        target_y = items[0].pos().y()
        for item in items[1:]:
            item.setY(target_y)
        
        print(f"Aligned {len(items)} items horizontally at Y={target_y:.1f}")

    def load_skin(self, pixmap_path: str, opacity: float = 1.0, scale: float = 1.0, x_pct: float = 0.0, y_pct: float = 0.0):
        if self.skin_item:
            self.scene.removeItem(self.skin_item)
        
        pixmap = QPixmap(pixmap_path)
        if pixmap.isNull():
            print(f"Error: Could not load pixmap from {pixmap_path}")
            return None

        self.skin_item = HUDSkinItem(pixmap, pixmap_path)
        self.scene.addItem(self.skin_item)
        
        self.skin_item.setOpacity(opacity)
        self.skin_item.setScale(scale)
        self.skin_item.setPos(x_pct * self.view_width, y_pct * self.view_height)
        
        self.skin_loaded.emit(self.skin_item)
        return self.skin_item

    def add_telemetry_field(self, field: str, rel_x: float, rel_y: float, color: str = "#FFFFFF", font_size: int = 12):
        if not self.skin_item:
            print("Error: No skin loaded. Load a skin before adding telemetry fields.")
            return

        item = TelemetryItem(field, self.skin_item)
        item.set_color(color)
        item.set_font_size(font_size)
        
        # Position relative to skin (0.0 to 1.0 of skin dimensions)
        skin_rect = self.skin_item.pixmap().rect()
        item.setPos(rel_x * skin_rect.width(), rel_y * skin_rect.height())
        
        # Track by unique field name or generate one for custom text
        key = f"field_{field}_{len(self.linked_elements)}"
        self.linked_elements[key] = item
        return item

    def add_custom_label(self, text: str, rel_x: float, rel_y: float, color: str = "#FFFFFF", font_size: int = 12):
        if not self.skin_item: return None
        
        item = TelemetryItem(f"custom:{text}", self.skin_item)
        item.is_custom = True
        item.custom_text = text
        item.set_color(color)
        item.set_font_size(font_size)
        item.setPlainText(text)
        
        skin_rect = self.skin_item.pixmap().rect()
        item.setPos(rel_x * skin_rect.width(), rel_y * skin_rect.height())
        
        key = f"custom_{len(self.linked_elements)}"
        self.linked_elements[key] = item
        return item

    def remove_item(self, item):
        if not item: return
        # Find and remove from dictionary
        keys_to_remove = [k for k, v in self.linked_elements.items() if v == item]
        for k in keys_to_remove:
            del self.linked_elements[k]
        
        if item.scene():
            self.scene.removeItem(item)

    def load_layout(self, layout_json: dict):
        hud_skin = layout_json.get("hud_skin")
        if not hud_skin:
            return

        # Clear existing elements
        for item in self.linked_elements.values():
            if item.scene():
                self.scene.removeItem(item)
        self.linked_elements = {}

        self.load_skin(
            hud_skin["path"],
            opacity=hud_skin.get("opacity", 1.0),
            scale=hud_skin.get("scale", 1.0),
            x_pct=hud_skin.get("x_pct", 0.0),
            y_pct=hud_skin.get("y_pct", 0.0)
        )

        for element in hud_skin.get("linked_elements", []):
            field = element.get("field", "")
            if field.startswith("custom:"):
                text = field.replace("custom:", "")
                item = self.add_custom_label(
                    text,
                    element["rel_x"],
                    element["rel_y"],
                    color=element.get("color", "#FFFFFF"),
                    font_size=element.get("font_size", 12)
                )
                if item:
                    item.setScale(element.get("scale", 1.0))
            else:
                item = self.add_telemetry_field(
                    field,
                    element["rel_x"],
                    element["rel_y"],
                    color=element.get("color", "#FFFFFF"),
                    font_size=element.get("font_size", 12)
                )
                if item:
                    item.setScale(element.get("scale", 1.0))

    def update_telemetry_data(self, waypoint: 'Waypoint'):
        """
        Updates the text of all linked telemetry elements based on waypoint data.
        """
        for key, item in self.linked_elements.items():
            if getattr(item, 'is_custom', False):
                continue
                
            field = item.field
            raw_val = getattr(waypoint, field, None)
            val = format_telemetry_value(field, raw_val)
            item.update_value(val)

    def get_layout_json(self):
        if not self.skin_item:
            return {}

        skin_rect = self.skin_item.pixmap().rect()
        linked_elements = []
        for key, item in self.linked_elements.items():
            field_name = item.field
            if getattr(item, 'is_custom', False):
                field_name = f"custom:{item.custom_text}"
                
            linked_elements.append({
                "field": field_name,
                "rel_x": item.pos().x() / skin_rect.width(),
                "rel_y": item.pos().y() / skin_rect.height(),
                "color": item.defaultTextColor().name(),
                "font_size": item.font().pixelSize(),
                "scale": item.scale()
            })

        return {
            "hud_skin": {
                "path": self.skin_item.path,
                "opacity": self.skin_item.opacity(),
                "scale": self.skin_item.scale(),
                "x_pct": self.skin_item.pos().x() / self.view_width,
                "y_pct": self.skin_item.pos().y() / self.view_height,
                "linked_elements": linked_elements
            }
        }

class HUDSkinItem(QGraphicsPixmapItem):
    def __init__(self, pixmap, path):
        super().__init__(pixmap)
        self.path = path
        self.setFlags(
            QGraphicsItem.ItemIsMovable | 
            QGraphicsItem.ItemIsSelectable | 
            QGraphicsItem.ItemSendsGeometryChanges
        )

class TelemetryItem(QGraphicsTextItem):
    def __init__(self, field, parent=None):
        super().__init__(parent)
        self.field = field
        self.setFlags(
            QGraphicsItem.ItemIsMovable | 
            QGraphicsItem.ItemIsSelectable | 
            QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setPlainText(f"[{field}]")
        font = QFont("Arial", 16)
        font.setPixelSize(16) 
        self.setFont(font)
        self.setDefaultTextColor(QColor("#FFFFFF"))
        self.document().setDocumentMargin(0)

    def set_color(self, hex_color):
        self.setDefaultTextColor(QColor(hex_color))

    def set_font_size(self, size):
        font = self.font()
        font.setPixelSize(size)
        self.setFont(font)

    def set_scale(self, scale):
        self.setScale(scale)

    def update_value(self, value):
        self.setPlainText(str(value))
