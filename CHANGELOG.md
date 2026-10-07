# Changelog

All notable changes to this project are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/).

## [0.7.15] - 2026-10-07

### Fixed
- Color: photos taken in the same second (with no fractions of a second in
  their date) are all saved in a batch; until now they could overwrite each
  other's output, leaving fewer files than photos.
- Windows: a video no longer fails at the end with a division error when its
  processing was measured as taking no time (Windows' coarse clock).

## [0.7.14] - 2026-10-07

### Added
- Log Viewer: "Adjust time…" on the Dive card corrects a Garmin dive whose
  computer clock was wrong: enter the real start time and time zone, and a
  corrected copy of the .fit log is saved (every sample moves; the original
  is kept).

### Fixed
- Windows: videos render on PCs without an NVIDIA graphics card (Intel or AMD
  graphics, virtual machines); the app now falls back to software encoding
  instead of failing every video.
- Color, Overlay Generator, Convertion: a run in which a file failed now ends
  as "Failed" instead of "Finished (exit code 0)".
- Color: when you pick an output file, the result is saved under exactly that
  name; a filename format or the photo's milliseconds no longer change it.
- Color: Sony videos' camera, lens, frame rate and recording date now also
  reach the output's XMP metadata; they were never written.
- Color: "Move original" keeps the original's file name as it was; a photo
  called DSC03491.JPG was moved as DSC03491.jpg.
- Color: Start says "Nothing to run" when Source or Output is empty instead
  of starting a run that fails, and the preview slider is cleared after
  picking a file that can't be read.
- Dive logs: a UDDF log's own CNS% is shown as logged instead of being
  replaced by UWMedia's recalculation; this includes UWMedia's own UDDF files.
- Dive logs: one unreadable number in a UDDF or Subsurface sample (depth,
  NDL, CNS, GF, battery...) no longer stops the whole log from loading.
- Tag Editor: a date with fractions of a second keeps its time zone, and a
  time zone of UTC+00:00 is no longer treated as missing.
- Advanced: tank names from a hand-edited config.yaml with unquoted serials
  can be renamed and removed.
- Linux: overlay text uses the bundled Arial-compatible font when Arial and
  Liberation Sans aren't installed, instead of the wider DejaVu Sans, so
  text fits the templates as on macOS and Windows.
- Windows, Linux: the Log Viewer's event list and the Overlay Designer's
  waypoint data now use a fixed-width font, as on macOS, so columns line up.

### Removed
- CLI: `--render-log` no longer writes a Final Cut Pro `.xml` (FCPXML) next to
  the rendered video; import the video itself.

## [0.7.13] - 2026-10-06

### Changed
- Overlays: text no longer gets a black outline by default, so small text
  stays crisp. It applies to every template and your own pages; turn it back
  on per element with "Black outline" in the Overlay Designer.
- Garmin x50i: the overlay is drawn larger by default, so its numbers and
  labels are no longer tiny and blurry in the video.

## [0.7.12] - 2026-10-05

### Added
- Color: new output filename option "Date + time + overlay"
  (20260905_143000_garmin_mk3i_main), named after the first overlay.

### Fixed
- Color: on a photo that isn't 16:9, the box shown while moving or resizing
  an overlay now lines up with the overlay instead of running off the frame.
- Color, Overlay Generator, Convertion, Color Tuning, Tag Editor and
  Advanced: file and folder dialogs start in your home folder instead of the
  drive root (/ on macOS), and remember the last folder used.

## [0.7.11] - 2026-10-05

### Fixed
- Dive Profile: the Open and Save dive log dialogs start in your home folder
  instead of the drive root (/ on macOS), and remember the last folder used.
- Overlay Designer: file dialogs (skin and background images, preview
  background, dive logs, page export and import) start in your home folder
  instead of the drive root (/ on macOS), and remember the last folder used.

## [0.7.10] - 2026-10-04

### Changed
- Dive Profile: sidemount tanks are set up one row per tank, with a Side
  picker (Left, Right or Stage) in place of the "Sidemount pair" tick box, so
  the second tank can be put on the right side.
- Dive Profile: a sidemount dive needs both a left and a right tank of the
  same gas before it is built or saved; the status line says what is missing.
- Dive Profile: the profile line takes the colour of the sidemount tank in
  use (T1 or T2), so every side switch shows in the graph and its legend.

### Fixed
- Dive Profile, log import: deco is now calculated with the standard Bühlmann
  ZHL-16C tissue table. The previous table was wrong and gave deco stops that
  were too short and NDLs that were too long (18 m on air at GF 70: about
  29 min, not 40). Recomputed TTS and ceilings on imported logs change with it.
- Dive Profile: a deco ascent always ends with at least a 3 m / 3 min stop.
  When a deco gas such as EAN50 cleared the obligation on the way up, the
  plan had no stops left after the gas switch.

## [0.7.9] - 2026-10-03

### Fixed
- Color: in the downloaded macOS app, one failing file no longer stops the
  whole batch with "Failed (exit code 13)"; that file is marked as an error
  and the rest carry on.
- Color: when several files run in parallel, the Current bar and the time
  estimate no longer jump past 100%.
- Color, Overlay Generator, Convertion: progress no longer misses updates
  that arrive split across reads, and a run killed by the system now says
  so instead of showing a bare exit code.

## [0.7.6] - 2026-10-03

### Fixed
- macOS: in the downloaded app, Color, Overlay Generator and Convertion now
  show live progress and status; they stayed at "Starting…" until the run
  ended.

## [0.7.5] - 2026-10-03

### Changed
- Color: videos with HUD overlays render about three times faster, close to
  colour correction alone (a 10 s 4K clip with two overlays: 97 s → 34 s).
- Color: the progress bar now moves during an overlay run: through the
  analysis, the HUD drawing and the encode. The status reads "Processing"
  once files are under way instead of staying at "Starting" until the first
  file finishes.
- Color: overlay videos now get the same colour correction as videos without
  overlays (before, they came out lighter and more washed out), and keep
  10-bit sources at full 10-bit precision. Translucent parts of a HUD, such as
  the dive profile's background, now show the corrected footage behind them.

### Fixed
- Color: 10-bit 4:2:2 H.264 clips (e.g. Sony XAVC) lost some frames when
  hardware acceleration was on (483 of 501 survived on a 10 s clip). They are
  now decoded in software and keep every frame.
- Color: the Current and Overall progress bars are now the same length.

## [0.7.4] - 2026-10-02

### Changed
- Log Viewer: redesigned after DiveSync's log view. Open files or a whole
  folder into one list of dives (Remove / Clear take them off again), and
  the selected dive is shown as a card of fields, a tanks and sensors table,
  a depth profile chart, the data the log carries and its events. Sensor
  serial numbers and GPS positions can be selected and copied (e.g. into
  Advanced → Sensor names). The sample table is still there, folded under
  **Samples**. The dialogs remember the last folder used.

## [0.7.3] - 2026-10-01

### Added
- Dive logs: Shearwater Cloud's own XML and CSV exports and Subsurface's CSV
  dive-profile export can now be read by Color, the Overlay Designer, the
  Overlay Generator, the Log Viewer and the CLI, next to UDDF, FIT and SSRF.
  The Shearwater files carry the computer's logged NDL, TTS, stops, ppO2,
  SAC and gas time remaining.
- Dive Profile Builder: **Open log** imports any log UWMedia reads, not only
  ones the builder saved: UDDF, FIT and SSRF from a dive computer or other
  software, and Shearwater Cloud XML/CSV or Subsurface CSV exports. The plan
  (gases, switches, GF, start pressure, profile) is rebuilt from its samples.

### Changed
- Color, Overlay Designer and CLI: a folder holding the same dive in several
  formats (e.g. its UDDF and Shearwater CSV) uses only the copy with the most
  data instead of whichever file was read last. Two different computers'
  logs of one dive are still both kept.

### Fixed
- A Shearwater Cloud `.xml` export was handed to the Subsurface reader and
  came up as "no dives found".

## [0.7.2] - 2026-09-30

### Added
- Color, Overlay Generator and Convertion show the time spent on a batch
  and, once a few percent are done, an estimate of the time left; the line
  stays after the run ("Finished in 13:41" / "Stopped after 2:10").
  Convertion's progress bar is now a real one (files done plus the encode
  in flight) instead of an indeterminate spinner.
- Depth graph shading is adjustable in the Overlay Designer: **Box** colour
  and **Box opacity** for the graph's background (black at 0.4 until now),
  **Fill** colour and **Fill opacity** for the area under the profile line,
  **Ceiling opacity** and **Stops opacity** for the shaded areas above it
  (element keys `background_color`, `background_opacity`, `fill_color`,
  `fill_opacity`, `ceiling_opacity`, `stops_opacity`, 0-1).
- Overlay Generator **Overlay size**: 1080p (the template's size, as before),
  **4K (2×)** for 4K footage, or **Full frame** 1080p / 4K with the overlay
  placed as in the template so there is nothing to position in the editor
  (CLI `--overlay-size`, `--overlay-full-frame`). Default 4K.
- Overlay Generator progress: one bar for the overlay being rendered (video
  n of N, or the frames of a single render) and one for the whole batch
  (videos × overlays), from the CLI's progress lines.
- Shearwater ascent-rate arrows (Perdix 2 manual p.10/12): the ascent
  chevrons element now takes its shape and colours from the brand's rules -
  six arrows, no divider bar, one per 3 m/min, white / yellow / flashing red
  - and the Perdix 2 main template carries it beside the depth. The Overlay
  Designer's **+ Add → Ascent chevrons** picks the brand's shape, with a
  **Divider bar** switch in the inspector.
- Overlay Designer **Orientation** for text elements and custom labels:
  horizontal, stacked (upright letters one under the other) or turned on
  its side reading up or down (element key `orientation`: `stacked`, `up`,
  `down`).
- Overlay Designer **+ Add** offers **depth_small_decimals** beside **depth**
  and **dive_time_small_seconds** beside **dive_time**: the depth with its
  decimal part, and the dive time with its seconds, in a small top-aligned
  font, as Garmin and Shearwater computers show them (ordinary depth /
  dive_time elements with the *Small suffix* style preset).
- Overlay Generator renders from a log file alone: a **Log directory / Log
  file (render without video)** switch above the **Dive logs** field. With it
  on, that field takes one dive log (e.g. one saved by the Dive Profile
  Builder) and **▶ Start** renders every selected overlay for the whole dive,
  with no video, into the output folder; Source, Output filename and Skip if
  target exists are greyed out as unused. The switch and both paths are
  remembered.
- **Tank setup** choice (no tank, single tank, sidemount, multi-tank, in that
  order) in the Overlay Generator and in Color's Add Overlay picker, instead
  of silently taking the first variant; the Overlay Designer lists variants
  in the same order with the same names.
- Dive Profile Builder **Open log…** reopens a log the builder saved, to edit
  and save it again. Every saved log now embeds the plan itself (UDDF
  `<applicationdata>`, Subsurface `<extradata>`, FIT developer fields) and is
  restored exactly; a log saved by an earlier version is rebuilt from its
  gases, gas switches, GF and samples. Logs from real dive computers or other
  programs are refused - only the builder's own logs open.
- Dive Profile Builder saves as Garmin FIT and Subsurface XML as well as UDDF
  (one **Save log…** button), posing as a chosen dive computer (the Garmin and
  Shearwater models UWMedia has templates for) with a serial number and a set
  start date/time for matching media.
- Dive Profile Builder dive types: open circuit, sidemount (paired left/right
  tanks, switched every N bar) and CCR (diluent loop with low/high setpoints and
  a switch depth, O2 cylinder, open-circuit bailout gases). This replaces the
  per-gas CCR gas type and setpoint.
- Dive Profile Builder chart shades the planned deco stops over the dive (every
  stop, darker for longer ones) in translucent grey - the ceiling itself is no
  longer drawn - and the hover box shows the ceiling at both GF high and GF low.
- Overlay Designer **Select log file** loads a single log file (e.g. one saved
  from the Dive Profile Builder) and previews it right away.
- Garmin x50i template: a green **STOP ↑5m** / amber **DECO ↑depth** box with
  the stop timer replaces the NDL field during a safety or deco stop, as on the
  real computer. The Garmin safety stop follows the Descent manual: after a
  dive deeper than 11 m, a 3:00 timer that starts within 1 m of 5 m, pauses
  more than 3 m above it and resets below 11 m. The box goes back to NDL once
  the timer completes or the deco stops clear - a diver already shallower than
  the start window after a 3 m deco stop gets no frozen stop box - and the
  computer's own safety-stop started/complete alerts override the depth rules.
  New element options: `hide_in_states` (any element) and badge
  `style: "box"`; the box's **Width** / **Height** are edited in the
  Overlay Designer inspector like a tank icon's.
- Template pages with tank variants share one layout: `main/normal.json` holds
  the skin and every element single tank and sidemount have in common, and
  each variant's `normal.json` is now a small overlay (`"base": "../normal.json"`
  plus its own tank block, with optional per-element `overrides` and
  `remove`). The Garmin x50i and Mk3i main pages are converted; moving a
  shared element in the Overlay Designer edits the base, so both variants
  follow, while tank elements and newly added elements stay with the
  variant being edited. Old-style complete variant files still load.
- Shearwater Perdix 3 templates follow the Perdix 3 manual (p.58-60): the
  stop replaces the NDL cell with "SAFETY" in a green box over the time in
  green, "PAUSED" in yellow, "SAFETY / CLEAR" when done, and "DECO" over
  "18m↑ 1min" as in the Tec layout's top row; the Tec page shows the same in
  its DECO column. The baked NDL and "min" labels were lifted out of the Big
  and Standard skins into template elements so they can hide, and the skins'
  screen backgrounds were flattened. New badge keys `<phase>_label` and
  `title_box`.
- The other Shearwater templates follow their own manuals: Petrel 3 gets the
  Perdix 2 treatment (shared base, AI info rows with SAC and the sidemount
  switch box, drawn tank icons, one skin); Teric and Tern show the stop in
  the NDL slot as their manuals draw it (p.25-26 / p.24-25): "SAFETY" with
  the time in green while counting, both yellow when paused, "SAFETY /
  CLEAR" when done, "DECO 15m↑ 2min" in deco, no check mark. A model's
  `badge_states` entry now only lists what differs from the brand's (a key
  set to `null` removes one), and the Shearwater safety-stop countdown
  resets when the dive goes past 11 m again.
- Shearwater Perdix 2 main page follows the manual's AI info row (p.42):
  single tank shows gas, the T1 tank and "GTR T1"; sidemount shows both
  tanks with "GTR 45 / SM / SAC 1.1" between them and a green box on the
  label of the tank to breathe from once the pair differs by more than 21 bar
  (new `sidemount_switch` rule and `tank_switch_highlight` element option).
  SAC and GTR are computed for logs that don't record them (Shearwater
  Cloud UDDF, Subsurface): SAC over the last two minutes normalised to the
  surface, GTR from it with a 50 bar reserve and the ascent at 10 m/min, as
  the manual defines them; SAC reads "wait" for the first two minutes. The
  page's two variants now share one base layout and one skin, whose screen
  background was flattened to plain black.
- Shearwater templates show stops the way the Perdix 2 manual (p.27-28,
  31-33) describes: the **SAFETY STOP** counter appears once the dive passes
  11 m with the planned time (3:00, or 5:00 with Adapt after 30 m or a low
  NDL), counts down under 6 m while within 2.4-8.3 m, pauses in yellow
  outside that band and shows a check mark while counting and when done;
  **DECO STOP** is red with "6m↑ 2min" in white, turning yellow with a
  flashing arrow within 5.1 m of the stop and green with a check mark at
  the stop; after the last stop **CLEAR** counts up from zero; NDL reads
  "0" in red during deco and turns yellow under 5 minutes. New
  `badge_states` keys (`value_color`, per-phase colours, `check_mark`,
  `show_depth`, `inline`, `timer_format`) and `deco_stop` / `deco_clear`
  rules drive it; Shearwater's old `clear` margin rule is gone.
- Garmin Mk3i templates show a safety or deco stop the way the Descent Mk3
  manual (p.10) does: the NDL slot becomes a small **↑ceiling** over the stop
  timer (`2:33`), in white with no STOP/DECO word, and the depth and ceiling
  flash red while the diver is more than 0.6 m above a deco ceiling (new
  `ceiling_broken` rule for Garmin). New badge element options `depth_font:
  "label"` and `timer_format: "m:ss"`; a `badge_states` label of `""` draws
  no title line.
- Depth graph options (Overlay Designer inspector): **Deco stops** (stops and
  ceiling shaded separately, kept after they clear), **Reveal profile over
  time** and a **Stop label** at the cursor. New **Generic → Dive Profile
  Deco** template uses all three.
- Log parsers recompute a deco ceiling for every sample (`Waypoint.ceiling`),
  Garmin FIT included.

### Changed
- Output filename presets: Color offers **Original**, **Original + color**
  (`DSC06641_color`, new - CLI `--filename-format "{filename}_color"`, where
  `{filename}` is the source name), **Date + time** and **Date + time +
  color**; the date-only preset is gone. Overlay Generator's two presets are
  now **Original + overlay** and **Date + time + overlay**. Selections saved
  under the old names still resolve.
- Per-user folders follow the platform conventions (via `platformdirs`):
  configuration (`settings.json`, `config.yaml`, `color.yaml`), data
  (templates, layouts) and cache are separate on Windows
  (`%APPDATA%\Christersson\UWMedia`, `%LOCALAPPDATA%\Christersson\UWMedia`
  and its `Cache`) and Linux (`~/.config/uwmedia`, `~/.local/share/uwmedia`,
  `~/.cache/uwmedia`); macOS keeps `~/Library/Application Support/
  org.christersson.uwmedia` plus `~/Library/Caches/org.christersson.uwmedia`.
  The old single folder is copied over on first start. A run's working
  files (rendered overlays, LUTs) go under the cache folder instead of the
  system temp dir and are cleared after a day.
- The Advanced page's **Custom filename formats** section is hidden (the
  saved patterns are kept but no longer listed on the Color page).
- Overlay Designer left column is shorter so the canvas keeps its height
  on an 800 px window: view mode, Bounds / Grid / Snap and zoom share one
  toolbar row, Telemetry / State / Time share one row, and the optional
  **Background and dive logs** tools moved from a collapsed section under
  the canvas to a popup under the **More** menu. The inspector's fields have
  fixed widths (numbers, names, fonts, colours) so selecting an element no
  longer pushes the right column past the window edge.
- The window opens at 1280×800 instead of 1280×720, giving every page 80 px
  more height (the pages resize with the window as before).
- Garmin Descent X50i templates use a 2× bezel image (946×602 px, the same
  product shot), so 4K renders no longer upscale it; the skin scale and every
  element size were halved/doubled to match, and the overlay renders
  pixel-for-pixel where it did before. Its labels are then 35 % larger and
  its values 20 % larger (the old 8 px labels were unreadable), with the
  unit and NDL labels moved clear of the bigger digits.
- Depth graph **Stop label** shows only the pending stop (`STOP 6m 2:00`);
  the `NDL 12` it used to show out of deco is gone, so the Generic Dive
  Profile Deco overlay no longer prints an NDL beside the cursor.
- Generic **Dive Profile Deco** overlay shows the whole dive - profile, deco
  stops and ceiling - from the first frame and only moves the cursor, like
  the plain Dive Profile; the deco shading now follows the graph's **Reveal
  profile over time** switch instead of always trailing the cursor. (The
  Dive Profile Builder's own chart is unchanged: it grows as waypoints are
  added.)
- Shearwater safety-stop badge: the stop time is centred under "SAFETY STOP"
  (hud_rules.json `value_align: "center"` on the badge state; an element's
  own `value_align` overrides it).
- Dive Profile Builder logs end deco cleanly: once the last stop clears, the
  saved log carries no stop, an unbounded NDL (99+) and a time to surface that
  is the direct ascent (plus the safety stop still to come, unless deco was
  done). UDDF logs now carry TTS per sample (UWMedia's own `<tts>` element)
  and the UDDF/Subsurface parsers prefer a logged TTS over their own
  recompute, run that recompute with the file's own gradient factors, and
  treat "no stop logged" as no stop in a file that logs its stops - so an
  older builder log no longer shows a DECO box and an 8-minute TTS down to
  the surface.
- The per-user data folder is now `org.christersson.uwmedia` instead of
  `UWMedia` (macOS `~/Library/Application Support/`, Windows `%APPDATA%`,
  Linux `~/.local/share`). An existing `UWMedia` folder is copied over on
  first start and left in place.
- App bundle identifier is now `org.christersson.uwmedia` (was
  `com.mikaelchristersson.uwmedia`).
- Dive Profile Builder logs: stops are held with the GF interpolated between
  GF low and GF high (as End dive does), and the logged first stop shows whole
  minutes, at least one - no more zero-length deep stops.

### Fixed
- Windows: starting the app from the Start Menu, Explorer or a shortcut
  no longer leaves a black console window open behind it for the whole
  session; it closes a blink after it appears. Starting from a terminal
  keeps the terminal attached as before.
- Color page: the HUD is no longer colour-corrected along with the footage.
  The lut3d correction ran on the composited frame, so a neutral bezel (the
  Garmin X50i) came out red-tinted; the HUD's pixels are now masked out of
  the correction and keep their own colours.
- Overlay Designer: the right-hand column (elements and inspector) shows a
  permanent scroll bar; it scrolled before, but the bar only appeared while
  scrolling, so nothing said more was below. The inspector is now grouped
  into folding sections and the Elements list folds too, so the settings in
  use fit without scrolling.
- Telemetry-only overlay videos were encoded at VideoToolbox's default
  bitrate: the `-crf 20` they asked for only means something to the software
  encoder. Each encoder now gets its own constant-quality flag (VideoToolbox
  `-q:v 65`, NVENC `-cq 20`, libx265 `-crf 18`).
- Overlay Generator skipped every dive-computer overlay (Garmin, Shearwater):
  the CLI refused their layouts with "unknown fields: state_badge" and the
  generator moved on without a word. The validator now knows the renderer's
  badge, held-NDL and tissue-bar fields, and a run that fails is named in the
  final status.
- UDDF logs flipped the HUD to deco while the log still showed an NDL (the
  parser's own ceiling recompute overrode the file), and Dive Profile Builder
  logs had a 0 m deco stop in the first second of deco.
- Dive Profile Builder NDL was judged at GF low instead of GF high, so it ran
  out far too early (18 m on air at GF 30/70: about 7 min instead of about 40)
  and showed NDL 0 while no deco was needed. Saved logs carry the corrected NDL.

## [0.7.0] - 2026-09-20

The GUI was rebuilt and the overlay system became fully editable. Everything
below is relative to 0.6.1 (releases 0.5.1 - 0.6.1 were not logged here; see
the GitHub tags).

### Added
- **Overlay Designer** (renamed from HUD Designer) is a full template editor again:
  select, drag, nudge (arrow keys), multi-select with marquee, align/distribute,
  copy/paste across pages, undo/redo, per-element names and a designer-only
  visibility toggle, grid overlay with snapping, quick size buttons, z-order
  controls, and a zoomable Design view (skin at native pixels) next to a Frame
  preview (1920x1080 composite). The canvas renders standalone against a
  synthetic dive with a state selector (normal / safety stop / deco / clear);
  loading a video, photo or dive log stays optional.
- Template persistence: built-in templates are read-only in the installed app;
  **Save as…** copies a page into one you own (under the same computer, another
  computer, or a new Custom computer) and **New custom…** starts a page from your
  own background image or a shape. Your templates live under the app data folder
  (`templates/<brand>/<computer>/<page>/normal.json` + `normal.png`), show up in
  every picker marked "· yours", and render through the CLI with `--layout`.
  Running from a source checkout saves straight into the repo instead
  (`UWMEDIA_TEMPLATES_TARGET=user` forces the per-user folder). Pages can be
  exported to / imported from a `.zip`.
- New overlay element types and attributes: horizontal/vertical text alignment,
  font family (bundled DejaVu Sans, Liberation Sans, Roboto, Roboto Mono, DSEG7
  Classic plus the platform Arial) and weight, optional text outline, a small
  top-aligned suffix (Garmin-style seconds and decimals), tank icons with a drawn
  outline or as a Shearwater-style segmented gauge, a tissue-load bar (segments
  or fill style), and an ascent-rate chevron indicator. `rules_profile` lets a
  custom template borrow a brand's colour and warning rules.
- Dive Profile Builder: plan a dive (gases, waypoints, Bühlmann simulation) and
  write it as UDDF, so overlays can be checked without a real log.
- Log Viewer and Tag Editor improvements; Garmin ascent rate is exposed in
  metres per minute and derived from depth for logs that lack it.

### Changed
- The desktop GUI moved from Toga to a Qt Quick (QML) / PySide6 shell; every
  page was redesigned and made to fit a 1280x720 window without scrolling
  (Overlay Generator, Convertion, Color Tuning, Tag Editor layouts tightened).
- Overlays are template-based: brand → dive computer → page (Garmin x50i and
  mk3i, Shearwater Perdix 2 and 3, Petrel, Peregrine, Teric, Tern, plus generic
  pages), with per-frame states (safety stop / deco / clear badges, blinking) and
  per-brand colour rules in `hud_rules.json`. Garmin and Shearwater skins had
  their baked-in dynamic graphics (tank outlines, tissue bar, chevrons) replaced
  by live elements.
- Template skin images are now tracked in git, so a fresh clone renders every
  built-in page.

### Fixed
- Overlay rendering could fall back to a very slow legacy path.
- The app could hang during rendering.
- Template round-trips no longer drop unknown element keys.

### Removed
- Video clipping.

## [0.5.0] - 2026-09-06

- Migrated packaging from PyInstaller to [Briefcase](https://briefcase.readthedocs.io/) - a single app now bundles the GUI and CLI together for macOS, Windows, and Linux.
- Added an MIT `LICENSE` file (previously only referenced from the README).
- Reordered the README's Usage section so the GUI walkthrough (with screenshots) comes before the CLI reference.
- Various GUI layout fixes (Process tab field ordering, window size).

## Earlier versions

Releases prior to 0.5.0 (0.0.1 - 0.4.1) predate this changelog; see the
[GitHub tags](https://github.com/MickeMannen/UWMedia/tags) and commit history
for that history.
