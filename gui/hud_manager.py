import json
from pathlib import Path
from PySide6.QtWidgets import (
    QGraphicsPixmapItem, QGraphicsTextItem, QGraphicsItem, 
    QGraphicsScene, QGraphicsView, QGraphicsPathItem
)
from PySide6.QtCore import Qt, QPointF, Signal, QObject, QRectF
from PySide6.QtGui import QPixmap, QColor, QFont, QPainterPath, QPen, QBrush

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
        self.linked_elements = {} # item -> item
        self.manufacturer = "Shearwater"
        self.model = "Perdix2"
        
        self.scene.selectionChanged.connect(self.on_selection_changed)

    def on_selection_changed(self):
        try:
            items = self.scene.selectedItems()
        except RuntimeError:
            return
            
        # Filter to only TelemetryItems or the Skin itself
        targets = [i for i in items if isinstance(i, (TelemetryItem, HUDSkinItem, HUDShapeItem, HUDGraphItem))]
        
        if targets:
            self.item_selected.emit(targets[0])
        else:
            self.item_selected.emit(None)

    def align_selected_horizontally(self):
        """Aligns selected telemetry items to the bottom edge of the first selected item."""
        self.align_selected("h_bottom")

    def align_selected(self, mode: str):
        """Aligns selected telemetry items based on the given mode."""
        try:
            items = [i for i in self.scene.selectedItems() if isinstance(i, TelemetryItem)]
        except RuntimeError:
            return
            
        if len(items) < 2:
            return

        if mode == "h_top":
            target_y = min(item.pos().y() for item in items)
            for item in items:
                item.setY(target_y)
        elif mode == "h_bottom":
            target_bottom = max(item.pos().y() + item.boundingRect().height() * item.scale() for item in items)
            for item in items:
                item_h = item.boundingRect().height() * item.scale()
                item.setY(target_bottom - item_h)
        elif mode == "h_center":
            min_y = min(item.pos().y() for item in items)
            max_bottom = max(item.pos().y() + item.boundingRect().height() * item.scale() for item in items)
            center_y = (min_y + max_bottom) / 2.0
            for item in items:
                item_h = item.boundingRect().height() * item.scale()
                item.setY(center_y - item_h / 2.0)
        elif mode == "v_left":
            target_x = min(item.pos().x() for item in items)
            for item in items:
                item.setX(target_x)
        elif mode == "v_right":
            target_right = max(item.pos().x() + item.boundingRect().width() * item.scale() for item in items)
            for item in items:
                item_w = item.boundingRect().width() * item.scale()
                item.setX(target_right - item_w)
        elif mode == "v_center":
            min_x = min(item.pos().x() for item in items)
            max_right = max(item.pos().x() + item.boundingRect().width() * item.scale() for item in items)
            center_x = (min_x + max_right) / 2.0
            for item in items:
                item_w = item.boundingRect().width() * item.scale()
                item.setX(center_x - item_w / 2.0)

        print(f"Aligned {len(items)} items using mode: {mode}")


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

    def create_shape_skin(self, width: int = 400, height: int = 200, color: str = "#000000", opacity: float = 0.5, corner_radius: int = 20, x_pct: float = 0.1, y_pct: float = 0.1):
        if self.skin_item:
            self.scene.removeItem(self.skin_item)
        
        self.skin_item = HUDShapeItem(width, height, color, corner_radius)
        self.scene.addItem(self.skin_item)
        
        self.skin_item.setOpacity(opacity)
        self.skin_item.setPos(x_pct * self.view_width, y_pct * self.view_height)
        
        self.skin_loaded.emit(self.skin_item)
        return self.skin_item

    def add_telemetry_field(self, field: str, rel_x: float, rel_y: float, color: str = "#FFFFFF", font_size: int = 30):
        if not self.skin_item:
            print("Error: No skin loaded. Load a skin before adding telemetry fields.")
            return

        item = TelemetryItem(field, self.skin_item)
        item.set_color(color)
        item.set_font_size(font_size)
        
        # Position relative to skin (0.0 to 1.0 of skin dimensions)
        rect = self.skin_item.pixmap().rect() if isinstance(self.skin_item, HUDSkinItem) else self.skin_item.rect()
        item.setPos(rel_x * rect.width(), rel_y * rect.height())
        
        # Track using the item itself as the key to avoid name collisions
        self.linked_elements[item] = item
        return item

    def add_depth_graph(self, rel_x: float, rel_y: float, width: int = 300, height: int = 150, color: str = "#00FF00", marker_style: str = "dot", marker_size: int = 6):
        if not self.skin_item:
            return None
            
        item = HUDGraphItem(parent=self.skin_item)
        item.set_color(color)
        item.set_dimensions(width, height)
        item.set_marker_style(marker_style)
        item.set_marker_size(marker_size)
        
        # Position relative to skin
        rect = self.skin_item.pixmap().rect() if isinstance(self.skin_item, HUDSkinItem) else self.skin_item.rect()
        item.setPos(rel_x * rect.width(), rel_y * rect.height())
        
        if getattr(self, 'last_waypoints', None) is not None:
            item.set_data(self.last_waypoints, self.last_current_wp)
            
        self.linked_elements[item] = item
        return item

    def add_custom_label(self, text: str, rel_x: float, rel_y: float, color: str = "#FFFFFF", font_size: int = 30):
        if not self.skin_item: return None
        
        item = TelemetryItem(f"custom:{text}", self.skin_item)
        item.is_custom = True
        item.custom_text = text
        item.set_color(color)
        item.set_font_size(font_size)
        item.setPlainText(text)
        
        rect = self.skin_item.pixmap().rect() if isinstance(self.skin_item, HUDSkinItem) else self.skin_item.rect()
        item.setPos(rel_x * rect.width(), rel_y * rect.height())
        
        self.linked_elements[item] = item
        return item

    def remove_item(self, item):
        if not item: return
        # Remove from dictionary
        if item in self.linked_elements:
            del self.linked_elements[item]
        
        if item.scene():
            self.scene.removeItem(item)

    def load_layout(self, layout_json: dict):
        self.manufacturer = layout_json.get("manufacturer", "Shearwater")
        self.model = layout_json.get("model", "Perdix2")
        hud_skin = layout_json.get("hud_skin")
        if not hud_skin:
            return

        # 1. Safely clear existing telemetry elements
        for item in list(self.linked_elements.values()):
            try:
                if item.scene():
                    self.scene.removeItem(item)
                item.setParentItem(None)
            except RuntimeError:
                pass
        self.linked_elements = {}

        # 2. Safely clear existing skin
        if self.skin_item:
            try:
                if self.skin_item.scene():
                    self.scene.removeItem(self.skin_item)
            except RuntimeError:
                pass
            self.skin_item = None

        # 3. Load new skin
        anchor = hud_skin.get("anchor", "TOP_LEFT")
        ref_x = hud_skin.get("ref_offset_x")
        ref_y = hud_skin.get("ref_offset_y")
        
        # Determine initial position (Top-Left of HUD in GUI)
        initial_x, initial_y = 0.0, 0.0
        
        # Prefer Anchor + Offset if available
        if ref_x is not None and ref_y is not None:
            # Reconstruct Top-Left from Anchor in current view
            base_x, base_y = 0.0, 0.0
            if 'CENTER' in anchor: base_x = self.view_width / 2.0
            elif 'RIGHT' in anchor: base_x = float(self.view_width)
            
            if 'MIDDLE' in anchor: base_y = self.view_height / 2.0
            elif 'BOTTOM' in anchor: base_y = float(self.view_height)
            
            # Pivot adjustment (we need HUD dimensions to find Top-Left)
            # This is tricky because we haven't loaded the skin yet.
            # We'll set the position AFTER loading the skin.
            pass 
        else:
            # Fallback to percentages
            initial_x = hud_skin.get("x_pct", 0.0) * self.view_width
            initial_y = hud_skin.get("y_pct", 0.0) * self.view_height
        
        if hud_skin.get("type") == "shape":
            self.skin_item = self.create_shape_skin(
                width=hud_skin.get("width", 400),
                height=hud_skin.get("height", 200),
                color=hud_skin.get("color", "#000000"),
                opacity=hud_skin.get("opacity", 0.5),
                corner_radius=hud_skin.get("corner_radius", 20),
                x_pct=0, y_pct=0 # Set temporary 0
            )
        else:
            skin_path = hud_skin.get("path")
            if skin_path:
                self.skin_item = self.load_skin(
                    skin_path,
                    opacity=hud_skin.get("opacity", 1.0),
                    scale=hud_skin.get("scale", 1.0),
                    x_pct=0, y_pct=0
                )
        
        if self.skin_item:
            self.skin_item.anchor = anchor
            
            # Now set the correct position based on anchor and offsets
            if ref_x is not None and ref_y is not None:
                rect = self.skin_item.rect() if isinstance(self.skin_item, HUDShapeItem) else self.skin_item.pixmap().rect()
                sw = rect.width() * self.skin_item.scale()
                sh = rect.height() * self.skin_item.scale()
                
                base_x, base_y = 0.0, 0.0
                if 'CENTER' in anchor: base_x = self.view_width / 2.0
                elif 'RIGHT' in anchor: base_x = float(self.view_width)
                if 'MIDDLE' in anchor: base_y = self.view_height / 2.0
                elif 'BOTTOM' in anchor: base_y = float(self.view_height)
                
                pivot_x, pivot_y = 0.0, 0.0
                if 'CENTER' in anchor: pivot_x = sw / 2.0
                elif 'RIGHT' in anchor: pivot_x = sw
                if 'MIDDLE' in anchor: pivot_y = sh / 2.0
                elif 'BOTTOM' in anchor: pivot_y = sh
                
                self.skin_item.setPos(base_x + ref_x - pivot_x, base_y + ref_y - pivot_y)
            else:
                # Use calculated fallback
                self.skin_item.setPos(initial_x, initial_y)

        # 4. Load new telemetry elements
        rect = self.skin_item.rect() if isinstance(self.skin_item, HUDShapeItem) else self.skin_item.pixmap().rect()
        for element in hud_skin.get("linked_elements", []):
            field = element.get("field", "")
            if element.get("type") == "graph" or field == "depth_graph":
                item = self.add_depth_graph(
                    rel_x=element["rel_x"],
                    rel_y=element["rel_y"],
                    width=element.get("width", 300),
                    height=element.get("height", 150),
                    color=element.get("color", "#00FF00"),
                    marker_style=element.get("marker_style", "dot"),
                    marker_size=element.get("marker_size", 6)
                )
            elif field.startswith("custom:"):
                text = field.replace("custom:", "")
                item = self.add_custom_label(
                    text,
                    element["rel_x"],
                    element["rel_y"],
                    color=element.get("color", "#FFFFFF"),
                    font_size=element.get("font_size", 12)
                )
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

    def update_telemetry_data(self, waypoint: 'Waypoint', waypoints: list = None):
        """
        Updates the text of all linked telemetry elements based on waypoint data.
        """
        self.last_current_wp = waypoint
        self.last_waypoints = waypoints
        for item in list(self.linked_elements.values()):
            try:
                if not item or not item.scene(): continue
                if isinstance(item, HUDGraphItem):
                    item.set_data(waypoints or [], waypoint)
                    continue
                if getattr(item, 'is_custom', False): continue
                    
                field = item.field
                if field == "safety_stop":
                    from utils.hud_rules_engine import get_safety_stop_text
                    mfg = getattr(self, 'manufacturer', 'Shearwater')
                    model = getattr(self, 'model', 'Perdix2')
                    val = get_safety_stop_text(mfg, model, waypoint)
                    raw_val = None
                elif field.startswith("tank_pressure:"):
                    tank_name = field.replace("tank_pressure:", "")
                    tank_data = waypoint.tanks.get(tank_name)
                    raw_val = tank_data.pressure_bar if tank_data else None
                    val = format_telemetry_value(field, raw_val)
                elif field.startswith("tank_name:"):
                    tank_name = field.replace("tank_name:", "")
                    tank_data = waypoint.tanks.get(tank_name)
                    val = tank_data.name if (tank_data and tank_data.name) else tank_name
                    raw_val = None
                else:
                    raw_val = getattr(waypoint, field, None)
                    val = format_telemetry_value(field, raw_val)
                
                item.update_value(val)
                
                # Dynamic threshold color evaluation
                from utils.hud_rules_engine import get_dynamic_color
                mfg = getattr(self, 'manufacturer', 'Shearwater')
                model = getattr(self, 'model', 'Perdix2')
                color = get_dynamic_color(mfg, model, field, raw_val, getattr(item, 'base_color', '#FFFFFF'))
                item.setDefaultTextColor(QColor(color))
            except RuntimeError:
                continue

    def get_layout_json(self):
        if not self.skin_item:
            return {}

        is_shape = isinstance(self.skin_item, HUDShapeItem)
        rect = self.skin_item.rect() if is_shape else self.skin_item.pixmap().rect()
        
        linked_elements = []
        for item in self.linked_elements.values():
            if isinstance(item, HUDGraphItem):
                linked_elements.append({
                    "field": item.field,
                    "rel_x": item.pos().x() / rect.width(),
                    "rel_y": item.pos().y() / rect.height(),
                    "color": item.color_hex,
                    "width": item.width,
                    "height": item.height,
                    "type": "graph",
                    "marker_style": item.marker_style,
                    "marker_size": item.marker_size
                })
                continue

            field_name = item.field
            if getattr(item, 'is_custom', False):
                field_name = f"custom:{item.custom_text}"
                
            linked_elements.append({
                "field": field_name,
                "rel_x": item.pos().x() / rect.width(),
                "rel_y": item.pos().y() / rect.height(),
                "color": getattr(item, 'base_color', item.defaultTextColor().name()),
                "font_size": item.font().pixelSize(),
                "scale": item.scale()
            })

        # --- Corner-to-Corner Anchor Logic ---
        anchor = getattr(self.skin_item, 'anchor', 'TOP_LEFT')
        pos = self.skin_item.pos()
        sw = rect.width() * self.skin_item.scale()
        sh = rect.height() * self.skin_item.scale()
        
        # We calculate the offset from the SCREEN ANCHOR to the HUD'S MATCHING ANCHOR point
        # e.g., BOTTOM_RIGHT offset = Distance from Screen Bottom-Right to HUD Bottom-Right
        ref_x, ref_y = 0.0, 0.0
        
        # 1. Resolve HUD's own anchor point (Top-Left of HUD is pos.x, pos.y)
        if 'LEFT' in anchor:
            hud_ref_x = pos.x()
        elif 'CENTER' in anchor:
            hud_ref_x = pos.x() + (sw / 2.0)
        elif 'RIGHT' in anchor:
            hud_ref_x = pos.x() + sw
            
        if 'TOP' in anchor:
            hud_ref_y = pos.y()
        elif 'MIDDLE' in anchor:
            hud_ref_y = pos.y() + (sh / 2.0)
        elif 'BOTTOM' in anchor:
            hud_ref_y = pos.y() + sh

        # 2. Resolve Screen anchor point
        if 'LEFT' in anchor:
            screen_ref_x = 0.0
        elif 'CENTER' in anchor:
            screen_ref_x = self.view_width / 2.0
        elif 'RIGHT' in anchor:
            screen_ref_x = float(self.view_width)
            
        if 'TOP' in anchor:
            screen_ref_y = 0.0
        elif 'MIDDLE' in anchor:
            screen_ref_y = self.view_height / 2.0
        elif 'BOTTOM' in anchor:
            screen_ref_y = float(self.view_height)

        # 3. Reference Offset is the distance between these two points
        ref_x = hud_ref_x - screen_ref_x
        ref_y = hud_ref_y - screen_ref_y

        skin_data = {
            "type": "shape" if is_shape else "image",
            "anchor": anchor,
            "ref_offset_x": ref_x,
            "ref_offset_y": ref_y,
            "opacity": self.skin_item.opacity(),
            "x_pct": pos.x() / self.view_width, # Legacy fallback
            "y_pct": pos.y() / self.view_height, # Legacy fallback
            "linked_elements": linked_elements
        }

        if is_shape:
            skin_data.update({
                "width": self.skin_item.width,
                "height": self.skin_item.height,
                "color": self.skin_item.color_hex,
                "corner_radius": self.skin_item.corner_radius
            })
        else:
            skin_data.update({
                "path": self.skin_item.path,
                "scale": self.skin_item.scale(),
            })

        return {
            "manufacturer": self.manufacturer,
            "model": self.model,
            "hud_skin": skin_data,
            "design_width": self.view_width,
            "design_height": self.view_height
        }

class HUDShapeItem(QGraphicsPathItem):
    def __init__(self, width, height, color_hex, corner_radius=20):
        super().__init__()
        self.width = width
        self.height = height
        self.color_hex = color_hex
        self.corner_radius = corner_radius
        self.path = None 
        self.anchor = "TOP_LEFT"
        
        self.setFlags(
            QGraphicsItem.ItemIsMovable | 
            QGraphicsItem.ItemIsSelectable | 
            QGraphicsItem.ItemSendsGeometryChanges
        )
        self.update_path()

    def update_path(self):
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self.width, self.height), self.corner_radius, self.corner_radius)
        self.setPath(path)
        self.setBrush(QBrush(QColor(self.color_hex)))
        self.setPen(QPen(Qt.NoPen))

    def rect(self):
        return QRectF(0, 0, self.width, self.height)

class HUDSkinItem(QGraphicsPixmapItem):
    def __init__(self, pixmap, path):
        super().__init__(pixmap)
        self.path = path
        self.anchor = "TOP_LEFT"
        self.setFlags(
            QGraphicsItem.ItemIsMovable | 
            QGraphicsItem.ItemIsSelectable | 
            QGraphicsItem.ItemSendsGeometryChanges
        )

class TelemetryItem(QGraphicsTextItem):
    def __init__(self, field, parent=None):
        super().__init__(parent)
        self.field = field
        self.base_color = "#FFFFFF"
        self.setFlags(
            QGraphicsItem.ItemIsMovable | 
            QGraphicsItem.ItemIsSelectable | 
            QGraphicsItem.ItemSendsGeometryChanges
        )
        
        display_name = field
        if field.startswith("tank_pressure:"):
            display_name = field.replace("tank_pressure:", "") + " (Bar)"
        elif field.startswith("tank_name:"):
            display_name = field.replace("tank_name:", "")
            
        self.setPlainText(display_name)
        font = QFont("Arial", 30)
        font.setPixelSize(30) 
        self.setFont(font)
        self.setDefaultTextColor(QColor("#FFFFFF"))
        self.document().setDocumentMargin(0)

    def set_color(self, hex_color):
        self.base_color = hex_color
        self.setDefaultTextColor(QColor(hex_color))

    def set_font_size(self, size):
        font = self.font()
        font.setPixelSize(size)
        self.setFont(font)

    def update_value(self, value):
        self.setPlainText(str(value))

class HUDGraphItem(QGraphicsPathItem):
    def __init__(self, field="depth_graph", parent=None):
        super().__init__(parent)
        self.field = field
        self.width = 300
        self.height = 150
        self.color_hex = "#00FF00"
        self.marker_style = "dot"
        self.marker_size = 6
        self.waypoints = []
        self.current_wp = None
        self.setFlags(
            QGraphicsItem.ItemIsMovable | 
            QGraphicsItem.ItemIsSelectable | 
            QGraphicsItem.ItemSendsGeometryChanges
        )
        self.update_path()

    def set_color(self, hex_color):
        self.color_hex = hex_color
        self.update_path()

    def set_dimensions(self, w, h):
        self.width = w
        self.height = h
        self.update_path()

    def set_marker_style(self, style):
        self.marker_style = style
        self.update_path()

    def set_marker_size(self, size):
        self.marker_size = size
        self.update_path()

    def rect(self):
        return QRectF(0, 0, self.width, self.height)

    def set_data(self, waypoints, current_wp):
        self.waypoints = waypoints
        self.current_wp = current_wp
        self.update_path()

    def update_path(self):
        # We define path just for selection bounding box in QGraphicsScene
        path = QPainterPath()
        path.addRect(QRectF(0, 0, self.width, self.height))
        self.setPath(path)
        self.setBrush(QBrush(Qt.NoBrush))
        self.setPen(QPen(Qt.NoPen)) # We draw custom outline in paint()
        self.update()

    def paint(self, painter, option, widget=None):
        # 1. Draw border and semi-transparent background
        pen = QPen(QColor(self.color_hex), 1, Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(QBrush(QColor(0, 0, 0, 100))) # Semi-transparent background
        painter.drawRect(0, 0, self.width, self.height)

        if not self.waypoints:
            return

        # 2. Scale points
        max_d = max(wp.depth for wp in self.waypoints) if self.waypoints else 1.0
        if max_d <= 0:
            max_d = 1.0
        max_d *= 1.1

        n_wps = len(self.waypoints)
        if n_wps < 2:
            return

        dx = self.width / (n_wps - 1)
        dy = self.height / max_d

        # 3. Draw filled area under the curve (semi-transparent)
        fill_path = QPainterPath()
        fill_path.moveTo(0, 0)
        for i in range(n_wps):
            x = i * dx
            y = self.waypoints[i].depth * dy
            fill_path.lineTo(x, y)
        fill_path.lineTo(self.width, 0)
        fill_path.closeSubpath()
        
        fill_color = QColor(self.color_hex)
        fill_color.setAlpha(40)
        painter.setBrush(QBrush(fill_color))
        painter.setPen(Qt.NoPen)
        painter.drawPath(fill_path)

        # 4. Draw depth profile line
        line_path = QPainterPath()
        line_path.moveTo(0, self.waypoints[0].depth * dy)
        for i in range(1, n_wps):
            line_path.lineTo(i * dx, self.waypoints[i].depth * dy)
        
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(self.color_hex), 2, Qt.SolidLine))
        painter.drawPath(line_path)

        # 5. Draw cursor indicator
        if self.current_wp:
            # Find closest waypoint by timestamp
            curr_idx = 0
            closest_diff = float('inf')
            for idx, wp in enumerate(self.waypoints):
                diff = abs((wp.timestamp - self.current_wp.timestamp).total_seconds())
                if diff < closest_diff:
                    closest_diff = diff
                    curr_idx = idx
            
            curr_x = curr_idx * dx
            curr_y = self.waypoints[curr_idx].depth * dy

            # Draw vertical cursor line
            painter.setPen(QPen(QColor(self.color_hex), 1, Qt.DotLine))
            painter.drawLine(curr_x, 0, curr_x, self.height)

            # Draw cursor marker
            if self.marker_style == "dot":
                painter.setPen(QPen(QColor("#FFFFFF"), 1))
                painter.setBrush(QBrush(QColor(self.color_hex)))
                painter.drawEllipse(QPointF(curr_x, curr_y), self.marker_size, self.marker_size)
            elif self.marker_style == "cross":
                painter.setPen(QPen(QColor(self.color_hex), 1, Qt.SolidLine))
                painter.drawLine(curr_x - self.marker_size, curr_y, curr_x + self.marker_size, curr_y)
                painter.drawLine(curr_x, curr_y - self.marker_size, curr_x, curr_y + self.marker_size)
            elif self.marker_style == "bold_cross":
                painter.setPen(QPen(QColor(self.color_hex), 3, Qt.SolidLine))
                painter.drawLine(curr_x - self.marker_size, curr_y, curr_x + self.marker_size, curr_y)
                painter.drawLine(curr_x, curr_y - self.marker_size, curr_x, curr_y + self.marker_size)

