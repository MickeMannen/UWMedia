# Overlay Designer

Edit any built-in overlay template or build your own from a background
image.

<p align="center">
  <img src="../media/overlay_designer.png" alt="Overlay Designer page" width="800">
</p>

## Picking a template

Choose **Brand → Computer → Page** (and **Variant** where there is one).

The **Telemetry** source is either **Dummy** - a synthetic dive, the default,
so you need no video or dive log - or **Loaded log**. Optionally:

- **Load video/photo** to design on top of real footage.
- **Select log directory** to drive the overlay from a real log. A log found
  there can be previewed directly, no video needed; **TZ offset** lines the
  log up with the media if their clocks differ.
- **Show raw waypoint data** lists the values of the current sample.

The **Time** slider moves through the dive and **State** forces a state (e.g.
deco, safety stop) so you can check how the overlay looks in it.

## Views

- **Design view** - the template at native pixels, for placing elements.
- **Frame preview** - the full 1920×1080 composite, the way it will be
  rendered. Here you can drag the whole skin into place.

**Zoom**, **Fit** and **100%** control the view; **Grid** with a **Grid size**
and **Snap** (to the grid and to other elements' edges) help alignment.

## Editing elements

- **+ Add** adds a telemetry field, a custom label, the state badge, tank
  icons or the depth graph.
- Click an element on the canvas (or in the **Elements** list) to edit it in
  the inspector: font, size, bold, colour, outline, alignment, anchor, offsets,
  opacity - and element-specific settings such as tank segments, chevron counts
  or the depth graph's marker.
- Drag to move, arrow keys to nudge, **+** / **−** to grow or shrink by 5 %.
- **Align** and **Distribute** line up several selected elements; **Align**
  moves the others onto the last-clicked one.
- Order with bring forward / send backward (Cmd/Ctrl-] / [), duplicate with
  Cmd/Ctrl-D, delete with Delete.
- **Undo** / **Redo** (Cmd/Ctrl-Z, Shift-Cmd/Ctrl-Z).
- Click the skin background to edit its **placement** (anchor, offsets,
  scale); **Replace image…** swaps the background image.

### Depth graph

The depth graph plots the whole dive with a cursor at the current moment. By
default it shades one grey band from the surface to the logged deco stop
depth. In the inspector:

| Option | What it does |
|---|---|
| **Color** / **Ceiling** | Profile line colour; ceiling (or, without *Deco stops*, the stop band) colour. |
| **Deco stops** | Shades the deco stops (a step area from the surface down to each logged stop level, in **Stops** colour) and the deco ceiling (a smooth area, in *Ceiling* colour) separately. Both appear as the dive reaches them and stay after they clear, so the finished graph shows every stop the dive picked up. The ceiling isn't in dive logs - UWMedia recomputes it (Bühlmann, GF high) when it reads the log. |
| **Reveal profile over time** | Draws the depth line only up to the current moment, so the dive draws itself as the video plays. The axes still cover the whole dive. |
| **Stop label** | The current stop next to the cursor, e.g. `STOP 6m 2:00`, or `NDL 12` out of deco, at the given **Size**. |

The **Generic → Dive Profile Deco** template has all three switched on - see
it with a deco log from the [Dive Profile Builder](dive-profile-builder.md).

## Saving

- Built-in templates are read-only in the installed app. **Save as…** copies
  the page into one you own - under the same computer (so it keeps that
  computer's colour and warning rules from `hud_rules.json`), another computer,
  or a new *Custom* computer.
- **Save** stores changes to a template you own; **Revert** goes back to the
  last saved version. Switching template with unsaved changes asks first.
- **New custom…** starts an empty page from your own background image (a
  dive-computer screenshot, a HUD graphic, a transparent PNG) or a plain
  rounded shape.
- **Export page as zip…** / **Import page from zip…** share a page with
  someone else.

Your templates are stored in the app's data folder:
`templates/<brand>/<computer>/<page>/normal.json` + `normal.png` (the folder
can be changed under [Advanced](advanced.md)). They appear in the
[Overlay Generator](overlay-generator.md) and in Color's *Add Overlay* picker
straight away, marked "· yours", and the CLI renders them with
`--layout <that folder>/normal.json`.

When running from a source checkout, saves go into the repo's
`overlays/templates/` (that's how the built-in templates are made); set
`UWMEDIA_TEMPLATES_TARGET=user` to use the per-user folder instead.

Please share if you make a fancy overlay!
