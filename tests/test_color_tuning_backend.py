"""
The Color Tuning page backend (uwmedia/backends/color_tuning_backend.py) and
the colour profiles behind it (utils/color_profiles.py, utils/color_params.py):
slider state, profile switching and saving, the legacy-pipeline switch and the
preview built from the fixture photo. The image dialog is stubbed, and saved
profiles go to the per-test config folder (conftest._isolated_user_dirs).
"""
import numpy as np
import pytest
import yaml

import ffmpeg.color as color_module
from conftest import PHOTO
from uwmedia.backends.color_tuning_backend import (
    FLOAT_SLIDER_SCALE,
    TUNING_PREVIEW_MAX_DIM,
    ColorTuningBackend,
    _rgb_to_qimage,
)
from utils.color_params import PARAM_GROUPS, PARAMS_BY_KEY
from utils.color_profiles import load_merged_color_profiles, save_user_profile, user_color_yaml_path


@pytest.fixture
def backend(settings_file, monkeypatch):
    # The legacy switch sets a module flag; monkeypatch puts it back afterwards.
    monkeypatch.setattr(color_module, "ENABLE_ADAPTIVE_DAMPING", color_module.ENABLE_ADAPTIVE_DAMPING)
    return ColorTuningBackend()


@pytest.fixture
def with_photo(backend, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(PHOTO), "")))
    backend.loadImage()
    return backend


def test_param_table_has_unique_keys_and_defaults_in_range():
    keys = [p[0] for _title, params in PARAM_GROUPS for p in params]
    assert len(keys) == len(set(keys)) == len(PARAMS_BY_KEY)
    for key, (_label, lo, hi, default, is_int) in PARAMS_BY_KEY.items():
        assert lo <= default <= hi, key
        if is_int:
            assert float(default).is_integer(), key


def test_bundled_profiles_only_use_known_params():
    for name, values in load_merged_color_profiles().items():
        unknown = set(values or {}) - set(PARAMS_BY_KEY)
        assert not unknown, f"profile {name!r} has unknown keys {unknown}"


def test_saving_a_user_profile_keeps_the_others(settings_file):
    save_user_profile("mine", {"red_scale": 0.5})
    save_user_profile("other", {"red_scale": 0.25})
    save_user_profile("mine", {"red_scale": 0.75})
    data = yaml.safe_load(user_color_yaml_path().read_text())
    assert data == {"mine": {"red_scale": 0.75}, "other": {"red_scale": 0.25}}
    merged = load_merged_color_profiles()
    assert merged["mine"]["red_scale"] == 0.75
    assert "default" in merged  # the bundled ones are still there


def test_a_user_profile_overrides_a_bundled_one(settings_file):
    save_user_profile("default", {"red_scale": 0.9})
    assert load_merged_color_profiles()["default"] == {"red_scale": 0.9}


def test_sliders_start_at_the_defaults(backend):
    groups = backend.groups
    assert [g["title"] for g in groups] == [title for title, _ in PARAM_GROUPS]
    assert sum(len(g["params"]) for g in groups) == len(PARAMS_BY_KEY)
    blur = PARAMS_BY_KEY["gw_blur_radius"]
    assert backend.sliderValues["gw_blur_radius"] == blur[3]
    assert backend.sliderTexts["gw_blur_radius"] == str(blur[3])
    assert backend.sliderValues["red_scale"] == round(PARAMS_BY_KEY["red_scale"][3] * FLOAT_SLIDER_SCALE)
    assert backend.sliderTexts["red_scale"] == f"{PARAMS_BY_KEY['red_scale'][3]:.3f}"
    assert backend.statusText == "No image loaded"
    assert backend.currentProfile in backend.profileList


def test_moving_and_resetting_a_slider(backend):
    backend.setSliderValue("red_scale", 4321)
    assert backend.tuning_engine.red_scale == pytest.approx(0.4321)
    assert backend.sliderTexts["red_scale"] == "0.432"
    backend.setSliderValue("gw_blur_radius", 15)
    assert backend.tuning_engine.gw_blur_radius == 15

    backend.resetSlider("red_scale")
    expected = backend.tuning_default_profile.get("red_scale", PARAMS_BY_KEY["red_scale"][3])
    assert backend.tuning_engine.red_scale == pytest.approx(expected)


def test_switching_profile_loads_its_values(backend):
    save_user_profile("deep", {"red_scale": 0.8, "gw_blur_radius": 21})
    backend.currentProfile = "deep"
    assert backend.currentProfile == "deep"
    assert backend.sliderValues["red_scale"] == 8000
    assert backend.sliderValues["gw_blur_radius"] == 21
    assert backend.tuning_engine.gw_blur_radius == 21
    backend.currentProfile = ""  # ignored
    assert backend.currentProfile == "deep"


def test_saving_profiles_from_the_sliders(backend):
    backend.setSliderValue("red_scale", 5000)
    backend.saveProfile()
    assert backend.statusText == f"Saved profile '{backend.currentProfile}'"
    assert load_merged_color_profiles()[backend.currentProfile]["red_scale"] == 0.5

    backend.newProfileName = "a-very-long-profile-name"
    assert backend.newProfileName == "a-very-lon"  # 10 characters at most
    backend.saveNewProfile()
    assert backend.currentProfile == "a-very-lon"
    assert "a-very-lon" in backend.profileList
    assert backend.newProfileName == ""
    saved = load_merged_color_profiles()["a-very-lon"]
    assert set(saved) == set(PARAMS_BY_KEY)

    backend.newProfileName = "   "
    backend.saveNewProfile()  # blank names are not saved
    assert "" not in load_merged_color_profiles()


def test_cancelled_image_dialog_changes_nothing(backend, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))
    backend.loadImage()
    assert backend.statusText == "No image loaded"
    assert backend.render_original_frame().size().toTuple() == (1, 1)  # the empty placeholder


def test_unreadable_image_is_reported(backend, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    bad = tmp_path / "broken.jpg"
    bad.write_bytes(b"not an image")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(bad), "")))
    backend.loadImage()
    assert backend.statusText == f"Could not load: {bad}"


def test_loaded_photo_gives_a_scaled_preview(with_photo):
    b = with_photo
    assert b.statusText == str(PHOTO)
    original = b.render_original_frame()
    assert max(original.width(), original.height()) == TUNING_PREVIEW_MAX_DIM
    result = b.render_result_frame()
    assert (result.width(), result.height()) == (original.width(), original.height())
    assert b._result_rgb.dtype == np.uint8
    assert not np.array_equal(b._result_rgb, b._original_rgb)  # the correction did something


def test_preview_follows_the_sliders_and_the_legacy_switch(with_photo):
    b = with_photo
    first_source = b.resultImageSource
    first = b._result_rgb.copy()

    b.setSliderValue("cifval", 0)  # blend weight 0: no restoration
    assert b.resultImageSource != first_source
    assert not np.array_equal(b._result_rgb, first)

    b.legacyPipeline = True
    assert color_module.ENABLE_ADAPTIVE_DAMPING is False
    b.legacyPipeline = False
    assert color_module.ENABLE_ADAPTIVE_DAMPING is True


def test_rgb_to_qimage_keeps_size_and_pixels():
    rgb = np.zeros((4, 6, 3), dtype=np.uint8)
    rgb[1, 2] = (10, 20, 30)
    img = _rgb_to_qimage(rgb)
    assert (img.width(), img.height()) == (6, 4)
    px = img.pixelColor(2, 1)
    assert (px.red(), px.green(), px.blue()) == (10, 20, 30)
    assert _rgb_to_qimage(None).size().toTuple() == (1, 1)
