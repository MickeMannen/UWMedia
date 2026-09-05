import asyncio
import json
import os
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import toga
from PIL import Image as PILImage
from toga.sources import AccessorColumn
from toga.style import Pack
from toga.style.pack import COLUMN, HIDDEN, ROW, VISIBLE

import ffmpeg.color as color_module
from ffmpeg.color import ColorCorrectionEngine
from gui.hud_renderer import draw_hud
from metadata.exif import MetadataHandler
from models.dive import Waypoint
from models.manager import DiveManager
from parsers.garmin import GarminParser
from parsers.subsurface import SubsurfaceParser
from parsers.uddf import UDDFParser
from utils.app_settings import add_unique, get_fields, load_settings, set_field, update_settings
from utils.color_params import PARAM_GROUPS, PARAMS_BY_KEY
from utils.color_profiles import (
    load_merged_color_profiles,
    save_user_profile,
    user_color_yaml_path,
)
from utils.hud_designer import (
    ANCHORS,
    MARKER_STYLES,
    align_elements,
    available_telemetry_fields,
    build_layout_json,
    element_display_name,
    element_position,
    hit_test,
    measure_element_box,
    parse_layout_elements,
    resolve_skin_position,
    skin_pixel_size,
)
from utils.layouts import list_layouts, user_layouts_dir
from utils.tag_editor import (
    TAG_EDITOR_EXTENSIONS,
    TAG_GUIDE,
    TARGET_TAGS,
    TZ_MODE_OPTIONS,
    TZ_OFFSETS,
    calculate_dji_datetimes,
    local_tz_offset_string,
    parse_date_from_filename,
)

THEME = {
    "sidebar_bg": "#1F2937",
    "sidebar_text": "#E5E7EB",
    "nav_active_bg": "#0EA5A4",
    "nav_active_text": "#FFFFFF",
    "text_muted": "#6B7280",
}

SECTIONS = ("Process", "Color Tuning", "Tag Editor", "HUD Designer", "Advanced", "Activity")

TUNING_PREVIEW_MAX_DIM = 600
DESIGNER_CANVAS_WIDTH = 900
DESIGNER_MANUFACTURER_MODELS = {
    "Shearwater": ["Perdix2", "Peregrine TX"],
    "Garmin": ["x50i"],
    "Generic": [],
}
DESIGNER_MARKER_LABELS = {"dot": "Highlight Dot", "cross": "Cross", "bold_cross": "Bold Cross"}
NEW_PROFILE_NAME_MAX_LEN = 10

# Every Process/Advanced field whose value should survive a restart, grouped
# by widget kind (each kind reads/restores its `.value` the same way, but
# must be restored in this order - see _restore_persisted_fields).
PERSISTED_TEXT_FIELDS = (
    "source_input", "output_input", "layout_input", "logs_input",
    "filename_format_input", "move_original_input", "render_output_input",
    "render_log_format_input", "start_time_input", "end_time_input",
)
PERSISTED_SELECTION_FIELDS = (
    "layout_select", "color_profile", "filename_format_select", "render_log_format_select",
)
PERSISTED_SWITCH_FIELDS = (
    "color_switch", "hw_accel_switch", "debug_switch", "summary_switch",
    "no_overwrite_switch", "render_video_log_switch",
)

LAYOUT_NONE = "None"
LAYOUT_CUSTOM = "Custom…"

FILENAME_FORMAT_PRESETS = [
    ("Keep original filename", ""),
    ("Date + time (20260905_143000)", "%Y%m%d_%H%M%S"),
    ("Date + time + color (20260905_143000_color)", "%Y%m%d_%H%M%S_color"),
    ("Date only (20260905)", "%Y%m%d"),
]
FORMAT_CUSTOM = "Custom…"

RENDER_LOG_FORMAT_PRESETS = [
    ("source_filename_hudname", "{filename}_{hud}"),
    ("source_datetaken_hudname", "{datetaken:%Y%m%d_%H%M%S}_{hud}"),
]


def load_color_profiles():
    try:
        data = load_merged_color_profiles()
        return list(data.keys()) or ["default"]
    except Exception:
        return ["default"]


class UWMediaApp(toga.App):
    def startup(self):
        self._build_fields()

        # Process/Advanced/Activity share one scrolling viewport, swapped in
        # and out of content_box. Color Tuning is deliberately not part of
        # that: its own layout keeps the image preview fixed and scrolls only
        # the slider cards beneath it (see _build_color_tuning_section) - for
        # that split to hold its bounded height, it can't itself be nested
        # inside another, unbounded-height ScrollContainer.
        self.sections = {
            "Process": self._build_process_section(),
            "Tag Editor": self._build_tag_editor_section(),
            "Advanced": self._build_advanced_section(),
            "Activity": self._build_activity_section(),
        }
        self.color_tuning_view = self._build_color_tuning_section()
        # Same reasoning as Color Tuning: the canvas needs to stay put while
        # only the (much taller) controls panel scrolls, so this can't be
        # nested inside the shared content_scroll either.
        self.hud_designer_view = self._build_hud_designer_section()

        # Only safe once every section above has been built: restoring a
        # switch like render_video_log_switch fires its on_change, which
        # reaches into row widgets (render_output_row etc.) those sections
        # just created.
        self._restore_persisted_fields()

        self.content_box = toga.Box(style=Pack(direction=COLUMN, flex=1))
        self.content_scroll = toga.ScrollContainer(
            horizontal=False, vertical=True, content=self.content_box, style=Pack(flex=1)
        )

        self.main_content_area = toga.Box(style=Pack(direction=COLUMN, flex=1))

        main_column = toga.Box(style=Pack(direction=COLUMN, flex=1))
        main_column.add(self._build_topbar())
        main_column.add(self.main_content_area)

        root = toga.Box(style=Pack(direction=ROW))
        root.add(self._build_sidebar())
        root.add(main_column)

        self.main_window = toga.MainWindow(title=self.formal_name, size=(960, 680))
        self.main_window.content = root
        self.main_window.show()

        self._select_section("Process")

    # ------------------------------------------------------------------
    # Widget construction
    # ------------------------------------------------------------------

    def _build_fields(self):
        # Native form controls (TextInput/Selection/Switch) are left without
        # forced colors so they keep following the system light/dark
        # appearance, same as before the redesign — Toga's Pack styling
        # doesn't reliably override their native-drawn foreground/background
        # on macOS, and fighting that produces low-contrast/broken-looking
        # controls in dark mode.
        field_style = Pack(flex=1)

        self.source_input = toga.TextInput(style=field_style)
        self.output_input = toga.TextInput(style=field_style)
        self.logs_input = toga.TextInput(style=field_style)
        self.layout_input = toga.TextInput(style=field_style)
        self.move_original_input = toga.TextInput(style=field_style)

        self.layout_select = toga.Selection(
            items=[LAYOUT_NONE], on_change=self.on_layout_select_change, style=field_style
        )
        self._refresh_layout_choices()

        self.color_switch = toga.Switch("Apply color correction")
        self.color_profile = toga.Selection(items=load_color_profiles())

        self.start_time_input = toga.TextInput(placeholder="HH:MM:SS", style=field_style)
        self.end_time_input = toga.TextInput(placeholder="HH:MM:SS", style=field_style)

        self.hw_accel_switch = toga.Switch(
            "Hardware acceleration", value=True, style=Pack(margin_bottom=8)
        )
        self.debug_switch = toga.Switch("Debug output", style=Pack(margin_bottom=8))
        self.summary_switch = toga.Switch("Show summary", style=Pack(margin_bottom=8))
        self.no_overwrite_switch = toga.Switch("Skip if target exists", style=Pack(margin_bottom=8))

        self.filename_format_input = toga.TextInput(
            placeholder="%Y%m%d_%H%M%S_color", style=field_style
        )
        self.filename_format_select = toga.Selection(
            items=[label for label, _ in FILENAME_FORMAT_PRESETS],
            on_change=self.on_filename_format_select_change,
            style=field_style,
        )
        self._refresh_filename_format_choices()

        self.render_output_input = toga.TextInput(style=field_style)
        self.render_video_log_switch = toga.Switch(
            "Render video/photo log overlay batch",
            on_change=self.on_render_video_log_toggle,
        )
        self.render_log_format_input = toga.TextInput(
            placeholder="{filename}_{hud}", style=field_style
        )
        self.render_log_format_select = toga.Selection(
            items=[label for label, _ in RENDER_LOG_FORMAT_PRESETS],
            on_change=self.on_render_log_format_select_change,
            style=field_style,
        )
        self._refresh_render_log_format_choices()
        self.render_log_format_select.value = "source_datetaken_hudname"
        self.render_log_format_input.value = self.render_log_format_choices["source_datetaken_hudname"]

        self.new_filename_format_input = toga.TextInput(
            placeholder='e.g. "%Y-%m-%d_%H-%M-%S"', style=field_style
        )
        self.new_render_log_format_input = toga.TextInput(
            placeholder='e.g. "{hud}_{filename}"', style=field_style
        )

        self.layouts_dir_input = toga.TextInput(style=field_style, readonly=True)
        self.color_dir_input = toga.TextInput(style=field_style, readonly=True)
        self._refresh_location_inputs()

        self._build_color_tuning_fields(field_style)
        self._build_tag_editor_fields(field_style)
        self._build_hud_designer_fields(field_style)

        self.log_output = toga.MultilineTextInput(readonly=True, style=Pack(flex=1, height=200))
        self.log_output.style.visibility = HIDDEN
        self.log_label = toga.Label("Terminal output", style=Pack(margin_top=10))
        self.log_label.style.visibility = HIDDEN

        self.run_button = toga.Button("Run", on_press=self.on_run, style=Pack(margin_left=10))
        self.progress_bar = toga.ProgressBar(max=None, style=Pack(width=120, margin_left=10))
        self.progress_bar.style.visibility = HIDDEN

        self.status_label = toga.Label("Idle", style=Pack(color=THEME["text_muted"]))
        self.activity_status_label = toga.Label(
            "Idle", style=Pack(margin_bottom=8, color=THEME["text_muted"])
        )

        self.show_terminal_switch = toga.Switch(
            "Show terminal output",
            value=False,
            on_change=self.on_show_terminal_toggle,
            style=Pack(margin_top=10),
        )

        self.is_running = False
        self.current_process = None
        self.abort_requested = False

        self._wire_field_persistence()

    # ------------------------------------------------------------------
    # Process/Advanced field persistence
    # ------------------------------------------------------------------

    def _wire_field_persistence(self):
        # Chain onto whatever on_change a field already has (if any) rather
        # than replacing it, so existing behavior (e.g. toggling a custom-
        # path row) still runs before the value is persisted.
        for name in PERSISTED_TEXT_FIELDS + PERSISTED_SELECTION_FIELDS + PERSISTED_SWITCH_FIELDS:
            widget = getattr(self, name)
            widget.on_change = self._chain_with_persist(widget.on_change, name)

    def _chain_with_persist(self, existing_handler, key):
        # existing_handler is already Toga's wrapped callable (from the
        # widget.on_change getter): it takes no arguments itself, since it
        # closes over the widget/interface from when it was first wrapped -
        # passing `widget` here as well would double up the argument the
        # original handler receives.
        def handler(widget):
            existing_handler()
            set_field(key, widget.value)

        return handler

    def _restore_persisted_fields(self):
        # Text first (so a "Custom..." selection has its free-text value
        # ready), then selections (which may overwrite paired *_input text
        # for a non-custom choice, and drive dependent row visibility), then
        # switches last (on_render_video_log_toggle reads render_log_format_
        # select.value, so that must already be restored).
        fields = get_fields()
        for name in PERSISTED_TEXT_FIELDS:
            if name in fields:
                getattr(self, name).value = fields[name]
        for name in PERSISTED_SELECTION_FIELDS:
            if name in fields:
                try:
                    getattr(self, name).value = fields[name]
                except ValueError:
                    pass  # saved choice no longer exists (e.g. layout file removed)
        for name in PERSISTED_SWITCH_FIELDS:
            if name in fields:
                getattr(self, name).value = bool(fields[name])

    def _build_color_tuning_fields(self, field_style):
        # One live engine instance backs the whole tuning UI - slider changes
        # mutate its attributes directly and re-run the (fast, resized-preview)
        # pipeline, same approach as the Qt tuning tool this section replaces.
        self.tuning_engine = ColorCorrectionEngine(ffmpeg_tool=None, color_profile="default")
        self.tuning_default_profile = load_merged_color_profiles().get("default", {})
        self._tuning_original_rgb = None
        self._tuning_block_updates = False

        self.color_tuning_profile_select = toga.Selection(
            items=load_color_profiles(), on_change=self.on_color_tuning_profile_change
        )
        self.color_original_view = toga.ImageView(style=Pack(flex=1, height=260))
        self.color_result_view = toga.ImageView(style=Pack(flex=1, height=260))
        self.color_tuning_status_label = toga.Label(
            "No image loaded", style=Pack(margin_top=5, color=THEME["text_muted"])
        )
        self.legacy_pipeline_switch = toga.Switch(
            "Use legacy pipeline", on_change=self.on_legacy_pipeline_toggle
        )
        self.new_color_profile_input = toga.TextInput(
            placeholder="New profile name (max 10 chars)",
            on_change=self.on_new_color_profile_name_change,
            style=field_style,
        )

        self.color_sliders = {}
        self.color_slider_labels = {}
        for _, params in PARAM_GROUPS:
            for key, _label, lo, hi, default, is_int in params:
                self.color_sliders[key] = toga.Slider(
                    min=lo,
                    max=hi,
                    value=default,
                    tick_count=(int(hi - lo) + 1) if is_int else None,
                    on_change=self._make_color_slider_handler(key, is_int),
                    style=Pack(flex=1),
                )
                self.color_slider_labels[key] = toga.Label(
                    self._format_color_value(default, is_int), style=Pack(width=60)
                )

    # ------------------------------------------------------------------
    # Color Tuning
    # ------------------------------------------------------------------

    def _format_color_value(self, value, is_int):
        return str(int(round(value))) if is_int else f"{value:.3f}"

    def _make_color_slider_handler(self, key, is_int):
        def handler(widget):
            value = int(round(widget.value)) if is_int else widget.value
            self.color_slider_labels[key].text = self._format_color_value(value, is_int)
            setattr(self.tuning_engine, key, value)
            if not self._tuning_block_updates:
                self._update_color_tuning_preview()

        return handler

    def _make_color_reset_handler(self, key):
        def handler(widget):
            _, _lo, _hi, default, _is_int = PARAMS_BY_KEY[key]
            self.color_sliders[key].value = self.tuning_default_profile.get(key, default)

        return handler

    def _color_slider_row(self, key, label_text):
        box = toga.Box(style=Pack(direction=ROW, margin_bottom=5, align_items="center"))
        box.add(toga.Label(label_text, style=Pack(width=190)))
        box.add(self.color_sliders[key])
        box.add(self.color_slider_labels[key])
        box.add(
            toga.Button(
                "↺", on_press=self._make_color_reset_handler(key), style=Pack(width=28, margin_left=5)
            )
        )
        return box

    def _update_color_tuning_preview(self):
        if self._tuning_original_rgb is None:
            return
        filt = self.tuning_engine.get_filter_matrix(self._tuning_original_rgb)
        result = self.tuning_engine.apply_filter(self._tuning_original_rgb, filt)
        self.color_result_view.image = toga.Image(PILImage.fromarray(result))

    def _apply_color_profile_to_sliders(self, name):
        profile = load_merged_color_profiles().get(name, {})
        self._tuning_block_updates = True
        for key, (_label, _lo, _hi, default, _is_int) in PARAMS_BY_KEY.items():
            self.color_sliders[key].value = profile.get(key, default)
        self._tuning_block_updates = False
        self._update_color_tuning_preview()

    def on_color_tuning_profile_change(self, widget):
        self._apply_color_profile_to_sliders(widget.value)

    def on_legacy_pipeline_toggle(self, widget):
        color_module.ENABLE_ADAPTIVE_DAMPING = not widget.value
        self._update_color_tuning_preview()

    async def on_load_tuning_image(self, widget):
        path = await self.main_window.dialog(toga.OpenFileDialog("Select image"))
        if not path:
            return
        image = cv2.imread(str(path))
        if image is None:
            self.color_tuning_status_label.text = f"Could not load: {path}"
            return
        h, w = image.shape[:2]
        scale = TUNING_PREVIEW_MAX_DIM / max(h, w)
        resized = cv2.resize(
            image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA
        )
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        self._tuning_original_rgb = rgb
        self.color_original_view.image = toga.Image(PILImage.fromarray(rgb))
        self.color_tuning_status_label.text = str(path)
        self._update_color_tuning_preview()

    def _gather_color_slider_values(self):
        values = {}
        for key, (_label, _lo, _hi, _default, is_int) in PARAMS_BY_KEY.items():
            raw = self.color_sliders[key].value
            values[key] = int(round(raw)) if is_int else float(raw)
        return values

    def on_new_color_profile_name_change(self, widget):
        if len(widget.value) > NEW_PROFILE_NAME_MAX_LEN:
            widget.value = widget.value[:NEW_PROFILE_NAME_MAX_LEN]

    def on_save_color_profile(self, widget):
        name = self.color_tuning_profile_select.value
        if not name:
            return
        save_user_profile(name, self._gather_color_slider_values())
        self.color_tuning_status_label.text = f"Saved profile '{name}'"

    def on_save_new_color_profile(self, widget):
        value = self.new_color_profile_input.value
        name = value.strip()[:NEW_PROFILE_NAME_MAX_LEN] if value else ""
        if not name:
            return
        save_user_profile(name, self._gather_color_slider_values())
        self.new_color_profile_input.value = ""
        self.color_tuning_profile_select.items = load_color_profiles()
        self.color_tuning_profile_select.value = name
        self.color_tuning_status_label.text = f"Saved new profile '{name}'"

    # ------------------------------------------------------------------
    # Layout / color / filename-format choice lists
    # ------------------------------------------------------------------

    def _refresh_layout_choices(self):
        self.layout_choices = {LAYOUT_NONE: ""}
        for name, path in list_layouts():
            self.layout_choices[name] = str(path)
        self.layout_choices[LAYOUT_CUSTOM] = None
        self.layout_select.items = list(self.layout_choices.keys())
        self.layout_select.value = LAYOUT_NONE

    def on_layout_select_change(self, widget):
        is_custom = widget.value == LAYOUT_CUSTOM
        if hasattr(self, "layout_custom_row"):
            self.layout_custom_row.style.visibility = VISIBLE if is_custom else HIDDEN
        if not is_custom:
            self.layout_input.value = self.layout_choices.get(widget.value) or ""

    def _refresh_filename_format_choices(self):
        self.filename_format_choices = dict(FILENAME_FORMAT_PRESETS)
        for pattern in load_settings().get("filename_formats") or []:
            self.filename_format_choices[pattern] = pattern
        items = list(self.filename_format_choices.keys()) + [FORMAT_CUSTOM]
        self.filename_format_select.items = items
        if self.filename_format_select.value not in items:
            self.filename_format_select.value = items[0]

    def on_filename_format_select_change(self, widget):
        is_custom = widget.value == FORMAT_CUSTOM
        if hasattr(self, "filename_format_custom_row"):
            self.filename_format_custom_row.style.visibility = VISIBLE if is_custom else HIDDEN
        if not is_custom:
            self.filename_format_input.value = self.filename_format_choices.get(widget.value, "")

    def on_add_filename_format(self, widget):
        pattern = self.new_filename_format_input.value.strip() if self.new_filename_format_input.value else ""
        if not pattern:
            return
        add_unique("filename_formats", pattern)
        self.new_filename_format_input.value = ""
        self._refresh_filename_format_choices()
        self.filename_format_select.value = pattern

    def _refresh_render_log_format_choices(self):
        self.render_log_format_choices = dict(RENDER_LOG_FORMAT_PRESETS)
        for pattern in load_settings().get("render_log_filename_formats") or []:
            self.render_log_format_choices[pattern] = pattern
        items = list(self.render_log_format_choices.keys()) + [FORMAT_CUSTOM]
        self.render_log_format_select.items = items
        if self.render_log_format_select.value not in items:
            self.render_log_format_select.value = items[0]

    def on_render_log_format_select_change(self, widget):
        is_custom = widget.value == FORMAT_CUSTOM
        if hasattr(self, "render_log_format_custom_row"):
            visible = is_custom and getattr(self.render_video_log_switch, "value", False)
            self.render_log_format_custom_row.style.visibility = VISIBLE if visible else HIDDEN
        if not is_custom:
            self.render_log_format_input.value = self.render_log_format_choices.get(widget.value, "")

    def on_add_render_log_format(self, widget):
        value = self.new_render_log_format_input.value
        pattern = value.strip() if value else ""
        if not pattern:
            return
        add_unique("render_log_filename_formats", pattern)
        self.new_render_log_format_input.value = ""
        self._refresh_render_log_format_choices()
        self.render_log_format_select.value = pattern

    def _refresh_location_inputs(self):
        self.layouts_dir_input.value = str(user_layouts_dir())
        self.color_dir_input.value = str(user_color_yaml_path().parent)

    async def on_choose_layouts_dir(self, widget):
        path = await self.main_window.dialog(toga.SelectFolderDialog("Select layouts folder"))
        if path:
            update_settings(layouts_dir=str(path))
            self._refresh_location_inputs()
            self._refresh_layout_choices()

    def on_reset_layouts_dir(self, widget):
        update_settings(layouts_dir=None)
        self._refresh_location_inputs()
        self._refresh_layout_choices()

    async def on_choose_color_dir(self, widget):
        path = await self.main_window.dialog(toga.SelectFolderDialog("Select color profiles folder"))
        if path:
            update_settings(color_profiles_dir=str(path))
            self._refresh_location_inputs()
            self.color_profile.items = load_color_profiles()

    def on_reset_color_dir(self, widget):
        update_settings(color_profiles_dir=None)
        self._refresh_location_inputs()
        self.color_profile.items = load_color_profiles()

    def _build_sidebar(self):
        sidebar = toga.Box(
            style=Pack(direction=COLUMN, width=200, background_color=THEME["sidebar_bg"])
        )
        sidebar.add(
            toga.Label(
                "UWMedia",
                style=Pack(
                    margin=(18, 16),
                    font_weight="bold",
                    font_size=16,
                    color=THEME["sidebar_text"],
                    background_color=THEME["sidebar_bg"],
                ),
            )
        )

        self.nav_buttons = {}
        for name in SECTIONS:
            button = toga.Button(
                name,
                on_press=self._nav_handler(name),
                style=Pack(
                    width=200,
                    margin_bottom=2,
                    background_color=THEME["sidebar_bg"],
                    color=THEME["sidebar_text"],
                ),
            )
            self.nav_buttons[name] = button
            sidebar.add(button)

        return sidebar

    def _nav_handler(self, name):
        def handler(widget):
            self._select_section(name)

        return handler

    def _select_section(self, name):
        # Swap the visible section by actually removing/adding it from its
        # container, rather than toggling style.display - on this Toga
        # version/backend, a display=NONE box's content still rendered/painted
        # (though not reliably positioned), bleeding the "hidden" section's
        # widgets into view below the active one. Only ever having one
        # section attached at a time sidesteps that.
        self.active_section = name
        self.main_content_area.clear()
        if name == "Color Tuning":
            self.main_content_area.add(self.color_tuning_view)
        elif name == "HUD Designer":
            self.main_content_area.add(self.hud_designer_view)
        else:
            self.content_box.clear()
            self.content_box.add(self.sections[name])
            self.main_content_area.add(self.content_scroll)

        # The Run/Idle controls drive the CLI subprocess pipeline (Process/
        # Advanced/Batch); Color Tuning, Tag Editor and HUD Designer are
        # self-contained in-app tools that never touch that pipeline, so
        # they're just clutter there.
        run_controls_visible = (
            HIDDEN if name in ("Color Tuning", "Tag Editor", "HUD Designer") else VISIBLE
        )
        self.status_label.style.visibility = run_controls_visible
        self.run_button.style.visibility = run_controls_visible

        for section_name, button in self.nav_buttons.items():
            selected = section_name == name
            button.style.background_color = (
                THEME["nav_active_bg"] if selected else THEME["sidebar_bg"]
            )
            button.style.color = THEME["nav_active_text"] if selected else THEME["sidebar_text"]
        self.section_title_label.text = name

    def _build_topbar(self):
        self.section_title_label = toga.Label(
            "Process",
            style=Pack(flex=1, font_weight="bold", font_size=14, color=THEME["nav_active_bg"]),
        )
        topbar = toga.Box(
            style=Pack(direction=ROW, align_items="center", margin=(14, 16))
        )
        topbar.add(self.section_title_label)
        topbar.add(self.status_label)
        topbar.add(self.progress_bar)
        topbar.add(self.run_button)
        return topbar

    def _card(self, title, *widgets):
        # No filled background here: native controls (TextInput/Switch/
        # Selection) don't reliably take Toga's background/color overrides
        # on macOS, so a card fill would fight the system's light/dark
        # rendering of those controls. Cards are grouped instead with an
        # accent-colored header and generous spacing.
        card = toga.Box(style=Pack(direction=COLUMN, margin=(0, 16, 24, 16)))
        card.add(
            toga.Label(
                title,
                style=Pack(
                    margin_bottom=8,
                    font_weight="bold",
                    color=THEME["nav_active_bg"],
                ),
            )
        )
        for widget in widgets:
            card.add(widget)
        return card

    def _build_process_section(self):
        section = toga.Box(style=Pack(direction=COLUMN))

        color_box = toga.Box(style=Pack(direction=ROW))
        color_box.add(self.color_switch)
        color_box.add(self.color_profile)

        self.layout_custom_row = self._row(
            "Custom path",
            self.layout_input,
            self._file_or_folder_buttons(self.layout_input),
        )
        self.layout_custom_row.style.visibility = HIDDEN

        self.filename_format_custom_row = self._row(
            "Custom pattern", self.filename_format_input, None
        )
        self.filename_format_custom_row.style.visibility = HIDDEN

        section.add(
            self._card(
                "Source & output",
                self._row("Source", self.source_input, self._file_or_folder_buttons(self.source_input)),
                self._row("Output", self.output_input, self._file_or_folder_buttons(self.output_input)),
                self._row("Layout / HUD package", self.layout_select, None),
                self.layout_custom_row,
            )
        )
        section.add(self._card("Color correction", color_box))
        section.add(
            self._card(
                "Metadata",
                self._row("Dive logs", self.logs_input, self._browse_button(self.logs_input, folder=True)),
                self._row("Filename format", self.filename_format_select, None),
                self.filename_format_custom_row,
            )
        )

        self.render_output_row = self._row(
            "Render output",
            self.render_output_input,
            self._browse_button(self.render_output_input, folder=True),
        )
        self.render_output_row.style.visibility = HIDDEN

        self.render_log_format_row = self._row(
            "Output filename pattern", self.render_log_format_select, None
        )
        self.render_log_format_row.style.visibility = HIDDEN

        self.render_log_format_custom_row = self._row(
            "Custom pattern", self.render_log_format_input, None
        )
        self.render_log_format_custom_row.style.visibility = HIDDEN

        section.add(
            self._card(
                "Batch & Render",
                self._row(
                    "Move original to",
                    self.move_original_input,
                    self._browse_button(self.move_original_input, folder=True),
                ),
                self.render_video_log_switch,
                self.render_output_row,
                self.render_log_format_row,
                self.render_log_format_custom_row,
            )
        )
        return section

    def _build_color_tuning_section(self):
        # Top (toolbar + image preview) stays in place; only the slider cards
        # scroll, in their own ScrollContainer below it - see the startup()
        # comment on why this section can't be nested in the shared
        # content_scroll for that split to hold.
        section = toga.Box(style=Pack(direction=COLUMN, flex=1))

        toolbar = toga.Box(style=Pack(direction=ROW, margin_bottom=8, align_items="center"))
        toolbar.add(toga.Button("Load Image…", on_press=self.on_load_tuning_image))
        toolbar.add(toga.Label("Profile:", style=Pack(margin=(0, 5, 0, 15))))
        toolbar.add(self.color_tuning_profile_select)
        toolbar.add(self.legacy_pipeline_switch)

        save_row = toga.Box(style=Pack(direction=ROW, align_items="center"))
        save_row.add(toga.Button("Save Profile", on_press=self.on_save_color_profile))
        save_row.add(self.new_color_profile_input)
        save_row.add(
            toga.Button("Save As New", on_press=self.on_save_new_color_profile, style=Pack(margin_left=5))
        )

        section.add(
            self._card("Sample image", toolbar, save_row, self.color_tuning_status_label)
        )

        images_row = toga.Box(style=Pack(direction=ROW))
        original_col = toga.Box(style=Pack(direction=COLUMN, flex=1, margin_right=8))
        original_col.add(toga.Label("Original", style=Pack(font_weight="bold", margin_bottom=4)))
        original_col.add(self.color_original_view)
        result_col = toga.Box(style=Pack(direction=COLUMN, flex=1, margin_left=8))
        result_col.add(toga.Label("Adjusted", style=Pack(font_weight="bold", margin_bottom=4)))
        result_col.add(self.color_result_view)
        images_row.add(original_col)
        images_row.add(result_col)
        section.add(self._card("Preview", images_row))

        sliders_box = toga.Box(style=Pack(direction=COLUMN))
        for group_title, params in PARAM_GROUPS:
            rows = [self._color_slider_row(key, label) for key, label, *_ in params]
            sliders_box.add(self._card(group_title, *rows))

        sliders_scroll = toga.ScrollContainer(
            horizontal=False, vertical=True, content=sliders_box, style=Pack(flex=1)
        )
        section.add(sliders_scroll)

        return section

    # ------------------------------------------------------------------
    # Tag Editor
    # ------------------------------------------------------------------

    def _build_tag_editor_fields(self, field_style):
        self.tag_meta_handler = MetadataHandler()
        self.tag_editor_files = []
        self.tag_editor_current_file = None
        self.tag_editor_current_tags = {}

        self.tag_editor_dir_label = toga.Label(
            "No directory selected", style=Pack(color=THEME["text_muted"], margin_bottom=8)
        )
        self.tag_editor_file_table = toga.Table(
            columns=[AccessorColumn("File", accessor="name")],
            on_select=self.on_tag_editor_file_select,
            style=Pack(flex=1, height=280),
        )

        self.tag_editor_file_name_label = toga.Label("None", style=Pack(font_weight="bold"))
        self.tag_editor_view_metadata_button = toga.Button(
            "View All Metadata", on_press=self.on_view_all_metadata, enabled=False
        )
        self.tag_editor_dji_label = toga.Label(
            "DJI file detected: values calculated from OriginalFilePath.",
            style=Pack(color="#4CAF50", font_weight="bold", margin_top=5),
        )
        self.tag_editor_dji_label.style.visibility = HIDDEN

        self.tag_inputs = {guide["tag"]: toga.TextInput(style=field_style) for guide in TAG_GUIDE}

        local_tz = local_tz_offset_string()
        tz_items = list(TZ_OFFSETS)
        if local_tz not in tz_items:
            tz_items.insert(0, local_tz)
        self.tag_editor_tz_select = toga.Selection(items=tz_items, value=local_tz, style=Pack(width=110))
        self.tag_editor_tz_mode_select = toga.Selection(items=list(TZ_MODE_OPTIONS), style=Pack(width=240))

        self.tag_editor_progress_bar = toga.ProgressBar(max=None, style=Pack(flex=1, margin_top=8))
        self.tag_editor_progress_bar.style.visibility = HIDDEN
        self.tag_editor_status_label = toga.Label(
            "", style=Pack(margin_top=5, color=THEME["text_muted"])
        )

    def _build_tag_editor_section(self):
        section = toga.Box(style=Pack(direction=COLUMN, flex=1))

        left = toga.Box(style=Pack(direction=COLUMN, width=260, margin_right=16))
        left.add(
            toga.Button(
                "Select Directory", on_press=self.on_tag_editor_select_dir, style=Pack(margin_bottom=8)
            )
        )
        left.add(self.tag_editor_dir_label)
        left.add(self.tag_editor_file_table)

        right = toga.Box(style=Pack(direction=COLUMN, flex=1))

        file_header = toga.Box(style=Pack(direction=ROW, align_items="center"))
        file_header.add(self.tag_editor_file_name_label)
        file_header.add(toga.Box(style=Pack(flex=1)))
        file_header.add(self.tag_editor_view_metadata_button)
        right.add(self._card("Selected file", file_header, self.tag_editor_dji_label))

        tag_boxes = []
        for guide in TAG_GUIDE:
            tag = guide["tag"]
            help_text = f"Intended: {guide['tz']}  |  Example: {guide['example']}  —  {guide['hint']}"
            box = toga.Box(style=Pack(direction=COLUMN, margin_bottom=10))
            box.add(toga.Label(tag, style=Pack(font_weight="bold")))
            box.add(self.tag_inputs[tag])
            box.add(toga.Label(help_text, style=Pack(color=THEME["text_muted"], font_size=10)))
            tag_boxes.append(box)
        right.add(self._card("Edit metadata tags", *tag_boxes))

        tz_row = toga.Box(style=Pack(direction=ROW, align_items="center"))
        tz_row.add(toga.Label("Timezone offset:", style=Pack(margin_right=5)))
        tz_row.add(self.tag_editor_tz_select)
        tz_row.add(toga.Label("Mode:", style=Pack(margin=(0, 5, 0, 15))))
        tz_row.add(self.tag_editor_tz_mode_select)
        tz_row.add(
            toga.Button(
                "Apply Timezone to All",
                on_press=self.on_batch_update_timezone,
                style=Pack(margin_left=10),
            )
        )
        right.add(self._card("Batch set directory timezone", tz_row))

        button_row = toga.Box(style=Pack(direction=ROW))
        button_row.add(toga.Button("Revert Changes", on_press=self.on_revert_tag_changes))
        button_row.add(
            toga.Button("Update All (DJI)", on_press=self.on_update_all_tags, style=Pack(margin_left=8))
        )
        button_row.add(
            toga.Button("Write to File", on_press=self.on_write_tags, style=Pack(margin_left=8))
        )
        right.add(button_row)
        right.add(self.tag_editor_progress_bar)
        right.add(self.tag_editor_status_label)

        columns = toga.Box(style=Pack(direction=ROW, flex=1))
        columns.add(left)
        columns.add(right)
        section.add(columns)
        return section

    def _set_tag_editor_busy(self, busy, text):
        self.tag_editor_progress_bar.style.visibility = VISIBLE if busy else HIDDEN
        if busy:
            self.tag_editor_progress_bar.start()
        else:
            self.tag_editor_progress_bar.stop()
        self.tag_editor_status_label.text = text

    async def on_tag_editor_select_dir(self, widget):
        path = await self.main_window.dialog(toga.SelectFolderDialog("Select media directory"))
        if not path:
            return
        directory = Path(path)
        self.tag_editor_dir_label.text = str(directory)

        files = sorted(
            (f for f in directory.iterdir() if f.is_file() and f.suffix.lower() in TAG_EDITOR_EXTENSIONS),
            key=lambda f: f.name.lower(),
        )
        self.tag_editor_files = files
        self.tag_editor_file_table.data = [{"name": f.name, "path": str(f)} for f in files]
        self.tag_editor_current_file = None
        self.tag_editor_view_metadata_button.enabled = False
        if files:
            self._display_tag_editor_file(files[0])

    def on_tag_editor_file_select(self, widget):
        row = widget.selection
        if row is None:
            self.tag_editor_view_metadata_button.enabled = False
            return
        self._display_tag_editor_file(Path(row.path))

    def _display_tag_editor_file(self, file_path):
        self.tag_editor_current_file = file_path
        self.tag_editor_file_name_label.text = file_path.name
        self.tag_editor_view_metadata_button.enabled = True

        tags_to_get = TARGET_TAGS + ["QuickTime:OriginalFilePath"]
        self.tag_editor_current_tags = self.tag_meta_handler.get_tags(file_path, tags_to_get)

        calculated = calculate_dji_datetimes(file_path, self.tag_editor_current_tags)
        if calculated:
            self.tag_editor_dji_label.style.visibility = VISIBLE
            for tag in TARGET_TAGS:
                self.tag_inputs[tag].value = calculated[tag]
        else:
            self.tag_editor_dji_label.style.visibility = HIDDEN
            for tag in TARGET_TAGS:
                self.tag_inputs[tag].value = self.tag_editor_current_tags.get(tag, "")

    def on_revert_tag_changes(self, widget):
        if self.tag_editor_current_file:
            self._display_tag_editor_file(self.tag_editor_current_file)

    async def on_write_tags(self, widget):
        if not self.tag_editor_current_file:
            return
        updates = {}
        for tag, tag_input in self.tag_inputs.items():
            new_val = (tag_input.value or "").strip()
            if new_val != self.tag_editor_current_tags.get(tag, ""):
                updates[tag] = new_val

        if not updates:
            await self.main_window.dialog(toga.InfoDialog("No Changes", "No changes detected to update."))
            return

        try:
            self.tag_meta_handler.set_tags(self.tag_editor_current_file, updates)
            self._display_tag_editor_file(self.tag_editor_current_file)
            await self.main_window.dialog(
                toga.InfoDialog("Success", f"Updated {len(updates)} tags successfully.")
            )
        except Exception as e:
            await self.main_window.dialog(toga.ErrorDialog("Error", f"Failed to update tags: {e}"))

    def _update_all_worker(self, file_path):
        tags_to_get = TARGET_TAGS + ["QuickTime:OriginalFilePath"]
        current_tags = self.tag_meta_handler.get_tags(file_path, tags_to_get)
        calculated = calculate_dji_datetimes(file_path, current_tags)
        if not calculated:
            return False
        updates = {
            tag: calculated[tag] for tag in TARGET_TAGS if calculated[tag] != current_tags.get(tag, "")
        }
        if updates:
            self.tag_meta_handler.set_tags(file_path, updates)
            return True
        return False

    async def on_update_all_tags(self, widget):
        files = self.tag_editor_files
        if not files:
            await self.main_window.dialog(toga.InfoDialog("No Files", "No files in the list to update."))
            return

        proceed = await self.main_window.dialog(
            toga.ConfirmDialog(
                "Confirm Update All",
                f"Scan all {len(files)} files and automatically update DJI videos with corrected datetimes?",
            )
        )
        if not proceed:
            return

        self._set_tag_editor_busy(True, f"Processing 0/{len(files)}...")
        updated_count = 0
        error_count = 0
        for i, file_path in enumerate(files):
            self.tag_editor_status_label.text = f"Processing {i + 1}/{len(files)}: {file_path.name}"
            try:
                if await asyncio.to_thread(self._update_all_worker, file_path):
                    updated_count += 1
            except Exception as e:
                error_count += 1
                print(f"Error updating {file_path.name}: {e}")
        self._set_tag_editor_busy(False, "")

        if self.tag_editor_current_file:
            self._display_tag_editor_file(self.tag_editor_current_file)

        if error_count:
            await self.main_window.dialog(
                toga.ErrorDialog(
                    "Finished with Errors",
                    f"Successfully updated {updated_count} files.\nFailed to update {error_count} files.",
                )
            )
        else:
            await self.main_window.dialog(
                toga.InfoDialog("Success", f"Successfully updated {updated_count} files.")
            )

    def _batch_tz_worker(self, file_path, mode, tz, tz_iso):
        local_dt = None
        if mode == "Keep local time, set offset":
            try:
                local_dt = self.tag_meta_handler.get_local_creation_date(file_path)
            except Exception:
                pass
            if not local_dt:
                local_dt = parse_date_from_filename(file_path)
            if not local_dt:
                try:
                    local_dt = datetime.fromtimestamp(file_path.stat().st_mtime)
                except Exception:
                    pass
        else:  # "Recalculate local time from UTC"
            utc_dt = None
            try:
                utc_dt = self.tag_meta_handler.get_standardized_creation_date(file_path)
            except Exception:
                tags_got = self.tag_meta_handler.get_tags(file_path, ["QuickTime:CreateDate", "CreateDate"])
                create_str = tags_got.get("QuickTime:CreateDate") or tags_got.get("CreateDate")
                if create_str:
                    try:
                        utc_dt = datetime.strptime(str(create_str)[:19], "%Y:%m:%d %H:%M:%S").replace(
                            tzinfo=timezone.utc
                        )
                    except Exception:
                        pass
            if utc_dt:
                local_dt = utc_dt.astimezone(tz).replace(tzinfo=None)
            else:
                try:
                    local_dt = self.tag_meta_handler.get_local_creation_date(file_path)
                except Exception:
                    pass
                if not local_dt:
                    local_dt = parse_date_from_filename(file_path)
                if not local_dt:
                    try:
                        local_dt = datetime.fromtimestamp(file_path.stat().st_mtime)
                    except Exception:
                        pass

        if not local_dt:
            return False

        local_str = local_dt.strftime("%Y:%m:%d %H:%M:%S")
        suffix = file_path.suffix.lower()
        if suffix in (".mp4", ".mov", ".m4v"):
            updates = {
                "QuickTime:CreationDate": local_str + tz_iso,
                "QuickTime:Timezone": tz_iso,
                "QuickTime:TimeZone": tz_iso,
                "EXIF:DateTimeOriginal": local_str,
                "EXIF:CreateDate": local_str,
            }
        else:
            updates = {
                "EXIF:DateTimeOriginal": local_str,
                "EXIF:CreateDate": local_str,
                "EXIF:OffsetTime": tz_iso,
                "EXIF:OffsetTimeOriginal": tz_iso,
                "EXIF:OffsetTimeDigitized": tz_iso,
            }
        self.tag_meta_handler.set_tags(file_path, updates)
        return True

    async def on_batch_update_timezone(self, widget):
        files = self.tag_editor_files
        if not files:
            await self.main_window.dialog(toga.InfoDialog("No Files", "No files in the list to update."))
            return

        tz_str = self.tag_editor_tz_select.value
        tz = self.tag_meta_handler._parse_timezone(tz_str)
        if not tz:
            await self.main_window.dialog(
                toga.ErrorDialog("Invalid Timezone", f"Invalid timezone format: '{tz_str}'.")
            )
            return

        td = tz.utcoffset(None)
        offset_mins = int(td.total_seconds() / 60)
        sign = "+" if offset_mins >= 0 else "-"
        hours = abs(offset_mins) // 60
        mins = abs(offset_mins) % 60
        tz_iso = f"{sign}{hours:02}:{mins:02}"

        mode = self.tag_editor_tz_mode_select.value

        proceed = await self.main_window.dialog(
            toga.ConfirmDialog(
                "Confirm Batch Timezone Update",
                f"Update all {len(files)} files in the directory to timezone {tz_iso}?\n\nMode: {mode}",
            )
        )
        if not proceed:
            return

        self._set_tag_editor_busy(True, f"Updating 0/{len(files)}...")
        updated_count = 0
        error_count = 0
        for i, file_path in enumerate(files):
            self.tag_editor_status_label.text = f"Updating {i + 1}/{len(files)}: {file_path.name}"
            try:
                if await asyncio.to_thread(self._batch_tz_worker, file_path, mode, tz, tz_iso):
                    updated_count += 1
            except Exception as e:
                error_count += 1
                print(f"Error updating timezone for {file_path.name}: {e}")
        self._set_tag_editor_busy(False, "")

        if self.tag_editor_current_file:
            self._display_tag_editor_file(self.tag_editor_current_file)

        if error_count:
            await self.main_window.dialog(
                toga.ErrorDialog(
                    "Finished with Errors",
                    f"Successfully updated timezone for {updated_count} files.\n"
                    f"Failed to update {error_count} files.",
                )
            )
        else:
            await self.main_window.dialog(
                toga.InfoDialog("Success", f"Successfully updated timezone for {updated_count} files.")
            )

    async def on_view_all_metadata(self, widget):
        if not self.tag_editor_current_file:
            return
        try:
            metadata = await asyncio.to_thread(self.tag_meta_handler.get_metadata, self.tag_editor_current_file)
        except Exception as e:
            await self.main_window.dialog(toga.ErrorDialog("Error", f"Failed to load metadata: {e}"))
            return
        if not metadata:
            await self.main_window.dialog(
                toga.InfoDialog("No Metadata", "No metadata could be extracted from this file.")
            )
            return
        self._show_metadata_viewer(self.tag_editor_current_file.name, metadata)

    def _show_metadata_viewer(self, file_name, metadata):
        rows = [
            {"tag": key, "value": str(value)}
            for key, value in sorted(metadata.items(), key=lambda kv: kv[0].lower())
        ]

        table = toga.Table(
            columns=[AccessorColumn("Tag", accessor="tag"), AccessorColumn("Value", accessor="value")],
            data=rows,
            style=Pack(flex=1),
        )

        def on_filter(widget):
            text = (widget.value or "").lower()
            table.data = [r for r in rows if text in r["tag"].lower() or text in r["value"].lower()]

        search_input = toga.TextInput(
            placeholder="Type to filter tag names or values...", on_change=on_filter, style=Pack(flex=1)
        )

        search_row = toga.Box(style=Pack(direction=ROW, margin_bottom=8, align_items="center"))
        search_row.add(toga.Label("Filter:", style=Pack(margin_right=5)))
        search_row.add(search_input)

        box = toga.Box(style=Pack(direction=COLUMN, margin=10, flex=1))
        box.add(search_row)
        box.add(table)

        window = toga.Window(title=f"Metadata Viewer - {file_name}", size=(700, 600))
        window.content = box
        window.show()

    # ------------------------------------------------------------------
    # HUD Designer
    # ------------------------------------------------------------------

    def _build_hud_designer_fields(self, field_style):
        self.designer_skin = None
        self.designer_elements = []
        self.designer_manufacturer = "Shearwater"
        self.designer_model = "Perdix2"
        self.designer_selected = None
        self.designer_view_w = 1920.0
        self.designer_view_h = 1080.0
        self.designer_bg_frame = None
        self.designer_video_cap = None
        self.designer_video_fps = 30.0
        self.designer_video_creation_date = None
        self.designer_dive_manager = DiveManager()
        self.designer_current_dive = None
        self.designer_current_waypoint = None
        self.designer_temp_dirs = []
        self._designer_drag_origin = None
        self._designer_drag_start = None
        self._designer_block_updates = False

        self.designer_canvas = toga.Canvas(
            style=Pack(width=DESIGNER_CANVAS_WIDTH, height=int(DESIGNER_CANVAS_WIDTH * 1080 / 1920)),
            on_press=self.on_designer_canvas_press,
            on_drag=self.on_designer_canvas_drag,
        )
        self.designer_time_slider = toga.Slider(
            min=0, max=1, value=0, enabled=False, on_change=self.on_designer_time_change, style=Pack(flex=1)
        )
        self.designer_time_label = toga.Label("00:00:00", style=Pack(width=90))
        self.designer_data_label = toga.Label("Depth: -- | Temp: --", style=Pack(margin_top=4))
        self.designer_log_label = toga.Label(
            "Current Log: None", style=Pack(color=THEME["text_muted"], margin_top=2)
        )
        self.designer_status_label = toga.Label("", style=Pack(margin_top=5, color=THEME["text_muted"]))

        self.designer_tz_slider = toga.Slider(
            min=-24, max=24, value=0, tick_count=49, on_change=self.on_designer_tz_change, style=Pack(flex=1)
        )
        self.designer_tz_label = toga.Label("0h", style=Pack(width=40))

        self.designer_mfg_select = toga.Selection(
            items=list(DESIGNER_MANUFACTURER_MODELS.keys()),
            value="Shearwater",
            on_change=self.on_designer_manufacturer_change,
            style=field_style,
        )
        self.designer_model_select = toga.Selection(
            items=list(DESIGNER_MANUFACTURER_MODELS["Shearwater"]),
            on_change=self.on_designer_model_change,
            style=field_style,
        )
        self.designer_anchor_select = toga.Selection(
            items=list(ANCHORS), on_change=self.on_designer_anchor_change, style=field_style
        )
        self.designer_opacity_slider = toga.Slider(
            min=0, max=1, value=1, on_change=self.on_designer_opacity_change, style=Pack(flex=1)
        )
        self.designer_opacity_label = toga.Label("1.00", style=Pack(width=45))
        self.designer_scale_slider = toga.Slider(
            min=0.01, max=5, value=1, on_change=self.on_designer_scale_change, style=Pack(flex=1)
        )
        self.designer_scale_label = toga.Label("1.00", style=Pack(width=45))

        self.designer_shape_width_slider = toga.Slider(
            min=10, max=2000, value=400, on_change=self.on_designer_shape_dim_change, style=Pack(flex=1)
        )
        self.designer_shape_width_label = toga.Label("400", style=Pack(width=45))
        self.designer_shape_height_slider = toga.Slider(
            min=10, max=2000, value=200, on_change=self.on_designer_shape_dim_change, style=Pack(flex=1)
        )
        self.designer_shape_height_label = toga.Label("200", style=Pack(width=45))
        self.designer_shape_radius_slider = toga.Slider(
            min=0, max=500, value=20, on_change=self.on_designer_shape_dim_change, style=Pack(flex=1)
        )
        self.designer_shape_radius_label = toga.Label("20", style=Pack(width=45))
        self.designer_shape_color_input = toga.TextInput(
            value="#000000", on_change=self.on_designer_shape_color_change, style=field_style
        )

        self.designer_item_color_input = toga.TextInput(
            value="#FFFFFF", on_change=self.on_designer_item_color_change, style=field_style
        )
        self.designer_item_font_slider = toga.Slider(
            min=8, max=200, value=30, on_change=self.on_designer_item_font_change, style=Pack(flex=1)
        )
        self.designer_item_font_label = toga.Label("30", style=Pack(width=45))
        self.designer_item_scale_slider = toga.Slider(
            min=0.1, max=5, value=1, on_change=self.on_designer_item_scale_change, style=Pack(flex=1)
        )
        self.designer_item_scale_label = toga.Label("1.00", style=Pack(width=45))
        self.designer_custom_text_input = toga.TextInput(
            on_change=self.on_designer_custom_text_change, style=field_style
        )
        self.designer_graph_width_slider = toga.Slider(
            min=10, max=2000, value=300, on_change=self.on_designer_graph_dim_change, style=Pack(flex=1)
        )
        self.designer_graph_width_label = toga.Label("300", style=Pack(width=45))
        self.designer_graph_height_slider = toga.Slider(
            min=10, max=2000, value=150, on_change=self.on_designer_graph_dim_change, style=Pack(flex=1)
        )
        self.designer_graph_height_label = toga.Label("150", style=Pack(width=45))
        self.designer_marker_style_select = toga.Selection(
            items=list(DESIGNER_MARKER_LABELS.values()),
            on_change=self.on_designer_marker_style_change,
            style=field_style,
        )
        self.designer_marker_size_slider = toga.Slider(
            min=1, max=50, value=6, on_change=self.on_designer_marker_size_change, style=Pack(flex=1)
        )
        self.designer_marker_size_label = toga.Label("6", style=Pack(width=45))

        self.designer_layers_table = toga.Table(
            columns=[AccessorColumn("Field", accessor="name")],
            multiple_select=True,
            on_select=self.on_designer_layers_select,
            style=Pack(flex=1, height=140),
        )
        self.designer_fields_table = toga.Table(
            columns=[AccessorColumn("Field", accessor="name")], style=Pack(flex=1, height=140)
        )
        self._designer_refresh_fields_table()
        self.designer_custom_label_input = toga.TextInput(
            placeholder="Custom label text...", style=field_style
        )
        self.designer_overlay_select = toga.Selection(items=["Depth Graph Overlay"], style=field_style)

    def _build_hud_designer_section(self):
        section = toga.Box(style=Pack(direction=ROW, flex=1))

        left = toga.Box(style=Pack(direction=COLUMN, margin_right=16))
        left.add(self.designer_canvas)
        slider_row = toga.Box(style=Pack(direction=ROW, margin_top=8, align_items="center"))
        slider_row.add(self.designer_time_slider)
        slider_row.add(self.designer_time_label)
        left.add(slider_row)
        left.add(self.designer_data_label)
        left.add(self.designer_log_label)
        left.add(self.designer_status_label)
        section.add(left)

        right = toga.Box(style=Pack(direction=COLUMN))

        bg_row1 = toga.Box(style=Pack(direction=ROW))
        bg_row1.add(toga.Button("Load Video/Photo", on_press=self.on_designer_load_background))
        bg_row1.add(
            toga.Button(
                "Select Log Directory", on_press=self.on_designer_load_logs, style=Pack(margin_left=5)
            )
        )
        tz_row = toga.Box(style=Pack(direction=ROW, align_items="center", margin_top=5))
        tz_row.add(toga.Label("TZ Offset (Log vs Media):", style=Pack(width=170)))
        tz_row.add(self.designer_tz_slider)
        tz_row.add(self.designer_tz_label)
        right.add(self._card("Background & Logs", bg_row1, tz_row))

        self.designer_scale_row = self._row("Scale", self.designer_scale_slider, self.designer_scale_label)
        self.designer_shape_width_row = self._row(
            "Width", self.designer_shape_width_slider, self.designer_shape_width_label
        )
        self.designer_shape_height_row = self._row(
            "Height", self.designer_shape_height_slider, self.designer_shape_height_label
        )
        self.designer_shape_radius_row = self._row(
            "Corner Radius", self.designer_shape_radius_slider, self.designer_shape_radius_label
        )
        self.designer_shape_color_row = self._row("BG Color (hex)", self.designer_shape_color_input, None)
        # Nothing is selected yet at build time, so _designer_sync_selection_ui's
        # skin-field population hasn't run - default the shape-only rows to
        # hidden (image-skin rows stay visible; they're harmless either way).
        for row in (
            self.designer_shape_width_row,
            self.designer_shape_height_row,
            self.designer_shape_radius_row,
            self.designer_shape_color_row,
        ):
            row.style.visibility = HIDDEN
        right.add(
            self._card(
                "Skin",
                self._row("Manufacturer", self.designer_mfg_select, None),
                self._row("Model", self.designer_model_select, None),
                self._row("Anchor", self.designer_anchor_select, None),
                self._row("Opacity", self.designer_opacity_slider, self.designer_opacity_label),
                self.designer_scale_row,
                self.designer_shape_width_row,
                self.designer_shape_height_row,
                self.designer_shape_radius_row,
                self.designer_shape_color_row,
            )
        )

        self.designer_item_color_row = self._row("Color (hex)", self.designer_item_color_input, None)
        self.designer_item_font_row = self._row(
            "Font Size", self.designer_item_font_slider, self.designer_item_font_label
        )
        self.designer_item_scale_row = self._row(
            "Item Scale", self.designer_item_scale_slider, self.designer_item_scale_label
        )
        self.designer_custom_text_row = self._row("Custom Text", self.designer_custom_text_input, None)
        self.designer_graph_width_row = self._row(
            "Width", self.designer_graph_width_slider, self.designer_graph_width_label
        )
        self.designer_graph_height_row = self._row(
            "Height", self.designer_graph_height_slider, self.designer_graph_height_label
        )
        self.designer_marker_style_row = self._row("Marker Style", self.designer_marker_style_select, None)
        self.designer_marker_size_row = self._row(
            "Marker Size", self.designer_marker_size_slider, self.designer_marker_size_label
        )
        right.add(
            self._card(
                "Selected Item",
                self.designer_item_color_row,
                self.designer_item_font_row,
                self.designer_item_scale_row,
                self.designer_custom_text_row,
                self.designer_graph_width_row,
                self.designer_graph_height_row,
                self.designer_marker_style_row,
                self.designer_marker_size_row,
            )
        )

        align_grid1 = toga.Box(style=Pack(direction=ROW))
        align_grid1.add(toga.Button("Align Top", on_press=self._designer_align_handler("h_top")))
        align_grid1.add(
            toga.Button(
                "Align Bottom", on_press=self._designer_align_handler("h_bottom"), style=Pack(margin_left=5)
            )
        )
        align_grid1.add(
            toga.Button(
                "Align H-Center", on_press=self._designer_align_handler("h_center"), style=Pack(margin_left=5)
            )
        )
        align_grid2 = toga.Box(style=Pack(direction=ROW, margin_top=5))
        align_grid2.add(toga.Button("Align Left", on_press=self._designer_align_handler("v_left")))
        align_grid2.add(
            toga.Button(
                "Align Right", on_press=self._designer_align_handler("v_right"), style=Pack(margin_left=5)
            )
        )
        align_grid2.add(
            toga.Button(
                "Align V-Center", on_press=self._designer_align_handler("v_center"), style=Pack(margin_left=5)
            )
        )
        right.add(
            self._card(
                "Layers",
                self.designer_layers_table,
                align_grid1,
                align_grid2,
                toga.Button(
                    "Delete Selected", on_press=self.on_designer_delete_selected, style=Pack(margin_top=5)
                ),
            )
        )

        custom_row = toga.Box(style=Pack(direction=ROW))
        custom_row.add(self.designer_custom_label_input)
        custom_row.add(
            toga.Button("Add Custom", on_press=self.on_designer_add_custom_label, style=Pack(margin_left=5))
        )
        overlay_row = toga.Box(style=Pack(direction=ROW, margin_top=5))
        overlay_row.add(self.designer_overlay_select)
        overlay_row.add(
            toga.Button("Add Overlay", on_press=self.on_designer_add_overlay, style=Pack(margin_left=5))
        )
        right.add(
            self._card(
                "Available Fields",
                self.designer_fields_table,
                toga.Button("Add Field", on_press=self.on_designer_add_field, style=Pack(margin_top=5)),
                custom_row,
                overlay_row,
            )
        )

        action_col = toga.Box(style=Pack(direction=COLUMN))
        action_col.add(toga.Button("Load PNG Skin", on_press=self.on_designer_load_skin))
        action_col.add(
            toga.Button(
                "Create Shape Background", on_press=self.on_designer_create_shape, style=Pack(margin_top=5)
            )
        )
        action_col.add(
            toga.Button(
                "Load HUD Package (.zip)", on_press=self.on_designer_load_package, style=Pack(margin_top=5)
            )
        )
        action_col.add(
            toga.Button(
                "Save HUD Package (.zip)", on_press=self.on_designer_save_package, style=Pack(margin_top=5)
            )
        )
        action_col.add(
            toga.Button(
                "Review Render (OpenCV)", on_press=self.on_designer_review_render, style=Pack(margin_top=5)
            )
        )
        action_col.add(
            toga.Button(
                "Show Raw Waypoint Data", on_press=self.on_designer_show_waypoint, style=Pack(margin_top=5)
            )
        )
        right.add(self._card("Actions", action_col))

        right_scroll = toga.ScrollContainer(
            horizontal=False, vertical=True, content=right, style=Pack(width=360, flex=1)
        )
        section.add(right_scroll)

        self._designer_sync_selection_ui()
        return section

    # -- rendering & selection --------------------------------------------------

    def _designer_layout_dict(self):
        return build_layout_json(
            self.designer_skin,
            self.designer_elements,
            self.designer_manufacturer,
            self.designer_model,
            self.designer_view_w,
            self.designer_view_h,
        )

    def _designer_set_canvas_dimensions(self, width, height):
        self.designer_view_w = float(width)
        self.designer_view_h = float(height)
        self.designer_canvas.style.height = DESIGNER_CANVAS_WIDTH * height / width

    def _redraw_designer_canvas(self):
        # Canvas.clear() is the inherited Widget child-removal method, not a
        # drawing-content reset - Canvas can't have children, so it raises.
        # The actual retained-mode drawing list lives at root_state, and
        # mutating it requires an explicit redraw() to take effect.
        canvas = self.designer_canvas
        canvas.root_state.drawing_actions.clear()
        if self.designer_bg_frame is None:
            canvas.redraw()
            return
        frame = self.designer_bg_frame.copy()
        if self.designer_skin:
            layout = self._designer_layout_dict()
            wp = self.designer_current_waypoint or Waypoint(timestamp=datetime.now(), depth=10.5, temp=22.0, time_since_start=0)
            waypoints = self.designer_current_dive.waypoints if self.designer_current_dive else None
            try:
                draw_hud(frame, layout, wp, waypoints=waypoints)
            except Exception as e:
                print(f"HUD Designer render error: {e}")
            self._designer_draw_selection(frame)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = toga.Image(PILImage.fromarray(rgb))
        disp_h = DESIGNER_CANVAS_WIDTH * self.designer_view_h / self.designer_view_w
        canvas.draw_image(image, 0, 0, width=DESIGNER_CANVAS_WIDTH, height=disp_h)
        canvas.redraw()

    def _designer_draw_selection(self, frame):
        if self.designer_selected is None or not self.designer_skin:
            return
        if self.designer_selected == "skin":
            x, y = self.designer_skin.get("x", 0.0), self.designer_skin.get("y", 0.0)
            w, h = skin_pixel_size(self.designer_skin)
        else:
            if not isinstance(self.designer_selected, int) or self.designer_selected >= len(self.designer_elements):
                return
            elem = self.designer_elements[self.designer_selected]
            x, y = element_position(elem, self.designer_skin)
            w, h = measure_element_box(elem, self.designer_skin)
        cv2.rectangle(frame, (int(x) - 2, int(y) - 2), (int(x + w) + 2, int(y + h) + 2), (0, 255, 255), 2)

    def _designer_valid_hex(self, text):
        if text and len(text) == 7 and text.startswith("#"):
            try:
                int(text[1:], 16)
                return text
            except ValueError:
                return None
        return None

    def _designer_sync_selection_ui(self):
        sel = self.designer_selected
        elem = None
        if isinstance(sel, int) and sel < len(self.designer_elements):
            elem = self.designer_elements[sel]
        is_graph = elem is not None and elem.get("type") == "graph"
        is_custom = elem is not None and elem.get("field", "").startswith("custom:")
        item_visible = elem is not None

        self.designer_item_color_row.style.visibility = VISIBLE if item_visible else HIDDEN
        self.designer_item_font_row.style.visibility = VISIBLE if (item_visible and not is_graph) else HIDDEN
        self.designer_item_scale_row.style.visibility = VISIBLE if (item_visible and not is_graph) else HIDDEN
        self.designer_custom_text_row.style.visibility = VISIBLE if (item_visible and is_custom) else HIDDEN
        self.designer_graph_width_row.style.visibility = VISIBLE if (item_visible and is_graph) else HIDDEN
        self.designer_graph_height_row.style.visibility = VISIBLE if (item_visible and is_graph) else HIDDEN
        self.designer_marker_style_row.style.visibility = VISIBLE if (item_visible and is_graph) else HIDDEN
        self.designer_marker_size_row.style.visibility = VISIBLE if (item_visible and is_graph) else HIDDEN

        if elem is not None:
            self._designer_populate_item_fields(elem)
        if sel == "skin" and self.designer_skin:
            self._designer_populate_skin_fields()

    def _designer_populate_item_fields(self, elem):
        self._designer_block_updates = True
        self.designer_item_color_input.value = elem.get("color", "#FFFFFF")
        if elem.get("type") == "graph":
            self.designer_graph_width_slider.value = elem.get("width", 300)
            self.designer_graph_width_label.text = str(elem.get("width", 300))
            self.designer_graph_height_slider.value = elem.get("height", 150)
            self.designer_graph_height_label.text = str(elem.get("height", 150))
            style = elem.get("marker_style", "dot")
            self.designer_marker_style_select.value = DESIGNER_MARKER_LABELS.get(style, "Highlight Dot")
            self.designer_marker_size_slider.value = elem.get("marker_size", 6)
            self.designer_marker_size_label.text = str(elem.get("marker_size", 6))
        else:
            self.designer_item_font_slider.value = elem.get("font_size", 30)
            self.designer_item_font_label.text = str(elem.get("font_size", 30))
            scale = elem.get("scale", 1.0)
            self.designer_item_scale_slider.value = scale
            self.designer_item_scale_label.text = f"{scale:.2f}"
            if elem.get("field", "").startswith("custom:"):
                self.designer_custom_text_input.value = elem["field"].replace("custom:", "")
        self._designer_block_updates = False

    def _designer_populate_skin_fields(self):
        self._designer_block_updates = True
        is_shape = self.designer_skin.get("type") == "shape"
        self.designer_anchor_select.value = self.designer_skin.get("anchor", "TOP_LEFT")
        opacity = self.designer_skin.get("opacity", 1.0)
        self.designer_opacity_slider.value = opacity
        self.designer_opacity_label.text = f"{opacity:.2f}"
        self.designer_scale_row.style.visibility = HIDDEN if is_shape else VISIBLE
        for row in (
            self.designer_shape_width_row,
            self.designer_shape_height_row,
            self.designer_shape_radius_row,
            self.designer_shape_color_row,
        ):
            row.style.visibility = VISIBLE if is_shape else HIDDEN
        if is_shape:
            self.designer_shape_width_slider.value = self.designer_skin.get("width", 400)
            self.designer_shape_width_label.text = str(self.designer_skin.get("width", 400))
            self.designer_shape_height_slider.value = self.designer_skin.get("height", 200)
            self.designer_shape_height_label.text = str(self.designer_skin.get("height", 200))
            self.designer_shape_radius_slider.value = self.designer_skin.get("corner_radius", 20)
            self.designer_shape_radius_label.text = str(self.designer_skin.get("corner_radius", 20))
            self.designer_shape_color_input.value = self.designer_skin.get("color", "#000000")
        else:
            scale = self.designer_skin.get("scale", 1.0)
            self.designer_scale_slider.value = scale
            self.designer_scale_label.text = f"{scale:.2f}"
        self._designer_block_updates = False

    def _designer_sync_manufacturer_model_ui(self):
        self._designer_block_updates = True
        if self.designer_manufacturer in DESIGNER_MANUFACTURER_MODELS:
            self.designer_mfg_select.value = self.designer_manufacturer
        models = DESIGNER_MANUFACTURER_MODELS.get(self.designer_manufacturer, [])
        self.designer_model_select.items = models
        if self.designer_model in models:
            self.designer_model_select.value = self.designer_model
        elif models:
            self.designer_model_select.value = models[0]
        self._designer_block_updates = False

    def _designer_refresh_fields_table(self):
        fields = available_telemetry_fields(self.designer_current_dive)
        self.designer_fields_table.data = [{"name": f} for f in fields]

    def _designer_refresh_layers_table(self):
        self.designer_layers_table.data = [
            {"name": element_display_name(e["field"])} for e in self.designer_elements
        ]

    # -- canvas interaction -------------------------------------------------

    def _designer_to_design_coords(self, x, y):
        scale = self.designer_view_w / DESIGNER_CANVAS_WIDTH
        return x * scale, y * scale

    def on_designer_canvas_press(self, widget, x, y, **kwargs):
        if self.designer_bg_frame is None:
            return
        dx, dy = self._designer_to_design_coords(x, y)
        hit = hit_test(dx, dy, self.designer_skin, self.designer_elements)
        self.designer_selected = hit
        self._designer_drag_origin = (dx, dy)
        if hit == "skin":
            self._designer_drag_start = (self.designer_skin.get("x", 0.0), self.designer_skin.get("y", 0.0))
        elif isinstance(hit, int):
            elem = self.designer_elements[hit]
            self._designer_drag_start = (elem["rel_x"], elem["rel_y"])
        else:
            self._designer_drag_start = None
        self._designer_sync_selection_ui()
        self._redraw_designer_canvas()

    def on_designer_canvas_drag(self, widget, x, y, **kwargs):
        if self.designer_selected is None or self._designer_drag_start is None or not self.designer_skin:
            return
        dx, dy = self._designer_to_design_coords(x, y)
        delta_x = dx - self._designer_drag_origin[0]
        delta_y = dy - self._designer_drag_origin[1]
        if self.designer_selected == "skin":
            self.designer_skin["x"] = self._designer_drag_start[0] + delta_x
            self.designer_skin["y"] = self._designer_drag_start[1] + delta_y
        else:
            skin_w, skin_h = skin_pixel_size(self.designer_skin)
            elem = self.designer_elements[self.designer_selected]
            elem["rel_x"] = self._designer_drag_start[0] + (delta_x / skin_w if skin_w else 0.0)
            elem["rel_y"] = self._designer_drag_start[1] + (delta_y / skin_h if skin_h else 0.0)
        self._redraw_designer_canvas()

    # -- background / logs ----------------------------------------------------

    def on_designer_time_change(self, widget):
        if self.designer_video_cap is None:
            return
        frame_idx = int(widget.value)
        self.designer_video_cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = self.designer_video_cap.read()
        if not ret:
            return
        frame = cv2.resize(
            frame, (int(self.designer_view_w), int(self.designer_view_h)), interpolation=cv2.INTER_AREA
        )
        self.designer_bg_frame = frame
        seconds = frame_idx / self.designer_video_fps
        self.designer_time_label.text = str(timedelta(seconds=int(seconds)))
        self._designer_sync_data_to_frame(seconds)
        self._redraw_designer_canvas()

    async def on_designer_load_background(self, widget):
        path = await self.main_window.dialog(toga.OpenFileDialog("Select background"))
        if not path:
            return
        self._designer_load_background_from_path(Path(path))

    def _designer_load_background_from_path(self, path):
        handler = MetadataHandler()
        try:
            self.designer_video_creation_date = handler.get_local_creation_date(path)
        except Exception:
            self.designer_video_creation_date = datetime.now()

        if path.suffix.lower() in (".mp4", ".mov"):
            self._designer_load_video(path)
        else:
            self._designer_load_image(path)
        self._designer_match_dive_to_media()

    def _designer_load_video(self, path):
        if self.designer_video_cap:
            self.designer_video_cap.release()
        cap = cv2.VideoCapture(str(path))
        ret, frame = cap.read()
        if not ret:
            self.designer_status_label.text = f"Could not read video: {path}"
            return
        self.designer_video_cap = cap
        self.designer_video_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = max(1, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))
        h, w = frame.shape[:2]
        target_w = 1920
        target_h = int(target_w * h / w)
        self._designer_set_canvas_dimensions(target_w, target_h)
        self.designer_bg_frame = cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_AREA)
        self.designer_time_slider.min = 0
        self.designer_time_slider.max = max(1, total_frames - 1)
        self.designer_time_slider.value = 0
        self.designer_time_slider.enabled = True
        self.designer_time_label.text = "00:00:00"
        self._redraw_designer_canvas()

    def _designer_load_image(self, path):
        if self.designer_video_cap:
            self.designer_video_cap.release()
            self.designer_video_cap = None
        img = cv2.imread(str(path))
        if img is None:
            self.designer_status_label.text = f"Could not read image: {path}"
            return
        h, w = img.shape[:2]
        target_w = 1920
        target_h = int(target_w * h / w)
        self._designer_set_canvas_dimensions(target_w, target_h)
        self.designer_bg_frame = cv2.resize(img, (target_w, target_h), interpolation=cv2.INTER_AREA)
        self.designer_time_slider.enabled = False
        self.designer_time_label.text = "Photo Mode"
        self._designer_sync_data_to_frame(0)
        self._redraw_designer_canvas()

    async def on_designer_load_logs(self, widget):
        path = await self.main_window.dialog(toga.SelectFolderDialog("Select dive log directory"))
        if not path:
            return
        self._designer_load_logs_from_path(Path(path))

    def _designer_load_logs_from_path(self, dir_path):
        self.designer_dive_manager = DiveManager()
        uddf, garmin, subsurface = UDDFParser(), GarminParser(), SubsurfaceParser()
        count = 0
        if not dir_path.exists():
            return
        for path in dir_path.iterdir():
            try:
                if path.suffix == ".uddf":
                    self.designer_dive_manager.add_dives(uddf.parse(path))
                    count += 1
                elif path.suffix == ".fit":
                    self.designer_dive_manager.add_dives(garmin.parse(path))
                    count += 1
                elif path.suffix in (".ssrf", ".xml"):
                    self.designer_dive_manager.add_dives(subsurface.parse(path))
                    count += 1
            except Exception as e:
                print(f"Error parsing {path.name}: {e}")
        self.designer_status_label.text = f"Loaded {count} log files from {dir_path.name}"
        self._designer_match_dive_to_media()

    def on_designer_tz_change(self, widget):
        self.designer_tz_label.text = f"{int(widget.value)}h"
        self._designer_match_dive_to_media()

    def _designer_match_dive_to_media(self):
        if not self.designer_video_creation_date:
            return
        adjusted = self.designer_video_creation_date + timedelta(hours=self.designer_tz_slider.value)
        self.designer_current_dive = self.designer_dive_manager.find_dive_for_timestamp(adjusted)
        if self.designer_current_dive:
            self._designer_refresh_fields_table()
            seconds = (
                self.designer_time_slider.value / self.designer_video_fps if self.designer_video_cap else 0
            )
            self._designer_sync_data_to_frame(seconds)
            self._redraw_designer_canvas()
        else:
            self.designer_data_label.text = "No matching dive found for this date/offset."

    def _designer_sync_data_to_frame(self, offset_seconds):
        if not self.designer_current_dive or not self.designer_video_creation_date:
            return
        target_ts = self.designer_video_creation_date + timedelta(
            hours=self.designer_tz_slider.value, seconds=offset_seconds
        )
        wp = None
        for w in self.designer_current_dive.waypoints:
            if w.timestamp >= target_ts:
                wp = w
                break
        self.designer_current_waypoint = wp
        if wp:
            self.designer_data_label.text = f"Depth: {wp.depth:.1f}m | Temp: {wp.temp:.1f}C"
            self.designer_log_label.text = f"Current Log: {wp.log_filename or 'Unknown'}"
        else:
            self.designer_data_label.text = "Out of dive range."
            self.designer_log_label.text = "Current Log: None (No Match)"

    # -- skin property handlers -----------------------------------------------

    def on_designer_manufacturer_change(self, widget):
        if self._designer_block_updates:
            return
        self.designer_manufacturer = widget.value
        models = DESIGNER_MANUFACTURER_MODELS.get(widget.value, [])
        self.designer_model_select.items = models
        if models:
            self.designer_model_select.value = models[0]
            self.designer_model = models[0]
        else:
            self.designer_model = ""
        self._redraw_designer_canvas()

    def on_designer_model_change(self, widget):
        if self._designer_block_updates:
            return
        self.designer_model = widget.value
        self._redraw_designer_canvas()

    def on_designer_anchor_change(self, widget):
        if self._designer_block_updates or not self.designer_skin:
            return
        self.designer_skin["anchor"] = widget.value
        self._redraw_designer_canvas()

    def on_designer_opacity_change(self, widget):
        if self._designer_block_updates or not self.designer_skin:
            return
        self.designer_skin["opacity"] = widget.value
        self.designer_opacity_label.text = f"{widget.value:.2f}"
        self._redraw_designer_canvas()

    def on_designer_scale_change(self, widget):
        if self._designer_block_updates or not self.designer_skin:
            return
        self.designer_skin["scale"] = widget.value
        self.designer_scale_label.text = f"{widget.value:.2f}"
        self._redraw_designer_canvas()

    def on_designer_shape_dim_change(self, widget):
        if self._designer_block_updates or not self.designer_skin:
            return
        self.designer_skin["width"] = int(self.designer_shape_width_slider.value)
        self.designer_skin["height"] = int(self.designer_shape_height_slider.value)
        self.designer_skin["corner_radius"] = int(self.designer_shape_radius_slider.value)
        self.designer_shape_width_label.text = str(self.designer_skin["width"])
        self.designer_shape_height_label.text = str(self.designer_skin["height"])
        self.designer_shape_radius_label.text = str(self.designer_skin["corner_radius"])
        self._redraw_designer_canvas()

    def on_designer_shape_color_change(self, widget):
        if self._designer_block_updates or not self.designer_skin:
            return
        color = self._designer_valid_hex(widget.value)
        if color:
            self.designer_skin["color"] = color
            self._redraw_designer_canvas()

    # -- selected item property handlers ---------------------------------------

    def on_designer_item_color_change(self, widget):
        if self._designer_block_updates or not isinstance(self.designer_selected, int):
            return
        color = self._designer_valid_hex(widget.value)
        if color:
            self.designer_elements[self.designer_selected]["color"] = color
            self._redraw_designer_canvas()

    def on_designer_item_font_change(self, widget):
        if self._designer_block_updates or not isinstance(self.designer_selected, int):
            return
        size = int(widget.value)
        self.designer_elements[self.designer_selected]["font_size"] = size
        self.designer_item_font_label.text = str(size)
        self._redraw_designer_canvas()

    def on_designer_item_scale_change(self, widget):
        if self._designer_block_updates or not isinstance(self.designer_selected, int):
            return
        self.designer_elements[self.designer_selected]["scale"] = widget.value
        self.designer_item_scale_label.text = f"{widget.value:.2f}"
        self._redraw_designer_canvas()

    def on_designer_custom_text_change(self, widget):
        if self._designer_block_updates or not isinstance(self.designer_selected, int):
            return
        elem = self.designer_elements[self.designer_selected]
        if elem.get("field", "").startswith("custom:"):
            elem["field"] = f"custom:{widget.value}"
            self._designer_refresh_layers_table()
            self._redraw_designer_canvas()

    def on_designer_graph_dim_change(self, widget):
        if self._designer_block_updates or not isinstance(self.designer_selected, int):
            return
        elem = self.designer_elements[self.designer_selected]
        if elem.get("type") != "graph":
            return
        elem["width"] = int(self.designer_graph_width_slider.value)
        elem["height"] = int(self.designer_graph_height_slider.value)
        self.designer_graph_width_label.text = str(elem["width"])
        self.designer_graph_height_label.text = str(elem["height"])
        self._redraw_designer_canvas()

    def on_designer_marker_style_change(self, widget):
        if self._designer_block_updates or not isinstance(self.designer_selected, int):
            return
        elem = self.designer_elements[self.designer_selected]
        if elem.get("type") != "graph":
            return
        reverse_map = {v: k for k, v in DESIGNER_MARKER_LABELS.items()}
        elem["marker_style"] = reverse_map.get(widget.value, "dot")
        self._redraw_designer_canvas()

    def on_designer_marker_size_change(self, widget):
        if self._designer_block_updates or not isinstance(self.designer_selected, int):
            return
        elem = self.designer_elements[self.designer_selected]
        if elem.get("type") != "graph":
            return
        elem["marker_size"] = int(widget.value)
        self.designer_marker_size_label.text = str(elem["marker_size"])
        self._redraw_designer_canvas()

    # -- layers / align / delete -----------------------------------------------

    def on_designer_layers_select(self, widget):
        selection = widget.selection
        if not selection:
            return
        rows = list(widget.data)
        last_row = selection[-1] if isinstance(selection, list) else selection
        try:
            index = rows.index(last_row)
        except ValueError:
            return
        self.designer_selected = index
        self._designer_sync_selection_ui()
        self._redraw_designer_canvas()

    def _designer_selected_layer_indices(self):
        selection = self.designer_layers_table.selection or []
        rows = list(self.designer_layers_table.data)
        return [rows.index(r) for r in selection if r in rows]

    def _designer_align_handler(self, mode):
        def handler(widget):
            indices = self._designer_selected_layer_indices()
            if len(indices) < 2 or not self.designer_skin:
                return
            align_elements(self.designer_elements, indices, self.designer_skin, mode)
            self._redraw_designer_canvas()

        return handler

    def on_designer_delete_selected(self, widget):
        indices = set(self._designer_selected_layer_indices())
        if isinstance(self.designer_selected, int):
            indices.add(self.designer_selected)
        for i in sorted(indices, reverse=True):
            del self.designer_elements[i]
        self.designer_selected = None
        self._designer_refresh_layers_table()
        self._designer_sync_selection_ui()
        self._redraw_designer_canvas()

    # -- add fields ---------------------------------------------------------

    def on_designer_add_field(self, widget):
        if not self.designer_skin:
            self.designer_status_label.text = "Load a skin before adding telemetry fields."
            return
        selected = self.designer_fields_table.selection
        if not selected:
            return
        self.designer_elements.append(
            {"field": selected.name, "rel_x": 0.5, "rel_y": 0.5, "color": "#FFFFFF", "font_size": 30, "scale": 1.0}
        )
        self._designer_refresh_layers_table()
        self._redraw_designer_canvas()

    def on_designer_add_custom_label(self, widget):
        if not self.designer_skin:
            self.designer_status_label.text = "Load a skin before adding a custom label."
            return
        text = (self.designer_custom_label_input.value or "").strip()
        if not text:
            return
        self.designer_elements.append(
            {
                "field": f"custom:{text}",
                "rel_x": 0.5,
                "rel_y": 0.5,
                "color": "#FFFFFF",
                "font_size": 30,
                "scale": 1.0,
            }
        )
        self.designer_custom_label_input.value = ""
        self._designer_refresh_layers_table()
        self._redraw_designer_canvas()

    def on_designer_add_overlay(self, widget):
        if not self.designer_skin:
            self.designer_status_label.text = "Load a skin before adding an overlay."
            return
        if self.designer_overlay_select.value == "Depth Graph Overlay":
            self.designer_elements.append(
                {
                    "field": "depth_graph",
                    "type": "graph",
                    "rel_x": 0.5,
                    "rel_y": 0.5,
                    "width": 300,
                    "height": 150,
                    "color": "#00FF00",
                    "marker_style": "dot",
                    "marker_size": 6,
                }
            )
            self._designer_refresh_layers_table()
            self._redraw_designer_canvas()

    # -- skin loading / package actions -----------------------------------------

    async def on_designer_load_skin(self, widget):
        path = await self.main_window.dialog(toga.OpenFileDialog("Select PNG skin"))
        if not path:
            return
        self._designer_load_skin_from_path(
            str(path), x=0.1 * self.designer_view_w, y=0.1 * self.designer_view_h
        )

    def _designer_load_skin_from_path(self, path, x, y, opacity=1.0, scale=0.5, anchor="TOP_LEFT"):
        img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if img is None:
            self.designer_status_label.text = f"Could not load skin: {path}"
            return
        native_h, native_w = img.shape[:2]
        self.designer_skin = {
            "type": "image",
            "path": path,
            "native_width": native_w,
            "native_height": native_h,
            "opacity": opacity,
            "scale": scale,
            "anchor": anchor,
            "x": x,
            "y": y,
        }
        self.designer_selected = "skin"
        self._designer_sync_selection_ui()
        self._redraw_designer_canvas()

    def on_designer_create_shape(self, widget):
        self.designer_skin = {
            "type": "shape",
            "width": 400,
            "height": 200,
            "color": "#000000",
            "corner_radius": 20,
            "opacity": 0.5,
            "anchor": "TOP_LEFT",
            "x": 0.1 * self.designer_view_w,
            "y": 0.1 * self.designer_view_h,
        }
        self.designer_selected = "skin"
        self._designer_sync_selection_ui()
        self._redraw_designer_canvas()

    async def on_designer_load_package(self, widget):
        path = await self.main_window.dialog(toga.OpenFileDialog("Load HUD package"))
        if not path:
            return
        tmp_dir = tempfile.mkdtemp(prefix="hud_designer_")
        try:
            with zipfile.ZipFile(str(path), "r") as zf:
                zf.extractall(tmp_dir)
            layout_path = Path(tmp_dir) / "hud_layout.json"
            if not layout_path.exists():
                self.designer_status_label.text = "Package missing hud_layout.json"
                shutil.rmtree(tmp_dir, ignore_errors=True)
                return
            with open(layout_path) as f:
                layout = json.load(f)
            self._designer_apply_layout(layout, tmp_dir)
            self.designer_temp_dirs.append(tmp_dir)
            self.designer_status_label.text = f"Loaded HUD package from {path}"
        except Exception as e:
            self.designer_status_label.text = f"Error loading HUD package: {e}"
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _designer_apply_layout(self, layout, base_dir):
        self.designer_manufacturer = layout.get("manufacturer", "Shearwater")
        self.designer_model = layout.get("model", "Perdix2")
        hud_skin = layout.get("hud_skin")
        if not hud_skin:
            return

        view_w, view_h = self.designer_view_w, self.designer_view_h

        if hud_skin.get("type") == "shape":
            skin = {
                "type": "shape",
                "width": hud_skin.get("width", 400),
                "height": hud_skin.get("height", 200),
                "color": hud_skin.get("color", "#000000"),
                "corner_radius": hud_skin.get("corner_radius", 20),
                "opacity": hud_skin.get("opacity", 0.5),
                "anchor": hud_skin.get("anchor", "TOP_LEFT"),
            }
            skin_w, skin_h = skin["width"], skin["height"]
        else:
            skin_path = hud_skin.get("path")
            abs_path = str(Path(base_dir) / skin_path) if skin_path else None
            native_w = native_h = 0
            if abs_path and Path(abs_path).exists():
                img = cv2.imread(abs_path)
                if img is not None:
                    native_h, native_w = img.shape[:2]
            skin = {
                "type": "image",
                "path": abs_path,
                "native_width": native_w,
                "native_height": native_h,
                "opacity": hud_skin.get("opacity", 1.0),
                "scale": hud_skin.get("scale", 1.0),
                "anchor": hud_skin.get("anchor", "TOP_LEFT"),
            }
            skin_w, skin_h = native_w * skin["scale"], native_h * skin["scale"]

        x, y = resolve_skin_position(hud_skin, skin_w, skin_h, view_w, view_h)
        skin["x"], skin["y"] = x, y

        self.designer_skin = skin
        self.designer_elements = parse_layout_elements(hud_skin)
        self.designer_selected = None
        self._designer_refresh_layers_table()
        self._designer_sync_manufacturer_model_ui()
        self._designer_sync_selection_ui()
        self._redraw_designer_canvas()

    async def on_designer_save_package(self, widget):
        if not self.designer_skin:
            self.designer_status_label.text = "No skin loaded. Cannot save HUD package."
            return
        path = await self.main_window.dialog(
            toga.SaveFileDialog("Save HUD package", suggested_filename="hud_package.zip")
        )
        if not path:
            return
        path = str(path)
        if not path.endswith(".zip"):
            path += ".zip"
        try:
            layout = self._designer_layout_dict()
            is_shape = self.designer_skin.get("type") == "shape"
            skin_path = self.designer_skin.get("path")
            if not is_shape and skin_path:
                layout["hud_skin"]["path"] = Path(skin_path).name

            with tempfile.TemporaryDirectory() as tmpdir:
                json_path = os.path.join(tmpdir, "hud_layout.json")
                with open(json_path, "w") as f:
                    json.dump(layout, f, indent=2)
                with zipfile.ZipFile(path, "w") as zf:
                    zf.write(json_path, arcname="hud_layout.json")
                    if not is_shape and skin_path and Path(skin_path).exists():
                        zf.write(skin_path, arcname=Path(skin_path).name)
            self.designer_status_label.text = f"Saved HUD package to {path}"
        except Exception as e:
            self.designer_status_label.text = f"Error saving HUD package: {e}"

    def on_designer_review_render(self, widget):
        if self.designer_bg_frame is None or not self.designer_skin:
            self.designer_status_label.text = "Load a background and skin first."
            return
        frame = self.designer_bg_frame.copy()
        layout = self._designer_layout_dict()
        wp = self.designer_current_waypoint or Waypoint(timestamp=datetime.now(), depth=10.5, temp=22.0, time_since_start=0)
        waypoints = self.designer_current_dive.waypoints if self.designer_current_dive else None
        draw_hud(frame, layout, wp, waypoints=waypoints)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = toga.Image(PILImage.fromarray(rgb))

        box = toga.Box(style=Pack(direction=COLUMN, flex=1))
        box.add(toga.ImageView(image=image, style=Pack(flex=1)))
        window = toga.Window(title="OpenCV Render Preview (Final Output Look)", size=(980, 580))
        window.content = box
        window.show()

    def on_designer_show_waypoint(self, widget):
        if not self.designer_current_waypoint:
            self.designer_status_label.text = "No waypoint data for current frame."
            return
        data_json = self.designer_current_waypoint.model_dump_json(indent=4)
        box = toga.Box(style=Pack(direction=COLUMN, margin=10, flex=1))
        box.add(toga.MultilineTextInput(value=data_json, readonly=True, style=Pack(flex=1)))
        window = toga.Window(title="Current Waypoint Raw Data", size=(500, 700))
        window.content = box
        window.show()

    def _build_advanced_section(self):
        section = toga.Box(style=Pack(direction=COLUMN))

        flags_box = toga.Box(style=Pack(direction=COLUMN))
        for switch in (
            self.hw_accel_switch,
            self.debug_switch,
            self.summary_switch,
            self.no_overwrite_switch,
        ):
            flags_box.add(switch)

        section.add(self._card("Flags", flags_box))
        section.add(
            self._card(
                "Time range",
                self._row("Start time", self.start_time_input, None),
                self._row("End time", self.end_time_input, None),
            )
        )
        section.add(
            self._card(
                "Locations",
                self._row(
                    "Layouts folder",
                    self.layouts_dir_input,
                    self._change_reset_buttons(self.on_choose_layouts_dir, self.on_reset_layouts_dir),
                ),
                self._row(
                    "Color profiles folder",
                    self.color_dir_input,
                    self._change_reset_buttons(self.on_choose_color_dir, self.on_reset_color_dir),
                ),
            )
        )
        section.add(
            self._card(
                "Custom filename formats",
                self._row(
                    "New format",
                    self.new_filename_format_input,
                    toga.Button("Add", on_press=self.on_add_filename_format, style=Pack(margin_left=5)),
                ),
                self._row(
                    "New overlay pattern",
                    self.new_render_log_format_input,
                    toga.Button("Add", on_press=self.on_add_render_log_format, style=Pack(margin_left=5)),
                ),
            )
        )
        return section

    def _build_activity_section(self):
        section = toga.Box(style=Pack(direction=COLUMN))
        section.add(
            self._card(
                "Run log",
                self.activity_status_label,
                self.show_terminal_switch,
                self.log_label,
                self.log_output,
            )
        )
        return section

    def _row(self, label_text, widget, extra):
        box = toga.Box(style=Pack(direction=ROW, margin_bottom=5))
        box.add(toga.Label(label_text, style=Pack(width=140)))
        box.add(widget)
        if extra is not None:
            box.add(extra)
        return box

    def _browse_button(self, target_input, folder):
        async def on_press(widget):
            dialog = (
                toga.SelectFolderDialog("Select folder")
                if folder
                else toga.OpenFileDialog("Select file")
            )
            path = await self.main_window.dialog(dialog)
            if path:
                target_input.value = str(path)

        return toga.Button("Browse", on_press=on_press, style=Pack(margin_left=5))

    def _file_or_folder_buttons(self, target_input):
        async def browse_file(widget):
            path = await self.main_window.dialog(toga.OpenFileDialog("Select file"))
            if path:
                target_input.value = str(path)

        async def browse_folder(widget):
            path = await self.main_window.dialog(toga.SelectFolderDialog("Select folder"))
            if path:
                target_input.value = str(path)

        box = toga.Box(style=Pack(direction=ROW))
        box.add(toga.Button("File…", on_press=browse_file, style=Pack(margin_left=5)))
        box.add(toga.Button("Folder…", on_press=browse_folder, style=Pack(margin_left=5)))
        return box

    def _change_reset_buttons(self, on_change, on_reset):
        box = toga.Box(style=Pack(direction=ROW))
        box.add(toga.Button("Change…", on_press=on_change, style=Pack(margin_left=5)))
        box.add(toga.Button("Reset", on_press=on_reset, style=Pack(margin_left=5)))
        return box

    def on_render_video_log_toggle(self, widget):
        visible = widget.value
        self.render_output_row.style.visibility = VISIBLE if visible else HIDDEN
        self.render_log_format_row.style.visibility = VISIBLE if visible else HIDDEN
        is_custom = self.render_log_format_select.value == FORMAT_CUSTOM
        self.render_log_format_custom_row.style.visibility = (
            VISIBLE if (visible and is_custom) else HIDDEN
        )

    def on_show_terminal_toggle(self, widget):
        self._set_terminal_visible(widget.value)

    def _set_terminal_visible(self, visible):
        self.show_terminal_switch.value = visible
        visibility = VISIBLE if visible else HIDDEN
        self.log_output.style.visibility = visibility
        self.log_label.style.visibility = visibility
        if visible:
            self.log_output.scroll_to_bottom()

    def _set_status(self, text):
        self.status_label.text = text
        self.activity_status_label.text = text

    # ------------------------------------------------------------------
    # Run / process control
    # ------------------------------------------------------------------

    def build_args(self):
        args = []
        source = self.source_input.value.strip() if self.source_input.value else ""
        if self.render_video_log_switch.value:
            output = self.render_output_input.value.strip() if self.render_output_input.value else ""
        else:
            output = self.output_input.value.strip() if self.output_input.value else ""
        if source:
            args.append(source)
        if output:
            args.append(output)
        if self.logs_input.value and self.logs_input.value.strip():
            args += ["--logs", self.logs_input.value.strip()]
        if self.color_switch.value:
            args += ["--color", self.color_profile.value]
        if self.start_time_input.value and self.start_time_input.value.strip():
            args += ["--start-time", self.start_time_input.value.strip()]
        if self.end_time_input.value and self.end_time_input.value.strip():
            args += ["--end-time", self.end_time_input.value.strip()]
        if self.hw_accel_switch.value:
            args.append("--hw-accel")
        if self.layout_input.value and self.layout_input.value.strip():
            args += ["--layout", self.layout_input.value.strip()]
        if self.debug_switch.value:
            args.append("--debug")
        if self.filename_format_input.value and self.filename_format_input.value.strip():
            args += ["--filename-format", self.filename_format_input.value.strip()]
        if self.no_overwrite_switch.value:
            args.append("--no-overwrite")
        if self.summary_switch.value:
            args.append("--summary")
        if self.move_original_input.value and self.move_original_input.value.strip():
            args += ["--move-original", self.move_original_input.value.strip()]
        if self.render_video_log_switch.value:
            args.append("--render-video-log")
            if self.render_log_format_input.value and self.render_log_format_input.value.strip():
                args += ["--render-log-filename-format", self.render_log_format_input.value.strip()]
        return args

    def build_command(self, args):
        # Packaged: sys.executable is this app's own compiled launcher stub.
        # Its argv is regurgitated verbatim into a fresh run of uwmedia/__main__.py
        # (it doesn't behave like a real interpreter, so it can't take "-m uwmedia" -
        # those tokens would just land in sys.argv as bogus CLI args). In `briefcase
        # dev`, sys.executable is a real python interpreter and needs "-m uwmedia"
        # to find the package at all.
        exe = Path(sys.executable)
        if "python" in exe.name.lower():
            return [sys.executable, "-m", "uwmedia", *args]
        return [sys.executable, *args]

    def append_log(self, text):
        self.log_output.value += text
        try:
            self.log_output.scroll_to_bottom()
        except Exception:
            pass

    async def on_run(self, widget):
        if self.is_running:
            self.abort_requested = True
            self._set_status("Aborting…")
            self.append_log("\n[aborting...]\n")
            if self.current_process is not None:
                try:
                    self.current_process.terminate()
                except ProcessLookupError:
                    pass
            return

        args = self.build_args()
        if not args:
            self.log_output.value = "Nothing to run: set a source file/directory first.\n"
            self._set_terminal_visible(True)
            return

        self.is_running = True
        self.abort_requested = False
        self.run_button.text = "Abort"
        self._set_status("Running…")
        self.progress_bar.style.visibility = VISIBLE
        self.progress_bar.start()
        self.log_output.value = ""
        cmd = self.build_command(args)
        self.append_log(f"$ {' '.join(cmd)}\n\n")
        returncode = None
        try:
            self.current_process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            while True:
                line = await self.current_process.stdout.readline()
                if not line:
                    break
                self.append_log(line.decode(errors="replace"))
            await self.current_process.wait()
            returncode = self.current_process.returncode
            self.append_log(f"\n[process exited with code {returncode}]\n")
            if returncode not in (0, None) and not self.show_terminal_switch.value:
                self._set_terminal_visible(True)
        except Exception as exc:
            self.append_log(f"\n[error launching process: {exc}]\n")
            self._set_terminal_visible(True)
            self._set_status("Error")
        finally:
            if self.abort_requested:
                self._set_status("Aborted")
            elif returncode == 0:
                self._set_status("Done — exit 0")
            elif returncode is not None:
                self._set_status(f"Failed — exit {returncode}")
            self.current_process = None
            self.is_running = False
            self.run_button.text = "Run"
            self.progress_bar.stop()
            self.progress_bar.style.visibility = HIDDEN


def main():
    # Packaged (Briefcase) runs pick these up from the app's dist-info metadata
    # automatically; explicit values here are what make `python -m uwmedia` work
    # from a plain source checkout too, where that metadata doesn't exist.
    return UWMediaApp(formal_name="UWMedia", app_id="com.mikaelchristersson.uwmedia")
