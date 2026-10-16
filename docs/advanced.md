# Advanced

App-wide settings. Everything here is saved in `settings.json` (or
`config.yaml` for sensor names) in the app's configuration folder - see
[Configuration files](configuration.md).

## Flags

- **Debug output** - verbose FFmpeg output and extra logging, for
  troubleshooting (same as the CLI's `--debug`).
- **Show summary** - a detailed summary at the end of a batch, with stage
  timings and FPS (same as `--summary`).

## Units

**Metric** (m, bar, °C - the default) or **Imperial** (ft, psi, °F). The
choice applies at once to the whole app: overlays and the Overlay
Designer's preview, the [Log Viewer](log-viewer.md)'s numbers, headers and
chart, and the [Dive Profile Builder](dive-profile-builder.md)'s inputs and
tables. Logs and saved dives stay in metres, bar and Celsius; only what is
shown converts. Overlays round the way the computer does - a Shearwater
shows whole feet, the Teric one decimal, stops at 10 / 20 ft and the safety
stop at 15 ft, pressures in whole psi - and a template may pin its own
system with a top-level `"units"` key. The CLI's `--units` overrides the
setting for one run.

## Locations

Where your own files are kept. **Change…** picks another folder, **Reset**
goes back to the default (the app's data folder for layouts and templates,
its configuration folder for colour profiles - see
[Getting started](getting-started.md#where-your-files-live)).

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
