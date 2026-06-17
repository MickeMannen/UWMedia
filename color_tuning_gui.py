import sys
import os
import yaml
import cv2
import numpy as np
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QSlider, QPushButton,
    QComboBox, QScrollArea, QGroupBox, QFormLayout, QHBoxLayout, QVBoxLayout,
    QFileDialog, QSizePolicy
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QImage
from ffmpeg.color import ColorCorrectionEngine

class ColorTuningApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("UWMedia Underwater Color Tuning Tool (Color Engine)")
        self.resize(1200, 800)
        
        # Paths & Configurations
        self.color_name = "color.yaml"
        self.yaml_path = self.locate_yaml()
        self.config_data = {}
        self.default_profile_data = {}
        self.current_profile = "default"
        
        # QSettings for remembering paths
        from PySide6.QtCore import QSettings
        self.settings = QSettings("UWMedia", "ColorTuning")
        self.last_orig_path = self.settings.value("last_orig_path", "")
        
        # Image state
        self.orig_image = None  # Full res original
        self.resized_orig = None  # Resized original BGR (for fast preview)
        
        # Color engine
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
        
        self.default_profile_data = self.config_data.get("default", {})

    def save_yaml(self):
        # Update current profile from sliders
        profile = self.config_data.get(self.current_profile, {})
        
        profile["cifval"] = float(self.slider_cifval.value() / 100.0)
        profile["red_threshold"] = float(self.slider_red_threshold.value() / 100.0)
        profile["red_scale"] = float(self.slider_red_scale.value() / 100.0)
        profile["blue_threshold"] = float(self.slider_blue_threshold.value() / 100.0)
        profile["blue_scale"] = float(self.slider_blue_scale.value() / 100.0)
        profile["black_point_cutoff"] = float(self.slider_black_point_cutoff.value() / 10000.0)
        profile["gw_mask_mult"] = float(self.slider_gw_mask_mult.value() / 100.0)
        profile["gw_mask_fallback"] = float(self.slider_gw_mask_fallback.value() / 100.0)
        profile["gw_blur_radius"] = int(self.slider_gw_blur_radius.value())
        profile["gw_blur_sigma"] = float(self.slider_gw_blur_sigma.value() / 10.0)
        profile["gw_isolation_threshold"] = float(self.slider_gw_isolation_threshold.value() / 1000.0)
        profile["gw_isolation_min_sum"] = float(self.slider_gw_isolation_min_sum.value())
        profile["dehaze_sat_cutoff"] = float(self.slider_dehaze_sat_cutoff.value() / 100.0)
        profile["dehaze_sat_scale"] = float(self.slider_dehaze_sat_scale.value() / 100.0)
        profile["dehaze_min"] = float(self.slider_dehaze_min.value() / 100.0)
        profile["dehaze_max"] = float(self.slider_dehaze_max.value() / 100.0)
        profile["exposure_cdf_cutoff"] = float(self.slider_exposure_cdf_cutoff.value() / 1000.0)
        profile["exposure_numerator"] = float(self.slider_exposure_numerator.value() / 100.0)
        profile["exposure_min"] = float(self.slider_exposure_min.value() / 100.0)
        profile["exposure_max"] = float(self.slider_exposure_max.value() / 100.0)
        profile["bh_min_idx"] = int(self.slider_bh_min_idx.value())
        profile["bh_max_idx"] = int(self.slider_bh_max_idx.value())
        profile["bh_decay"] = float(self.slider_bh_decay.value() / 100.0)
        profile["bh_fallback"] = float(self.slider_bh_fallback.value() / 100.0)
        profile["sharpness"] = float(self.slider_sharpness.value() / 100.0)
        profile["darkness"] = float(self.slider_darkness.value() / 100.0)
        
        self.config_data[self.current_profile] = profile
        
        try:
            with open(self.yaml_path, 'w') as f:
                yaml.dump(self.config_data, f, default_flow_style=False, sort_keys=False)
            print(f"Saved configuration to: {self.yaml_path}")
            if self.current_profile == "default":
                self.default_profile_data = self.config_data.get("default", {})
        except Exception as e:
            print(f"Error saving yaml: {e}")

    def save_new_profile(self):
        from PySide6.QtWidgets import QInputDialog
        new_name, ok = QInputDialog.getText(self, "Save Profile", "Enter new profile name:")
        if ok and new_name:
            new_name = new_name.strip()
            if not new_name:
                return
            
            # Update current profile from sliders
            profile = {}
            profile["cifval"] = float(self.slider_cifval.value() / 100.0)
            profile["red_threshold"] = float(self.slider_red_threshold.value() / 100.0)
            profile["red_scale"] = float(self.slider_red_scale.value() / 100.0)
            profile["blue_threshold"] = float(self.slider_blue_threshold.value() / 100.0)
            profile["blue_scale"] = float(self.slider_blue_scale.value() / 100.0)
            profile["black_point_cutoff"] = float(self.slider_black_point_cutoff.value() / 10000.0)
            profile["gw_mask_mult"] = float(self.slider_gw_mask_mult.value() / 100.0)
            profile["gw_mask_fallback"] = float(self.slider_gw_mask_fallback.value() / 100.0)
            profile["gw_blur_radius"] = int(self.slider_gw_blur_radius.value())
            profile["gw_blur_sigma"] = float(self.slider_gw_blur_sigma.value() / 10.0)
            profile["gw_isolation_threshold"] = float(self.slider_gw_isolation_threshold.value() / 1000.0)
            profile["gw_isolation_min_sum"] = float(self.slider_gw_isolation_min_sum.value())
            profile["dehaze_sat_cutoff"] = float(self.slider_dehaze_sat_cutoff.value() / 100.0)
            profile["dehaze_sat_scale"] = float(self.slider_dehaze_sat_scale.value() / 100.0)
            profile["dehaze_min"] = float(self.slider_dehaze_min.value() / 100.0)
            profile["dehaze_max"] = float(self.slider_dehaze_max.value() / 100.0)
            profile["exposure_cdf_cutoff"] = float(self.slider_exposure_cdf_cutoff.value() / 1000.0)
            profile["exposure_numerator"] = float(self.slider_exposure_numerator.value() / 100.0)
            profile["exposure_min"] = float(self.slider_exposure_min.value() / 100.0)
            profile["exposure_max"] = float(self.slider_exposure_max.value() / 100.0)
            profile["bh_min_idx"] = int(self.slider_bh_min_idx.value())
            profile["bh_max_idx"] = int(self.slider_bh_max_idx.value())
            profile["bh_decay"] = float(self.slider_bh_decay.value() / 100.0)
            profile["bh_fallback"] = float(self.slider_bh_fallback.value() / 100.0)
            profile["sharpness"] = float(self.slider_sharpness.value() / 100.0)
            profile["darkness"] = float(self.slider_darkness.value() / 100.0)
            
            self.config_data[new_name] = profile
            
            try:
                with open(self.yaml_path, 'w') as f:
                    yaml.dump(self.config_data, f, default_flow_style=False, sort_keys=False)
                print(f"Saved new profile '{new_name}' to: {self.yaml_path}")
                
                # Refresh profiles combo box and select the new one
                self.block_updates = True
                self.combo_profile.clear()
                self.combo_profile.addItems(list(self.config_data.keys()))
                self.combo_profile.setCurrentText(new_name)
                self.current_profile = new_name
                self.block_updates = False
                
                self.trigger_pipeline_update()
            except Exception as e:
                print(f"Error saving new profile: {e}")

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
        
        toolbar.addSpacing(20)
        
        lbl_profile = QLabel("Profile:")
        lbl_profile.setStyleSheet("font-weight: bold;")
        toolbar.addWidget(lbl_profile)
        
        self.combo_profile = QComboBox()
        self.combo_profile.addItems(list(self.config_data.keys()) if self.config_data else ["default", "vivid", "subtle"])
        self.combo_profile.currentTextChanged.connect(self.change_profile)
        toolbar.addWidget(self.combo_profile)
        
        toolbar.addStretch()

        self.btn_save_new = QPushButton("Save as New Profile")
        self.btn_save_new.setStyleSheet("background-color: #3b82f6;") # Blue
        self.btn_save_new.clicked.connect(self.save_new_profile)
        toolbar.addWidget(self.btn_save_new)
        
        self.btn_save = QPushButton("Save to color.yaml")
        self.btn_save.setStyleSheet("background-color: #10b981;") # Emerald Green
        self.btn_save.clicked.connect(self.save_yaml)
        toolbar.addWidget(self.btn_save)
        
        # Image Grid (Original vs Result)
        grid_layout = QHBoxLayout()
        left_layout.addLayout(grid_layout)
        
        # Original Image View (Left)
        orig_v = QVBoxLayout()
        orig_v.addWidget(QLabel("<b>Original</b>"))
        self.lbl_original = QLabel("No original image loaded")
        self.lbl_original.setAlignment(Qt.AlignCenter)
        self.lbl_original.setStyleSheet("background-color: #0f0f12; border: 1px solid #2e2e38; border-radius: 6px;")
        self.lbl_original.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        orig_v.addWidget(self.lbl_original)
        grid_layout.addLayout(orig_v)
        
        # Result Image View (Right)
        result_v = QVBoxLayout()
        result_v.addWidget(QLabel("<b>Adjusted (Color Engine)</b>"))
        self.lbl_result = QLabel("No preview available")
        self.lbl_result.setAlignment(Qt.AlignCenter)
        self.lbl_result.setStyleSheet("background-color: #0f0f12; border: 1px solid #2e2e38; border-radius: 6px;")
        self.lbl_result.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        result_v.addWidget(self.lbl_result)
        grid_layout.addLayout(result_v)

        # Status Bar in the bottom of the screen
        from PySide6.QtWidgets import QStatusBar
        self.setStatusBar(QStatusBar(self))

        # Right Side - Control Panel (Sliders)
        control_scroll = QScrollArea()
        control_scroll.setWidgetResizable(True)
        control_scroll.setFixedWidth(420)
        main_layout.addWidget(control_scroll, stretch=1)
        
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(5, 5, 5, 5)
        control_scroll.setWidget(scroll_widget)
        
        # 1. Color Restoration
        group_restoration = QGroupBox("1. Color Restoration & Blend")
        restoration_layout = QFormLayout(group_restoration)
        
        self.slider_cifval, self.lbl_cifval = self.create_float_slider(
            0.0, 1.0, 1.0, 100, restoration_layout, "cifval (Blend Weight):",
            lambda: self.slider_cifval.setValue(int(self.default_profile_data.get("cifval", 1.0) * 100))
        )
        self.slider_red_threshold, self.lbl_red_threshold = self.create_float_slider(
            0.0, 1.0, 0.3, 100, restoration_layout, "Red Threshold:",
            lambda: self.slider_red_threshold.setValue(int(self.default_profile_data.get("red_threshold", 0.3) * 100))
        )
        self.slider_red_scale, self.lbl_red_scale = self.create_float_slider(
            0.01, 1.0, 0.2, 100, restoration_layout, "Red Scale:",
            lambda: self.slider_red_scale.setValue(int(self.default_profile_data.get("red_scale", 0.2) * 100))
        )
        self.slider_blue_threshold, self.lbl_blue_threshold = self.create_float_slider(
            0.0, 1.0, 0.3, 100, restoration_layout, "Blue Threshold:",
            lambda: self.slider_blue_threshold.setValue(int(self.default_profile_data.get("blue_threshold", 0.3) * 100))
        )
        self.slider_blue_scale, self.lbl_blue_scale = self.create_float_slider(
            0.01, 2.0, 0.6, 100, restoration_layout, "Blue Scale:",
            lambda: self.slider_blue_scale.setValue(int(self.default_profile_data.get("blue_scale", 0.6) * 100))
        )
        scroll_layout.addWidget(group_restoration)
        
        # 2. Black Point Floors
        group_black_point = QGroupBox("2. Black Point Floors")
        black_point_layout = QFormLayout(group_black_point)
        
        self.slider_black_point_cutoff, self.lbl_black_point_cutoff = self.create_float_slider(
            0.0001, 0.01, 0.001, 10000, black_point_layout, "CDF Cutoff Floor:",
            lambda: self.slider_black_point_cutoff.setValue(int(self.default_profile_data.get("black_point_cutoff", 0.001) * 10000)),
            precision=4
        )
        scroll_layout.addWidget(group_black_point)
        
        # 3. Gray World WB
        group_wb = QGroupBox("3. Gray World WB")
        wb_layout = QFormLayout(group_wb)
        
        self.slider_gw_mask_mult, self.lbl_gw_mask_mult = self.create_float_slider(
            0.5, 3.0, 1.5, 100, wb_layout, "Mask Multiplier:",
            lambda: self.slider_gw_mask_mult.setValue(int(self.default_profile_data.get("gw_mask_mult", 1.5) * 100))
        )
        self.slider_gw_mask_fallback, self.lbl_gw_mask_fallback = self.create_float_slider(
            0.0, 1.0, 0.2, 100, wb_layout, "Mask Fallback Weight:",
            lambda: self.slider_gw_mask_fallback.setValue(int(self.default_profile_data.get("gw_mask_fallback", 0.2) * 100))
        )
        self.slider_gw_blur_radius, self.lbl_gw_blur_radius = self.create_int_slider(
            1, 31, 9, wb_layout, "Gaussian Blur Radius:",
            lambda: self.slider_gw_blur_radius.setValue(int(self.default_profile_data.get("gw_blur_radius", 9)))
        )
        self.slider_gw_blur_sigma, self.lbl_gw_blur_sigma = self.create_float_slider(
            0.1, 5.0, 1.8, 10, wb_layout, "Gaussian Blur Sigma:",
            lambda: self.slider_gw_blur_sigma.setValue(int(self.default_profile_data.get("gw_blur_sigma", 1.8) * 10))
        )
        self.slider_gw_isolation_threshold, self.lbl_gw_isolation_threshold = self.create_float_slider(
            0.001, 0.5, 0.07, 1000, wb_layout, "Isolation Variation:",
            lambda: self.slider_gw_isolation_threshold.setValue(int(self.default_profile_data.get("gw_isolation_threshold", 0.07) * 1000)),
            precision=3
        )
        self.slider_gw_isolation_min_sum, self.lbl_gw_isolation_min_sum = self.create_int_slider(
            10, 500, 100, wb_layout, "Isolation Min Sum:",
            lambda: self.slider_gw_isolation_min_sum.setValue(int(self.default_profile_data.get("gw_isolation_min_sum", 100.0)))
        )
        scroll_layout.addWidget(group_wb)
        
        # 4. Dehaze
        group_dehaze = QGroupBox("4. De-haze Adjustment")
        dehaze_layout = QFormLayout(group_dehaze)
        
        self.slider_dehaze_sat_cutoff, self.lbl_dehaze_sat_cutoff = self.create_float_slider(
            0.01, 0.5, 0.1, 100, dehaze_layout, "Saturation Cutoff:",
            lambda: self.slider_dehaze_sat_cutoff.setValue(int(self.default_profile_data.get("dehaze_sat_cutoff", 0.1) * 100))
        )
        self.slider_dehaze_sat_scale, self.lbl_dehaze_sat_scale = self.create_float_slider(
            0.1, 2.0, 0.75, 100, dehaze_layout, "Saturation Divisor:",
            lambda: self.slider_dehaze_sat_scale.setValue(int(self.default_profile_data.get("dehaze_sat_scale", 0.75) * 100))
        )
        self.slider_dehaze_min, self.lbl_dehaze_min = self.create_float_slider(
            0.5, 1.0, 0.81, 100, dehaze_layout, "Dehaze Min Bound:",
            lambda: self.slider_dehaze_min.setValue(int(self.default_profile_data.get("dehaze_min", 0.81) * 100))
        )
        self.slider_dehaze_max, self.lbl_dehaze_max = self.create_float_slider(
            1.0, 2.0, 1.0, 100, dehaze_layout, "Dehaze Max Bound:",
            lambda: self.slider_dehaze_max.setValue(int(self.default_profile_data.get("dehaze_max", 1.0) * 100))
        )
        scroll_layout.addWidget(group_dehaze)
        
        # 5. Exposure
        group_exposure = QGroupBox("5. Exposure Normalization")
        exposure_layout = QFormLayout(group_exposure)
        
        self.slider_exposure_cdf_cutoff, self.lbl_exposure_cdf_cutoff = self.create_float_slider(
            0.001, 0.1, 0.01, 1000, exposure_layout, "CDF Brightness Cutoff:",
            lambda: self.slider_exposure_cdf_cutoff.setValue(int(self.default_profile_data.get("exposure_cdf_cutoff", 0.01) * 1000)),
            precision=3
        )
        self.slider_exposure_numerator, self.lbl_exposure_numerator = self.create_float_slider(
            0.1, 2.0, 0.5, 100, exposure_layout, "Target Reference Brightness:",
            lambda: self.slider_exposure_numerator.setValue(int(self.default_profile_data.get("exposure_numerator", 0.5) * 100))
        )
        self.slider_exposure_min, self.lbl_exposure_min = self.create_float_slider(
            0.5, 2.0, 1.0, 100, exposure_layout, "Exposure Min Mult:",
            lambda: self.slider_exposure_min.setValue(int(self.default_profile_data.get("exposure_min", 1.0) * 100))
        )
        self.slider_exposure_max, self.lbl_exposure_max = self.create_float_slider(
            1.0, 4.0, 2.0, 100, exposure_layout, "Exposure Max Mult:",
            lambda: self.slider_exposure_max.setValue(int(self.default_profile_data.get("exposure_max", 2.0) * 100))
        )
        scroll_layout.addWidget(group_exposure)
        
        # 6. Blue Hue Translation
        group_hue = QGroupBox("6. OKLCh Blue Hue Translation")
        hue_layout = QFormLayout(group_hue)
        
        self.slider_bh_min_idx, self.lbl_bh_min_idx = self.create_int_slider(
            0, 255, 155, hue_layout, "Min Hue Scanning Bin:",
            lambda: self.slider_bh_min_idx.setValue(int(self.default_profile_data.get("bh_min_idx", 155)))
        )
        self.slider_bh_max_idx, self.lbl_bh_max_idx = self.create_int_slider(
            0, 255, 218, hue_layout, "Max Hue Scanning Bin:",
            lambda: self.slider_bh_max_idx.setValue(int(self.default_profile_data.get("bh_max_idx", 218)))
        )
        self.slider_bh_decay, self.lbl_bh_decay = self.create_float_slider(
            0.0, 1.0, 0.85, 100, hue_layout, "Scan Decay Weight:",
            lambda: self.slider_bh_decay.setValue(int(self.default_profile_data.get("bh_decay", 0.85) * 100))
        )
        self.slider_bh_fallback, self.lbl_bh_fallback = self.create_float_slider(
            0.0, 1.0, 0.67, 100, hue_layout, "Fallback Blue Hue:",
            lambda: self.slider_bh_fallback.setValue(int(self.default_profile_data.get("bh_fallback", 0.67) * 100))
        )
        scroll_layout.addWidget(group_hue)
        
        # 7. Final Adjustments (Sharpness & Darkness)
        group_final = QGroupBox("7. Final Adjustments")
        final_layout = QFormLayout(group_final)
        
        self.slider_sharpness, self.lbl_sharpness = self.create_float_slider(
            0.0, 3.0, 0.0, 100, final_layout, "Sharpness:",
            lambda: self.slider_sharpness.setValue(int(self.default_profile_data.get("sharpness", 0.0) * 100))
        )
        self.slider_darkness, self.lbl_darkness = self.create_float_slider(
            -1.0, 1.0, 0.0, 100, final_layout, "Darkness:",
            lambda: self.slider_darkness.setValue(int(self.default_profile_data.get("darkness", 0.0) * 100))
        )
        scroll_layout.addWidget(group_final)
        
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

    def create_float_slider(self, min_val, max_val, default, multiplier, form_layout, label_text, reset_callback, precision=2):
        label_val = QLabel(f"{default:.{precision}f}")
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
            label_val.setText(f"{val_f:.{precision}f}")
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
            
        self.slider_cifval.setValue(int(profile.get("cifval", 1.0) * 100))
        self.lbl_cifval.setText(f"{profile.get('cifval', 1.0):.2f}")
        
        self.slider_red_threshold.setValue(int(profile.get("red_threshold", 0.3) * 100))
        self.lbl_red_threshold.setText(f"{profile.get('red_threshold', 0.3):.2f}")
        
        self.slider_red_scale.setValue(int(profile.get("red_scale", 0.2) * 100))
        self.lbl_red_scale.setText(f"{profile.get('red_scale', 0.2):.2f}")
        
        self.slider_blue_threshold.setValue(int(profile.get("blue_threshold", 0.3) * 100))
        self.lbl_blue_threshold.setText(f"{profile.get('blue_threshold', 0.3):.2f}")
        
        self.slider_blue_scale.setValue(int(profile.get("blue_scale", 0.6) * 100))
        self.lbl_blue_scale.setText(f"{profile.get('blue_scale', 0.6):.2f}")
        
        self.slider_black_point_cutoff.setValue(int(profile.get("black_point_cutoff", 0.001) * 10000))
        self.lbl_black_point_cutoff.setText(f"{profile.get('black_point_cutoff', 0.001):.4f}")
        
        self.slider_gw_mask_mult.setValue(int(profile.get("gw_mask_mult", 1.5) * 100))
        self.lbl_gw_mask_mult.setText(f"{profile.get('gw_mask_mult', 1.5):.2f}")
        
        self.slider_gw_mask_fallback.setValue(int(profile.get("gw_mask_fallback", 0.2) * 100))
        self.lbl_gw_mask_fallback.setText(f"{profile.get('gw_mask_fallback', 0.2):.2f}")
        
        self.slider_gw_blur_radius.setValue(int(profile.get("gw_blur_radius", 9)))
        self.lbl_gw_blur_radius.setText(str(profile.get("gw_blur_radius", 9)))
        
        self.slider_gw_blur_sigma.setValue(int(profile.get("gw_blur_sigma", 1.8) * 10))
        self.lbl_gw_blur_sigma.setText(f"{profile.get('gw_blur_sigma', 1.8):.2f}")
        
        self.slider_gw_isolation_threshold.setValue(int(profile.get("gw_isolation_threshold", 0.07) * 1000))
        self.lbl_gw_isolation_threshold.setText(f"{profile.get('gw_isolation_threshold', 0.07):.3f}")
        
        self.slider_gw_isolation_min_sum.setValue(int(profile.get("gw_isolation_min_sum", 100.0)))
        self.lbl_gw_isolation_min_sum.setText(f"{profile.get('gw_isolation_min_sum', 100.0):.1f}")
        
        self.slider_dehaze_sat_cutoff.setValue(int(profile.get("dehaze_sat_cutoff", 0.1) * 100))
        self.lbl_dehaze_sat_cutoff.setText(f"{profile.get('dehaze_sat_cutoff', 0.1):.2f}")
        
        self.slider_dehaze_sat_scale.setValue(int(profile.get("dehaze_sat_scale", 0.75) * 100))
        self.lbl_dehaze_sat_scale.setText(f"{profile.get('dehaze_sat_scale', 0.75):.2f}")
        
        self.slider_dehaze_min.setValue(int(profile.get("dehaze_min", 0.81) * 100))
        self.lbl_dehaze_min.setText(f"{profile.get('dehaze_min', 0.81):.2f}")
        
        self.slider_dehaze_max.setValue(int(profile.get("dehaze_max", 1.0) * 100))
        self.lbl_dehaze_max.setText(f"{profile.get('dehaze_max', 1.0):.2f}")
        
        self.slider_exposure_cdf_cutoff.setValue(int(profile.get("exposure_cdf_cutoff", 0.01) * 1000))
        self.lbl_exposure_cdf_cutoff.setText(f"{profile.get('exposure_cdf_cutoff', 0.01):.3f}")
        
        self.slider_exposure_numerator.setValue(int(profile.get("exposure_numerator", 0.5) * 100))
        self.lbl_exposure_numerator.setText(f"{profile.get('exposure_numerator', 0.5):.2f}")
        
        self.slider_exposure_min.setValue(int(profile.get("exposure_min", 1.0) * 100))
        self.lbl_exposure_min.setText(f"{profile.get('exposure_min', 1.0):.2f}")
        
        self.slider_exposure_max.setValue(int(profile.get("exposure_max", 2.0) * 100))
        self.lbl_exposure_max.setText(f"{profile.get('exposure_max', 2.0):.2f}")
        
        self.slider_bh_min_idx.setValue(int(profile.get("bh_min_idx", 155)))
        self.lbl_bh_min_idx.setText(str(profile.get("bh_min_idx", 155)))
        
        self.slider_bh_max_idx.setValue(int(profile.get("bh_max_idx", 218)))
        self.lbl_bh_max_idx.setText(str(profile.get("bh_max_idx", 218)))
        
        self.slider_bh_decay.setValue(int(profile.get("bh_decay", 0.85) * 100))
        self.lbl_bh_decay.setText(f"{profile.get('bh_decay', 0.85):.2f}")
        
        self.slider_bh_fallback.setValue(int(profile.get("bh_fallback", 0.67) * 100))
        self.lbl_bh_fallback.setText(f"{profile.get('bh_fallback', 0.67):.2f}")
        
        self.slider_sharpness.setValue(int(profile.get("sharpness", 0.0) * 100))
        self.lbl_sharpness.setText(f"{profile.get('sharpness', 0.0):.2f}")
        
        self.slider_darkness.setValue(int(profile.get("darkness", 0.0) * 100))
        self.lbl_darkness.setText(f"{profile.get('darkness', 0.0):.2f}")

    def choose_original(self):
        initial_dir = "test_data/color_correction/"
        if self.last_orig_path:
            p_dir = Path(self.last_orig_path).parent
            if p_dir.exists():
                initial_dir = str(p_dir)
        filename, _ = QFileDialog.getOpenFileName(self, "Open Original Photo", initial_dir, "Images (*.jpg *.jpeg *.png *.JPG *.JPEG *.PNG)")
        if filename:
            self.last_orig_path = filename
            self.settings.setValue("last_orig_path", filename)
            self.load_original(filename)

    def load_original(self, filepath):
        self.orig_image = cv2.imread(filepath)
        if self.orig_image is not None:
            h, w = self.orig_image.shape[:2]
            max_dim = 600
            scale = max_dim / max(h, w)
            target_w = int(w * scale)
            target_h = int(h * scale)
            self.resized_orig = cv2.resize(self.orig_image, (target_w, target_h), interpolation=cv2.INTER_AREA)
            
            # Display Original Image in left view
            rgb = cv2.cvtColor(self.resized_orig, cv2.COLOR_BGR2RGB)
            self.show_pixmap(rgb, self.lbl_original)
            
            # Show status bar info
            abs_path = os.path.abspath(filepath)
            self.statusBar().showMessage(abs_path)
            
            self.trigger_pipeline_update()

    def auto_load_default_sample(self):
        # First try the remembered path if it exists
        if self.last_orig_path and os.path.exists(self.last_orig_path):
            self.load_original(self.last_orig_path)
            return

        default_file = Path("test_data/color_correction/DSC06641.JPG")
        if default_file.exists():
            self.load_original(str(default_file))

    def trigger_pipeline_update(self):
        if getattr(self, 'block_updates', False) or self.resized_orig is None:
            return
            
        self.engine.cifval = float(self.slider_cifval.value() / 100.0)
        self.engine.red_threshold = float(self.slider_red_threshold.value() / 100.0)
        self.engine.red_scale = float(self.slider_red_scale.value() / 100.0)
        self.engine.blue_threshold = float(self.slider_blue_threshold.value() / 100.0)
        self.engine.blue_scale = float(self.slider_blue_scale.value() / 100.0)
        self.engine.black_point_cutoff = float(self.slider_black_point_cutoff.value() / 10000.0)
        self.engine.gw_mask_mult = float(self.slider_gw_mask_mult.value() / 100.0)
        self.engine.gw_mask_fallback = float(self.slider_gw_mask_fallback.value() / 100.0)
        self.engine.gw_blur_radius = int(self.slider_gw_blur_radius.value())
        self.engine.gw_blur_sigma = float(self.slider_gw_blur_sigma.value() / 10.0)
        self.engine.gw_isolation_threshold = float(self.slider_gw_isolation_threshold.value() / 1000.0)
        self.engine.gw_isolation_min_sum = float(self.slider_gw_isolation_min_sum.value())
        self.engine.dehaze_sat_cutoff = float(self.slider_dehaze_sat_cutoff.value() / 100.0)
        self.engine.dehaze_sat_scale = float(self.slider_dehaze_sat_scale.value() / 100.0)
        self.engine.dehaze_min = float(self.slider_dehaze_min.value() / 100.0)
        self.engine.dehaze_max = float(self.slider_dehaze_max.value() / 100.0)
        self.engine.exposure_cdf_cutoff = float(self.slider_exposure_cdf_cutoff.value() / 1000.0)
        self.engine.exposure_numerator = float(self.slider_exposure_numerator.value() / 100.0)
        self.engine.exposure_min = float(self.slider_exposure_min.value() / 100.0)
        self.engine.exposure_max = float(self.slider_exposure_max.value() / 100.0)
        self.engine.bh_min_idx = int(self.slider_bh_min_idx.value())
        self.engine.bh_max_idx = int(self.slider_bh_max_idx.value())
        self.engine.bh_decay = float(self.slider_bh_decay.value() / 100.0)
        self.engine.bh_fallback = float(self.slider_bh_fallback.value() / 100.0)
        self.engine.sharpness = float(self.slider_sharpness.value() / 100.0)
        self.engine.darkness = float(self.slider_darkness.value() / 100.0)
        
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
