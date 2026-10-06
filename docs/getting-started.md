# Getting started

## Install

### Packaged app

Download an installer from the [Releases](https://github.com/MickeMannen/UWMedia/releases)
page (Windows / macOS / Linux). Releases are created and attached by hand, not
on every push - on macOS, check that a download is described as
signed/notarized before assuming it opens without a Gatekeeper warning.

On macOS there are two downloads:

- **`UWMedia-*.dmg`** - the plain GUI app; drag it to `/Applications`.
  Recommended for most users.
- **`UWMedia-Terminal-*.pkg`** - the same GUI plus a scriptable `uwmedia`
  terminal command; installs to `/Library` instead of `/Applications`. Use
  this if you want to run batch processing from the command line.

Windows and Linux ship a single CLI + GUI build.

### From source

Requirements:

1. **Python 3.10+**
2. **FFmpeg** in your `PATH`
3. **ExifTool** in your `PATH`

(If FFmpeg or ExifTool live elsewhere, point to them on the
[Advanced](advanced.md) page.)

```bash
git clone https://github.com/MickeMannen/UWMedia.git
cd UWMedia
pip install -r requirements.txt
```

## Run

```bash
python -m uwmedia      # desktop app, from source
briefcase dev          # desktop app, via Briefcase
python cli_main.py …   # command line - see cli.md
```

## Where your files live

Everything you create or change is kept in per-user folders, so it survives
reinstalls and updates. The app never writes into its install location.

| OS | Configuration | Data | Cache |
|---|---|---|---|
| macOS | `~/Library/Application Support/org.christersson.uwmedia/` | same folder | `~/Library/Caches/org.christersson.uwmedia/` |
| Windows | `%APPDATA%\Christersson\UWMedia\` | `%LOCALAPPDATA%\Christersson\UWMedia\` | `%LOCALAPPDATA%\Christersson\UWMedia\Cache\` |
| Linux | `$XDG_CONFIG_HOME/uwmedia/` (default `~/.config/uwmedia/`) | `$XDG_DATA_HOME/uwmedia/` (default `~/.local/share/uwmedia/`) | `$XDG_CACHE_HOME/uwmedia/` (default `~/.cache/uwmedia/`) |

What lives where:

- **Configuration** - `settings.json` (settings and remembered form values),
  `config.yaml` (sensor names) and `color.yaml` (your colour profiles). The
  colour-profile folder can be moved on the [Advanced](advanced.md) page.
- **Data** - `templates/` (your overlay templates) and `layouts/` (custom HUD
  layouts). Both folders can be moved on the Advanced page.
- **Cache** - `tmp/uwmedia_*` working folders of a run (rendered overlays,
  LUT files, the overlay list handed to the CLI, template imports). Folders
  older than a day are removed when the app or CLI starts.

Earlier versions kept everything in one folder. The first time a newer
version starts, its contents are copied into the folders above (never moved,
so the old folder is left as it was):

| OS | Old single folder |
|---|---|
| macOS | `~/Library/Application Support/UWMedia/` (the current folder already has the new name, so nothing moves) |
| Windows | `%APPDATA%\org.christersson.uwmedia\`, then `%APPDATA%\UWMedia\` |
| Linux | `~/.local/share/org.christersson.uwmedia/`, then `~/.local/share/UWMedia/` |

On Windows and Linux the three configuration files go to the configuration
folder and everything else to the data folder.

The environment variables `UWMEDIA_CONFIG_DIR`, `UWMEDIA_DATA_DIR` and
`UWMEDIA_CACHE_DIR` override the folders above, for a portable install or
to keep a test run away from your real settings.

Bundled templates and profiles are never overwritten. See
[Configuration files](configuration.md) for what's in each file.

## Typical workflow

This is how the author uses UWMedia with Final Cut Pro:

1. **Colour correction** - run the [Color](color.md) page (or `--color`) on
   all videos and photos from the dive.
2. **Telemetry overlays** - for the corrected videos, render matching overlay
   videos with the [Overlay Generator](overlay-generator.md), often several
   different overlays per video.
3. **Import** - import videos and overlays into one folder in the editor.
4. **Sync** - create a synchronized clip for each video and pick the overlay
   you want for that clip.
5. **Edit** as normal. Keeping the overlay as a separate layer makes things
   like stabilisation easy, since only the footage moves.

Overlays are matched to dives by time, so the media's date and timezone have
to be right - the [Tag Editor](tag-editor.md) fixes them if the camera clock
was off.
