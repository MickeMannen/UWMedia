"""
ffmpeg/ffmpeg_class.py: the encoder choice per platform, the ffprobe helpers
on the fixture clips, run_command's progress lines and errors, and the
command process_video builds (checked without encoding, plus one small real
encode).
"""
import subprocess
from datetime import datetime

import pytest

import ffmpeg.ffmpeg_class as ffc
from conftest import DJI_CLIP, SONY_CLIP
from ffmpeg.ffmpeg_class import FfmpegClass


@pytest.fixture
def ff(settings_file):
    return FfmpegClass(hw_accel=False)


def test_missing_ffmpeg_is_a_clear_error(settings_file, monkeypatch):
    monkeypatch.setattr(ffc, "get_ffmpeg_path", lambda: None)
    with pytest.raises(RuntimeError, match="FFmpeg executable not found"):
        FfmpegClass()


def test_missing_ffprobe_is_a_clear_error(ff):
    ff.ffprobe_path = None
    with pytest.raises(RuntimeError, match="ffprobe executable not found"):
        ff.get_video_duration(SONY_CLIP)


@pytest.mark.parametrize("hw, os_type, encoder, quality", [
    (False, "Darwin", "libx265", ["-crf", "18"]),
    (True, "Darwin", "hevc_videotoolbox", ["-q:v", "65"]),
    (True, "Windows", "hevc_nvenc", ["-rc", "vbr", "-cq", "20", "-b:v", "0"]),
    (True, "Linux", "libx265", ["-crf", "18"]),
])
def test_encoder_and_quality_flags_per_platform(ff, hw, os_type, encoder, quality):
    ff.hw_accel = hw
    ff.os_type = os_type
    assert ff.get_encoder() == encoder
    assert ff.quality_args() == quality


def test_version_and_path(ff):
    assert ff.get_version().startswith("ffmpeg version")
    assert ff.get_path() == ff.executable_path


@pytest.mark.parametrize("clip, pix_fmt, hw_ok", [
    (SONY_CLIP, "yuv422p10le", False),  # 10-bit 4:2:2 H.264: no hardware decode
    (DJI_CLIP, "yuv420p10le", True),   # HEVC decodes in hardware
])
def test_probe_helpers_on_the_fixture_clips(ff, clip, pix_fmt, hw_ok):
    assert ff.get_video_duration(clip) == pytest.approx(2.0, abs=0.1)
    assert tuple(ff.get_video_dimensions(clip)) == (1280, 720)
    assert ff.get_video_pix_fmt(clip) == pix_fmt
    assert ff.hw_decodable(clip) is hw_ok
    assert ff.get_video_frame_count(clip) > 0
    assert ff.get_video_bitrate(clip) > 0


def test_probe_fallbacks_for_files_that_are_not_video(ff, tmp_path):
    bogus = tmp_path / "bogus.mp4"
    bogus.write_bytes(b"not a video")
    assert ff.hw_decodable(bogus) is True  # unknown: let the decoder try
    assert ff.get_video_frame_count(bogus) == 0


def test_unknown_bitrate_falls_back_to_10_mbps(ff, monkeypatch):
    answers = []
    def fake_run(cmd, **kwargs):
        answers.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="N/A\n")
    monkeypatch.setattr(ffc.subprocess, "run", fake_run)
    assert ff.get_video_bitrate(SONY_CLIP) == 10_000_000
    assert "stream=bit_rate" in answers[0] and "format=bit_rate" in answers[1]


def test_run_command_reports_progress_over_its_range(ff, tmp_path, capsys):
    out = tmp_path / "out.mp4"
    args = ["-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10:duration=2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)]
    result = ff.run_command(args, duration=2.0, progress_label="clip.mp4", progress_range=(50.0, 100.0))
    assert result.returncode == 0 and out.exists()
    lines = [l for l in capsys.readouterr().out.splitlines() if l.startswith("UWMEDIA_FFMPEG_PROGRESS")]
    assert lines, "no progress lines"
    values = [float(l.split()[1]) for l in lines]
    assert all(l.endswith(" clip.mp4") for l in lines)
    assert values == sorted(values)
    assert 50.0 <= values[0] and values[-1] == 100.0


def test_run_command_without_label_or_duration(ff, tmp_path, capsys):
    out = tmp_path / "out.mp4"
    args = ["-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10:duration=1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)]
    ff.run_command(args, duration=1.0)
    lines = [l for l in capsys.readouterr().out.splitlines() if l.startswith("UWMEDIA_FFMPEG_PROGRESS")]
    assert lines[-1] == "UWMEDIA_FFMPEG_PROGRESS 100.0"
    ff.run_command(args)  # no duration: no progress at all
    assert "UWMEDIA_FFMPEG_PROGRESS" not in capsys.readouterr().out


def test_run_command_raises_with_ffmpegs_error(ff, tmp_path):
    with pytest.raises(subprocess.CalledProcessError) as err:
        ff.run_command(["-i", str(tmp_path / "missing.mp4"), str(tmp_path / "out.mp4")])
    assert "missing.mp4" in err.value.stderr


@pytest.fixture
def captured(ff, monkeypatch):
    """process_video with run_command stubbed out: the arguments it would run."""
    calls = []
    monkeypatch.setattr(ff, "run_command", lambda args, duration=None, **k: calls.append(args))
    return calls


def test_process_video_passthrough_copies_streams_and_sets_the_date(ff, captured, tmp_path):
    out = tmp_path / "out.mp4"
    ff.process_video(SONY_CLIP, out, datetime(2025, 10, 19, 10, 21, 31), tz_offset_mins=-210)
    args = captured[0]
    assert args[args.index("-c") + 1] == "copy"
    assert args[args.index("-metadata") + 1] == "creation_time=2025-10-19T10:21:31-0330"
    assert args[-1] == str(out)
    assert "-vcodec" not in args


def test_process_video_reencode_builds_scale_bitrate_and_colour_tags(ff, captured, tmp_path):
    out = tmp_path / "out.mp4"
    stats = ff.process_video(DJI_CLIP, out, datetime(2026, 5, 2, 10, 6, 59), tz_offset_mins=420,
                             target_resolution=(640, 360), bitrate="2M")
    args = captured[0]
    assert args[args.index("-filter_complex") + 1].startswith("scale=640:360:force_original_aspect_ratio=decrease")
    assert args[args.index("-vcodec") + 1] == "libx265"
    assert args[args.index("-b:v") + 1] == "2M"
    assert args[args.index("-tag:v") + 1] == "hvc1"
    assert args[args.index("-metadata") + 1] == "creation_time=2026-05-02T10:06:59+0700"
    assert args[args.index("-pix_fmt") + 1] == "yuv420p"
    assert stats["total_frames"] > 0


def test_process_video_keeps_the_source_bitrate(ff, captured, tmp_path):
    ff.process_video(SONY_CLIP, tmp_path / "out.mp4", datetime(2025, 10, 19), color_correct=True)
    args = captured[0]
    assert int(args[args.index("-b:v") + 1]) == ff.get_video_bitrate(SONY_CLIP)
    assert "-filter_complex" not in args and "-metadata" not in args


@pytest.mark.render
def test_process_video_encodes_a_smaller_copy(ff, tmp_path):
    out = tmp_path / "small.mp4"
    stats = ff.process_video(DJI_CLIP, out, datetime(2026, 5, 2, 10, 6, 59),
                             target_resolution=(320, 180), bitrate="500k")
    assert out.exists()
    assert tuple(ff.get_video_dimensions(out)) == (320, 180)
    assert ff.get_video_pix_fmt(out) == "yuv420p"
    assert stats["render_time"] > 0
