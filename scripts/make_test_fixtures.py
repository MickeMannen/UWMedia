"""Build the small test media in tests/fixtures/media from the private
full-size originals in test_data/release_test.

    python scripts/make_test_fixtures.py OUT_DIR

Every file is re-encoded smaller with ALL metadata stripped, then only an
allowlist of tags the app reads (dates, time zones, camera make/model, the
DJI recording path its time-zone logic uses) is copied back. Serial numbers,
shutter counts, lens data, maker notes, GPS and thumbnails never carry over.

The owner reviews every output (picture and metadata) before it is copied
into tests/fixtures/media and committed - see tests/fixtures/README.md.
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE = REPO_ROOT / "test_data" / "release_test"

PHOTO_TAGS = [
    "-EXIF:Make", "-EXIF:Model", "-EXIF:Orientation",
    "-EXIF:DateTimeOriginal", "-EXIF:CreateDate", "-EXIF:ModifyDate",
    "-EXIF:OffsetTime", "-EXIF:OffsetTimeOriginal", "-EXIF:OffsetTimeDigitized",
    "-EXIF:SubSecTime", "-EXIF:SubSecTimeOriginal", "-EXIF:SubSecTimeDigitized",
]
VIDEO_TAGS = [
    "-QuickTime:CreateDate", "-QuickTime:ModifyDate",
    "-Keys:CreationDate", "-Keys:CreationTime",
]
DJI_EXTRA_TAGS = ["-UserData:OriginalFilePath"]

# (output name, source, ffmpeg video args, extra tags)
VIDEOS = [
    ("h264_10bit_422_720p_2s.mp4", "20251019_M0284.MP4",
     ["-c:v", "libx264", "-profile:v", "high422", "-pix_fmt", "yuv422p10le", "-crf", "26"], []),
    ("hevc_10bit_420_720p_2s.mp4", "DJI_20260502110658_0002_D_A001.MP4",
     ["-c:v", "libx265", "-pix_fmt", "yuv420p10le", "-crf", "30", "-tag:v", "hvc1",
      "-x265-params", "log-level=error"], DJI_EXTRA_TAGS),
]
# (output name, source, size)
PHOTOS = [
    ("jpeg_3x2_2mp.jpg", "DSC03491.JPG", (1800, 1200)),
]


def run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"failed: {' '.join(map(str, cmd))}\n{result.stderr}")


def copy_allowlisted_tags(source, target, tags):
    run(["exiftool", "-q", "-overwrite_original", "-TagsFromFile", str(source), *tags, str(target)])


def make_video(out_dir, name, source_name, video_args, extra_tags):
    source = SOURCE / source_name
    target = out_dir / name
    run(["ffmpeg", "-v", "error", "-y", "-ss", "0", "-t", "2", "-i", str(source),
         "-map", "0:v:0", "-map", "0:a:0?", "-map_metadata", "-1", "-map_chapters", "-1",
         "-vf", "scale=1280:720", *video_args, "-c:a", "copy",
         "-movflags", "+faststart", str(target)])
    copy_allowlisted_tags(source, target, VIDEO_TAGS + extra_tags)


def make_photo(out_dir, name, source_name, size):
    source = SOURCE / source_name
    target = out_dir / name
    with Image.open(source) as img:
        img.convert("RGB").resize(size, Image.LANCZOS).save(target, "JPEG", quality=90)  # no EXIF
    copy_allowlisted_tags(source, target, PHOTO_TAGS)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out_dir", type=Path)
    args = parser.parse_args()
    for tool in ("ffmpeg", "exiftool"):
        if not shutil.which(tool):
            sys.exit(f"{tool} not found on PATH")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for name, source, video_args, extra in VIDEOS:
        make_video(args.out_dir, name, source, video_args, extra)
        print("made", args.out_dir / name)
    for name, source, size in PHOTOS:
        make_photo(args.out_dir, name, source, size)
        print("made", args.out_dir / name)


if __name__ == "__main__":
    main()
