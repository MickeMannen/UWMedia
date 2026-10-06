# Test fixtures

Small test media that live in git. They are used by the render tests in
place of the private full-size originals in `test_data/` (see
`testing_plan.md`, "Fixture layout").

Rules (`CONTRIBUTING.md`):
- Every file is reviewed by the owner, picture and metadata, before it is
  committed. Each file's row below is that review record.
- No dive logs here or anywhere in git. Tests that need a log generate a
  synthetic one at run time.

## How the media is made

`scripts/make_test_fixtures.py OUT_DIR` builds the files from
`test_data/release_test`. Each file is re-encoded smaller with all metadata
stripped. Only an allowlist of tags the app reads is then copied back:
creation dates and time zones, plus camera make/model for photos and the
recording path for DJI clips. Serial numbers, shutter counts, lens data,
maker notes, GPS and thumbnails never carry over.

A rebuilt file has a different checksum from the one below, so it needs a
new review before it replaces the committed file.

## Files

| File | Made from | What tests need from it | Kept metadata | SHA-256 | Reviewed |
|---|---|---|---|---|---|
| `media/video/h264_10bit_422_720p_2s.mp4` | Sony `20251019_M0284.MP4`, first 2 s, 1280x720 | H.264 High 4:2:2 10-bit (hardware decoders can't take it), 50 fps, PCM audio; recorded 2025-10-19 10:21:31 +08:00 | QuickTime CreateDate/ModifyDate, Keys CreationDate/CreationTime | `e964b91f603063cf5c0070e33b339a4d8bebaf9a6106fdde449172ce14ee8990` | Owner, 2026-10-06 |
| `media/video/hevc_10bit_420_720p_2s.mp4` | DJI `DJI_20260502110658_0002_D_A001.MP4`, first 2 s, 1280x720 | HEVC Main 10 4:2:0 (hardware-decodable), 50 fps, AAC audio; recorded 2026-05-02 10:06:59 +07:00. Shows a diver - the owner, who approved it. | QuickTime CreateDate/ModifyDate, Keys CreationDate/CreationTime, UserData OriginalFilePath | `ca09af189662e4cfff1a41da9ddf8aaa51c6fb87a8aeb6297dac57a62d4a7fe7` | Owner, 2026-10-06 |
| `media/photo/jpeg_3x2_2mp.jpg` | Sony `DSC03491.JPG`, 1800x1200 | 3:2 JPEG; taken 2025-12-03 09:15:48.980 +08:00 (filename tests expect `_980`) | Make, Model, Orientation, DateTimeOriginal/CreateDate/ModifyDate, OffsetTime*, SubSecTime* | `2f8a2dfddd6b093a3c93e9cb2ccad08dcb00b7a4bbb7f0bcc328166c21557b5a` | Owner, 2026-10-06 |
