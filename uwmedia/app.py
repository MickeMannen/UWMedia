import asyncio
import sys
from pathlib import Path

import toga
import yaml
from toga.style import Pack
from toga.style.pack import COLUMN, ROW

from utils.resource_paths import find_resource

CONVERT_CHOICES = ["1080p", "720p", "480p", "360p"]


def load_color_profiles():
    path = find_resource("color.yaml", __file__)
    if not path:
        return ["default"]
    try:
        with open(path, "r") as handle:
            data = yaml.safe_load(handle) or {}
        profiles = list(data.keys())
        return profiles or ["default"]
    except Exception:
        return ["default"]


class UWMediaApp(toga.App):
    def startup(self):
        self.source_input = toga.TextInput(style=Pack(flex=1))
        self.output_input = toga.TextInput(style=Pack(flex=1))
        self.logs_input = toga.TextInput(style=Pack(flex=1))
        self.layout_input = toga.TextInput(style=Pack(flex=1))
        self.move_original_input = toga.TextInput(style=Pack(flex=1))

        self.color_switch = toga.Switch("Apply color correction")
        self.color_profile = toga.Selection(items=load_color_profiles())

        self.start_time_input = toga.TextInput(placeholder="HH:MM:SS", style=Pack(flex=1))
        self.end_time_input = toga.TextInput(placeholder="HH:MM:SS", style=Pack(flex=1))

        self.hw_accel_switch = toga.Switch("Hardware acceleration")
        self.debug_switch = toga.Switch("Debug output")
        self.summary_switch = toga.Switch("Show summary")
        self.no_overwrite_switch = toga.Switch("Skip if target exists")

        self.filename_format_input = toga.TextInput(
            placeholder="%Y%m%d_%H%M%S_color", style=Pack(flex=1)
        )

        self.convert_switches = {res: toga.Switch(res) for res in CONVERT_CHOICES}

        self.render_video_log_switch = toga.Switch(
            "Render video/photo log overlay batch (requires --layout and Logs dir)"
        )

        self.log_output = toga.MultilineTextInput(readonly=True, style=Pack(flex=1, height=200))
        self.run_button = toga.Button("Run", on_press=self.on_run, style=Pack(margin_top=10))

        root = toga.Box(style=Pack(direction=COLUMN, margin=10))

        root.add(self._row("Source", self.source_input, self._browse_button(self.source_input, folder=None)))
        root.add(self._row("Output", self.output_input, self._browse_button(self.output_input, folder=True)))
        root.add(self._row("Dive logs", self.logs_input, self._browse_button(self.logs_input, folder=True)))
        root.add(self._row("Layout / HUD package", self.layout_input, self._browse_button(self.layout_input, folder=None)))
        root.add(self._row("Move original to", self.move_original_input, self._browse_button(self.move_original_input, folder=True)))

        color_box = toga.Box(style=Pack(direction=ROW, margin_bottom=5))
        color_box.add(self.color_switch)
        color_box.add(self.color_profile)
        root.add(color_box)

        root.add(self._row("Start time", self.start_time_input, None))
        root.add(self._row("End time", self.end_time_input, None))
        root.add(self._row("Filename format", self.filename_format_input, None))

        switches_box = toga.Box(style=Pack(direction=ROW, margin_bottom=5))
        for switch in (
            self.hw_accel_switch,
            self.debug_switch,
            self.summary_switch,
            self.no_overwrite_switch,
        ):
            switches_box.add(switch)
        root.add(switches_box)

        convert_box = toga.Box(style=Pack(direction=ROW, margin_bottom=5))
        convert_box.add(toga.Label("Convert to:", style=Pack(margin_right=10)))
        for switch in self.convert_switches.values():
            convert_box.add(switch)
        root.add(convert_box)

        root.add(self.render_video_log_switch)
        root.add(self.run_button)
        root.add(toga.Label("Output", style=Pack(margin_top=10)))
        root.add(self.log_output)

        self.main_window = toga.MainWindow(title=self.formal_name)
        self.main_window.content = root
        self.main_window.show()

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

    def build_args(self):
        args = []
        source = self.source_input.value.strip() if self.source_input.value else ""
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
        selected_res = [res for res, switch in self.convert_switches.items() if switch.value]
        if selected_res:
            args += ["--convert", *selected_res]
        if self.render_video_log_switch.value:
            args.append("--render-video-log")
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

    async def on_run(self, widget):
        args = self.build_args()
        if not args:
            self.log_output.value = "Nothing to run: set a source file/directory first.\n"
            return

        self.run_button.enabled = False
        self.log_output.value = ""
        cmd = self.build_command(args)
        self.append_log(f"$ {' '.join(cmd)}\n\n")
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                self.append_log(line.decode(errors="replace"))
            await process.wait()
            self.append_log(f"\n[process exited with code {process.returncode}]\n")
        except Exception as exc:
            self.append_log(f"\n[error launching process: {exc}]\n")
        finally:
            self.run_button.enabled = True


def main():
    return UWMediaApp()
