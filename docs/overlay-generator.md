# Overlay Generator

Batch-renders **telemetry-only** overlays - black background, sized to the
template, to 4K, or as a full frame (see **Overlay size**) - for every video
and photo in a folder. Each file is matched to its dive by time, and the
overlay has the same start time and duration as the footage, ready to sync
in your video editor.

<p align="center">
  <img src="../media/overlay_batch.png" alt="Overlay Generator page" width="800">
</p>

## Using it

1. Pick the **Source** folder (your videos/photos), the **Output** folder and
   the **Dive logs** folder. The switch above **Dive logs** stays on **Log
   directory** for this; **Log file** is for a dive with no video (see
   below).
2. **Select overlay** - choose **HUD brand → Dive computer → Page** and press
   **+ Add**. Add as many overlays as you want; each one is rendered for every
   file. To use a template JSON from anywhere on disk, pick **Custom…** as the
   brand and enter its **Custom path**.
   Templates you made in the [Overlay Designer](overlay-designer.md) are
   listed as "· yours".
3. **Output filename** - **Original + overlay** (`GX010042_garmin_mk3i_main`)
   or **Date + time + overlay** (`20251101_121212_garmin_mk3i_main`).
4. **Overlay size** - how big the overlay video is. **1080p** is the
   template's size in a 1920×1080 frame; **4K (2×)** twice that, so it sits
   1:1 on 4K footage (text and graphs are rendered at that size, not
   upscaled); **Full frame** renders the whole 1920×1080 or 3840×2160 frame
   with the overlay where the template places it, so it drops onto the
   footage with nothing to position - key out the black in your editor.
5. **Skip if target exists** skips files already rendered, so an interrupted
   batch can be resumed.
6. **Hardware acceleration** uses the GPU encoder where available.
7. Press **▶ Start** (**■ Abort** stops it).

Only one batch job (Color, Overlay Generator or Convertion) can run at a time.

**Progress** shows two bars while a batch runs: the overlay being rendered
(which video of how many, or the frames of a single render) and the whole
batch - every video times every overlay. Overlays are rendered one after the
other; the videos of one overlay in parallel, so the first bar advances as
videos finish. If an overlay's run fails (for example the CLI refusing a
layout), the final status names it and the reason instead of moving on
silently. Under the bars, the time spent so far and, once a few percent of
the whole batch are done, an estimate of the time left.

## Tank setup

A page that comes in tank variants (no tank, single tank, sidemount,
multi-tank) has a **Tank setup** choice under the page. It is a choice, not
read from the logs: pick the one that matches the dive you're rendering
before pressing **+ Add**. The overlay's name in the list ends with the
variant. Color's *Add Overlay* picker has the same choice.

## Rendering from a log file only

For a dive with no video, for example one saved by the
[Dive Profile Builder](dive-profile-builder.md), flip the switch above
**Dive logs** to **Log file (render without video)**, pick the log in that
same field and press **▶ Start**. Every selected overlay is rendered for
the whole dive, start to end at 30 frames per second, into the output
folder as `<log name>_<overlay>.mp4` (an existing file is never
overwritten; a numbered copy is written instead). **Source**, **Output
filename** and **Skip if target exists** are greyed out because this mode
does not use them; **Overlay size** applies as usual. The switch and both
paths are remembered, so flipping back to **Log directory** brings back the
folder you had there.

## Tips

- Overlays are matched by the media's date taken, so it has to be right -
  including the timezone. Fix it in the [Tag Editor](tag-editor.md) first if
  the camera clock was off.
- No real dive with the situation you want to show (deco, gas switches…)?
  Make one in the [Dive Profile Builder](dive-profile-builder.md).
- CLI equivalent: `--render-video-log` (whole folder) or `--render-log`
  (one log, no media) - see [CLI](cli.md).
