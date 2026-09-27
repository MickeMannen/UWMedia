# Advanced

App-wide settings. Everything here is saved in `settings.json` (or
`config.yaml` for sensor names) in the app's data folder - see
[Configuration files](configuration.md).

## Flags

- **Debug output** - verbose FFmpeg output and extra logging, for
  troubleshooting (same as the CLI's `--debug`).
- **Show summary** - a detailed summary at the end of a batch, with stage
  timings and FPS (same as `--summary`).

## Locations

Where your own files are kept. **Change…** picks another folder, **Reset**
goes back to the default in the app's data folder.

- **Layouts folder** - custom HUD layouts.
- **Templates folder** - your overlay templates from the
  [Overlay Designer](overlay-designer.md).
- **Color profiles folder** - where your `color.yaml` from
  [Color Tuning](color-tuning.md) is saved.

## Sensor names

Garmin tank transmitters are identified by serial number. Map each serial to
a friendly name (e.g. "Left", "Right", "Stage") so overlays and the
[Log Viewer](log-viewer.md) show the name.

- **Edit Tank Sensor Names…** opens the list.
- **Scan Logs Folder…** finds every serial in a folder of logs.
- **Add serial manually** adds one by hand.

The mapping is stored in `config.yaml` (shown under *Config file*). The CLI's
`--create-config` builds the same file from a log folder.

## External tools

Paths to **ffmpeg** and **exiftool**. Leave them empty to use the ones found
on your `PATH` or in the usual install locations.

## About

The **About** page shows the version, license, links (GitHub, YouTube), the
third-party tools UWMedia uses and **Check for updates**.
