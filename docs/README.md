# UWMedia documentation

UWMedia colour-corrects underwater photos and videos and renders dive-computer
telemetry overlays (depth, time, NDL, PO2, tank pressure …) from your dive logs.

## Start here

- [Getting started](getting-started.md) - install, run, where your files live.
- [Typical workflow](getting-started.md#typical-workflow) - from raw footage to a finished video.

## The app, page by page

The desktop app has one page per entry in the sidebar:

| Page | What it's for |
|---|---|
| [Color](color.md) | Batch colour correction, optionally with overlays burned in. |
| [Overlay Generator](overlay-generator.md) | Batch-render telemetry-only overlay videos/photos to sync in your editor. |
| [Convertion](convertion.md) | Re-encode videos to smaller resolutions. |
| [Color Tuning](color-tuning.md) | Tune and save colour-correction profiles on a sample image. |
| [Tag Editor](tag-editor.md) | View and fix date/timezone metadata. |
| [Log Viewer](log-viewer.md) | Browse parsed dive logs dive by dive and sample by sample. |
| [Overlay Designer](overlay-designer.md) | Edit built-in overlay templates or build your own. |
| [Dive Profile Builder](dive-profile-builder.md) | Draw a synthetic OC, sidemount or CCR dive and save it as a UDDF, FIT or Subsurface log - test data for overlays, **not** dive planning. |
| [Advanced](advanced.md) | Folders, external tools, tank sensor names, filename formats, flags. |

## Reference

- [Command line (CLI)](cli.md) - every option of `cli_main.py`.
- [Configuration files](configuration.md) - `color.yaml`, `hud_rules.json`, `config.yaml`, `settings.json`.
- [Building the app](building.md) - packaging with Briefcase.
- [How it works](technical.md) - LUT colour pipeline, threaded rendering, metadata, layout validation.
