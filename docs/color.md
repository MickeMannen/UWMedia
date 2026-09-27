# Color

Batch colour correction for a file or a whole folder of photos and videos,
with optional telemetry overlays burned in.

<p align="center">
  <img src="../media/main.png" alt="Color page" width="800">
</p>

## Using it

1. **Source & output** - pick the source (a file or a folder) and the output
   folder. Point **Dive logs** at the folder with your logs if you want
   overlays.
2. **Color correction** - tick *Apply color correction* and pick a profile
   (`default`, `vivid`, `subtle`, or one you made in
   [Color Tuning](color-tuning.md)).
3. **Overlays** (optional) - **+ Add Overlay…** picks a template (brand →
   dive computer → page). Drag the overlay into place on the **Live preview**.
   You can add several; **Remove Selected** takes one off again. Each file is
   matched to its dive by the time it was taken.
4. **Output filename** - **Original** keeps the name (only the extension is
   made lower-case, e.g. `DSC06641.JPG` → `DSC06641.jpg`), **Original +
   color** adds `_color` to it (`DSC06641_color.jpg`), or name files by the
   date + time taken (`20260905_143000`) or date + time + `_color`.
5. **Hardware acceleration** uses the GPU encoder where available.
6. Press **▶ Start** (it becomes **■ Abort** while running). Progress is
   shown for the current file and overall, with the time spent and, once a
   few percent are done, an estimate of the time left. The line stays after
   the run ("Finished in 13:41").

Only one batch job (Color, Overlay Generator or Convertion) can run at a time.

## Good to know

- Video colour correction runs as a 3D LUT inside FFmpeg, which is much
  faster than processing frame by frame - see [How it works](technical.md).
- The original camera metadata (QuickTime, DJI, Sony …) is copied to the
  output, and the date taken is kept.
- Overlays are drawn at the footage's own resolution and are left out of the
  colour correction: the correction is applied to the video underneath, so a
  dive computer's bezel and text keep the colours you see in the
  [Overlay Designer](overlay-designer.md) instead of picking up the underwater
  red boost.
- If you'd rather keep overlays as a separate layer in your editor, use the
  [Overlay Generator](overlay-generator.md) instead of burning them in here.
- CLI equivalent: `python cli_main.py SRC OUT --color [profile] [--logs DIR --layout …]`
  - see [CLI](cli.md).
