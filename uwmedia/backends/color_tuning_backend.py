"""Color Tuning page backend - qml_development.md Phase 4. QObject exposed to
uwmedia/qml/ColorTuningPage.qml as the "colorTuningBackend"
context property, plus two QQuickImageProviders (Original/Adjusted
preview panes) - same redraw-on-demand mechanism Color's own backend
already established.

Ported close to verbatim from uwmedia/pages/color_tuning_page.py
(the old Widgets page, kept as reference only) - 26 sliders across 7
groups, generated from the same shared uwmedia.color_params.PARAM_GROUPS
table the Toga original and the old Widgets page both use, not
hand-duplicated per slider.

Reused verbatim: ColorCorrectionEngine (ffmpeg.color), load_merged_color_
profiles/save_user_profile (utils.color_profiles), PARAM_GROUPS/
PARAMS_BY_KEY (utils.color_params).

No settings persistence - checked directly against PERSISTED_TEXT_FIELDS/
PERSISTED_SELECTION_FIELDS/PERSISTED_SWITCH_FIELDS in uwmedia/app.py by
the old Widgets page's own docstring: none of this page's fields are
persisted in the Toga app either, not an oversight.

Deliberately not ported: the old page's manual 10-char profile-name
truncation - a QML TextField's maximumLength property already enforces
the same limit natively (this page's own QML equivalent of the old
page's documented "QLineEdit.setMaxLength(10) already does this"
finding), so there's no workaround left to port.

Reactivity note, worth remembering for any later page with a
Repeater-driven form: `groups` is exposed `constant=True` (label/range/
key structure never changes at runtime) precisely so the QML Repeater
never rebuilds its whole Item tree; the actual per-slider VALUE/text
state lives in separate `sliderValues`/`sliderTexts` dict Propertys with
their own notify signal, read via `sliderValues[key]` inside each
delegate's own value binding - moving one slider re-evaluates every
delegate's *property binding* (cheap) without ever destroying/recreating
the 26 delegate Items themselves (expensive) the way swapping `groups`
itself on every move would have.
"""
import numpy as np
from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider

import ffmpeg.color as color_module
from ffmpeg.color import ColorCorrectionEngine
from utils.color_params import PARAM_GROUPS, PARAMS_BY_KEY
from utils.color_profiles import load_merged_color_profiles, save_user_profile

TUNING_PREVIEW_MAX_DIM = 600
NEW_PROFILE_NAME_MAX_LEN = 10
FLOAT_SLIDER_SCALE = 10000


def _load_color_profiles():
    try:
        data = load_merged_color_profiles()
        return list(data.keys()) or ["default"]
    except Exception:
        return ["default"]


def _format_color_value(value, is_int):
    return str(int(round(value))) if is_int else f"{value:.3f}"


class ColorTuningBackend(QObject):
    profilesChanged = Signal()
    legacyPipelineChanged = Signal()
    slidersChanged = Signal()
    statusChanged = Signal()
    previewChanged = Signal()

    def __init__(self):
        super().__init__()

        self.tuning_engine = ColorCorrectionEngine(ffmpeg_tool=None, color_profile="default")
        self.tuning_default_profile = load_merged_color_profiles().get("default", {})
        self._original_rgb = None
        self._result_rgb = None
        self._original_revision = 0
        self._result_revision = 0

        self._profiles = _load_color_profiles()
        self._current_profile = self._profiles[0]
        self._legacy_pipeline = False
        self._new_profile_name = ""
        self._status_text = "No image loaded"

        self._slider_values = {}
        self._slider_texts = {}
        for _title, params in PARAM_GROUPS:
            for key, _label, _lo, _hi, default, is_int in params:
                self._slider_values[key] = int(default) if is_int else round(default * FLOAT_SLIDER_SCALE)
                self._slider_texts[key] = _format_color_value(default, is_int)
                setattr(self.tuning_engine, key, default)

    # ------------------------------------------------------------------
    # Static slider structure - see module docstring for why this is
    # `constant=True` rather than part of the reactive slider state.
    # ------------------------------------------------------------------

    @Property("QVariant", constant=True)
    def groups(self):
        return [
            {
                "title": title,
                "params": [
                    {
                        "key": key,
                        "label": label,
                        "isInt": is_int,
                        "sliderMin": int(lo) if is_int else round(lo * FLOAT_SLIDER_SCALE),
                        "sliderMax": int(hi) if is_int else round(hi * FLOAT_SLIDER_SCALE),
                    }
                    for key, label, lo, hi, _default, is_int in params
                ],
            }
            for title, params in PARAM_GROUPS
        ]

    @Property("QVariant", notify=slidersChanged)
    def sliderValues(self):
        return dict(self._slider_values)

    @Property("QVariant", notify=slidersChanged)
    def sliderTexts(self):
        return dict(self._slider_texts)

    @Slot(str, int)
    def setSliderValue(self, key, raw_value):
        _label, _lo, _hi, _default, is_int = PARAMS_BY_KEY[key]
        value = raw_value if is_int else raw_value / FLOAT_SLIDER_SCALE
        self._slider_values[key] = raw_value
        self._slider_texts[key] = _format_color_value(value, is_int)
        setattr(self.tuning_engine, key, value)
        self.slidersChanged.emit()
        self._update_preview()

    @Slot(str)
    def resetSlider(self, key):
        _label, _lo, _hi, default, is_int = PARAMS_BY_KEY[key]
        value = self.tuning_default_profile.get(key, default)
        raw = int(value) if is_int else round(value * FLOAT_SLIDER_SCALE)
        self.setSliderValue(key, raw)

    def _apply_profile_to_sliders(self, name):
        profile = load_merged_color_profiles().get(name, {})
        for key, (_label, _lo, _hi, default, is_int) in PARAMS_BY_KEY.items():
            value = profile.get(key, default)
            raw = int(value) if is_int else round(value * FLOAT_SLIDER_SCALE)
            self._slider_values[key] = raw
            self._slider_texts[key] = _format_color_value(value, is_int)
            setattr(self.tuning_engine, key, value)
        self.slidersChanged.emit()
        self._update_preview()

    # ------------------------------------------------------------------
    # Profile/legacy-pipeline/status
    # ------------------------------------------------------------------

    @Property(list, constant=True)
    def profileList(self):
        return self._profiles

    @Property(str, notify=profilesChanged)
    def currentProfile(self):
        return self._current_profile

    @currentProfile.setter
    def currentProfile(self, name):
        if not name or name == self._current_profile:
            return
        self._current_profile = name
        self.profilesChanged.emit()
        self._apply_profile_to_sliders(name)

    @Property(bool, notify=legacyPipelineChanged)
    def legacyPipeline(self):
        return self._legacy_pipeline

    @legacyPipeline.setter
    def legacyPipeline(self, value):
        if value == self._legacy_pipeline:
            return
        self._legacy_pipeline = value
        color_module.ENABLE_ADAPTIVE_DAMPING = not value
        self.legacyPipelineChanged.emit()
        self._update_preview()

    @Property(str, notify=statusChanged)
    def statusText(self):
        return self._status_text

    def _set_status(self, text):
        self._status_text = text
        self.statusChanged.emit()

    @Property(str, notify=statusChanged)
    def newProfileName(self):
        return self._new_profile_name

    @newProfileName.setter
    def newProfileName(self, value):
        value = value[:NEW_PROFILE_NAME_MAX_LEN]
        if value == self._new_profile_name:
            return
        self._new_profile_name = value
        self.statusChanged.emit()

    # ------------------------------------------------------------------
    # Load image / save profile - ported close to verbatim from
    # _on_load_tuning_image/_gather_color_slider_values/
    # _on_save_color_profile/_on_save_new_color_profile.
    # ------------------------------------------------------------------

    @Slot()
    def loadImage(self):
        from PySide6.QtWidgets import QFileDialog

        import cv2

        path, _ = QFileDialog.getOpenFileName(None, "Select image")
        if not path:
            return
        image = cv2.imread(path)
        if image is None:
            self._set_status(f"Could not load: {path}")
            return
        h, w = image.shape[:2]
        scale = TUNING_PREVIEW_MAX_DIM / max(h, w)
        resized = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        self._original_rgb = rgb
        self._original_revision += 1
        self.previewChanged.emit()
        self._set_status(str(path))
        self._update_preview()

    def _gather_slider_values(self):
        values = {}
        for key, (_label, _lo, _hi, _default, is_int) in PARAMS_BY_KEY.items():
            raw = self._slider_values[key]
            values[key] = raw if is_int else raw / FLOAT_SLIDER_SCALE
        return values

    @Slot()
    def saveProfile(self):
        name = self._current_profile
        if not name:
            return
        save_user_profile(name, self._gather_slider_values())
        self._set_status(f"Saved profile '{name}'")

    @Slot()
    def saveNewProfile(self):
        name = self._new_profile_name.strip()[:NEW_PROFILE_NAME_MAX_LEN]
        if not name:
            return
        save_user_profile(name, self._gather_slider_values())
        self._new_profile_name = ""
        self._profiles = _load_color_profiles()
        self._current_profile = name
        self.profilesChanged.emit()
        self._set_status(f"Saved new profile '{name}'")

    # ------------------------------------------------------------------
    # Preview - two QQuickImageProviders (Original/Adjusted), same
    # cache-busting-URL mechanism qml_development.md's Phase 0 spike proved
    # and Color's own backend already uses.
    # ------------------------------------------------------------------

    def _update_preview(self):
        if self._original_rgb is None:
            return
        filt = self.tuning_engine.get_filter_matrix(self._original_rgb)
        self._result_rgb = self.tuning_engine.apply_filter(self._original_rgb, filt)
        self._result_revision += 1
        self.previewChanged.emit()

    @Property(str, notify=previewChanged)
    def originalImageSource(self):
        return f"image://colortuningoriginal/frame?r={self._original_revision}"

    @Property(str, notify=previewChanged)
    def resultImageSource(self):
        return f"image://colortuningresult/frame?r={self._result_revision}"

    def render_original_frame(self):
        return _rgb_to_qimage(self._original_rgb)

    def render_result_frame(self):
        return _rgb_to_qimage(self._result_rgb)


def _rgb_to_qimage(rgb_array):
    if rgb_array is None:
        return QImage(1, 1, QImage.Format.Format_RGB888)
    rgb = np.ascontiguousarray(rgb_array).astype("uint8")
    h, w = rgb.shape[:2]
    qimage = QImage(rgb.data, w, h, rgb.strides[0], QImage.Format.Format_RGB888)
    return qimage.copy()


class ColorTuningImageProvider(QQuickImageProvider):
    def __init__(self, render_fn):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._render_fn = render_fn

    def requestImage(self, id, size, requestedSize):
        return self._render_fn()
