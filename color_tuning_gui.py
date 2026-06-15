import sys
import os
import yaml
import cv2
import numpy as np
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QSlider, QPushButton,
    QComboBox, QScrollArea, QGroupBox, QFormLayout, QHBoxLayout, QVBoxLayout,
    QFileDialog, QTabWidget, QSizePolicy
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QImage
from ffmpeg.color_new import ColorCorrectionEngine

class ColorTuningApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("UWMedia Underwater Color Tuning Tool")
        self.resize(1200, 800)
        
        # Paths & Configurations
        self.color_name = "color.yaml"
        self.yaml_path = self.locate_yaml()
        self.config_data = {}
        self.default_profile_data = {}
        self.current_profile = "default"
        
        # Image state
        self.orig_image = None  # Full res original
        self.target_image = None  # Full res target
        self.resized_orig = None  # Resized original BGR (for fast preview)
        self.resized_target = None  # Resized target BGR (for display)
        
        # Color engine
        # We pass None for ffmpeg_tool since we only use apply_filter & get_filter_matrix on local frames
        self.engine = ColorCorrectionEngine(ffmpeg_tool=None, color_profile="default")
        
        # Load configuration
        self.load_yaml()
        
        # Setup UI
        self.setup_ui()
        
        # Load initial profile slider values
        self.block_updates = True
        self.update_sliders_from_profile()
        self.block_updates = False
        
        # Try loading default sample if it exists in release_test
        self.auto_load_default_sample()

    def locate_yaml(self):
        cwd_path = Path.cwd() / self.color_name
        if getattr(sys, 'frozen', False):
            app_path = Path(sys.executable).parent / self.color_name
        else:
            app_path = Path(__file__).parent / self.color_name
            
        if cwd_path.exists():
            return cwd_path
        return app_path

    def load_yaml(self):
        if self.yaml_path.exists():
            with open(self.yaml_path, 'r') as f:
                self.config_data = yaml.safe_load(f) or {}
            print(f"Loaded config from: {self.yaml_path}")
        else:
            print(f"Warning: {self.color_name} not found. Starting with empty configuration.")
            self.config_data = {"default": {}}
        
        # Keep copy of default profile values for the reset buttons
        self.default_profile_data = self.config_data.get("default", {})

    def save_yaml(self):
        # Update current profile from sliders
        profile = self.config_data.get(self.current_profile, {})
        
        # HSV Shifting Bins
        shifts = []
        sats = []
        vals = []
        for i in range(12):
            shifts.append(float(self.bin_shift_sliders[i].value()))
            sats.append(float(self.bin_sat_sliders[i].value() / 100.0))
            vals.append(float(self.bin_val_sliders[i].value() / 100.0))
            
        profile["bin_shifts"] = shifts
        profile["bin_sats"] = sats
        profile["bin_vals"] = vals
        
        # CLAHE
        profile["clahe_blend"] = float(self.slider_clahe_blend.value() / 100.0)
        profile["clahe_clip_limit"] = float(self.slider_clahe_clip.value() / 10.0)
        profile["clahe_grid_size"] = [
            int(self.slider_clahe_grid_x.value()),
            int(self.slider_clahe_grid_y.value())
        ]
        
        # Denoise
        profile["denoise_type"] = self.combo_denoise_type.currentText()
        profile["denoise_d"] = int(self.slider_denoise_d.value())
        profile["denoise_sigma_color"] = float(self.slider_denoise_sigma_c.value())
        profile["denoise_sigma_space"] = float(self.slider_denoise_sigma_s.value())
        
        # Red Boost
        profile["red_boost_alpha"] = float(self.slider_red_boost.value() / 100.0)
        
        # WB Gains
        profile["wb_red_gain"] = float(self.slider_wb_red.value() / 100.0)
        profile["wb_green_gain"] = float(self.slider_wb_green.value() / 100.0)
        profile["wb_blue_gain"] = float(self.slider_wb_blue.value() / 100.0)
        
        # Global Saturation
        profile["global_saturation_factor"] = float(self.slider_global_sat.value() / 100.0)
        
        # Sharpening
        profile["sharpen_type"] = self.combo_sharpen_type.currentText()
        profile["sharpen_amount"] = float(self.slider_sharpen_amt.value() / 100.0)
        profile["sharpen_radius"] = float(self.slider_sharpen_rad.value() / 10.0)
        
        self.config_data[self.current_profile] = profile
        
        try:
            with open(self.yaml_path, 'w') as f:
                yaml.dump(self.config_data, f, default_flow_style=False, sort_keys=False)
            print(f"Saved configuration to: {self.yaml_path}")
            # Update cache of defaults if we saved default profile
            if self.current_profile == "default":
                self.default_profile_data = self.config_data.get("default", {})
        except Exception as e:
            print(f"Error saving yaml: {e}")

    def setup_ui(self):
        # Apply dark stylesheet
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1a1a1e;
                color: #e2e2e7;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
            QGroupBox {
                border: 1px solid #2e2e38;
                border-radius: 8px;
                margin-top: 14px;
                padding-top: 14px;
                font-weight: bold;
                color: #3b82f6;
                background-color: #202026;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 12px;
                padding: 0 5px;
            }
            QLabel {
                color: #e2e2e7;
            }
            QSlider::groove:horizontal {
                border: 1px solid #2e2e38;
                height: 5px;
                background: #121214;
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #3b82f6;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                border: 1px solid #3b82f6;
                width: 12px;
                height: 12px;
                margin-top: -4px;
                border-radius: 6px;
            }
            QPushButton {
                background-color: #3b82f6;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
            QPushButton:pressed {
                background-color: #1d4ed8;
            }
            QComboBox {
                background-color: #2c2c35;
                border: 1px solid #2e2e38;
                border-radius: 5px;
                padding: 3px 6px;
                color: white;
            }
            QScrollArea {
                border: none;
                background-color: #1a1a1e;
            }
            QTabWidget::panel {
                border: 1px solid #2e2e38;
                background: #202026;
                border-radius: 6px;
            }
            QTabBar::tab {
                background: #272730;
                border: 1px solid #2e2e38;
                padding: 5px 10px;
                color: #a1a1aa;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background: #202026;
                color: #3b82f6;
                border-bottom-color: #202026;
                font-weight: bold;
            }
        """)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # Left Side - Image Preview Area
        left_layout = QVBoxLayout()
        main_layout.addLayout(left_layout, stretch=3)
        
        # Top toolbar
        toolbar = QHBoxLayout()
        left_layout.addLayout(toolbar)
        
        self.btn_load_orig = QPushButton("Load Original Image")
        self.btn_load_orig.clicked.connect(self.choose_original)
        toolbar.addWidget(self.btn_load_orig)
        
        self.btn_load_target = QPushButton("Load Target Image")
        self.btn_load_target.clicked.connect(self.choose_target)
        toolbar.addWidget(self.btn_load_target)
        
        toolbar.addSpacing(20)
        
        lbl_profile = QLabel("Profile:")
        lbl_profile.setStyleSheet("font-weight: bold;")
        toolbar.addWidget(lbl_profile)
        
        self.combo_profile = QComboBox()
        self.combo_profile.addItems(["default", "vivid", "subtle"])
        self.combo_profile.currentTextChanged.connect(self.change_profile)
        toolbar.addWidget(self.combo_profile)
        
        toolbar.addStretch()
        
        self.btn_save = QPushButton("Save to color.yaml")
        self.btn_save.setStyleSheet("background-color: #10b981;") # Emerald Green
        self.btn_save.clicked.connect(self.save_yaml)
        toolbar.addWidget(self.btn_save)
        
        # Image Grid (Target vs Result)
        grid_layout = QHBoxLayout()
        left_layout.addLayout(grid_layout)
        
        # Target Image View (Left)
        target_v = QVBoxLayout()
        target_v.addWidget(QLabel("<b>Target (Manual Edit)</b>"))
        self.lbl_target = QLabel("No target image loaded")
        self.lbl_target.setAlignment(Qt.AlignCenter)
        self.lbl_target.setStyleSheet("background-color: #0f0f12; border: 1px solid #2e2e38; border-radius: 6px;")
        self.lbl_target.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        target_v.addWidget(self.lbl_target)
        grid_layout.addLayout(target_v)
        
        # Result Image View (Right)
        result_v = QVBoxLayout()
        result_v.addWidget(QLabel("<b>Result (Color Correction Engine)</b>"))
        self.lbl_result = QLabel("No preview available")
        self.lbl_result.setAlignment(Qt.AlignCenter)
        self.lbl_result.setStyleSheet("background-color: #0f0f12; border: 1px solid #2e2e38; border-radius: 6px;")
        self.lbl_result.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        result_v.addWidget(self.lbl_result)
        grid_layout.addLayout(result_v)

        # Right Side - Control Panel (Sliders)
        control_scroll = QScrollArea()
        control_scroll.setWidgetResizable(True)
        control_scroll.setFixedWidth(420)
        main_layout.addWidget(control_scroll, stretch=1)
        
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(5, 5, 5, 5)
        control_scroll.setWidget(scroll_widget)
        
        # 1. Denoise controls
        group_denoise = QGroupBox("1. Denoise")
        denoise_layout = QFormLayout(group_denoise)
        
        self.combo_denoise_type = QComboBox()
        self.combo_denoise_type.addItems(["bilateral", "gaussian", "none"])
        self.combo_denoise_type.currentTextChanged.connect(self.trigger_pipeline_update)
        
        btn_reset_denoise_type = QPushButton("↺")
        btn_reset_denoise_type.setFixedWidth(20)
        btn_reset_denoise_type.setFixedHeight(20)
        btn_reset_denoise_type.setToolTip("Reset to default")
        btn_reset_denoise_type.setStyleSheet("background-color: #2e2e38; padding: 0px; font-size: 11px; color: #a1a1aa;")
        btn_reset_denoise_type.clicked.connect(lambda: self.combo_denoise_type.setCurrentText(self.default_profile_data.get("denoise_type", "bilateral")))
        
        row_denoise_type = QWidget()
        lay_denoise_type = QHBoxLayout(row_denoise_type)
        lay_denoise_type.setContentsMargins(0, 0, 0, 0)
        lay_denoise_type.addWidget(self.combo_denoise_type)
        lay_denoise_type.addWidget(btn_reset_denoise_type)
        
        denoise_layout.addRow("Type:", row_denoise_type)
        
        self.slider_denoise_d, self.lbl_denoise_d = self.create_int_slider(
            1, 15, 5, denoise_layout, "d (Diameter):",
            lambda: self.slider_denoise_d.setValue(int(self.default_profile_data.get("denoise_d", 5)))
        )
        self.slider_denoise_sigma_c, self.lbl_denoise_sigma_c = self.create_int_slider(
            1, 100, 15, denoise_layout, "Sigma Color:",
            lambda: self.slider_denoise_sigma_c.setValue(int(self.default_profile_data.get("denoise_sigma_color", 15.0)))
        )
        self.slider_denoise_sigma_s, self.lbl_denoise_sigma_s = self.create_int_slider(
            1, 100, 15, denoise_layout, "Sigma Space:",
            lambda: self.slider_denoise_sigma_s.setValue(int(self.default_profile_data.get("denoise_sigma_space", 15.0)))
        )
        scroll_layout.addWidget(group_denoise)
        
        # 2. Red Boost
        group_red = QGroupBox("2. Red Channel Boost")
        red_layout = QFormLayout(group_red)
        self.slider_red_boost, self.lbl_red_boost = self.create_float_slider(
            0.0, 3.0, 1.5, 100, red_layout, "Boost Alpha:",
            lambda: self.slider_red_boost.setValue(int(self.default_profile_data.get("red_boost_alpha", 1.5) * 100))
        )
        scroll_layout.addWidget(group_red)
        
        # 3. Gray World WB
        group_wb = QGroupBox("3. Gray World WB Gains")
        wb_layout = QFormLayout(group_wb)
        self.slider_wb_red, self.lbl_wb_red = self.create_float_slider(
            0.0, 1.5, 0.15, 100, wb_layout, "Red WB Gain:",
            lambda: self.slider_wb_red.setValue(int(self.default_profile_data.get("wb_red_gain", 0.15) * 100))
        )
        self.slider_wb_green, self.lbl_wb_green = self.create_float_slider(
            0.0, 1.5, 1.0, 100, wb_layout, "Green WB Gain:",
            lambda: self.slider_wb_green.setValue(int(self.default_profile_data.get("wb_green_gain", 1.0) * 100))
        )
        self.slider_wb_blue, self.lbl_wb_blue = self.create_float_slider(
            0.0, 1.5, 1.0, 100, wb_layout, "Blue WB Gain:",
            lambda: self.slider_wb_blue.setValue(int(self.default_profile_data.get("wb_blue_gain", 1.0) * 100))
        )
        scroll_layout.addWidget(group_wb)
        
        # 4. CLAHE
        group_clahe = QGroupBox("4. CLAHE De-haze")
        clahe_layout = QFormLayout(group_clahe)
        self.slider_clahe_blend, self.lbl_clahe_blend = self.create_float_slider(
            0.0, 1.0, 0.3, 100, clahe_layout, "L Blend weight:",
            lambda: self.slider_clahe_blend.setValue(int(self.default_profile_data.get("clahe_blend", 0.3) * 100))
        )
        self.slider_clahe_clip, self.lbl_clahe_clip = self.create_float_slider(
            0.1, 10.0, 1.0, 10, clahe_layout, "Clip Limit:",
            lambda: self.slider_clahe_clip.setValue(int(self.default_profile_data.get("clahe_clip_limit", 1.0) * 10))
        )
        self.slider_clahe_grid_x, self.lbl_clahe_grid_x = self.create_int_slider(
            1, 32, 8, clahe_layout, "Grid size X:",
            lambda: self.slider_clahe_grid_x.setValue(int(self.default_profile_data.get("clahe_grid_size", [8, 8])[0]))
        )
        self.slider_clahe_grid_y, self.lbl_clahe_grid_y = self.create_int_slider(
            1, 32, 8, clahe_layout, "Grid size Y:",
            lambda: self.slider_clahe_grid_y.setValue(int(self.default_profile_data.get("clahe_grid_size", [8, 8])[1]))
        )
        scroll_layout.addWidget(group_clahe)
        
        # 5. Saturation & HSV shifting (Tab widget for 12 bins)
        group_hsv = QGroupBox("5. Selective Saturation & HSV")
        hsv_box_layout = QVBoxLayout(group_hsv)
        
        self.slider_global_sat, self.lbl_global_sat = self.create_float_slider_in_layout(
            0.0, 3.0, 1.15, 100, hsv_box_layout, "Global Saturation Factor:",
            lambda: self.slider_global_sat.setValue(int(self.default_profile_data.get("global_saturation_factor", 1.15) * 100))
        )
        
        hsv_tabs = QTabWidget()
        hsv_box_layout.addWidget(hsv_tabs)
        
        tab_shifts = QWidget()
        tab_sats = QWidget()
        tab_vals = QWidget()
        
        hsv_tabs.addTab(tab_shifts, "Hue Shifts")
        hsv_tabs.addTab(tab_sats, "Sats")
        hsv_tabs.addTab(tab_vals, "Vals")
        
        # Lay out tabs
        form_shifts = QFormLayout(tab_shifts)
        form_sats = QFormLayout(tab_sats)
        form_vals = QFormLayout(tab_vals)
        
        self.bin_shift_sliders = []
        self.bin_shift_labels = []
        
        self.bin_sat_sliders = []
        self.bin_sat_labels = []
        
        self.bin_val_sliders = []
        self.bin_val_labels = []
        
        bin_names = [
            "0 (Red/Org 15°)", "1 (Yellow 45°)", "2 (Lime 75°)", "3 (Green 105°)",
            "4 (Cyan-G 135°)", "5 (Cyan 165°)", "6 (Blue-C 195°)", "7 (Blue 225°)",
            "8 (D-Blue 255°)", "9 (Violet 285°)", "10 (Magenta 315°)", "11 (Pink 345°)"
        ]
        
        for i in range(12):
            # Shifts (-180 to 180 deg)
            s_shift, l_shift = self.create_int_slider_raw(
                -180, 180, 0, form_shifts, f"Bin {bin_names[i]}:",
                lambda checked=False, idx=i: self.bin_shift_sliders[idx].setValue(int(self.default_profile_data.get("bin_shifts", [0]*12)[idx]))
            )
            self.bin_shift_sliders.append(s_shift)
            self.bin_shift_labels.append(l_shift)
            
            # Sats (0.0 to 3.0)
            s_sat, l_sat = self.create_float_slider_raw(
                0.0, 3.0, 1.0, 100, form_sats, f"Bin {bin_names[i]}:",
                lambda checked=False, idx=i: self.bin_sat_sliders[idx].setValue(int(self.default_profile_data.get("bin_sats", [1.0]*12)[idx] * 100))
            )
            self.bin_sat_sliders.append(s_sat)
            self.bin_sat_labels.append(l_sat)
            
            # Vals (0.0 to 2.0)
            s_val, l_val = self.create_float_slider_raw(
                0.0, 2.0, 1.0, 100, form_vals, f"Bin {bin_names[i]}:",
                lambda checked=False, idx=i: self.bin_val_sliders[idx].setValue(int(self.default_profile_data.get("bin_vals", [1.0]*12)[idx] * 100))
            )
            self.bin_val_sliders.append(s_val)
            self.bin_val_labels.append(l_val)
            
        scroll_layout.addWidget(group_hsv)
        
        # 6. Sharpen
        group_sharpen = QGroupBox("6. Sharpening")
        sharpen_layout = QFormLayout(group_sharpen)
        
        self.combo_sharpen_type = QComboBox()
        self.combo_sharpen_type.addItems(["kernel", "unsharp", "none"])
        self.combo_sharpen_type.currentTextChanged.connect(self.trigger_pipeline_update)
        
        btn_reset_sharpen_type = QPushButton("↺")
        btn_reset_sharpen_type.setFixedWidth(20)
        btn_reset_sharpen_type.setFixedHeight(20)
        btn_reset_sharpen_type.setToolTip("Reset to default")
        btn_reset_sharpen_type.setStyleSheet("background-color: #2e2e38; padding: 0px; font-size: 11px; color: #a1a1aa;")
        btn_reset_sharpen_type.clicked.connect(lambda: self.combo_sharpen_type.setCurrentText(self.default_profile_data.get("sharpen_type", "kernel")))
        
        row_sharpen_type = QWidget()
        lay_sharpen_type = QHBoxLayout(row_sharpen_type)
        lay_sharpen_type.setContentsMargins(0, 0, 0, 0)
        lay_sharpen_type.addWidget(self.combo_sharpen_type)
        lay_sharpen_type.addWidget(btn_reset_sharpen_type)
        
        sharpen_layout.addRow("Type:", row_sharpen_type)
        
        self.slider_sharpen_amt, self.lbl_sharpen_amt = self.create_float_slider(
            0.0, 2.0, 0.25, 100, sharpen_layout, "Amount:",
            lambda: self.slider_sharpen_amt.setValue(int(self.default_profile_data.get("sharpen_amount", 0.25) * 100))
        )
        self.slider_sharpen_rad, self.lbl_sharpen_rad = self.create_float_slider(
            0.1, 5.0, 1.0, 10, sharpen_layout, "Radius:",
            lambda: self.slider_sharpen_rad.setValue(int(self.default_profile_data.get("sharpen_radius", 1.0) * 10))
        )
        scroll_layout.addWidget(group_sharpen)
        
        scroll_layout.addStretch()

    def create_int_slider(self, min_val, max_val, default, form_layout, label_text, reset_callback):
        label_val = QLabel(str(default))
        label_val.setStyleSheet("font-weight: bold; color: #a1a1aa; min-width: 25px;")
        
        slider = QSlider(Qt.Horizontal)
        slider.setMinimum(min_val)
        slider.setMaximum(max_val)
        slider.setValue(default)
        
        btn_reset = QPushButton("↺")
        btn_reset.setFixedWidth(20)
        btn_reset.setFixedHeight(20)
        btn_reset.setToolTip("Reset to default")
        btn_reset.setStyleSheet("background-color: #2e2e38; padding: 0px; font-size: 11px; color: #a1a1aa;")
        btn_reset.clicked.connect(reset_callback)
        
        def update_val(val):
            label_val.setText(str(val))
            self.trigger_pipeline_update()
            
        slider.valueChanged.connect(update_val)
        
        row_widget = QWidget()
        row_lay = QHBoxLayout(row_widget)
        row_lay.setContentsMargins(0, 0, 0, 0)
        row_lay.addWidget(slider)
        row_lay.addWidget(label_val)
        row_lay.addWidget(btn_reset)
        
        form_layout.addRow(label_text, row_widget)
        return slider, label_val

    def create_int_slider_raw(self, min_val, max_val, default, form_layout, label_text, reset_callback):
        label_val = QLabel(str(default))
        label_val.setStyleSheet("font-weight: bold; color: #a1a1aa; min-width: 35px;")
        
        slider = QSlider(Qt.Horizontal)
        slider.setMinimum(min_val)
        slider.setMaximum(max_val)
        slider.setValue(default)
        
        btn_reset = QPushButton("↺")
        btn_reset.setFixedWidth(20)
        btn_reset.setFixedHeight(20)
        btn_reset.setToolTip("Reset to default")
        btn_reset.setStyleSheet("background-color: #2e2e38; padding: 0px; font-size: 11px; color: #a1a1aa;")
        btn_reset.clicked.connect(reset_callback)
        
        def update_val(val):
            label_val.setText(str(val))
            self.trigger_pipeline_update()
            
        slider.valueChanged.connect(update_val)
        
        row_widget = QWidget()
        row_lay = QHBoxLayout(row_widget)
        row_lay.setContentsMargins(0, 0, 0, 0)
        row_lay.addWidget(slider)
        row_lay.addWidget(label_val)
        row_lay.addWidget(btn_reset)
        
        form_layout.addRow(label_text, row_widget)
        return slider, label_val

    def create_float_slider(self, min_val, max_val, default, multiplier, form_layout, label_text, reset_callback):
        label_val = QLabel(f"{default:.2f}")
        label_val.setStyleSheet("font-weight: bold; color: #a1a1aa; min-width: 35px;")
        
        slider = QSlider(Qt.Horizontal)
        slider.setMinimum(int(min_val * multiplier))
        slider.setMaximum(int(max_val * multiplier))
        slider.setValue(int(default * multiplier))
        
        btn_reset = QPushButton("↺")
        btn_reset.setFixedWidth(20)
        btn_reset.setFixedHeight(20)
        btn_reset.setToolTip("Reset to default")
        btn_reset.setStyleSheet("background-color: #2e2e38; padding: 0px; font-size: 11px; color: #a1a1aa;")
        btn_reset.clicked.connect(reset_callback)
        
        def update_val(val):
            val_f = val / float(multiplier)
            label_val.setText(f"{val_f:.2f}")
            self.trigger_pipeline_update()
            
        slider.valueChanged.connect(update_val)
        
        row_widget = QWidget()
        row_lay = QHBoxLayout(row_widget)
        row_lay.setContentsMargins(0, 0, 0, 0)
        row_lay.addWidget(slider)
        row_lay.addWidget(label_val)
        row_lay.addWidget(btn_reset)
        
        form_layout.addRow(label_text, row_widget)
        return slider, label_val

    def create_float_slider_raw(self, min_val, max_val, default, multiplier, form_layout, label_text, reset_callback):
        label_val = QLabel(f"{default:.2f}")
        label_val.setStyleSheet("font-weight: bold; color: #a1a1aa; min-width: 35px;")
        
        slider = QSlider(Qt.Horizontal)
        slider.setMinimum(int(min_val * multiplier))
        slider.setMaximum(int(max_val * multiplier))
        slider.setValue(int(default * multiplier))
        
        btn_reset = QPushButton("↺")
        btn_reset.setFixedWidth(20)
        btn_reset.setFixedHeight(20)
        btn_reset.setToolTip("Reset to default")
        btn_reset.setStyleSheet("background-color: #2e2e38; padding: 0px; font-size: 11px; color: #a1a1aa;")
        btn_reset.clicked.connect(reset_callback)
        
        def update_val(val):
            val_f = val / float(multiplier)
            label_val.setText(f"{val_f:.2f}")
            self.trigger_pipeline_update()
            
        slider.valueChanged.connect(update_val)
        
        row_widget = QWidget()
        row_lay = QHBoxLayout(row_widget)
        row_lay.setContentsMargins(0, 0, 0, 0)
        row_lay.addWidget(slider)
        row_lay.addWidget(label_val)
        row_lay.addWidget(btn_reset)
        
        form_layout.addRow(label_text, row_widget)
        return slider, label_val

    def create_float_slider_in_layout(self, min_val, max_val, default, multiplier, layout, label_text, reset_callback):
        container = QWidget()
        lay = QHBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
        
        lbl = QLabel(label_text)
        label_val = QLabel(f"{default:.2f}")
        label_val.setStyleSheet("font-weight: bold; color: #a1a1aa; min-width: 35px;")
        
        slider = QSlider(Qt.Horizontal)
        slider.setMinimum(int(min_val * multiplier))
        slider.setMaximum(int(max_val * multiplier))
        slider.setValue(int(default * multiplier))
        
        btn_reset = QPushButton("↺")
        btn_reset.setFixedWidth(20)
        btn_reset.setFixedHeight(20)
        btn_reset.setToolTip("Reset to default")
        btn_reset.setStyleSheet("background-color: #2e2e38; padding: 0px; font-size: 11px; color: #a1a1aa;")
        btn_reset.clicked.connect(reset_callback)
        
        def update_val(val):
            val_f = val / float(multiplier)
            label_val.setText(f"{val_f:.2f}")
            self.trigger_pipeline_update()
            
        slider.valueChanged.connect(update_val)
        
        lay.addWidget(lbl)
        lay.addWidget(slider)
        lay.addWidget(label_val)
        lay.addWidget(btn_reset)
        
        layout.addWidget(container)
        return slider, label_val

    def change_profile(self, profile_name):
        self.current_profile = profile_name
        self.block_updates = True
        self.update_sliders_from_profile()
        self.block_updates = False
        self.trigger_pipeline_update()

    def update_sliders_from_profile(self):
        profile = self.config_data.get(self.current_profile, {})
        if not profile:
            return
            
        # HSV Shifts
        shifts = profile.get("bin_shifts", [0.0]*12)
        sats = profile.get("bin_sats", [1.0]*12)
        vals = profile.get("bin_vals", [1.0]*12)
        
        for i in range(12):
            self.bin_shift_sliders[i].setValue(int(shifts[i]))
            self.bin_shift_labels[i].setText(str(int(shifts[i])))
            
            self.bin_sat_sliders[i].setValue(int(sats[i] * 100))
            self.bin_sat_labels[i].setText(f"{sats[i]:.2f}")
            
            self.bin_val_sliders[i].setValue(int(vals[i] * 100))
            self.bin_val_labels[i].setText(f"{vals[i]:.2f}")
            
        # CLAHE
        c_blend = profile.get("clahe_blend", 0.3)
        self.slider_clahe_blend.setValue(int(c_blend * 100))
        self.lbl_clahe_blend.setText(f"{c_blend:.2f}")
        
        c_clip = profile.get("clahe_clip_limit", 1.0)
        self.slider_clahe_clip.setValue(int(c_clip * 10))
        self.lbl_clahe_clip.setText(f"{c_clip:.2f}")
        
        grid = profile.get("clahe_grid_size", [8, 8])
        self.slider_clahe_grid_x.setValue(int(grid[0]))
        self.lbl_clahe_grid_x.setText(str(grid[0]))
        self.slider_clahe_grid_y.setValue(int(grid[1]))
        self.lbl_clahe_grid_y.setText(str(grid[1]))
        
        # Denoise
        d_type = profile.get("denoise_type", "bilateral")
        self.combo_denoise_type.setCurrentText(d_type)
        
        d_d = profile.get("denoise_d", 5)
        self.slider_denoise_d.setValue(int(d_d))
        self.lbl_denoise_d.setText(str(d_d))
        
        d_sig_c = profile.get("denoise_sigma_color", 15.0)
        self.slider_denoise_sigma_c.setValue(int(d_sig_c))
        self.lbl_denoise_sigma_c.setText(str(int(d_sig_c)))
        
        d_sig_s = profile.get("denoise_sigma_space", 15.0)
        self.slider_denoise_sigma_s.setValue(int(d_sig_s))
        self.lbl_denoise_sigma_s.setText(str(int(d_sig_s)))
        
        # Red Boost
        r_boost = profile.get("red_boost_alpha", 1.5)
        self.slider_red_boost.setValue(int(r_boost * 100))
        self.lbl_red_boost.setText(f"{r_boost:.2f}")
        
        # WB Gains
        wb_r = profile.get("wb_red_gain", 0.15)
        self.slider_wb_red.setValue(int(wb_r * 100))
        self.lbl_wb_red.setText(f"{wb_r:.2f}")
        
        wb_g = profile.get("wb_green_gain", 1.0)
        self.slider_wb_green.setValue(int(wb_g * 100))
        self.lbl_wb_green.setText(f"{wb_g:.2f}")
        
        wb_b = profile.get("wb_blue_gain", 1.0)
        self.slider_wb_blue.setValue(int(wb_b * 100))
        self.lbl_wb_blue.setText(f"{wb_b:.2f}")
        
        # Global sat
        g_sat = profile.get("global_saturation_factor", 1.15)
        self.slider_global_sat.setValue(int(g_sat * 100))
        self.lbl_global_sat.setText(f"{g_sat:.2f}")
        
        # Sharpen
        s_type = profile.get("sharpen_type", "kernel")
        self.combo_sharpen_type.setCurrentText(s_type)
        
        s_amt = profile.get("sharpen_amount", 0.25)
        self.slider_sharpen_amt.setValue(int(s_amt * 100))
        self.lbl_sharpen_amt.setText(f"{s_amt:.2f}")
        
        s_rad = profile.get("sharpen_radius", 1.0)
        self.slider_sharpen_rad.setValue(int(s_rad * 10))
        self.lbl_sharpen_rad.setText(f"{s_rad:.2f}")

    def choose_original(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Open Original Photo", "test_data/color_correction/", "Images (*.jpg *.jpeg *.png *.JPG *.JPEG *.PNG)")
        if filename:
            self.load_original(filename)
            
            # Automatically try to find target image (e.g. if loaded DSC06641.JPG, look for DSC06641_Edited.JPEG)
            p = Path(filename)
            edited_sibling1 = p.parent / f"{p.stem}_Edited.JPEG"
            edited_sibling2 = p.parent / f"{p.stem}_Edited.jpg"
            edited_sibling3 = p.parent / f"{p.stem}_Edited.JPG"
            
            if edited_sibling1.exists():
                self.load_target(str(edited_sibling1))
            elif edited_sibling2.exists():
                self.load_target(str(edited_sibling2))
            elif edited_sibling3.exists():
                self.load_target(str(edited_sibling3))

    def choose_target(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Open Target Photo", "test_data/color_correction/", "Images (*.jpg *.jpeg *.png *.JPG *.JPEG *.PNG)")
        if filename:
            self.load_target(filename)

    def load_original(self, filepath):
        self.orig_image = cv2.imread(filepath)
        if self.orig_image is not None:
            # Resize for fast interactive processing
            h, w = self.orig_image.shape[:2]
            max_dim = 600
            scale = max_dim / max(h, w)
            target_w = int(w * scale)
            target_h = int(h * scale)
            self.resized_orig = cv2.resize(self.orig_image, (target_w, target_h), interpolation=cv2.INTER_AREA)
            
            self.trigger_pipeline_update()

    def load_target(self, filepath):
        self.target_image = cv2.imread(filepath)
        if self.target_image is not None:
            # Resize to match current display height of resized original
            if self.resized_orig is not None:
                th, tw = self.resized_orig.shape[:2]
                self.resized_target = cv2.resize(self.target_image, (tw, th), interpolation=cv2.INTER_AREA)
            else:
                h, w = self.target_image.shape[:2]
                max_dim = 600
                scale = max_dim / max(h, w)
                self.resized_target = cv2.resize(self.target_image, (int(w*scale), int(h*scale)), interpolation=cv2.INTER_AREA)
                
            rgb = cv2.cvtColor(self.resized_target, cv2.COLOR_BGR2RGB)
            self.show_pixmap(rgb, self.lbl_target)

    def auto_load_default_sample(self):
        # Default sample to load automatically (DSC06641)
        default_file = Path("test_data/color_correction/DSC06641.JPG")
        if default_file.exists():
            self.load_original(str(default_file))
            target_file = Path("test_data/color_correction/DSC06641_Edited.JPEG")
            if target_file.exists():
                self.load_target(str(target_file))

    def trigger_pipeline_update(self):
        if getattr(self, 'block_updates', False) or self.resized_orig is None:
            return
            
        # Update engine fields dynamically from sliders
        # HSV Shifts
        shifts = []
        sats = []
        vals = []
        for i in range(12):
            shifts.append(float(self.bin_shift_sliders[i].value()))
            sats.append(float(self.bin_sat_sliders[i].value() / 100.0))
            vals.append(float(self.bin_val_sliders[i].value() / 100.0))
            
        self.engine.bin_shifts = np.array(shifts) / 2.0
        self.engine.bin_sats = np.array(sats)
        self.engine.bin_vals = np.array(vals)
        
        # CLAHE
        self.engine.clahe_blend = float(self.slider_clahe_blend.value() / 100.0)
        self.engine.clahe_clip_limit = float(self.slider_clahe_clip.value() / 10.0)
        self.engine.clahe_grid_size = (
            int(self.slider_clahe_grid_x.value()),
            int(self.slider_clahe_grid_y.value())
        )
        
        # Denoise
        self.engine.denoise_type = self.combo_denoise_type.currentText()
        self.engine.denoise_d = int(self.slider_denoise_d.value())
        self.engine.denoise_sigma_color = float(self.slider_denoise_sigma_c.value())
        self.engine.denoise_sigma_space = float(self.slider_denoise_sigma_s.value())
        
        # Red Boost
        self.engine.red_boost_alpha = float(self.slider_red_boost.value() / 100.0)
        
        # WB Gains
        self.engine.wb_red_gain = float(self.slider_wb_red.value() / 100.0)
        self.engine.wb_green_gain = float(self.slider_wb_green.value() / 100.0)
        self.engine.wb_blue_gain = float(self.slider_wb_blue.value() / 100.0)
        
        # Global sat
        self.engine.global_saturation_factor = float(self.slider_global_sat.value() / 100.0)
        
        # Sharpen
        self.engine.sharpen_type = self.combo_sharpen_type.currentText()
        self.engine.sharpen_amount = float(self.slider_sharpen_amt.value() / 100.0)
        self.engine.sharpen_radius = float(self.slider_sharpen_rad.value() / 10.0)
        
        # Run Pipeline
        rgb_orig = cv2.cvtColor(self.resized_orig, cv2.COLOR_BGR2RGB)
        filt = self.engine.get_filter_matrix(rgb_orig)
        result_rgb = self.engine.apply_filter(rgb_orig, filt)
        
        # Display Result
        self.show_pixmap(result_rgb, self.lbl_result)

    def show_pixmap(self, rgb_image, label):
        h, w, ch = rgb_image.shape
        bytes_per_line = ch * w
        qimg = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format_RGB888)
        pix = QPixmap.fromImage(qimg)
        label.setPixmap(pix)

def main():
    app = QApplication(sys.argv)
    window = ColorTuningApp()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
