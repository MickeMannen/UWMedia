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

## Custom filename formats

Save your own output-filename patterns, built from the file's date taken with
`strftime` codes (`%Y` year, `%m` month, `%d` day, `%H` hour, `%M` minute,
`%S` second), e.g. `%Y%m%d_%H%M%S_Bali` → `20260905_143000_Bali`.

- Saved patterns are listed with an example name and can be removed again.
- They appear straight away in the [Color](color.md) page's **Output
  filename** list, after the built-in choices.
- A pattern must contain at least one date code (otherwise every file would
  get the same name) and no `/` or `\`.

The same patterns work with the CLI's `--filename-format`.

## About

The **About** page shows the version, license, links (GitHub, YouTube), the
third-party tools UWMedia uses and **Check for updates**.
