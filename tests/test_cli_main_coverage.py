"""cli_main.py paths the render tests don't reach: argument validation and
its error messages, the start-up guards, --export-json / --create-config,
log loading and dive matching (several logs, --tz-adjust, no dive matched),
the parallel batch (one bad file doesn't stop the others, Ctrl+C), the
single-file sequential path, --no-overwrite / --overwrite, --move-original,
--fix-tz / --force-media-tz, the plain-video and --convert paths, photo
overlays, the summary, and the helpers called directly.

main() runs in-process with exiftool (MetadataHandler) and, where the encode
isn't the point, ffmpeg (FfmpegClass) replaced by fakes, so these stay fast.
Only one test renders for real (--render-log to a folder)."""
import json
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

import cli_main
from conftest import REPO_ROOT, write_synthetic_log
from ffmpeg import FfmpegClass as RealFfmpeg
from metadata.exif import MetadataHandler as RealMetadataHandler
from models.manager import DiveManager

DIVE_START = datetime(2025, 12, 3, 9, 0)            # synthetic dive: 09:00-09:45
IN_DIVE = datetime(2025, 12, 3, 9, 15, 48)
AFTER_DIVE = datetime(2025, 12, 3, 10, 20, 0)      # inside it only with --tz-adjust 1
LAYOUT_ZIP = REPO_ROOT / "overlays" / "generic_depth_temp.zip"
PROGRESS_RE = re.compile(r"^UWMEDIA_PROGRESS \d+/(\d+) (\S+) (.*)$", re.M)


# --- fakes -------------------------------------------------------------------

class FakeMeta:
    """MetadataHandler without exiftool: dates and failures from `cfg`."""

    def __init__(self, cfg):
        self.cfg = cfg

    def get_local_creation_date(self, path):
        value = self.cfg.dates.get(path.name, self.cfg.default_date)
        if isinstance(value, BaseException):
            raise value
        return value

    def get_timezone_offset(self, path):
        error = self.cfg.tz_errors.get(path.name)
        if error:
            raise error
        return self.cfg.tz

    def copy_all(self, src, dest, force_tz_mins=None, custom_tags=None):
        if self.cfg.copy_error:
            raise self.cfg.copy_error
        self.cfg.copied.append((Path(src).name, Path(dest).name, force_tz_mins, custom_tags))

    def set_tags(self, path, tags):
        self.cfg.tags.append((Path(path).name, tags))


class FakeFfmpeg:
    """FfmpegClass whose encode just writes a stub file (or fails for the
    resolutions in `fail`)."""
    fail = ()

    def __init__(self, hw_accel=False, debug=False):
        pass

    def process_video(self, input_path, output_path, target_resolution=None, **kwargs):
        if target_resolution and target_resolution[1] in self.fail:
            raise RuntimeError(f"encoder died at {target_resolution[1]}p")
        Path(output_path).write_bytes(b"encoded")
        return {"total_frames": 60, "render_time": 1.0, "render_fps": 60.0}


class FakeColorEngine:
    """ColorCorrectionEngine for photos: a fixed brightening, no analysis."""

    def __init__(self, ff, color_profile=None):
        pass

    def get_filter_matrix(self, rgb):
        return None

    def apply_filter(self, rgb, filt):
        return np.clip(rgb.astype(np.int16) + 40, 0, 255).astype(np.uint8)


@pytest.fixture
def cli(monkeypatch, capsys):
    """Runs cli_main.main() in-process: cli.run(*argv) -> (exit code, stdout)."""
    cfg = SimpleNamespace(dates={}, default_date=IN_DIVE, tz=480, tz_errors={},
                          copy_error=None, copied=[], tags=[])
    monkeypatch.setattr(cli_main, "check_dependencies", lambda is_gui=False: {})
    monkeypatch.setattr(cli_main, "MetadataHandler", lambda: FakeMeta(cfg))
    monkeypatch.setattr(cli_main, "FfmpegClass", FakeFfmpeg)
    monkeypatch.setattr("ffmpeg.color.ColorCorrectionEngine", FakeColorEngine)

    def run(*argv):
        monkeypatch.setattr(sys, "argv", ["cli_main.py", *map(str, argv)])
        try:
            cli_main.main()
            code = 0
        except SystemExit as e:
            code = e.code
        return code, capsys.readouterr().out

    cfg.run = run
    return cfg


def _photo(path, size=(48, 64), value=60):
    """A small grey image (JPEG or PNG by suffix, any case)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, data = cv2.imencode(path.suffix.lower(), np.full((*size, 3), value, np.uint8))
    path.write_bytes(data.tobytes())
    return path


def _layout_json(tmp_path):
    """The small generic depth/temp layout as a plain JSON (a copy, since the
    CLI rewrites a JSON layout's relative skin path in place)."""
    path = tmp_path / "layouts" / "depth_temp.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(LAYOUT_ZIP) as z:
        path.write_bytes(z.read("hud_layout.json"))
    return path


def _statuses(out):
    return {name: status for _, status, name in PROGRESS_RE.findall(out) if status != "start"}


# --- start-up guards -----------------------------------------------------------

@pytest.mark.parametrize("argv, parent, frozen", [
    (["cli_main.py", "a", "b"], object(), False),                         # multiprocessing child
    (["cli_main.py", "--multiprocessing-fork", "x"], None, False),
    (["cli_main.py", "-c", "from multiprocessing.spawn import main"], None, False),
    (["cli_main.py"], None, True),                                        # bare relaunch of a frozen app
], ids=["mp-child", "fork-flag", "dash-c", "frozen-no-args"])
def test_helper_relaunches_return_without_running(monkeypatch, capsys, argv, parent, frozen):
    called = []
    monkeypatch.setattr(cli_main, "check_dependencies", lambda is_gui=False: called.append(1))
    monkeypatch.setattr(cli_main.multiprocessing, "parent_process", lambda: parent)
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(sys, "argv", argv)
    assert cli_main.main() is None
    assert called == [] and capsys.readouterr().out == ""


# --- argument validation -------------------------------------------------------

def test_missing_source_and_output(cli):
    code, out = cli.run()
    assert code == 2
    assert "Error: Source and output are required unless using --render-log or --export-json." in out


def test_parser_errors_print_a_hint(cli):
    code, out = cli.run("--no-such-flag")
    assert code == 2
    assert "Error: unrecognized arguments: --no-such-flag" in out
    assert "Use --help for usage information." in out


def test_naming_options_are_mutually_exclusive(cli, tmp_path):
    code, out = cli.run(tmp_path, tmp_path / "out", "--keep-filename", "--filename-format", "x")
    assert code == 2 and "not allowed with argument" in out


def test_render_log_argument_errors(cli, tmp_path):
    log = tmp_path / "dive.uddf"
    log.write_text("<uddf/>")
    code, out = cli.run("--render-log", log)
    assert code == 1 and "Error: --render-log requires --layout to be specified." in out

    code, out = cli.run("--render-log", log, "ten", "--layout", LAYOUT_ZIP)
    assert code == 1 and "Error: Number of waypoints must be an integer, got 'ten'" in out

    code, out = cli.run("--render-log", tmp_path / "nope.uddf", "--layout", LAYOUT_ZIP)
    assert code == 1 and f"Error: Dive log file '{tmp_path / 'nope.uddf'}' does not exist." in out


@pytest.mark.parametrize("extra, code, message", [
    ([], 1, "Error: --render-video-log requires --layout to be specified."),
    (["--layout", LAYOUT_ZIP], 1, "Error: --render-video-log requires --logs to be specified."),
    (["--layout", LAYOUT_ZIP, "--logs", "."], 2,
     "Error: Source (input folder) and output (output folder) are required when using --render-video-log."),
], ids=["no-layout", "no-logs", "no-folders"])
def test_render_video_log_argument_errors(cli, extra, code, message):
    got, out = cli.run("--render-video-log", *extra)
    assert got == code
    assert message in out


def test_source_must_exist(cli, tmp_path):
    code, out = cli.run(tmp_path / "missing.jpg", tmp_path / "out")
    assert code == 1
    assert f"Error: Source path '{tmp_path / 'missing.jpg'}' does not exist." in out


def test_source_and_output_cannot_be_the_same(cli, tmp_path):
    code, out = cli.run(tmp_path, tmp_path)
    assert code == 1 and "Error: Source and output paths cannot be the same." in out


def test_output_folder_must_be_writable(cli, tmp_path, monkeypatch):
    _photo(tmp_path / "in" / "a.jpg")
    (tmp_path / "out").mkdir()
    monkeypatch.setattr(cli_main.os, "access", lambda path, mode: False)
    code, out = cli.run(tmp_path / "in" / "a.jpg", tmp_path / "out")
    assert code == 1
    assert f"Error: Output directory '{tmp_path / 'out'}' is not writable." in out


def test_source_folder_needs_an_output_folder(cli, tmp_path):
    _photo(tmp_path / "in" / "a.jpg")
    (tmp_path / "out.jpg").write_bytes(b"x")
    code, out = cli.run(tmp_path / "in", tmp_path / "out.jpg")
    assert code == 1 and "Error: Source is a directory but output is a file." in out


def test_hud_package_errors(cli, tmp_path):
    _photo(tmp_path / "a.jpg")
    code, out = cli.run(tmp_path / "a.jpg", tmp_path / "out", "--layout", tmp_path / "missing.zip")
    assert code == 1 and f"Error: HUD package {tmp_path / 'missing.zip'} not found." in out

    package = tmp_path / "empty.zip"
    with zipfile.ZipFile(package, "w") as z:
        z.writestr("readme.txt", "no layout here")
    code, out = cli.run(tmp_path / "a.jpg", tmp_path / "out", "--layout", package)
    assert code == 1 and "Error: HUD package missing hud_layout.json" in out


def test_overlays_file_errors(cli, tmp_path):
    _photo(tmp_path / "a.jpg")
    code, out = cli.run(tmp_path / "a.jpg", tmp_path / "out", "--overlays-file", tmp_path / "overlays.json")
    assert code == 1 and f"Error: --overlays-file {tmp_path / 'overlays.json'} not found." in out

    listing = tmp_path / "overlays.json"
    listing.write_text(json.dumps([{"layout_path": str(tmp_path / "gone.json"), "x": 0.1, "y": 0.1, "scale": 1}]))
    code, out = cli.run(tmp_path / "a.jpg", tmp_path / "out", "--overlays-file", listing)
    assert code == 1
    assert f"Error: overlay layout '{tmp_path / 'gone.json'}' (from --overlays-file) not found." in out


def test_logs_must_be_a_folder(cli, tmp_path):
    _photo(tmp_path / "a.jpg")
    code, out = cli.run(tmp_path / "a.jpg", tmp_path / "out", "--logs", tmp_path / "nologs")
    assert code == 1 and f"Error: Log directory {tmp_path / 'nologs'} not found." in out


def test_layout_with_unknown_fields_is_refused(cli, tmp_path):
    _photo(tmp_path / "a.jpg")
    layout = tmp_path / "bad.json"
    layout.write_text(json.dumps({"hud_skin": {"type": "shape", "linked_elements": [
        {"field": "depth"}, {"field": "warp_speed"}]}}))
    code, out = cli.run(tmp_path / "a.jpg", tmp_path / "out", "--layout", layout)
    assert code == 1 and "Error: Layout bad.json contains unknown fields: warp_speed" in out
    assert not (tmp_path / "out").exists()


# --- --export-json and --create-config -------------------------------------------

def test_export_json_writes_one_file_per_log(cli, tmp_path, monkeypatch):
    real_read = cli_main.read_log_file

    def read(path, args, shift_fit=False):
        if path.name == "crash.uddf":
            raise ValueError("parser blew up")
        return real_read(path, args, shift_fit)
    monkeypatch.setattr(cli_main, "read_log_file", read)
    logs = tmp_path / "logs"
    logs.mkdir()
    write_synthetic_log(logs / "a.uddf", DIVE_START)
    write_synthetic_log(logs / "b.fit", DIVE_START, computer="Garmin Descent X50i")
    (logs / "empty.ssrf").write_text('<divelog program="subsurface" version="3"><dives></dives></divelog>')
    (logs / "broken.fit").write_bytes(b"not a fit file")
    (logs / "crash.uddf").write_text("<uddf/>")
    (logs / "notes.txt").write_text("not a log")
    (logs / ".hidden.uddf").write_text("ignored")
    out_dir = tmp_path / "json"

    code, out = cli.run("--export-json", out_dir, "--logs", logs, "--tz-adjust", "2")
    assert code == 0
    assert sorted(p.name for p in out_dir.iterdir()) == ["a.json", "b.json"]
    assert "No dives found in empty.ssrf" in out
    assert "No dives found in broken.fit" in out
    assert "Error parsing crash.uddf: parser blew up" in out
    assert "Export completed. Processed 2 log files." in out
    # --tz-adjust shifts both formats in the export (FIT too, unlike a render)
    for name in ("a.json", "b.json"):
        waypoints = json.loads((out_dir / name).read_text())
        assert waypoints[0]["timestamp"] == "2025-12-03 11:00:00"
        assert set(waypoints[0]) == {"timestamp", "depth"}


def test_export_json_needs_an_existing_log_folder(cli, tmp_path):
    code, out = cli.run("--export-json", tmp_path / "nowhere")
    assert code == 1
    assert f"Error: Log directory '{tmp_path / 'nowhere'}' does not exist or is not a directory." in out
    assert not (tmp_path / "nowhere").exists()


def test_create_config_collects_tank_serials(cli, tmp_path, monkeypatch):
    saved = []
    monkeypatch.setattr("utils.config.get_config",
                        lambda: SimpleNamespace(save_config=saved.append, is_loaded=lambda: True))
    logs = tmp_path / "logs"
    logs.mkdir()
    write_synthetic_log(logs / "dive.fit", DIVE_START, computer="Garmin Descent X50i")
    write_synthetic_log(logs / "dive.uddf", DIVE_START)   # not scanned for tanks
    _photo(tmp_path / "a.jpg")

    code, out = cli.run(tmp_path / "a.jpg", tmp_path / "out", "--logs", logs, "--create-config")
    assert code == 0
    assert saved == [["100001"]]
    assert "You can now edit config.yaml" in out
    assert not (tmp_path / "out").exists()


# --- logs, dive matching, time zones ---------------------------------------------

def test_photos_match_their_own_dive_across_several_logs(cli, tmp_path, monkeypatch):
    monkeypatch.setattr("utils.config.get_config", lambda: SimpleNamespace(is_loaded=lambda: False))
    logs = tmp_path / "logs"
    logs.mkdir()
    write_synthetic_log(logs / "december.uddf", DIVE_START)
    write_synthetic_log(logs / "october.fit", datetime(2025, 10, 19, 10, 0), computer="Garmin Descent X50i")
    (logs / "readme.txt").write_text("not a log")
    (logs / ".DS_Store").write_bytes(b"")
    (logs / "subfolder").mkdir()
    _photo(tmp_path / "in" / "dec.jpg")
    _photo(tmp_path / "in" / "oct.jpg")
    _photo(tmp_path / "in" / "may.jpg")
    cli.dates.update({"dec.jpg": IN_DIVE, "oct.jpg": datetime(2025, 10, 19, 10, 30),
                      "may.jpg": datetime(2026, 5, 2, 10, 6)})

    code, out = cli.run(tmp_path / "in", tmp_path / "out", "--logs", logs)
    assert code == 0
    assert "Matched dive starting at 2025-12-03 09:00:00" in out
    assert "Matched dive starting at 2025-10-19 10:00:00" in out
    assert out.count("Warning: No matching dive log found for this file.") == 1
    assert "Creation Date: 2026-05-02 10:06:00" in out
    # FIT logs and no config.yaml: the tank-name warning
    assert "WARNING: Garmin logs found but no config.yaml loaded." in out
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == [
        "20251019_103000.jpg", "20251203_091548.jpg", "20260502_100600.jpg"]


def test_tz_adjust_moves_the_log_onto_the_media(cli, tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    write_synthetic_log(logs / "dive.uddf", DIVE_START)
    _photo(tmp_path / "a.jpg")
    cli.default_date = AFTER_DIVE

    code, out = cli.run(tmp_path / "a.jpg", tmp_path / "out1", "--logs", logs)
    assert code == 0 and "Warning: No matching dive log found for this file." in out

    code, out = cli.run(tmp_path / "a.jpg", tmp_path / "out2", "--logs", logs, "--tz-adjust", "1")
    assert code == 0 and "Matched dive starting at 2025-12-03 10:00:00" in out
    assert "<timezone>" in (logs / "dive.uddf").read_text()


def test_read_log_file_tz_adjust(tmp_path):
    args = SimpleNamespace(tz_adjust=2)
    uddf = write_synthetic_log(tmp_path / "dive.uddf", DIVE_START)
    fit = write_synthetic_log(tmp_path / "dive.fit", DIVE_START, computer="Garmin Descent X50i")
    (tmp_path / "notes.txt").write_text("x")

    dive = cli_main.read_log_file(uddf, args)[0]
    assert dive.start_time == datetime(2025, 12, 3, 11, 0)
    assert dive.waypoints[0].timestamp == datetime(2025, 12, 3, 11, 0)
    # FIT dives carry UTC, so they shift only for the JSON export
    assert cli_main.read_log_file(fit, args)[0].start_time == DIVE_START
    assert cli_main.read_log_file(fit, args, shift_fit=True)[0].start_time == datetime(2025, 12, 3, 11, 0)
    assert cli_main.read_log_file(tmp_path / "notes.txt", args) is None


def test_force_media_tz_is_used_and_passed_to_the_metadata_copy(cli, tmp_path):
    _photo(tmp_path / "a.jpg")
    code, out = cli.run(tmp_path / "a.jpg", tmp_path / "out", "--force-media-tz", "5.5")
    assert code == 0
    assert "Using Forced Timezone Offset: +5.5 hours" in out
    assert cli.copied == [("a.jpg", "20251203_091548.jpg", 330, None)]


def test_detected_media_tz_is_reported(cli, tmp_path):
    _photo(tmp_path / "a.jpg")
    cli.tz = -330
    code, out = cli.run(tmp_path / "a.jpg", tmp_path / "out")
    assert code == 0 and "Detected Timezone Offset: -5.5 hours" in out
    assert cli.copied[0][2] is None   # only a forced offset is written


# --- --fix-tz ----------------------------------------------------------------------

def test_fix_tz_needs_an_offset_or_tags(cli, tmp_path):
    _photo(tmp_path / "a.jpg")
    code, out = cli.run(tmp_path / "a.jpg", tmp_path / "out", "--fix-tz")
    assert code == 1
    assert "Error: --fix-tz requires --force-media-tz or --modify-quicktime to be specified." in out


def test_fix_tz_copies_and_rewrites_metadata(cli, tmp_path):
    source = _photo(tmp_path / "a.jpg")
    code, out = cli.run(source, tmp_path / "out", "--fix-tz", "--force-media-tz", "-3", "--summary")
    assert code == 0
    target = tmp_path / "out" / "20251203_091548.jpg"
    assert target.read_bytes() == source.read_bytes()
    assert cli.copied == [("a.jpg", "20251203_091548.jpg", -180, None)]
    assert "Success: Metadata updated." in out and "Metadata Copying" in out


def test_fix_tz_reports_a_metadata_failure(cli, tmp_path):
    _photo(tmp_path / "a.jpg")
    cli.copy_error = RuntimeError("exiftool refused")
    code, out = cli.run(tmp_path / "a.jpg", tmp_path / "out", "--fix-tz",
                        "--modify-quicktime", "QuickTime:CreateDate=2025:12:03 01:15:48")
    assert code == 0
    assert "Error updating metadata: exiftool refused" in out
    assert (tmp_path / "out" / "20251203_091548.jpg").exists()


# --- batches -----------------------------------------------------------------------

def test_parallel_batch_one_bad_file_does_not_stop_the_rest(cli, tmp_path):
    src = tmp_path / "in"
    for name in ("a.jpg", "b.jpg", "bad.jpg", "boom.jpg"):
        _photo(src / name)
    (src / ".hidden.jpg").write_bytes(b"ignored")
    cli.dates.update({"a.jpg": datetime(2025, 12, 3, 9, 15, 48, 120000),
                      "b.jpg": datetime(2025, 12, 3, 9, 20, 0),
                      "bad.jpg": ValueError("no date tag")})
    cli.tz_errors["boom.jpg"] = RuntimeError("probe crashed")

    code, out = cli.run(src, tmp_path / "out", "--summary")
    assert code == 1  # the good files are done, but the run reports the failures
    assert "2 of 4 files failed." in out
    assert "Starting parallel batch processing with" in out
    # Date-named outputs; a photo keeps its milliseconds apart
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["20251203_091548_120.jpg", "20251203_092000.jpg"]
    assert "Error extracting metadata for" in out and "no date tag" in out
    assert "Error processing boom.jpg: probe crashed" in out
    statuses = _statuses(out)
    assert set(statuses) == {"a.jpg", "b.jpg", "bad.jpg", "boom.jpg"}
    assert statuses["a.jpg"] == statuses["b.jpg"] == "done"
    assert statuses["boom.jpg"] == "error"
    assert set(re.findall(r"^UWMEDIA_PROGRESS_ACTIVE (.*)$", out, re.M)) == set(statuses)
    assert re.search(r"^UWMEDIA_PROGRESS 4/4 ", out, re.M)
    assert "UWMEDIA_PROGRESS 0/4 start -" in out
    plain = re.sub(r"\033\[[0-9;]*m", "", out)
    assert "File: bad.jpg - Failed: Error extracting metadata: no date tag" in plain
    assert "File: boom.jpg - Failed: probe crashed" in plain
    assert "File: a.jpg (Photo)" in plain and "Copying Photo" in plain


def test_metadata_error_is_reported_as_error_in_progress(cli, tmp_path):
    for name in ("a.jpg", "bad.jpg"):
        _photo(tmp_path / "in" / name)
    cli.dates["bad.jpg"] = ValueError("no date tag")
    code, out = cli.run(tmp_path / "in", tmp_path / "out")
    assert _statuses(out)["bad.jpg"] == "error"
    assert code == 1


def test_a_run_without_failures_exits_0(cli, tmp_path):
    for name in ("a.jpg", "b.jpg"):
        _photo(tmp_path / "in" / name)
    code, out = cli.run(tmp_path / "in", tmp_path / "out")
    assert code == 0 and "failed." not in out


def test_ctrl_c_stops_the_batch(cli, tmp_path):
    for name in ("a.jpg", "b.jpg"):
        _photo(tmp_path / "in" / name)
    cli.tz_errors["a.jpg"] = KeyboardInterrupt()
    code, out = cli.run(tmp_path / "in", tmp_path / "out")
    assert code == 1
    assert "KeyboardInterrupt received. Shutting down worker threads..." in out
    assert "All tasks complete." not in out


def test_single_file_folder_runs_sequentially(cli, tmp_path):
    _photo(tmp_path / "in" / "only.jpg")
    code, out = cli.run(tmp_path / "in", tmp_path / "out")
    assert code == 0
    assert "parallel" not in out
    assert "UWMEDIA_PROGRESS 1/1 done only.jpg" in out
    assert (tmp_path / "out" / "20251203_091548.jpg").exists()


def test_single_file_to_an_explicit_file_name(cli, tmp_path):
    _photo(tmp_path / "a.jpg")
    (tmp_path / "out").mkdir()
    code, out = cli.run(tmp_path / "a.jpg", tmp_path / "out" / "Picked.JPG")
    assert code == 0
    assert [p.name for p in (tmp_path / "out").iterdir()] == ["Picked.jpg"]


# --- existing targets, moving originals ----------------------------------------------

def test_no_overwrite_skips_existing_targets(cli, tmp_path):
    for name in ("a.jpg", "b.jpg"):
        _photo(tmp_path / "in" / name)
    cli.dates.update({"a.jpg": datetime(2025, 12, 3, 9, 15, 0), "b.jpg": datetime(2025, 12, 3, 9, 16, 0)})
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "20251203_091500.jpg").write_bytes(b"earlier output")

    code, out = cli.run(tmp_path / "in", out_dir, "--color", "--no-overwrite", "--summary")
    assert code == 0
    assert (out_dir / "20251203_091500.jpg").read_bytes() == b"earlier output"
    assert (out_dir / "20251203_091600.jpg").exists()
    assert sorted(p.name for p in out_dir.iterdir()) == ["20251203_091500.jpg", "20251203_091600.jpg"]
    assert _statuses(out) == {"a.jpg": "skipped", "b.jpg": "done"}
    assert "Skipped (Target exists)" in out and "Color Correction" in out


def test_overwrite_replaces_the_target(cli, tmp_path):
    _photo(tmp_path / "a.jpg")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "20251203_091548.jpg").write_bytes(b"earlier output")

    code, out = cli.run(tmp_path / "a.jpg", out_dir, "--color", "--overwrite")
    assert code == 0
    assert "Overwriting existing target file:" in out
    assert [p.name for p in out_dir.iterdir()] == ["20251203_091548.jpg"]
    assert cv2.imread(str(out_dir / "20251203_091548.jpg")).mean() > 80   # brightened, not the old bytes


def test_without_overwrite_flags_a_numbered_name_is_used(cli, tmp_path):
    _photo(tmp_path / "a.jpg")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "20251203_091548.jpg").write_bytes(b"earlier output")
    code, _ = cli.run(tmp_path / "a.jpg", out_dir, "--color")
    assert code == 0
    assert sorted(p.name for p in out_dir.iterdir()) == ["20251203_091548.jpg", "20251203_091548_1.jpg"]


def test_move_original_after_processing(cli, tmp_path):
    source = _photo(tmp_path / "in" / "DSC01.JPG")
    done = tmp_path / "done"
    done.mkdir()
    (done / "DSC01.JPG").write_bytes(b"an earlier original")

    code, out = cli.run(source, tmp_path / "out", "--color", "--move-original", done, "--summary")
    assert code == 0
    assert not source.exists()
    assert sorted(p.name for p in done.iterdir()) == ["DSC01.JPG", "DSC01_1.JPG"]
    assert (tmp_path / "out" / "20251203_091548.jpg").exists()
    assert "Moving Original File" in out


def test_move_original_failure_keeps_the_source(cli, tmp_path):
    source = _photo(tmp_path / "in" / "a.jpg")
    blocker = tmp_path / "done"
    blocker.write_bytes(b"a file, not a folder")
    code, out = cli.run(source, tmp_path / "out", "--color", "--move-original", blocker)
    assert code == 0
    assert source.exists()
    assert "Error moving original file" in out


def test_move_original_needs_color_or_layout(cli, tmp_path):
    source = _photo(tmp_path / "in" / "a.jpg")
    code, _ = cli.run(source, tmp_path / "out", "--move-original", tmp_path / "done")
    assert code == 0
    assert source.exists() and not (tmp_path / "done").exists()


# --- photos -----------------------------------------------------------------------

def test_unreadable_photo_is_copied_as_is(cli, tmp_path):
    source = tmp_path / "broken.jpg"
    source.write_bytes(b"not really a jpeg")
    code, out = cli.run(source, tmp_path / "out", "--color")
    assert code == 0
    assert "Error: Could not read image" in out
    assert (tmp_path / "out" / "20251203_091548.jpg").read_bytes() == b"not really a jpeg"


def test_metadata_copy_failure_is_a_warning(cli, tmp_path):
    _photo(tmp_path / "a.jpg")
    cli.copy_error = RuntimeError("exiftool missing")
    code, out = cli.run(tmp_path / "a.jpg", tmp_path / "out")
    assert code == 0
    assert "Warning: Failed to copy metadata: exiftool missing" in out
    assert (tmp_path / "out" / "20251203_091548.jpg").exists()


def test_photo_overlay_from_layout_and_overlays_file(cli, tmp_path, synthetic_logs):
    source = _photo(tmp_path / "a.png", size=(360, 640), value=0)
    layout = _layout_json(tmp_path)
    listing = tmp_path / "overlays.json"
    listing.write_text(json.dumps([{"layout_path": str(layout), "x": 0.1, "y": 0.1, "scale": 0.5}]))

    code, out = cli.run(source, tmp_path / "out", "--logs", synthetic_logs, "--layout", layout,
                        "--overlays-file", listing, "--keep-filename", "--summary")
    assert code == 0, out
    result = cv2.imread(str(tmp_path / "out" / "a.png"))
    assert result.shape == (360, 640, 3) and result.max() > 0   # the overlays drew on the black photo
    assert "HUD Overlay" in out


def test_photo_overlay_without_a_dive_is_left_plain(cli, tmp_path):
    source = _photo(tmp_path / "a.png", size=(90, 160), value=0)
    code, out = cli.run(source, tmp_path / "out", "--layout", _layout_json(tmp_path), "--keep-filename")
    assert code == 0
    assert cv2.imread(str(tmp_path / "out" / "a.png")).max() == 0


# --- videos (ffmpeg faked) ------------------------------------------------------------

def test_plain_video_goes_through_ffmpeg(cli, tmp_path):
    source = tmp_path / "clip.MP4"
    source.write_bytes(b"fake video")
    cli.default_date = datetime(2025, 12, 3, 9, 15, 48, 500000)   # no ms suffix on videos

    code, out = cli.run(source, tmp_path / "out", "--summary")
    assert code == 0
    assert (tmp_path / "out" / "20251203_091548.mp4").read_bytes() == b"encoded"
    plain = re.sub(r"\033\[[0-9;]*m", "", out)
    assert "File: clip.MP4 (Video)" in plain and "FFmpeg Native Processing" in plain
    assert "Overall FPS:" in plain


def test_convert_carries_on_after_a_failed_resolution(cli, tmp_path, monkeypatch):
    monkeypatch.setattr(FakeFfmpeg, "fail", (480,))
    source = tmp_path / "GX010001.MP4"
    source.write_bytes(b"fake video")

    code, out = cli.run(source, tmp_path / "out", "--convert", "720p", "480p", "360p", "--summary")
    assert code == 1  # the other sizes are written, but the run reports the failure
    assert "Error converting to 480p: encoder died at 480p" in out
    assert "Failed: Conversion failed: 480p" in re.sub(r"\033\[[0-9;]*m", "", out)
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["GX010001 360p.mp4", "GX010001 720p.mp4"]
    assert _statuses(out) == {"GX010001 720p.mp4": "done", "GX010001 480p.mp4": "error",
                              "GX010001 360p.mp4": "done"}


def test_process_conversions_skips_unknown_names_and_warns_on_metadata(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli_main, "FfmpegClass", FakeFfmpeg)
    cfg = SimpleNamespace(copy_error=RuntimeError("no exiftool"))
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"v")
    args = SimpleNamespace(convert=["8k", "720p"], hw_accel=False, debug=False,
                           force_media_tz=1.0, modify_quicktime=None)
    cli_main.process_conversions(source, tmp_path, args, IN_DIVE, 60, FakeMeta(cfg))
    out = capsys.readouterr().out
    assert "Warning: Failed to copy metadata: no exiftool" in out
    assert sorted(p.name for p in tmp_path.iterdir()) == ["clip 720p.mp4", "clip.mp4"]


# --- --render-video-log and --render-log -------------------------------------------------

def test_render_video_log_photo_with_bad_name_pattern(cli, tmp_path, synthetic_logs):
    _photo(tmp_path / "in" / "a.jpg")
    _photo(tmp_path / "in" / "b.jpg")
    cli.copy_error = RuntimeError("exiftool missing")
    code, out = cli.run(tmp_path / "in", tmp_path / "out", "--render-video-log", "--layout", LAYOUT_ZIP,
                        "--logs", synthetic_logs, "--render-log-filename-format", "{filename}_{nope}")
    assert code == 0
    assert "Error formatting render-log filename with pattern '{filename}_{nope}'" in out
    assert "Warning: Failed to copy metadata: exiftool missing" in out
    names = sorted(p.name for p in (tmp_path / "out").iterdir())
    assert names == ["a_generic_depth_temp.jpg", "b_generic_depth_temp.jpg"]


@pytest.mark.render
def test_render_log_to_a_folder_names_the_file_after_log_and_layout(cli, tmp_path, monkeypatch):
    monkeypatch.setattr(cli_main, "FfmpegClass", RealFfmpeg)   # a real encode here

    def _no_exiftool(self, path, tags):
        raise RuntimeError("exiftool missing")
    monkeypatch.setattr(RealMetadataHandler, "set_tags", _no_exiftool)
    log = write_synthetic_log(tmp_path / "dive.uddf", DIVE_START)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "dive_generic_depth_temp.mp4").write_bytes(b"earlier render")

    code, out = cli.run(out_dir, "--render-log", log, "3", "--layout", LAYOUT_ZIP)
    assert code == 0, out
    rendered = out_dir / "dive_generic_depth_temp_1.mp4"
    assert rendered.stat().st_size > 1000
    assert "Warning: Failed to write creation date metadata: exiftool missing" in out


def _render_log_args(tmp_path, limit):
    return SimpleNamespace(tz_adjust=0, limit_waypoints=limit, original_layout_stem="hud",
                           hw_accel=False, debug=False, layout=None)


def test_process_log_only_errors(tmp_path, monkeypatch, capsys):
    notes = tmp_path / "notes.txt"
    notes.write_text("x")
    with pytest.raises(SystemExit) as e:
        cli_main.process_log_only(notes, tmp_path, _render_log_args(tmp_path, None), None, None)
    assert e.value.code == 1 and "Error: Unsupported log format .txt" in capsys.readouterr().out

    log = write_synthetic_log(tmp_path / "dive.uddf", DIVE_START)
    with pytest.raises(SystemExit) as e:   # one waypoint: no time to render
        cli_main.process_log_only(log, tmp_path, _render_log_args(tmp_path, 1), None, None)
    assert e.value.code == 1 and "Error: Dive duration is zero." in capsys.readouterr().out

    monkeypatch.setattr(cli_main, "read_log_file", lambda path, args: [])
    with pytest.raises(SystemExit) as e:
        cli_main.process_log_only(log, tmp_path, _render_log_args(tmp_path, None), None, None)
    assert e.value.code == 1 and "Error: No dives found in dive.uddf" in capsys.readouterr().out


# --- helpers called directly ---------------------------------------------------------------

def test_validate_layout_messages(tmp_path, capsys):
    manager = DiveManager()
    assert cli_main.validate_layout(tmp_path / "missing.json", manager) is None

    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(SystemExit) as e:
        cli_main.validate_layout(bad, manager)
    assert e.value.code == 1 and "Error: Failed to parse layout JSON bad.json" in capsys.readouterr().out

    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"hud_skin": {}}))
    cli_main.validate_layout(empty, manager)
    assert "Warning: Layout empty.json has no linked telemetry elements." in capsys.readouterr().out


def test_validate_layout_warns_about_tanks_missing_from_the_logs(tmp_path, capsys):
    layout = tmp_path / "tanks.json"
    layout.write_text(json.dumps({"hud_skin": {"linked_elements": [
        {"field": "tank_pressure:111"}, {"field": "tank_name:222"}, {"field": "custom:bar"}]}}))
    dive = SimpleNamespace(waypoints=[SimpleNamespace(tanks=None), SimpleNamespace(tanks={"111": 200})])
    manager = SimpleNamespace(dives={("s", "e"): dive, ("s2", "e2"): SimpleNamespace(waypoints=[])})
    cli_main.validate_layout(layout, manager)
    assert "Warning: Layout references tank serials not found in loaded logs: 222" in capsys.readouterr().out

    dive.waypoints[1].tanks["222"] = 150
    cli_main.validate_layout(layout, manager)
    assert capsys.readouterr().out == ""


def test_overlay_canvas_with_an_unreadable_skin_image():
    layout = {"hud_skin": {"type": "image", "path": str(Path("no") / "such" / "skin.png")}}
    width, height, render_log, resolved = cli_main.overlay_canvas(layout, SimpleNamespace(overlay_size="4k"))
    assert (width, height, render_log) == (3840, 2160, True)
    assert resolved["hud_skin"]["anchor"] == "CENTER"
    assert "anchor" not in layout["hud_skin"]   # the caller's layout isn't changed


def _naming_args(source, **kw):
    base = dict(render_video_log=False, original_layout_stem=None, overlay_instances=None,
                render_log_filename_format="{filename}_{hud}", filename_format=None,
                keep_filename=False, source=source)
    base.update(kw)
    return SimpleNamespace(**base)


def test_output_filename_variants(tmp_path, capsys):
    source = tmp_path / "DSC01.JPG"
    taken = datetime(2025, 12, 3, 9, 15, 48, 980000)
    # Same folder, single file, no pattern: the source name (plus milliseconds)
    assert cli_main.output_filename(source, tmp_path, _naming_args(source), taken) == "DSC01_980.jpg"
    # A forced name (an explicit output file) only gets its extension lower-cased
    assert cli_main.output_filename(source, tmp_path, _naming_args(source), taken.replace(microsecond=0),
                                    "Mine.JPEG") == "Mine.jpeg"
    # {datetaken} in the render-log pattern; a broken pattern falls back to name_hud
    args = _naming_args(source, render_video_log=True, original_layout_stem="hud",
                        render_log_filename_format="{datetaken:%Y%m%d}_{hud}")
    assert cli_main.output_filename(source, tmp_path, args, taken) == "20251203_hud.jpg"
    args.render_log_filename_format = "{oops"
    assert cli_main.output_filename(source, tmp_path, args, taken) == "DSC01_hud.jpg"
    assert "Error formatting render-log filename" in capsys.readouterr().out


def test_resolve_target_path_overwrite(tmp_path, capsys):
    source = tmp_path / "src.jpg"
    source.write_bytes(b"s")
    target = tmp_path / "out.jpg"
    target.write_bytes(b"t")
    args = SimpleNamespace(color="default", layout=None, render_video_log=False, no_overwrite=False, overwrite=True)
    assert cli_main.resolve_target_path(target, source, args) == (target, False)
    assert "Overwriting existing target file" in capsys.readouterr().out
    # Even --overwrite never writes over the source itself
    assert cli_main.resolve_target_path(source, source, args) == (tmp_path / "src_1.jpg", False)


@pytest.mark.parametrize("extra", [[], ["--filename-format", "%Y%m%d_%H%M%S"]])
def test_an_explicit_output_file_name_is_used_as_given(cli, tmp_path, extra):
    """No milliseconds added and no filename format applied: the Color page's
    "output file" is the name the user picked."""
    _photo(tmp_path / "a.jpg")
    cli.dates["a.jpg"] = datetime(2025, 12, 3, 9, 15, 48, 980000)
    (tmp_path / "out").mkdir()
    code, out = cli.run(tmp_path / "a.jpg", tmp_path / "out" / "Picked.jpg", "--color", *extra)
    assert code == 0, out
    assert [p.name for p in (tmp_path / "out").iterdir()] == ["Picked.jpg"]
