"""Color Tuning page - PySide6 port of uwmedia/app.py's
_build_color_tuning_fields/_build_color_tuning_section and friends, see
pyside6_rework.md Phase 4.

Built entirely in Python, no .ui file - like Phase 1's AddHudDialog, this
page's content (22 sliders across 7 groups) is generated from a shared
data table (utils/color_params.py's PARAM_GROUPS), the same way the Toga
original builds it, so hand-authoring static Designer XML would just be
duplicating that loop in a second, harder-to-keep-in-sync form.

Reused verbatim: ColorCorrectionEngine (ffmpeg.color), load_merged_color_
profiles/save_user_profile (utils.color_profiles), PARAM_GROUPS/
PARAMS_BY_KEY (utils.color_params) - all zero-Toga-dependency engine code.

QSlider only accepts integer values, unlike toga.Slider's continuous
float range - float params are scaled by FLOAT_SLIDER_SCALE (10000) for
slider storage and divided back on read, giving 0.0001 step resolution,
finer than any of this page's own float ranges need.

No settings persistence - checked directly against PERSISTED_TEXT_FIELDS/
PERSISTED_SELECTION_FIELDS/PERSISTED_SWITCH_FIELDS in uwmedia/app.py: none
of this page's own fields (profile choice, legacy-pipeline switch, slider
values) are in those lists, so the Toga original doesn't persist this page
either - not an oversight.

Deliberately not ported: on_new_color_profile_name_change's manual 10-char
truncation - QLineEdit.setMaxLength(10) already enforces the same limit
natively, so the Toga workaround has no Qt equivalent to port.
"""
import cv2
import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

import ffmpeg.color as color_module
from ffmpeg.color import ColorCorrectionEngine
from utils.color_params import PARAM_GROUPS, PARAMS_BY_KEY
from utils.color_profiles import load_merged_color_profiles, save_user_profile

TUNING_PREVIEW_MAX_DIM = 600
NEW_PROFILE_NAME_MAX_LEN = 10
FLOAT_SLIDER_SCALE = 10000


def load_color_profiles():
    try:
        data = load_merged_color_profiles()
        return list(data.keys()) or ["default"]
    except Exception:
        return ["default"]


class ColorTuningPage(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.tuning_engine = ColorCorrectionEngine(ffmpeg_tool=None, color_profile="default")
        self.tuning_default_profile = load_merged_color_profiles().get("default", {})
        self._tuning_original_rgb = None

        self.color_sliders = {}
        self.color_slider_labels = {}

        self._build_ui()
        self._wire_signals()

    # ------------------------------------------------------------------
    # Layout - ported from _build_color_tuning_section/_color_slider_row.
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)

        sample_group = QtWidgets.QGroupBox("Sample image")
        sample_layout = QtWidgets.QVBoxLayout(sample_group)

        toolbar = QtWidgets.QHBoxLayout()
        self.load_image_button = QtWidgets.QPushButton("Load Image…")
        toolbar.addWidget(self.load_image_button)
        toolbar.addWidget(QtWidgets.QLabel("Profile:"))
        self.color_tuning_profile_select = QtWidgets.QComboBox()
        self.color_tuning_profile_select.addItems(load_color_profiles())
        toolbar.addWidget(self.color_tuning_profile_select)
        self.legacy_pipeline_switch = QtWidgets.QCheckBox("Use legacy pipeline")
        toolbar.addWidget(self.legacy_pipeline_switch)
        toolbar.addStretch(1)
        sample_layout.addLayout(toolbar)

        save_row = QtWidgets.QHBoxLayout()
        self.save_profile_button = QtWidgets.QPushButton("Save Profile")
        save_row.addWidget(self.save_profile_button)
        self.new_color_profile_input = QtWidgets.QLineEdit()
        self.new_color_profile_input.setPlaceholderText("New profile name (max 10 chars)")
        self.new_color_profile_input.setMaxLength(NEW_PROFILE_NAME_MAX_LEN)
        save_row.addWidget(self.new_color_profile_input)
        self.save_new_profile_button = QtWidgets.QPushButton("Save As New")
        save_row.addWidget(self.save_new_profile_button)
        save_row.addStretch(1)
        sample_layout.addLayout(save_row)

        self.color_tuning_status_label = QtWidgets.QLabel("No image loaded")
        self.color_tuning_status_label.setWordWrap(True)
        sample_layout.addWidget(self.color_tuning_status_label)

        root.addWidget(sample_group)

        preview_group = QtWidgets.QGroupBox("Preview")
        images_row = QtWidgets.QHBoxLayout(preview_group)

        original_col = QtWidgets.QVBoxLayout()
        original_title = QtWidgets.QLabel("Original")
        original_title.setStyleSheet("font-weight: bold;")
        original_col.addWidget(original_title)
        self.color_original_view = QtWidgets.QLabel()
        self.color_original_view.setMinimumHeight(260)
        self.color_original_view.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        original_col.addWidget(self.color_original_view)
        images_row.addLayout(original_col)

        result_col = QtWidgets.QVBoxLayout()
        result_title = QtWidgets.QLabel("Adjusted")
        result_title.setStyleSheet("font-weight: bold;")
        result_col.addWidget(result_title)
        self.color_result_view = QtWidgets.QLabel()
        self.color_result_view.setMinimumHeight(260)
        self.color_result_view.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        result_col.addWidget(self.color_result_view)
        images_row.addLayout(result_col)

        root.addWidget(preview_group)

        sliders_container = QtWidgets.QWidget()
        sliders_box = QtWidgets.QVBoxLayout(sliders_container)
        for group_title, params in PARAM_GROUPS:
            group = QtWidgets.QGroupBox(group_title)
            group_layout = QtWidgets.QVBoxLayout(group)
            for key, label, lo, hi, default, is_int in params:
                group_layout.addLayout(self._build_slider_row(key, label, lo, hi, default, is_int))
            sliders_box.addWidget(group)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(sliders_container)
        root.addWidget(scroll, stretch=1)

    def _build_slider_row(self, key, label_text, lo, hi, default, is_int):
        row = QtWidgets.QHBoxLayout()
        label = QtWidgets.QLabel(label_text)
        label.setFixedWidth(190)
        row.addWidget(label)

        slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        if is_int:
            slider.setMinimum(int(lo))
            slider.setMaximum(int(hi))
            slider.setValue(int(default))
            slider.setTickInterval(1)
        else:
            slider.setMinimum(round(lo * FLOAT_SLIDER_SCALE))
            slider.setMaximum(round(hi * FLOAT_SLIDER_SCALE))
            slider.setValue(round(default * FLOAT_SLIDER_SCALE))
        self.color_sliders[key] = slider
        row.addWidget(slider, stretch=1)

        value_label = QtWidgets.QLabel(self._format_color_value(default, is_int))
        value_label.setFixedWidth(60)
        self.color_slider_labels[key] = value_label
        row.addWidget(value_label)

        reset_button = QtWidgets.QPushButton("↺")
        reset_button.setFixedWidth(28)
        reset_button.clicked.connect(self._make_color_reset_handler(key))
        row.addWidget(reset_button)

        slider.valueChanged.connect(self._make_color_slider_handler(key, is_int))
        return row

    def _wire_signals(self):
        self.load_image_button.clicked.connect(self._on_load_tuning_image)
        self.color_tuning_profile_select.currentTextChanged.connect(self._on_color_tuning_profile_change)
        self.legacy_pipeline_switch.toggled.connect(self._on_legacy_pipeline_toggle)
        self.save_profile_button.clicked.connect(self._on_save_color_profile)
        self.save_new_profile_button.clicked.connect(self._on_save_new_color_profile)

    # ------------------------------------------------------------------
    # Color Tuning - ported from the same-named Toga methods.
    # ------------------------------------------------------------------

    def _format_color_value(self, value, is_int):
        return str(int(round(value))) if is_int else f"{value:.3f}"

    def _make_color_slider_handler(self, key, is_int):
        def handler(raw_value):
            value = raw_value if is_int else raw_value / FLOAT_SLIDER_SCALE
            self.color_slider_labels[key].setText(self._format_color_value(value, is_int))
            setattr(self.tuning_engine, key, value)
            self._update_color_tuning_preview()

        return handler

    def _make_color_reset_handler(self, key):
        def handler(checked=False):
            _label, _lo, _hi, default, is_int = PARAMS_BY_KEY[key]
            value = self.tuning_default_profile.get(key, default)
            slider = self.color_sliders[key]
            slider.setValue(int(value) if is_int else round(value * FLOAT_SLIDER_SCALE))

        return handler

    def _update_color_tuning_preview(self):
        if self._tuning_original_rgb is None:
            return
        filt = self.tuning_engine.get_filter_matrix(self._tuning_original_rgb)
        result = self.tuning_engine.apply_filter(self._tuning_original_rgb, filt)
        self._set_pixmap(self.color_result_view, result)

    def _apply_color_profile_to_sliders(self, name):
        profile = load_merged_color_profiles().get(name, {})
        for key, (_label, _lo, _hi, default, is_int) in PARAMS_BY_KEY.items():
            value = profile.get(key, default)
            slider = self.color_sliders[key]
            slider.blockSignals(True)
            slider.setValue(int(value) if is_int else round(value * FLOAT_SLIDER_SCALE))
            slider.blockSignals(False)
            self.color_slider_labels[key].setText(self._format_color_value(value, is_int))
            setattr(self.tuning_engine, key, value)
        self._update_color_tuning_preview()

    def _on_color_tuning_profile_change(self, name):
        if name:
            self._apply_color_profile_to_sliders(name)

    def _on_legacy_pipeline_toggle(self, checked):
        color_module.ENABLE_ADAPTIVE_DAMPING = not checked
        self._update_color_tuning_preview()

    def _on_load_tuning_image(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select image")
        if not path:
            return
        image = cv2.imread(path)
        if image is None:
            self.color_tuning_status_label.setText(f"Could not load: {path}")
            return
        h, w = image.shape[:2]
        scale = TUNING_PREVIEW_MAX_DIM / max(h, w)
        resized = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        self._tuning_original_rgb = rgb
        self._set_pixmap(self.color_original_view, rgb)
        self.color_tuning_status_label.setText(str(path))
        self._update_color_tuning_preview()

    def _gather_color_slider_values(self):
        values = {}
        for key, (_label, _lo, _hi, _default, is_int) in PARAMS_BY_KEY.items():
            raw = self.color_sliders[key].value()
            values[key] = raw if is_int else raw / FLOAT_SLIDER_SCALE
        return values

    def _on_save_color_profile(self):
        name = self.color_tuning_profile_select.currentText()
        if not name:
            return
        save_user_profile(name, self._gather_color_slider_values())
        self.color_tuning_status_label.setText(f"Saved profile '{name}'")

    def _on_save_new_color_profile(self):
        value = self.new_color_profile_input.text()
        name = value.strip()[:NEW_PROFILE_NAME_MAX_LEN] if value else ""
        if not name:
            return
        save_user_profile(name, self._gather_color_slider_values())
        self.new_color_profile_input.clear()
        self.color_tuning_profile_select.clear()
        self.color_tuning_profile_select.addItems(load_color_profiles())
        self.color_tuning_profile_select.setCurrentText(name)
        self.color_tuning_status_label.setText(f"Saved new profile '{name}'")

    # ------------------------------------------------------------------
    # QLabel+QPixmap preview - same technique as color_page.py's own
    # _redraw_preview (see pyside6_rework.md's toga.Canvas decision).
    # ------------------------------------------------------------------

    def _set_pixmap(self, label, rgb_array):
        rgb = np.ascontiguousarray(rgb_array).astype("uint8")
        h, w = rgb.shape[:2]
        qimage = QtGui.QImage(rgb.tobytes(), w, h, w * 3, QtGui.QImage.Format.Format_RGB888)
        pixmap = QtGui.QPixmap.fromImage(qimage)
        scaled = pixmap.scaled(
            label.width() or 400, 260,
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        label.setPixmap(scaled)
