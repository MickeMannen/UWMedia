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
4. **Output filename** - keep the original name (only the extension is made
   lower-case, e.g. `DSC06641.JPG` → `DSC06641.jpg`), or name files by the date
   taken (`20260905`), date + time (`20260905_143000`) or date + time + `_color`.
   Your own patterns saved on the [Advanced](advanced.md#custom-filename-formats)
   page are listed after these, e.g. `%Y%m%d_Bali → 20260905_Bali`.
5. **Hardware acceleration** uses the GPU encoder where available.
6. Press **▶ Start** (it becomes **■ Abort** while running). Progress is
   shown for the current file and overall.

Only one batch job (Color, Overlay Generator or Convertion) can run at a time.

## Good to know

- Video colour correction runs as a 3D LUT inside FFmpeg, which is much
  faster than processing frame by frame - see [How it works](technical.md).
- The original camera metadata (QuickTime, DJI, Sony …) is copied to the
  output, and the date taken is kept.
- If you'd rather keep overlays as a separate layer in your editor, use the
  [Overlay Generator](overlay-generator.md) instead of burning them in here.
- CLI equivalent: `python cli_main.py SRC OUT --color [profile] [--logs DIR --layout …]`
  - see [CLI](cli.md).
