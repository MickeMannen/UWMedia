import json
from pathlib import Path
from PySide6.QtWidgets import (
    QGraphicsPixmapItem, QGraphicsTextItem, QGraphicsItem, 
    QGraphicsScene, QGraphicsView
)
from PySide6.QtCore import Qt, QPointF, Signal, QObject
from PySide6.QtGui import QPixmap, QColor, QFont

class HUDManager(QObject):
    """
    Manages the HUD Skin and linked telemetry elements in a PySide6 QGraphicsScene.
    """
    layout_changed = Signal(dict)

    def __init__(self, scene: QGraphicsScene, view_width: int, view_height: int):
        super().__init__()
        self.scene = scene
        self.view_width = view_width
        self.view_height = view_height
        self.skin_item = None
        self.linked_elements = {} # field -> TelemetryItem

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
        
        self.linked_elements[field] = item
        return item

    def load_layout(self, layout_json: dict):
        hud_skin = layout_json.get("hud_skin")
        if not hud_skin:
            return

        self.load_skin(
            hud_skin["path"],
            opacity=hud_skin.get("opacity", 1.0),
            scale=hud_skin.get("scale", 1.0),
            x_pct=hud_skin.get("x_pct", 0.0),
            y_pct=hud_skin.get("y_pct", 0.0)
        )

        for element in hud_skin.get("linked_elements", []):
            self.add_telemetry_field(
                element["field"],
                element["rel_x"],
                element["rel_y"],
                color=element.get("color", "#FFFFFF"),
                font_size=element.get("font_size", 12)
            )

    def update_telemetry_data(self, waypoint: 'Waypoint'):
        """
        Updates the text of all linked telemetry elements based on waypoint data.
        """
        for field, item in self.linked_elements.items():
            value = getattr(waypoint, field, "N/A")
            
            # Formatting based on field type
            if isinstance(value, float):
                formatted_val = f"{value:.1f}"
            else:
                formatted_val = str(value)
                
            item.update_value(formatted_val)

    def get_layout_json(self):
        if not self.skin_item:
            return {}

        skin_rect = self.skin_item.pixmap().rect()
        linked_elements = []
        for field, item in self.linked_elements.items():
            linked_elements.append({
                "field": field,
                "rel_x": item.pos().x() / skin_rect.width(),
                "rel_y": item.pos().y() / skin_rect.height(),
                "color": item.defaultTextColor().name(),
                "font_size": item.font().pointSize()
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
        self.setFont(QFont("Arial", 12))
        self.setDefaultTextColor(QColor("#FFFFFF"))

    def set_color(self, hex_color):
        self.setDefaultTextColor(QColor(hex_color))

    def set_font_size(self, size):
        font = self.font()
        font.setPointSize(size)
        self.setFont(font)

    def set_scale(self, scale):
        self.setScale(scale)

    def update_value(self, value):
        self.setPlainText(str(value))
