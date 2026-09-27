# How it works

## 3D LUT colour correction

For video colour correction UWMedia turns the profile's parameters from
`color.yaml` into a 3D lookup table (a `.cube` file) and lets FFmpeg apply it
with its `lut3d` filter. That skips decoding every frame into Python and doing
the maths there, which makes it up to about 10× faster.

## Threaded overlay rendering

When telemetry overlays are drawn onto video, three threads run in parallel -
decoding, drawing and encoding - and frames are processed in place in BGR, so
there are no extra colour-space conversions and all CPU cores are kept busy.

With colour correction on, the frames are piped to FFmpeg with an alpha
channel marking every pixel the overlay drew, and the filter graph applies
the LUT to the footage only, merging the overlay's own pixels back on top
(`maskedmerge`). The dive computer's bezel and text are therefore never
colour-corrected.

## Telemetry-only renders

The Overlay Generator's videos (and `--render-log` / `--render-video-log`)
are rendered frame by frame in Python and piped to FFmpeg as HEVC. Frames
are only redrawn when the dive log's sample changes, so a long dive with
one-second samples encodes quickly. Each encoder gets its own
constant-quality setting (`-q:v` for VideoToolbox, `-cq` for NVENC, `-crf`
for libx265) rather than a bitrate. The canvas is the template's own size
in its 1920×1080 design frame, twice that for 4K, or the whole frame with
the overlay placed as the layout anchors it - see **Overlay size** in the
[Overlay Generator](overlay-generator.md).

## Metadata

UWMedia uses **ExifTool** (through PyExifTool) so processed files keep their
metadata. It copies all vendor-specific tags and handles the awkward timezone
offsets in DJI, Sony and GoPro files. Location, timezone and the matching
dive log's date are written into generated overlays as well.

## Matching media to dives

Photos and videos are matched to a dive by the time they were taken. That's why the media's date and
timezone must be right - see [Tag Editor](tag-editor.md).

## Layout validation

Before a batch starts, UWMedia checks the overlay layout against the dive
logs:

- **Fields** - every telemetry field the layout uses (depth, temperature, …)
  exists in the data, or is one the renderer synthesises itself (the stop
  badge, the depth graph, the held NDL, the tissue-load bar).
- **Tank sensors** - warns if the layout expects tank data (e.g. from a Garmin
  transmitter) that isn't in the logs.
- **Files** - the layout JSON is valid and its skin images can be found.

## Dive Profile Builder simulation

The [Dive Profile Builder](dive-profile-builder.md) runs a Bühlmann ZHL-16C
tissue model with gradient factors, second by second, to produce NDL, ceiling,
deco stops, TTS, CNS and tank pressure for a hand-drawn dive. It exists to
produce test data for overlays and **must not be used for dive planning**.
