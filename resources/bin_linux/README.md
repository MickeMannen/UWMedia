This directory is empty in git on purpose — it's populated right before a
Briefcase build (CI does this automatically; see the "fetch vendored
binaries" step to be added in `.github/workflows/build.yml`).

At build time it should contain, downloaded from the
[`deps-2026.09`](https://github.com/MickeMannen/UWMedia/releases/tag/deps-2026.09)
release and verified against `resources/licenses/BINARY_MANIFEST.json`:

- `ffmpeg`, `ffprobe` — from the `ffmpeg-linux-amd64` / `ffprobe-linux-amd64`
  assets, `chmod +x` after download
- `exiftool`, `lib/` — extracted from the `exiftool-unix-13.59.tar.gz` asset
  (`Image-ExifTool-13.59/exiftool` and `Image-ExifTool-13.59/lib/` as-is,
  `lib/` must stay a direct sibling of the `exiftool` script — the script's
  own `BEGIN` block resolves its module path as `dirname($0)/lib`, not a
  differently-named folder), `chmod +x exiftool`. Needs the OS's system
  Perl at runtime (present by default on virtually every distro).

Not needed for running the app as a plain Python script from source — that
mode resolves ffmpeg/exiftool from PATH / local installs, unchanged.
