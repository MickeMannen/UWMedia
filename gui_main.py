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
    QSpinBox, QListWidget, QListWidgetItem
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap, QColor, QFont, QPainter, QImage
from gui.hud_manager import HUDManager
from gui.hud_controls import HUDControls
from models.manager import DiveManager
from parsers.shearwater import ShearwaterParser
from parsers.garmin import GarminParser
from metadata.exif import MetadataHandler
from models.dive import Waypoint

class HUDDesignerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("UWMedia HUD Designer & Sync")
        self.resize(1600, 900)

        # State
        self.video_cap = None
        self.bg_pixmap_item = None
        self.dive_manager = DiveManager()
        self.current_dive = None
        self.video_creation_date = None
        self.video_fps = 30.0

        # Central Widget
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)

        # Left Column: Canvas + Slider
        self.canvas_layout = QVBoxLayout()
        
        self.scene = QGraphicsScene(0, 0, 1920, 1080)
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setBackgroundBrush(Qt.black)
        
        self.canvas_layout.addWidget(self.view)
        
        # Video Slider
        self.slider_layout = QHBoxLayout()
        self.time_slider = QSlider(Qt.Horizontal)
        self.time_slider.setEnabled(False)
        self.time_slider.valueChanged.connect(self.on_slider_moved)
        self.time_label = QLabel("00:00:00")
        self.data_label = QLabel("Depth: -- | Temp: --")
        
        self.slider_layout.addWidget(self.time_slider)
        self.slider_layout.addWidget(self.time_label)
        self.canvas_layout.addLayout(self.slider_layout)
        self.canvas_layout.addWidget(self.data_label)
        
        self.main_layout.addLayout(self.canvas_layout, stretch=4)

        # Right Column: Controls Panel
        self.controls_scroll = QWidget()
        self.controls_layout = QVBoxLayout(self.controls_scroll)
        
        # 1. Background & Logs
        bg_box = QGroupBox("1. Background & Logs")
        bg_form = QFormLayout(bg_box)
        
        self.btn_load_bg = QPushButton("Load Video/Photo")
        self.btn_load_bg.clicked.connect(self.load_background_dialog)
        
        self.btn_load_logs = QPushButton("Select Log Directory")
        self.btn_load_logs.clicked.connect(self.load_log_dir_dialog)
        
        self.tz_spin = QSpinBox()
        self.tz_spin.setRange(-24, 24)
        self.tz_spin.setValue(0)
        self.tz_spin.setSuffix(" hours")
        self.tz_spin.valueChanged.connect(self.match_dive_to_media)
        
        bg_form.addRow(self.btn_load_bg)
        bg_form.addRow(self.btn_load_logs)
        bg_form.addRow("TZ Offset (Log vs Media):", self.tz_spin)
        self.controls_layout.addWidget(bg_box)

        # 2. HUD Core (Manager)
        self.hud_manager = HUDManager(self.scene, 1920, 1080)
        self.hud_controls = HUDControls(self.hud_manager)
        self.controls_layout.addWidget(self.hud_controls)

        # 3. Telemetry Fields List
        fields_box = QGroupBox("3. Available Fields")
        fields_layout = QVBoxLayout(fields_box)
        self.fields_list = QListWidget()

        # Dynamically get fields from Waypoint class
        wp_fields = list(Waypoint.model_fields.keys())
        for f in sorted(wp_fields):
            item = QListWidgetItem(f)
            self.fields_list.addItem(item)

        self.fields_list.itemDoubleClicked.connect(self.add_field)
        fields_layout.addWidget(QLabel("Double-click to add:"))
        fields_layout.addWidget(self.fields_list)
        self.controls_layout.addWidget(fields_box)

        
        # 4. HUD Actions
        action_box = QGroupBox("4. HUD Actions")
        action_layout = QVBoxLayout(action_box)
        self.btn_load_skin = QPushButton("Load PNG Skin")
        self.btn_load_skin.clicked.connect(self.load_skin_dialog)
        self.btn_save_layout = QPushButton("Save HUD Package (.zip)")
        self.btn_save_layout.clicked.connect(self.save_layout_dialog)
        
        action_layout.addWidget(self.btn_load_skin)
        action_layout.addWidget(self.btn_save_layout)
        self.controls_layout.addWidget(action_box)
        
        self.controls_layout.addStretch()
        self.main_layout.addWidget(self.controls_scroll, stretch=1)

    def add_field(self, item):
        field = item.text()
        self.hud_manager.add_telemetry_field(field, 0.5, 0.5)

    def load_log_dir_dialog(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Dive Log Directory")
        if not dir_path: return
        
        self.dive_manager = DiveManager() # Reset manager
        p_dir = Path(dir_path)
        shearwater = ShearwaterParser()
        garmin = GarminParser()
        
        count = 0
        for path in p_dir.iterdir():
            if path.suffix == ".uddf": 
                self.dive_manager.add_dives(shearwater.parse(path))
                count += 1
            elif path.suffix == ".fit":
                self.dive_manager.add_dives(garmin.parse(path))
                count += 1
        
        print(f"Loaded {count} log files from {p_dir.name}")
        self.match_dive_to_media()

    def load_background_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Background", "", "Media (*.mp4 *.mov *.jpg *.png)")
        if not path: return
        
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
        
        self.match_dive_to_media()

    def match_dive_to_media(self):
        if self.video_creation_date:
            # Apply TZ offset to the media date to match log times
            adjusted_date = self.video_creation_date + timedelta(hours=self.tz_spin.value())
            self.current_dive = self.dive_manager.find_dive_for_timestamp(adjusted_date)
            
            if self.current_dive:
                print(f"Matched dive! Offset: {self.tz_spin.value()}h")
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
            self.hud_manager.update_telemetry_data(wp)
        else:
            self.data_label.setText("Out of dive range.")

    def set_bg_pixmap(self, pixmap):
        if not self.bg_pixmap_item:
            self.bg_pixmap_item = QGraphicsPixmapItem(pixmap)
            self.scene.addItem(self.bg_pixmap_item)
            self.bg_pixmap_item.setZValue(-1)
        else:
            self.bg_pixmap_item.setPixmap(pixmap)
        
        self.scene.setSceneRect(pixmap.rect())
        self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
        self.hud_manager.view_width = pixmap.width()
        self.hud_manager.view_height = pixmap.height()

    def load_skin_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select PNG Skin", "", "PNG (*.png)")
        if path: self.hud_manager.load_skin(path, x_pct=0.1, y_pct=0.1, scale=0.5)

    def save_layout_dialog(self):
        if not self.hud_manager.skin_item:
            print("No skin loaded. Cannot save HUD package.")
            return

        path, _ = QFileDialog.getSaveFileName(self, "Save HUD Package", "hud_package.zip", "ZIP Archive (*.zip)")
        if path:
            layout = self.hud_manager.get_layout_json()
            skin_path = Path(self.hud_manager.skin_item.path)
            
            # Use relative path in JSON for the zip archive
            layout["hud_skin"]["path"] = skin_path.name

            with tempfile.TemporaryDirectory() as tmpdir:
                json_path = os.path.join(tmpdir, "hud_layout.json")
                with open(json_path, 'w') as f:
                    json.dump(layout, f, indent=2)
                
                # Copy skin to temp dir
                tmp_skin_path = os.path.join(tmpdir, skin_path.name)
                shutil.copy2(skin_path, tmp_skin_path)
                
                # Create ZIP
                with zipfile.ZipFile(path, "w") as zip_file:
                    zip_file.write(json_path, arcname="hud_layout.json")
                    zip_file.write(tmp_skin_path, arcname=skin_path.name)
            print(f"Saved HUD package to {path}")

def main():
    app = QApplication(sys.argv)
    window = HUDDesignerWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
