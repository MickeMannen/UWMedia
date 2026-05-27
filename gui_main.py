import sys
import cv2
import json
import zipfile
import tempfile
import os
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QGraphicsView, QGraphicsScene, 
    QVBoxLayout, QHBoxLayout, QWidget, QFileDialog, QPushButton,
    QSlider, QLabel, QGraphicsPixmapItem, QGroupBox, QFormLayout,
    QSpinBox, QListWidget, QListWidgetItem, QLineEdit, QScrollArea,
    QDialog, QTextEdit, QMenu, QGesture, QPinchGesture, QGestureEvent
)
from PySide6.QtCore import Qt, QTimer, QSettings, QEvent
from PySide6.QtGui import QPixmap, QColor, QFont, QPainter, QImage, QMouseEvent
from gui.hud_manager import HUDManager, TelemetryItem
from gui.hud_controls import HUDControls
from models.manager import DiveManager
from parsers.uddf import UDDFParser
from parsers.garmin import GarminParser
from parsers.subsurface import SubsurfaceParser
from metadata.exif import MetadataHandler
from models.dive import Waypoint

class ZoomableGraphicsView(QGraphicsView):
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.parent_win = parent
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setBackgroundBrush(Qt.black)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self._is_panning = False
        
        # Grab gesture for touchpad pinch zoom
        self.grabGesture(Qt.PinchGesture)

    def event(self, event):
        if event.type() == QEvent.Gesture:
            return self.gestureEvent(event)
        return super().event(event)

    def gestureEvent(self, event):
        pinch = event.gesture(Qt.PinchGesture)
        if pinch:
            self.pinchTriggered(pinch)
            return True
        return False

    def pinchTriggered(self, gesture):
        factor = gesture.scaleFactor()
        # Dampen zoom to make it less reactive
        dampened_factor = 1.0 + (factor - 1.0) * 0.4
        self.scale(dampened_factor, dampened_factor)

    def wheelEvent(self, event):
        # Zoom only when Ctrl key is held (standard trackpad/mouse scroll behavior)
        if event.modifiers() == Qt.ControlModifier:
            angle = event.angleDelta().y()
            # Dampen scroll wheel zoom factor
            factor = 1.0 + (angle / 1200.0) * 0.3
            factor = max(0.9, min(1.1, factor))
            self.scale(factor, factor)
        else:
            # Delegate to standard scroll behavior (panning/scrolling)
            super().wheelEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            self._is_panning = True
            # Simulate a left-click for the scroll hand drag to work
            fake_event = QMouseEvent(event.type(), event.pos(), Qt.LeftButton, Qt.LeftButton, event.modifiers())
            super().mousePressEvent(fake_event)
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self.setDragMode(QGraphicsView.NoDrag)
            self._is_panning = False
            fake_event = QMouseEvent(event.type(), event.pos(), Qt.LeftButton, Qt.LeftButton, event.modifiers())
            super().mouseReleaseEvent(fake_event)
        else:
            super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        selected_items = []
        try:
            selected_items = [item for item in self.scene().selectedItems() if isinstance(item, TelemetryItem)]
        except RuntimeError:
            pass

        if len(selected_items) >= 2 and self.parent_win and hasattr(self.parent_win, 'hud_manager'):
            menu = QMenu(self)
            
            h_menu = menu.addMenu("Horizontal Alignment")
            h_top = h_menu.addAction("Align Top")
            h_bottom = h_menu.addAction("Align Bottom")
            h_center = h_menu.addAction("Align Center")
            
            v_menu = menu.addMenu("Vertical Alignment")
            v_left = v_menu.addAction("Align Left")
            v_right = v_menu.addAction("Align Right")
            v_center = v_menu.addAction("Align Center")
            
            action = menu.exec(event.globalPos())
            if not action:
                return
                
            if action == h_top:
                self.parent_win.hud_manager.align_selected("h_top")
            elif action == h_bottom:
                self.parent_win.hud_manager.align_selected("h_bottom")
            elif action == h_center:
                self.parent_win.hud_manager.align_selected("h_center")
            elif action == v_left:
                self.parent_win.hud_manager.align_selected("v_left")
            elif action == v_right:
                self.parent_win.hud_manager.align_selected("v_right")
            elif action == v_center:
                self.parent_win.hud_manager.align_selected("v_center")
        else:
            super().contextMenuEvent(event)

class HUDDesignerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # Get revision from main entry point
        try:
            from main import REVISION
            self.revision = REVISION
        except ImportError:
            self.revision = "dev"

        self.setWindowTitle(f"UWMedia HUD Designer & Sync - Rev: {self.revision}")
        self.resize(1280, 720) # More reasonable default for laptops
        self.settings = QSettings("UWMedia", "HUDDesigner")

        # State
        self.video_cap = None
        self.bg_pixmap_item = None
        self.dive_manager = DiveManager()
        self.current_dive = None
        self.video_creation_date = None
        self.video_fps = 30.0
        
        self.last_video_path = self.settings.value("last_video_path", "")
        self.last_log_dir = self.settings.value("last_log_dir", "")
        self.last_hud_path = self.settings.value("last_hud_path", "")
        self.last_skin_path = self.settings.value("last_skin_path", "")

        # Central Widget
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)

        # Left Column: Canvas + Slider
        self.canvas_layout = QVBoxLayout()
        
        self.scene = QGraphicsScene(0, 0, 1920, 1080)
        self.view = ZoomableGraphicsView(self.scene, self)
        self.view.setRenderHint(QPainter.Antialiasing)
        
        self.canvas_layout.addWidget(self.view)
        
        # Reset Zoom Button overlay or below? Below is easier for now.
        self.btn_reset_zoom = QPushButton("Reset Zoom")
        self.btn_reset_zoom.clicked.connect(lambda: self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio))
        self.canvas_layout.addWidget(self.btn_reset_zoom)
        
        # Video Slider
        self.slider_layout = QHBoxLayout()
        self.time_slider = QSlider(Qt.Horizontal)
        self.time_slider.setEnabled(False)
        self.time_slider.valueChanged.connect(self.on_slider_moved)
        self.time_label = QLabel("00:00:00")
        self.data_label = QLabel("Depth: -- | Temp: --")
        self.log_label = QLabel("Current Log: None")
        self.log_label.setStyleSheet("color: #888; font-style: italic;")
        
        self.slider_layout.addWidget(self.time_slider)
        self.slider_layout.addWidget(self.time_label)
        self.canvas_layout.addLayout(self.slider_layout)
        self.canvas_layout.addWidget(self.data_label)
        self.canvas_layout.addWidget(self.log_label)
        
        self.main_layout.addLayout(self.canvas_layout, stretch=4)

        # Right Column: Controls Panel with Scroll Area
        self.right_panel_scroll = QScrollArea()
        self.right_panel_scroll.setWidgetResizable(True)
        self.right_panel_scroll.setFixedWidth(350)
        
        self.controls_content = QWidget()
        self.controls_layout = QVBoxLayout(self.controls_content)
        self.right_panel_scroll.setWidget(self.controls_content)
        
        # 1. Background & Logs
        bg_box = QGroupBox("1. Background & Logs")
        bg_form = QFormLayout(bg_box)
        
        load_bg_layout = QHBoxLayout()
        self.btn_load_bg = QPushButton("Load Video/Photo")
        self.btn_load_bg.clicked.connect(self.load_background_dialog)
        self.btn_reload_bg = QPushButton("Reload")
        self.btn_reload_bg.clicked.connect(self.reload_last_background)
        self.btn_reload_bg.setEnabled(bool(self.last_video_path))
        load_bg_layout.addWidget(self.btn_load_bg)
        load_bg_layout.addWidget(self.btn_reload_bg)
        
        load_log_layout = QHBoxLayout()
        self.btn_load_logs = QPushButton("Select Log Directory")
        self.btn_load_logs.clicked.connect(self.load_log_dir_dialog)
        self.btn_reload_logs = QPushButton("Reload")
        self.btn_reload_logs.clicked.connect(self.reload_last_logs)
        self.btn_reload_logs.setEnabled(bool(self.last_log_dir))
        load_log_layout.addWidget(self.btn_load_logs)
        load_log_layout.addWidget(self.btn_reload_logs)
        
        self.tz_spin = QSpinBox()
        self.tz_spin.setRange(-24, 24)
        self.tz_spin.setValue(0)
        self.tz_spin.setSuffix(" hours")
        self.tz_spin.valueChanged.connect(self.match_dive_to_media)
        
        bg_form.addRow(load_bg_layout)
        bg_form.addRow(load_log_layout)
        bg_form.addRow("TZ Offset (Log vs Media):", self.tz_spin)
        self.controls_layout.addWidget(bg_box)

        # 2. HUD Core (Manager)
        # Reduced initial size by 20% (1920*0.8=1536, 1080*0.8=864) for better UI fit
        self.hud_manager = HUDManager(self.scene, 1536, 864)
        self.hud_controls = HUDControls(self.hud_manager)
        self.controls_layout.addWidget(self.hud_controls)

        # 3. Telemetry Fields List
        fields_box = QGroupBox("3. Available Fields")
        fields_layout = QVBoxLayout(fields_box)
        self.fields_list = QListWidget()
        self.update_available_fields()

        self.fields_list.itemDoubleClicked.connect(self.add_field)
        fields_layout.addWidget(QLabel("Double-click to add:"))
        fields_layout.addWidget(self.fields_list)
        
        # Custom Label
        custom_layout = QHBoxLayout()
        self.custom_text_input = QLineEdit()
        self.custom_text_input.setPlaceholderText("Custom Label...")
        self.btn_add_custom = QPushButton("Add")
        self.btn_add_custom.clicked.connect(self.add_custom_label)
        custom_layout.addWidget(self.custom_text_input)
        custom_layout.addWidget(self.btn_add_custom)
        fields_layout.addLayout(custom_layout)
        
        self.controls_layout.addWidget(fields_box)

        
        # 4. HUD Actions
        action_box = QGroupBox("4. HUD Actions")
        action_layout = QVBoxLayout(action_box)
        self.btn_load_skin = QPushButton("Load PNG Skin")
        self.btn_load_skin.clicked.connect(self.load_skin_dialog)
        self.btn_create_shape = QPushButton("Create Shape Background")
        self.btn_create_shape.clicked.connect(lambda: self.hud_manager.create_shape_skin())
        self.btn_load_package = QPushButton("Load HUD Package (.zip)")
        self.btn_load_package.clicked.connect(self.load_package_dialog)
        self.btn_save_layout = QPushButton("Save HUD Package (.zip)")
        self.btn_save_layout.clicked.connect(self.save_layout_dialog)
        
        self.btn_align_h = QPushButton("Align Horizontally")
        self.btn_align_h.clicked.connect(self.hud_manager.align_selected_horizontally)

        self.btn_review_render = QPushButton("Review Render (OpenCV)")
        self.btn_review_render.clicked.connect(self.review_render)
        self.btn_review_render.setStyleSheet("background-color: #2E7D32; color: white; font-weight: bold;")

        self.btn_show_wp = QPushButton("Show Raw Waypoint Data")
        self.btn_show_wp.clicked.connect(self.show_waypoint_data_dialog)
        
        action_layout.addWidget(self.btn_load_skin)
        action_layout.addWidget(self.btn_create_shape)
        action_layout.addWidget(self.btn_load_package)
        action_layout.addWidget(self.btn_save_layout)
        action_layout.addWidget(self.btn_align_h)
        action_layout.addWidget(self.btn_review_render)
        action_layout.addWidget(self.btn_show_wp)
        self.controls_layout.addWidget(action_box)
        
        self.controls_layout.addStretch()
        self.main_layout.addWidget(self.right_panel_scroll)
        
        self.scene.selectionChanged.connect(self.on_selection_changed)
        self.btn_align_h.setEnabled(False)

    def update_available_fields(self):
        """Refreshes the fields list with primary fields and any specific tanks found in the dive."""
        self.fields_list.clear()
        
        # 1. Standard Fields
        standard_fields = list(Waypoint.model_fields.keys())
        standard_fields.append("primary_tank_pressure")
        standard_fields.append("gasmix")
        
        for f in sorted(standard_fields):
            if f == "tanks": continue # Don't add raw dict
            self.fields_list.addItem(QListWidgetItem(f))
            
        # 2. Dynamic Tank Fields
        if self.current_dive and self.current_dive.waypoints:
            unique_tanks = set()
            for wp in self.current_dive.waypoints:
                for tank_name in wp.tanks.keys():
                    unique_tanks.add(tank_name)
            
            for tank_name in sorted(list(unique_tanks)):
                self.fields_list.addItem(QListWidgetItem(f"tank_pressure:{tank_name}"))
                self.fields_list.addItem(QListWidgetItem(f"tank_name:{tank_name}"))

    def on_selection_changed(self):
        try:
            items = self.scene.selectedItems()
        except RuntimeError:
            return
            
        telemetry_items = [i for i in items if isinstance(i, TelemetryItem)]
        self.btn_align_h.setEnabled(len(telemetry_items) >= 2)

    def add_field(self, item):
        field = item.text()
        self.hud_manager.add_telemetry_field(field, 0.5, 0.5)

    def add_custom_label(self):
        text = self.custom_text_input.text()
        if text:
            self.hud_manager.add_custom_label(text, 0.5, 0.5)
            self.custom_text_input.clear()
    def keyPressEvent(self, event):
        if event.key() in [Qt.Key_Delete, Qt.Key_Backspace]:
            try:
                selected = self.scene.selectedItems()
            except RuntimeError:
                return
            for item in selected:
                if isinstance(item, TelemetryItem):
                    self.hud_manager.remove_item(item)
        super().keyPressEvent(event)

    def review_render(self):
        """Generates a preview frame using the actual OpenCV rendering logic."""
        if not self.video_cap or not self.current_dive:
            print("Video or Dive Log not loaded.")
            return

        # 1. Capture current frame
        frame_idx = self.time_slider.value()
        self.video_cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = self.video_cap.read()
        if not ret:
            print("Failed to read frame.")
            return

        # 2. Match waypoint
        elapsed_total = frame_idx / self.video_fps
        current_time = self.video_creation_date + timedelta(seconds=elapsed_total)
        wp = self.current_dive.get_waypoint_at(current_time)
        if not wp:
            from models.dive import Waypoint
            wp = Waypoint(timestamp=current_time, depth=10.5, temp=22.0)

        # 3. Get layout
        layout = self.hud_manager.get_layout_json()
        if not layout:
            print("No layout data.")
            return

        # 4. Draw HUD using SHARED logic
        from gui.hud_renderer import draw_hud
        draw_hud(frame, layout, wp)

        # 5. Show in a popup window
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h_p, w_p, ch = rgb_frame.shape
        qimg = QImage(rgb_frame.data, w_p, h_p, w_p * ch, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg)

        preview_dialog = QWidget(None, Qt.Window)
        preview_dialog.setWindowTitle("OpenCV Render Preview (Final Output Look)")
        preview_dialog.setLayout(QVBoxLayout())
        label = QLabel()
        # Scale preview to 50% (960x540) to avoid screen overflow
        label.setPixmap(pixmap.scaled(960, 540, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        preview_dialog.layout().addWidget(label)
        preview_dialog.show()
        self.preview_window = preview_dialog # Keep reference

    def reload_last_logs(self):
        if self.last_log_dir:
            self.load_logs_from_path(self.last_log_dir)

    def reload_last_background(self):
        if self.last_video_path:
            self.load_background_from_path(self.last_video_path)

    def load_log_dir_dialog(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Dive Log Directory", self.last_log_dir)
        if dir_path:
            self.load_logs_from_path(dir_path)

    def load_logs_from_path(self, dir_path):
        self.dive_manager = DiveManager() # Reset manager
        p_dir = Path(dir_path)
        uddf = UDDFParser()
        garmin = GarminParser()
        subsurface = SubsurfaceParser()
        
        count = 0
        if not p_dir.exists():
            print(f"Error: Log directory {dir_path} no longer exists.")
            return

        for path in p_dir.iterdir():
            if path.suffix == ".uddf": 
                self.dive_manager.add_dives(uddf.parse(path))
                count += 1
            elif path.suffix == ".fit":
                self.dive_manager.add_dives(garmin.parse(path))
                count += 1
            elif path.suffix in (".ssrf", ".xml"):
                self.dive_manager.add_dives(subsurface.parse(path))
                count += 1
        
        self.last_log_dir = str(dir_path)
        self.settings.setValue("last_log_dir", self.last_log_dir)
        self.btn_reload_logs.setEnabled(True)
        
        print(f"Loaded {count} log files from {p_dir.name}")
        self.match_dive_to_media()

    def load_background_dialog(self):
        initial_dir = str(Path(self.last_video_path).parent) if self.last_video_path else ""
        path, _ = QFileDialog.getOpenFileName(self, "Select Background", initial_dir, "Media (*.mp4 *.mov *.jpg *.png)")
        if path:
            self.load_background_from_path(path)

    def load_background_from_path(self, path):
        # Extract metadata for sync
        handler = MetadataHandler()
        try:
            self.video_creation_date = handler.get_local_creation_date(Path(path))
            print(f"Media Date: {self.video_creation_date}")
        except:
            self.video_creation_date = datetime.now()

        suffix = Path(path).suffix.lower()
        if suffix in ['.mp4', '.mov']: self.load_video_background(path)
        else: self.load_image_background(path)
        
        self.last_video_path = str(path)
        self.settings.setValue("last_video_path", self.last_video_path)
        self.btn_reload_bg.setEnabled(True)
        
        self.match_dive_to_media()

    def match_dive_to_media(self):
        if self.video_creation_date:
            # Apply TZ offset to the media date to match log times
            adjusted_date = self.video_creation_date + timedelta(hours=self.tz_spin.value())
            self.current_dive = self.dive_manager.find_dive_for_timestamp(adjusted_date)
            
            if self.current_dive:
                print(f"Matched dive! Offset: {self.tz_spin.value()}h")
                self.update_available_fields()
                self.sync_data_to_frame(self.time_slider.value() / self.video_fps)
            else:
                self.data_label.setText("No matching dive found for this date/offset.")

    def load_video_background(self, path):
        self.video_cap = cv2.VideoCapture(path)
        self.video_fps = self.video_cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(self.video_cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.time_slider.setRange(0, total_frames - 1)
        self.time_slider.setEnabled(True)
        self.on_slider_moved(0)

    def load_image_background(self, path):
        if self.video_cap:
            self.video_cap.release()
            self.video_cap = None
        
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            self.set_bg_pixmap(pixmap)
            self.time_slider.setEnabled(False)
            self.time_label.setText("Photo Mode")
            self.sync_data_to_frame(0)

    def on_slider_moved(self, frame_idx):
        if self.video_cap:
            self.video_cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = self.video_cap.read()
            if ret:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = frame.shape
                q_img = QImage(frame.data, w, h, ch * w, QImage.Format_RGB888)
                self.set_bg_pixmap(QPixmap.fromImage(q_img))
                
                # Update time label
                seconds = frame_idx / self.video_fps
                self.time_label.setText(str(timedelta(seconds=int(seconds))))
                self.sync_data_to_frame(seconds)

    def sync_data_to_frame(self, offset_seconds):
        if not self.current_dive or not self.video_creation_date:
            return
        
        # Apply the same TZ offset here
        target_ts = self.video_creation_date + timedelta(hours=self.tz_spin.value(), seconds=offset_seconds)
        
        # Find closest waypoint
        wp = None
        for w in self.current_dive.waypoints:
            if w.timestamp >= target_ts:
                wp = w
                break
        
        if wp:
            self.data_label.setText(f"Depth: {wp.depth:.1f}m | Temp: {wp.temp:.1f}C")
            self.log_label.setText(f"Current Log: {wp.log_filename or 'Unknown'}")
            self.hud_manager.update_telemetry_data(wp)
        else:
            self.data_label.setText("Out of dive range.")
            self.log_label.setText("Current Log: None (No Match)")

    def set_bg_pixmap(self, pixmap):
        is_new = self.bg_pixmap_item is None
        
        # Standardize Designer to 1920px reference width
        # We use a dynamic height based on the aspect ratio to avoid cropping
        # This ensures all saved percentages are relative to the FULL frame
        target_w = 1920
        aspect = pixmap.width() / pixmap.height()
        target_h = int(target_w / aspect)
        
        # Scale background to fit our normalized design canvas
        scaled_bg = pixmap.scaled(target_w, target_h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

        if is_new:
            self.bg_pixmap_item = QGraphicsPixmapItem(scaled_bg)
            self.scene.addItem(self.bg_pixmap_item)
            self.bg_pixmap_item.setZValue(-1)
        else:
            self.bg_pixmap_item.setPixmap(scaled_bg)
        
        self.scene.setSceneRect(0, 0, target_w, target_h)
        if is_new:
            self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
        
        # Inform HUDManager of our normalized reference dimensions
        self.hud_manager.view_width = target_w
        self.hud_manager.view_height = target_h

    def load_skin_dialog(self):
        initial_dir = str(Path(self.last_skin_path).parent) if self.last_skin_path else ""
        path, _ = QFileDialog.getOpenFileName(self, "Select PNG Skin", initial_dir, "PNG (*.png)")
        if path:
            self.hud_manager.load_skin(path, x_pct=0.1, y_pct=0.1, scale=0.5)
            self.last_skin_path = str(path)
            self.settings.setValue("last_skin_path", self.last_skin_path)

    def load_package_dialog(self):
        initial_dir = str(Path(self.last_hud_path).parent) if self.last_hud_path else ""
        path, _ = QFileDialog.getOpenFileName(self, "Load HUD Package", initial_dir, "ZIP HUD Package (*.zip)")
        if not path:
            return
        
        self.last_hud_path = str(path)
        self.settings.setValue("last_hud_path", self.last_hud_path)

        # Extract to a temp directory
        tmp_dir = tempfile.mkdtemp(prefix="hud_pkg_")
        try:
            with zipfile.ZipFile(path, 'r') as zip_ref:
                zip_ref.extractall(tmp_dir)
            
            layout_path = Path(tmp_dir) / "hud_layout.json"
            if not layout_path.exists():
                print("Error: Package missing hud_layout.json")
                shutil.rmtree(tmp_dir)
                return

            with open(layout_path, 'r') as f:
                layout = json.load(f)
            
            # Resolve the skin path relative to the extracted directory
            hud_skin = layout.get("hud_skin", {})
            skin_rel_path = hud_skin.get("path")
            if skin_rel_path:
                skin_abs_path = str(Path(tmp_dir) / skin_rel_path)
                hud_skin["path"] = skin_abs_path
            
            self.hud_manager.load_layout(layout)
            print(f"Loaded HUD package from {path}")
            
            # Immediately refresh data on the HUD
            self.sync_data_to_frame(self.time_slider.value() / self.video_fps)

            # Note: We don't rmtree here because the HUDManager might need the skin file path
            # However, we should track it for cleanup on window close.
            if not hasattr(self, 'temp_dirs'): self.temp_dirs = []
            self.temp_dirs.append(tmp_dir)
        except Exception as e:
            print(f"Error loading HUD package: {e}")
            if os.path.exists(tmp_dir):
                shutil.rmtree(tmp_dir)

    def save_layout_dialog(self):
        if not self.hud_manager or not self.hud_manager.skin_item:
            print("No skin loaded. Cannot save HUD package.")
            return

        initial_dir = str(Path(self.last_hud_path).parent) if self.last_hud_path else ""
        default_file = os.path.join(initial_dir, "hud_package.zip") if initial_dir else "hud_package.zip"
        
        path, _ = QFileDialog.getSaveFileName(self, "Save HUD Package", default_file, "ZIP Archive (*.zip)")
        if not path:
            return

        if not path.endswith(".zip"):
            path += ".zip"
        
        self.last_hud_path = str(path)
        self.settings.setValue("last_hud_path", self.last_hud_path)

        try:
            layout = self.hud_manager.get_layout_json()
            hud_skin = layout.get("hud_skin", {})
            is_shape = hud_skin.get("type") == "shape"
            
            # Use getattr to safely get path from HUDSkinItem or HUDShapeItem
            skin_path_val = getattr(self.hud_manager.skin_item, 'path', None)
            skin_path = Path(skin_path_val) if skin_path_val else None
            
            if not is_shape and skin_path:
                # Use relative path in JSON for the zip archive
                hud_skin["path"] = skin_path.name

            with tempfile.TemporaryDirectory() as tmpdir:
                json_path = os.path.join(tmpdir, "hud_layout.json")
                with open(json_path, 'w') as f:
                    json.dump(layout, f, indent=2)
                
                # Create ZIP
                with zipfile.ZipFile(path, "w") as zip_file:
                    zip_file.write(json_path, arcname="hud_layout.json")
                    if not is_shape and skin_path and skin_path.exists():
                        # Copy and write skin image
                        tmp_skin_path = os.path.join(tmpdir, skin_path.name)
                        shutil.copy2(skin_path, tmp_skin_path)
                        zip_file.write(tmp_skin_path, arcname=skin_path.name)
            
            print(f"Saved HUD package to {path}")
        except Exception as e:
            print(f"Error saving HUD package: {e}")

    def show_waypoint_data_dialog(self):
        """Opens a window showing the raw data for the current waypoint."""
        if not self.current_dive:
            print("No dive log loaded.")
            return

        # Get current waypoint
        frame_idx = self.time_slider.value()
        seconds = frame_idx / self.video_fps
        target_ts = self.video_creation_date + timedelta(hours=self.tz_spin.value(), seconds=seconds)
        
        wp = None
        for w in self.current_dive.waypoints:
            if w.timestamp >= target_ts:
                wp = w
                break
        
        if not wp:
            print("No waypoint data for current frame.")
            return

        # Format data as JSON for pretty display
        data_json = wp.model_dump_json(indent=4)
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Current Waypoint Raw Data")
        dialog.resize(600, 800)
        layout = QVBoxLayout(dialog)
        
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText(data_json)
        # Use monospace font for JSON
        font = QFont("Courier New" if sys.platform == "win32" else "Menlo")
        font.setStyleHint(QFont.Monospace)
        text_edit.setFont(font)
        
        layout.addWidget(text_edit)
        
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(dialog.accept)
        layout.addWidget(btn_close)

        dialog.exec()

    def closeEvent(self, event):
        """Cleanup temporary directories on close."""
        if hasattr(self, 'temp_dirs'):
            for d in self.temp_dirs:
                if os.path.exists(d):
                    try:
                        shutil.rmtree(d)
                    except:
                        pass
        super().closeEvent(event)

import multiprocessing

def main():
    if "--multiprocessing-fork" in sys.argv:
        return
    app = QApplication(sys.argv)
    window = HUDDesignerWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
