# Command line (CLI)

Everything the batch pages do can be scripted with `cli_main.py` (or the
`uwmedia` command from the macOS *Terminal* package - see
[Getting started](getting-started.md)).

```bash
python cli_main.py [options] [source] [output]
```

`source` is a file or folder of photos/videos, `output` a file or folder.

## Examples

```bash
# Colour correction with the fast 3D LUT pipeline (default profile)
python cli_main.py ./raw/ ./out/ --color

# ...with a named profile and GPU encoding
python cli_main.py ./raw/ ./out/ --color vivid --hw-accel

# Colour correction plus a burned-in telemetry overlay
python cli_main.py ./raw/ ./out/ --logs ./dive_logs/ --layout skins/perdix.zip --color

# Telemetry-only overlays for every file in a folder, matched to the logs by time
python cli_main.py ./raw/ ./out/ --render-video-log --layout skins/perdix.zip --logs ./dive_logs/

# Telemetry-only video straight from one log (size follows the layout)
python cli_main.py --render-log dive_log.fit --layout perdix_layout.json

# ...only the first 100 samples, for quick tests
python cli_main.py --render-log dive_log.fit 100 --layout perdix_layout.json

# Downscale videos
python cli_main.py ./raw/ ./small/ --convert 1080p 720p

# Fix the timezone metadata only
python cli_main.py ./raw/ --force-media-tz +8 --fix-tz
```

## Processing

| Option | Meaning |
|---|---|
| `--color [PROFILE]` | Apply colour correction. Without a name the `default` profile is used; others are e.g. `vivid`, `subtle` or your own. |
| `--hw-accel` | Use hardware (GPU) encoding. |
| `--convert RES …` | Downscale to one or more of `1080p`, `720p`, `480p`, `360p`. Output is a folder. |
| `--summary` | Detailed summary at the end, with stage timings and FPS. |
| `--debug` | Verbose FFmpeg output and debugging info. |

## Overlays and dive logs

| Option | Meaning |
|---|---|
| `--logs DIR` | Folder with dive logs: `.fit` (Garmin), `.uddf` (Shearwater), `.xml`/`.ssrf` (Subsurface) - Dive Profile Builder logs in any of the three. Avoid duplicate logs of the same dive. |
| `--layout FILE` | JSON layout or ZIP HUD package to overlay. Turns the overlay on. |
| `--overlays-file FILE` | JSON list `[{layout_path, x, y, scale}, …]` of several overlays composited onto one colour-correction run (what the Color page does). Each `layout_path` must be a JSON layout, not a ZIP. |
| `--render-log LOG [N]` | Telemetry-only video from one log (needs `--layout`). Optional `N` renders only the first N samples. An FCPXML `.xml` is written next to the video for direct import into Final Cut Pro. |
| `--render-video-log` | Telemetry-only video/photo on a black background for every file in `source`, matched to the logs by time (needs `--layout` and `--logs`). |
| `--render-log-filename-format T` | Output names for `--render-video-log`. Tokens: `{filename}` (source name), `{hud}` (layout name), `{datetaken:%Y%m%d_%H%M%S}` (date taken). |
| `--export-json DIR` | Parse every log in `DIR` and write it as JSON next to it. |
| `--create-config` | Scan the log folder for Garmin tank sensors and create `config.yaml` (sensor names). |
| `--tz-adjust H` | Shift the log time by H hours (for Shearwater logs). |

## Output files

| Option | Meaning |
|---|---|
| `--filename-format T` | Output name from the date taken, `strftime` codes, e.g. `"%Y%m%d_%H%M%S_Bali"`. |
| `--keep-filename` | Keep the source file's name (extension lower-cased). Can't be combined with `--filename-format`. |
| `--no-overwrite` | Skip files whose output already exists. |
| `--overwrite` | Replace an existing output instead of adding `_1`, `_2` … |
| `--move-original DIR` | Move each source file to `DIR` after it was processed successfully. |

Without `--filename-format` or `--keep-filename`, a batch run (or a run into
another folder) names files by date taken, `%Y%m%d_%H%M%S`; photos get the
milliseconds added (`_123`) so shots from the same second don't clash.

`--no-overwrite`, `--overwrite` and `--move-original` apply when running
`--color` or `--layout`. The source file itself is never overwritten - if the
output would land on it, `_1` is added instead.

## Metadata

| Option | Meaning |
|---|---|
| `--force-media-tz H` | Force the media's timezone offset (hours, e.g. `+8`, `-5.5`). |
| `--fix-tz` | Only update the timezone metadata, then exit (needs `--force-media-tz`). |
| `--modify-quicktime TAG=VALUE …` | Set QuickTime tags by hand, e.g. `'QuickTime:CreateDate=2021:11:12 11:03:02'`. |

The configuration files the CLI reads are described in
[Configuration files](configuration.md).
