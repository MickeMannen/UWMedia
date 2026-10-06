"""
Output file naming in cli_main.py (output_filename / resolve_target_path):
--keep-filename, --filename-format, the date-taken default, and the guard
that never writes over the source file. Files live in tmp_path only.
"""
from argparse import Namespace
from datetime import datetime

import pytest

from cli_main import output_filename, resolve_target_path

TAKEN = datetime(2026, 9, 5, 14, 30, 0, 123456)


def _args(source, **overrides):
    args = dict(
        source=source, render_video_log=False, original_layout_stem=None, render_log_filename_format=None,
        filename_format=None, keep_filename=False, color="default", layout=None,
        no_overwrite=False, overwrite=False,
    )
    args.update(overrides)
    return Namespace(**args)


@pytest.fixture
def photo(tmp_path):
    src_dir = tmp_path / "raw"
    src_dir.mkdir()
    path = src_dir / "DSC06641.JPG"
    path.write_bytes(b"x")
    return path


def test_keep_filename_keeps_name_in_batch_to_other_folder(tmp_path, photo):
    out = tmp_path / "out"
    args = _args(photo.parent, keep_filename=True)
    # No millisecond suffix and no date naming - just the original name.
    assert output_filename(photo, out, args, TAKEN) == "DSC06641.jpg"


def test_default_batch_naming_is_still_date_taken(tmp_path, photo):
    args = _args(photo.parent)
    assert output_filename(photo, tmp_path / "out", args, TAKEN) == "20260905_143000_123.jpg"


def test_filename_format_pattern(tmp_path, photo):
    args = _args(photo.parent, filename_format="%Y%m%d_Bali")
    assert output_filename(photo, tmp_path / "out", args, TAKEN) == "20260905_Bali_123.jpg"


def test_filename_token_keeps_source_name_without_milliseconds(tmp_path, photo):
    """"{filename}_color" (the Color page's Original + color preset): the
    source name plus the suffix, no photo millisecond suffix - the name is
    already unique per source, like --keep-filename."""
    args = _args(photo.parent, filename_format="{filename}_color")
    assert output_filename(photo, tmp_path / "out", args, TAKEN) == "DSC06641_color.jpg"
    args = _args(photo.parent, filename_format="%Y%m%d_{filename}")
    assert output_filename(photo, tmp_path / "out", args, TAKEN) == "20260905_DSC06641.jpg"


def test_keep_filename_into_source_folder_never_overwrites_source(photo):
    # The output is DSC06641.jpg. Where file names ignore case (macOS, Windows)
    # that is the source DSC06641.JPG itself, so it gets _1; on Linux it's another file.
    case_insensitive = photo.with_name("DSC06641.jpg").exists()
    for overwrite in (False, True):
        args = _args(photo.parent, keep_filename=True, overwrite=overwrite)
        name = output_filename(photo, photo.parent, args, TAKEN)
        target, skipped = resolve_target_path(photo.parent / name, photo, args)
        assert not skipped
        assert target.name == ("DSC06641_1.jpg" if case_insensitive else "DSC06641.jpg")
        assert not (target.exists() and target.samefile(photo))  # the source itself is left alone
    assert photo.read_bytes() == b"x"


def test_no_overwrite_does_not_skip_because_of_the_source(photo):
    args = _args(photo.parent, keep_filename=True, no_overwrite=True)
    target, skipped = resolve_target_path(photo.parent / "DSC06641.jpg", photo, args)
    assert not skipped
    assert target != photo


def test_no_overwrite_still_skips_earlier_output(tmp_path, photo):
    out = tmp_path / "out"
    out.mkdir()
    (out / "DSC06641.jpg").write_bytes(b"old")
    args = _args(photo.parent, keep_filename=True, no_overwrite=True)
    _, skipped = resolve_target_path(out / "DSC06641.jpg", photo, args)
    assert skipped


def test_keep_filename_and_filename_format_are_exclusive():
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "cli_main.py", "--keep-filename", "--filename-format", "%Y"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "not allowed with argument" in result.stdout + result.stderr  # the CLI prints errors to stdout


def test_hud_token_is_the_first_overlay_name(tmp_path, photo):
    """"%Y%m%d_%H%M%S_{hud}" (the Color page's Date + time + overlay
    preset): the first --overlays-file entry's name, or the --layout's."""
    overlays = [{"layout_path": "/tmp/x/garmin_mk3i_main.json"}, {"layout_path": "/tmp/x/shearwater_perdix.json"}]
    args = _args(photo.parent, filename_format="%Y%m%d_%H%M%S_{hud}", overlay_instances=overlays)
    assert output_filename(photo, tmp_path / "out", args, TAKEN) == "20260905_143000_garmin_mk3i_main_123.jpg"
    args = _args(photo.parent, filename_format="%Y%m%d_%H%M%S_{hud}", original_layout_stem="my_hud")
    assert output_filename(photo, tmp_path / "out", args, TAKEN) == "20260905_143000_my_hud_123.jpg"


def test_hud_token_without_an_overlay_is_left_out(tmp_path, photo):
    args = _args(photo.parent, filename_format="%Y%m%d_%H%M%S_{hud}")
    assert output_filename(photo, tmp_path / "out", args, TAKEN) == "20260905_143000_123.jpg"
