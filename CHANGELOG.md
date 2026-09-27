# Changelog

All notable changes to this project are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
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
  `style: "box"`.
- Depth graph options (Overlay Designer inspector): **Deco stops** (stops and
  ceiling shaded separately, kept after they clear), **Reveal profile over
  time** and a **Stop label** at the cursor. New **Generic → Dive Profile
  Deco** template uses all three.
- Log parsers recompute a deco ceiling for every sample (`Waypoint.ceiling`),
  Garmin FIT included.

### Changed
- The per-user data folder is now `org.christersson.uwmedia` instead of
  `UWMedia` (macOS `~/Library/Application Support/`, Windows `%APPDATA%`,
  Linux `~/.local/share`). An existing `UWMedia` folder is copied over on
  first start and left in place.
- App bundle identifier is now `org.christersson.uwmedia` (was
  `com.mikaelchristersson.uwmedia`).

### Fixed
- UDDF logs flipped the HUD to deco while the log still showed an NDL (the
  parser's own ceiling recompute overrode the file), and Dive Profile Builder
  logs had a 0 m deco stop in the first second of deco.
- Dive Profile Builder NDL was judged at GF low instead of GF high, so it ran
  out far too early (18 m on air at GF 30/70: about 7 min instead of about 40)
  and showed NDL 0 while no deco was needed. Saved logs carry the corrected NDL.

### Changed
- Dive Profile Builder logs: stops are held with the GF interpolated between
  GF low and GF high (as End dive does), and the logged first stop shows whole
  minutes, at least one - no more zero-length deep stops.

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
