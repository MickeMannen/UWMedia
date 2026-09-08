This directory is empty in git on purpose — it's populated right before a
Briefcase build (CI does this automatically; see the "fetch vendored
binaries" step to be added in `.github/workflows/build.yml`).

At build time it should contain, downloaded from the
[`deps-2026.09`](https://github.com/MickeMannen/UWMedia/releases/tag/deps-2026.09)
release and verified against `resources/licenses/BINARY_MANIFEST.json`:

- `ffmpeg.exe`, `ffprobe.exe` — from the `ffmpeg-windows-amd64.exe` /
  `ffprobe-windows-amd64.exe` assets (already named correctly, no rename
  needed)
- `exiftool(-k).exe`, `exiftool_files/` — extracted from the
  `exiftool-windows-13.59.zip` asset. **Both must ship together** — this
  is not a single self-contained exe; `exiftool_files/` carries ExifTool's
  own bundled private Perl interpreter (`perl.exe`, `perl532.dll`), the
  real `exiftool.pl` script, and `lib/`. No system Perl needed, but the
  folder is required.

Not needed for running the app as a plain Python script from source — that
mode resolves ffmpeg/exiftool from PATH / local installs, unchanged.
