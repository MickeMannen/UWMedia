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

Everything you create or change - your own overlay templates, colour
profiles, settings and remembered form values - is kept in a per-user data
folder, so it survives reinstalls and updates:

| OS | Folder |
|---|---|
| macOS | `~/Library/Application Support/org.christersson.uwmedia/` |
| Windows | `%APPDATA%\org.christersson.uwmedia\` |
| Linux | `$XDG_DATA_HOME/org.christersson.uwmedia/` (usually `~/.local/share/org.christersson.uwmedia/`) |

Earlier versions used a folder named `UWMedia` in the same place; its
contents are copied to the new folder the first time a newer version starts
(the old folder is left as it was).

Bundled templates and profiles are never overwritten. The template and
colour-profile folders can be moved on the [Advanced](advanced.md) page. See
[Configuration files](configuration.md) for what's in each file.

## Typical workflow

This is how the author uses UWMedia with Final Cut Pro:

1. **Colour correction** - run the [Color](color.md) page (or `--color`) on
   all videos and photos from the dive.
2. **Telemetry overlays** - for the corrected videos, render matching overlay
   videos with the [Overlay Generator](overlay-generator.md), often several
   different overlays per video.
3. **Import** - import videos and overlays into one folder in the editor.
   (Overlays rendered straight from a log with the CLI's `--render-log` also
   get an FCPXML `.xml` for direct import into Final Cut Pro.)
4. **Sync** - create a synchronized clip for each video and pick the overlay
   you want for that clip.
5. **Edit** as normal. Keeping the overlay as a separate layer makes things
   like stabilisation easy, since only the footage moves.

Overlays are matched to dives by time, so the media's date and timezone have
to be right - the [Tag Editor](tag-editor.md) fixes them if the camera clock
was off.
