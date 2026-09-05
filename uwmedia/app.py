import asyncio
import sys
from pathlib import Path

import cv2
import toga
from PIL import Image as PILImage
from toga.style import Pack
from toga.style.pack import COLUMN, HIDDEN, ROW, VISIBLE

import ffmpeg.color as color_module
from ffmpeg.color import ColorCorrectionEngine
from utils.app_settings import add_unique, get_fields, load_settings, set_field, update_settings
from utils.color_params import PARAM_GROUPS, PARAMS_BY_KEY
from utils.color_profiles import (
    load_merged_color_profiles,
    save_user_profile,
    user_color_yaml_path,
)
from utils.layouts import list_layouts, user_layouts_dir

THEME = {
    "sidebar_bg": "#1F2937",
    "sidebar_text": "#E5E7EB",
    "nav_active_bg": "#0EA5A4",
    "nav_active_text": "#FFFFFF",
    "text_muted": "#6B7280",
}

SECTIONS = ("Process", "Color Tuning", "Advanced", "Activity")

TUNING_PREVIEW_MAX_DIM = 600
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
            "Advanced": self._build_advanced_section(),
            "Activity": self._build_activity_section(),
        }
        self.color_tuning_view = self._build_color_tuning_section()

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
        else:
            self.content_box.clear()
            self.content_box.add(self.sections[name])
            self.main_content_area.add(self.content_scroll)

        # The Run/Idle controls drive the CLI subprocess pipeline (Process/
        # Advanced/Batch); Color Tuning is a self-contained in-app preview
        # that never touches that pipeline, so they're just clutter there.
        run_controls_visible = VISIBLE if name != "Color Tuning" else HIDDEN
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
