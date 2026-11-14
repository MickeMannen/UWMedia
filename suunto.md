  # Suunto: EON Core, EON Steel Black and Nautic overlays, Suunto log import

Status: **draft 2** (2026-11-14). A plan only; no code has changed. Sources are
the three manuals and four product photos in `test_data/dive_computers/suunto/`,
the structure of Suunto's log formats (facts only: element names, units,
time base), and sample Suunto app exports. Draft 2 adds the cleaned device
images (§ 1.0) and more JSON details (§ 2.1, § 5). Items marked "to verify" have
not been checked against a real file.

## 0. Summary

- Three new template computers: **Suunto EON Core**, **Suunto EON Steel Black**
  (one family, same firmware look, different screen) and **Suunto Nautic**
  (a different, newer look).
- Three new log readers, in this order of value:
  1. **Suunto app JSON** (`.json`): the only export the Nautic has, and the
     current one for the EON Core and EON Steel Black. Carries NDL, TTS,
     ceiling, tank pressure and events.
  2. **SML** (`.sml`, Suunto DM5 export): older EON logs only. DM5 was
     discontinued in January 2020 and the Nautic never had it.
  3. **Suunto DM4 / DM5 XML** (`.xml`, `<Dive xmlns=".../Suunto.Diving.Dal">`):
     same era as SML.
- The Suunto app also writes a **FIT** file next to each JSON export. It is
  sparse (no tank pressure, NDL, ceiling or gas switches) but holds the mixes
  and gradient factors the Nautic's JSON lacks. This picks up the existing
  roadmap item "Suunto FIT logs" (§ 3.3).
- New rendering pieces the Suunto screens need: an **arc gauge** element (the
  EON NDL / ascent-time / tank / stop arc), a **segmented vertical bar** (the
  ascent-rate bar on the left and the EON's NDL / tank scale on the right),
  and a **filled pill** around the stop timer (Nautic). The arc is the same
  element the roadmap already wants for freediving and the Mk3i arcs.

## 1. What the manuals say

Manuals on hand (add them to the table in `hud_rules_sources.md`):

| Model | File | Revision | Pages |
|---|---|---|---|
| Suunto EON Core | `Suunto_EONCore_UserGuide_EN.pdf` | User Guide 4.0, 2024-12-19 | 66 |
| Suunto EON Steel Black | `Suunto_EONSteelBlack_UserGuide_EN.pdf` | User Guide 3.0, 2023-03-02 | 69 |
| Suunto Nautic | `Suunto_Nautic_UserGuide_EN.pdf` | 2025-12-01 | 67 |

Printed page numbers equal PDF page numbers in all three. The manuals'
screen images are small (EON Core about 110x85 px, EON Steel Black about
208x158 px), so they fix the layout and colours but not exact positions.
Real device photos or screenshots are needed for the geometry, as they were
for the X50i (§ 6).

### 1.0 Device images (skins)

Product photos from Suunto (front view, 2026-11-14), cleaned the way
`garmin_x50i/garmin_x50i base.png` was: cropped to the housing (strap
removed), transparent background, display blanked to black, the printed
SUUNTO logo and the buttons kept. The originals stay beside them.

| Clean image | Size | Display area (x0, y0, x1, y1) | From | Shows (before cleaning) |
|---|---|---|---|---|
| `eon_steel_black_clean.png` | 1724 x 995 | 310, 190, 1131, 806 | `SS050558000-Suunto_EON_Steel_Black_Front_View-…jpg` | Classic, CCR: depth / dive time, deepstop / asc. time, CC / SP 1.3, orange deco bar |
| `eon_steel_clean.png` (silver) | 427 x 240 | 70, 42, 289, 201 | `SS050558000-Suunto_EON_Steel_Front_View-…jpeg` | Classic, CCR: stop / no deco, diluent Air / SP 1.3, cyan tank bar 0-250 |
| `eon_core_clean.png` | 384 x 221 | 68, 42, 285, 193 | `suunto eon core.jpeg` | Graphical: no deco / stop / depth on top, tank arc 0-250 centre, Nx 32, dive time |
| `nautic_clean.png` | 918 x 526 | 75, 60, 785, 462 (rounded, r 28) | `suunto_nautic-…-1200x1200.webp` | Surface screen: MAX DEPTH, ACTIVE GAS, LAST DIVE, NO DECO >99' with green bar, TANK PRESSURE with the blue / yellow / red gauge, SURFACE TIME, status strip |

- The display areas are measured in the cleaned image's pixels: where a
  template's elements go.
- Only the Steel Black photo is large enough to measure a layout from. The
  EON Steel and Core photos are small JPEGs, usable as skins at small sizes.
- **The un-cleaned photos are the best layout references on hand**, better
  than the manual figures: positions, font and colours of the Classic CCR,
  Graphical tank and Nautic surface screens. They are marketing renders, not
  in-water screens: the "assumed" notes in each manifest say so.
- The silver EON Steel is the same computer as the Steel Black in another
  housing: a second skin for the `eon_steel_black` pages (§ 3.7), not a
  computer of its own.

### 1.1 EON Core and EON Steel Black

The two share the firmware look. Differences that matter here: screen size
(the Steel Black's is larger; aspect ratio and resolution to verify, both
look 4:3 landscape), and the Core manual is newer (Bühlmann 16 GF described
in more detail, p.17-18).

- **Modes:** Air/Nitrox, Trimix, CCR (fixed-setpoint backup: low 0.4-0.9,
  high 1.0-1.5, auto switch at 4.5 m / 21 m) and Gauge. No freedive. Up to
  10 custom modes, each with up to 4 views (set in the Suunto app).
- **Display styles:** Classic, Prominent and Graphical; each has the views
  No deco, Compass, Tank pressure and Timer.
  - **Classic** (Steel Black default; Steel p.31, p.54): a 3 x 2 grid with thin
    dividers. Depth (white, smaller decimal) | dive time (green, `24′`);
    stop / deepstop / ceiling depth | `no deco` NDL (green), which becomes
    `asc. time` (orange) in deco; row 3 depends on the mode: max | avg,
    gas | tank, `Tx 18|45` | tank, `CC` | `SP 1.3`. The bottom-right
    field is the **switch window**: tank, gas time, timer, avg / max,
    consumption, CNS / OTU, pO2. A segmented bar on the right edge: NDL 0-100
    green, orange in deco, tank 0-250 bar cyan (from the figures; the text
    does not describe it).
  - **Prominent** (EON Core default; Core p.11, p.30-31): depth large and
    dive time green on the left, temperature bottom-left, a large **arc**
    on the right with a label and value inside (`no deco 75′` green,
    `asc. time` orange, `stop 2′50` yellow / red, `tank, bar 125`
    blue), switch window bottom-right, a top strip with battery hours and
    the stop / status text (`3.0 SAFETY STOP`, `17.7 CEILING` red,
    `DECO` orange top-right).
  - **Graphical** (Core p.52, Steel p.11, p.54): a large central semicircle
    arc (NDL 0-100, or tank 0-250 cyan), small fields around it.
  - **Everywhere:** battery icon + remaining dive hours top-left, the clock
    under it (Steel), vertical **ascent-rate bar** on the left edge,
    temperature bottom-left, view dots bottom-centre, small grey lowercase
    labels with units (`depth, m`, `tank, bar`), minutes with a prime (`49′`),
    stop counters `2′20` with smaller seconds.
- **Deco** (Core p.25-28, Steel p.25-28, p.41-43): NDL `>99′` above 99;
  ascent time 0-999. Ceiling arrows: white ▼▲ inside the window (ceiling to
  ceiling + 3 m), yellow ▼ and yellow value in the 0.6 m safe margin above
  it, red ▼ + red value + alarm beyond that. After 3 minutes above the
  ceiling, Fused RGBM 2 shows **Locked**; Bühlmann 16 GF shows a red
  vertical **CEILING BROKEN** bar instead. Continuous or Stepped (3 m)
  profile; last stop 3 or 6 m.
- **Safety stop:** 3 / 4 / 5 min, counted between 2.4 and 6 m; yellow when
  voluntary, red when mandatory (after an ascent-rate violation).
  **Deepstop** on dives deeper than 20 m at half the max depth, ±1.5 m window,
  same arrow logic (always on with helium).
- **Notices** (Core p.13-14, Steel p.13-15): a rounded, yellow-bordered dark
  pop-up over the middle-right (`pO₂ high`, `Tank pressure`, `Change gas`,
  `Setpoint switched 1.3`, `Bookmark saved: 1`); after it is acknowledged the
  value stays in the switch window. Alarms are red, warnings red or yellow,
  notifications yellow.
- **Ascent bar:** 2 m/min per step; green below 8, yellow 8-10, red above 10.
- **Tank POD:** the active gas's pressure only; blue, yellow below the user
  alarm, red below 50 bar. Gas time `n/a` without a POD, `--` with no
  signal, 0 and red below 35 bar.
- **Algorithms:** Suunto Fused RGBM 2 (default; personal setting -2 to +2) or
  Bühlmann 16 GF (ZHL-16C, default GF 30/70).
- **Logs:** a fixed 10 s sample rate; bookmarks, bearing locks and timer start
  / stop are logged.

### 1.2 Nautic

- **Screen:** a wide rounded rectangle (about 1.9:1, landscape) AMOLED, black
  background, thin dark-grey dividers. Not round. No Nautic S in the manual.
- **Modes:** Single gas and Multigas (up to 5 gases, Trimix). No gauge mode
  ("Algorithm off" = bottom timer, p.46), no CCR, no freedive menu entry. Max
  60 m.
- **Main screen** (p.22, 23, 33, 47, 51, 52): depth top-left (smaller decimal
  and `m`); dive time `24'05` under it; the deco cell beside it (cyan
  `NO DECO` over `>99'`, or the variant `NDL >99'` green over `TTS 00'`
  orange); a thin vertical bar right of the deco value (green, orange in
  deco; probably tissue loading, unexplained); the stop row bottom-left
  (`3.0m SAFETY STOP`, `6m 4'` `STOP`, `CEILING`) with the timer in a
  filled amber pill; the ascent-rate bar in a centre column; the **switch
  window** on the right (cyan uppercase label over a white value, "Double" =
  two fields or "Large" = one); a status strip bottom-right (POD icon,
  temperature, battery %).
- **Switch-window fields** (p.24-27): max depth, clock, avg depth, ascent
  speed, tank pressure (single with a vertical gauge bar, or sidemount with
  two horizontal bars 1 / 2), gas consumption, gas time, TTS, ceiling,
  ppO2 + MOD, GF `40/85`, GF99 / Surf GF, Δ+5 / @5, active gas, OTU + CNS;
  Large only: tissues bar graph, compass, stopwatch.
- **Deco:** an orange `DECO` badge replaces `NO DECO` and the value becomes
  TTS. Yellow ▲▼ arrows beside the depth in the stop window; yellow ▼ inside
  the 0.6 m margin above the ceiling, red ▼ and a red stop row beyond it; after
  3 min a red, hatched **ALGORITHM DEVIATION!** panel in the switch window.
  `STOP DONE` in a cyan bar when the safety stop ends.
- **Alarms** (p.36-39): red mandatory, yellow caution, cyan notify. User alarms
  fill the field (depth yellow, tank / dive time cyan, NDL yellow). Sidemount
  switch: a cyan `SIDEMOUNT 20bar` panel. Gas switch: the whole switch window
  cyan, `SWITCH GAS / NX99`.
- **Ascent bar** (p.23): 2 m/min per step; grey below 2, green 4-8, yellow
  above 8, red at 10, a red box with white chevrons above 10 for 5 s.
- **Algorithm:** Bühlmann 16 GF only, presets Low 45/95, Medium 40/85
  (default), High 35/75 or custom. No RGBM.
- **Logs:** 10 s scuba samples; synced to the Suunto app only.

## 2. Suunto log formats

### 2.1 Suunto app JSON (`.json`)

How to get it: Suunto app → a dive → export (on Android since about app
6.0.2, mid-2025; the iOS menu is to verify). The app writes a FIT file with
the same name next to it.

- Root `{"DeviceLog": {"Header", "Device", "Samples": [...], "Windows": [...]}}`.
  Only `Header.ActivityType == 51` (scuba) is a dive; the app exports every
  sport.
- Header: `DateTime` ISO 8601 with offset (the only Suunto format with a time
  zone); `Device.Name` (internal names: the Nautic is `"Vaasa"`, the Ocean
  `"Porvoo"`, an EON gives `"EON Core"`); `Duration` s; `Depth.Max/Avg` m;
  `Temperature.Max/Min` in **Kelvin, swapped** (Min is the warmer; seen on
  every Ocean file, to verify on EON and Nautic; the samples give the same
  figures anyway).
- `Header.Diving` (EON): `Algorithm`, `Conservatism`, `DiveMode`,
  `SurfacePressure` (Pa), `Gases[]` (`Oxygen` / `Helium` fractions, `TankSize`
  m³, `StartPressure` / `EndPressure` Pa, `TransmitterID`), start / end
  CNS / OTU. EON gas numbers are 1-based array positions, Nautic ones 0-based
  in an explicit `GasNumber`. **The Nautic's block has no algorithm or GF**;
  a sidemount Nautic log has no `Diving` block at all.
- Samples: sparse records, each with `TimeISO8601`; `Depth` m,
  `Temperature` K, `NoDecTime` s (6000 = the 100-minute cap), `TimeToSurface`
  s, `Ceiling` m (0 outside deco), `GasTime` s, `Cylinders[]{GasNumber,
  Pressure, Pressure2}` Pa (`Pressure2` = a second transmitter on the same
  gas, i.e. sidemount), `Ventilation` m³/s (× 60000 = L/min), Nautic
  `RtGradientFactors{gf99, gfSurface}`, `DiveRoute`, `DiveRouteOrigin` (GPS).
  Duplicate timestamps within a second happen; keep the first.
- Dive start: the first `State` event `"Dive Active"` (EON) or
  `DiveEvents.DiveStatus: true` (Nautic).
- Events: EON `Events[]` of `{Notify|Warning|Alarm|State: {Type, Active}}`
  and `GasSwitch{GasNumber}`; Nautic one `DiveEvents` object per sample.
  Types include Safety Stop, Safety Stop Ahead, Mandatory Safety Stop, Deco,
  Ceiling Broken, Deep Stop, Ascent Speed, PO2 High, CNS80%, Tank Pressure,
  Air Time, Bookmark, SetPoint.
- Missing: **no deco stop time** (only ceiling + TTS), heading not seen in the
  public samples (to verify with a compass dive), the gas mix is sometimes
  absent (always on the Ocean).

Further facts seen in D5 (2021 and 2025 firmware) and Ocean exports, not
EON or Nautic ones, so likely, not confirmed, for our three:

- Absent markers, not readings: `NoDecTime` -1 (0 is a reading: deco has
  started), `TimeToSurface` 0 on the Ocean, `RtGradientFactors.gf99` -100.
  `Ceiling` 0 means no ceiling.
- `gf99` values up to 12 575 occur on deco ascents and Suunto does not define
  the field: show GF99 only after checking it against our own Bühlmann
  pass on a real file.
- Samples are not always in time order (the Ocean goes up to 1.05 s
  backwards): sort, then drop duplicates.
- Samples after `DiveTime` are surface readings: cut the profile there, and
  take tank start / end pressures from inside the dive.
- `Header.Diving.Algorithm` is written both "Suunto Fused2 RGBM" and "Suunto
  Fused RGBM 2"; `DiveMode` is Air, Nitrox or Mixed; `Conservatism` can be
  negative.
- Gas numbering: the D5 is 1-based, the Ocean 0-based (confirms the split
  above). The Ocean has no `Header.Diving` at all; it numbers five cylinder
  slots and writes `null` for unpaired ones.
- `Latitude` / `Longitude` in samples are radians, `DiveRouteOrigin` degrees.
  UWMedia has no use for either (and they are private).
- Depth in samples is metres (checked in the fixtures: 44.79 against a header
  maximum of 46.29).
- `Device.Name` is user-settable ("Porvoo" on one Ocean), so the model must
  come from more than the name: also the firmware / hardware info and the
  shape of the file (to work out on real EON and Nautic exports).

### 2.2 SML (`.sml`)

- `<sml xmlns="http://www.suunto.com/schemas/sml"><DeviceLog><Header>…
  <Device>…<Samples><Sample>`: the same SBEM tree as the JSON, as XML.
- Differences: `Header/DateTime` is local time **without a zone**; samples
  carry `<Time>` in seconds from the start; events are nested
  `<Events><State><Type>…<Active>`.
- Other logbook programs rarely read SML, so there is no fallback route
  for it. No EON SML file has been seen; the one seen is from a HelO2. Whether an EON SML carries `NoDecTime`, `Cylinders` and
  a heading is to verify.
- Shares one sample reader with the JSON: both become the same Python dicts,
  then one builder makes Waypoints (the pattern `parsers/shearwater.py` uses
  for its XML and CSV).

### 2.3 Suunto DM4 / DM5 XML (`.xml`)

- Root `<Dive xmlns="http://schemas.datacontract.org/2004/07/Suunto.Diving.Dal">`.
- Header: `StartTime` (local, no zone), `Source` (model), `SerialNumber`,
  `SampleInterval`, `MinGf` / `MaxGf`, `Algorithm` (an int code).
- Gases: `DiveMixtures/DiveMixture{Oxygen, Helium (%), StartPressure,
  EndPressure, TransmitterId, DiveGasChanges}`.
- Samples: `DiveSamples/Dive.Sample{Time s, Depth m, Temperature °C, Pressure,
  Ceiling, GasTime, Heading, SacRate}`, nil as `i:nil`. Pressure units to
  verify (the DM5 database stores mbar). DM4 files may only have the base64
  `ProfileBlob` / `SampleBlob`; read those only if a real DM4 file turns up.
- Events: `Marks/Mark{MarkTime, Type, Heading}`.
- **Heading:** this is the first format UWMedia would read with a compass
  heading in its samples; see § 3.6.

Not planned: the DM3 `.SDE` zip (Vyper era, none of the three computers) and
the DM4 / DM5 SQLite database (a whole personal logbook).

### 2.4 Fallback that already works

Desktop logbook programs that download the EON Core and EON Steel (Black)
directly over USB / BLE can export UDDF or another format UWMedia reads
today. The device name in those exports must still map to the new Suunto
templates (§ 3.5). The Nautic has no direct download: its only routes are
the app's JSON and FIT.

## 3. Implementation

### 3.1 Parsers (`parsers/suunto.py`)

- `SuuntoJSONParser`, `SuuntoSMLParser` (one shared builder) and
  `SuuntoDMXMLParser`, all `BaseParser`s returning `List[Dive]` (one dive per
  file; skip non-scuba JSON with a clear message).
- Units in one place: K → °C, Pa → bar, m³/s → L/min, s stays s (Waypoint's
  `ndl` / `tts` are seconds). NDL 6000 s → the device's `>99′`.
- Fields → Waypoint: `depth`, `temp`, `ndl`, `tts`, `ceiling` (the log's own
  where present), `tanks` keyed by gas number with the mix and
  `TransmitterID`-free names (sidemount `Pressure` / `Pressure2` → two
  tanks, as the X50i sidemount does), `gas_o2_percent` / `gas_he_percent`
  from the gas in use after `GasSwitch`, `volume_sac` / `rmv` from
  `Ventilation`, `air_remaining` from `GasTime`, `gf` / `surf_gf` from the
  Nautic's `RtGradientFactors`, `cns`, `battery`, `setpoint` from SetPoint
  events (EON CCR mode, to verify on a real CCR log), `dive_alerts` from the
  events (§ 3.4).
- Sparse samples: carry the last value of each key forward to the next
  sample; resample onto the 10 s grid (EON) or keep the irregular Nautic
  times; drop duplicate timestamps.
- Time: JSON is zone-aware (convert to the naive local time the other
  parsers produce, keep the offset on the Dive if the model has a place for
  it); SML and DM XML are local already.
- Deco: run the existing `parsers/deco_pass.apply_deco_and_gas` like the
  other parsers, but **keep the logged NDL / TTS / ceiling** where the log
  has them (the device's numbers beat a recomputation, and Fused RGBM 2
  cannot be recomputed). The pass fills the stop depth / time Suunto never
  logs, and fills the gaps between Nautic samples. GF: the log's (DM XML
  `MinGf` / `MaxGf`; the paired FIT for the Nautic), else the device default
  (Nautic 40/85, EON Bühlmann 30/70). On an RGBM dive say "approximated
  with Bühlmann" in the Log Viewer the way other recomputed values are marked.
- Paired FIT: if `<name>.fit` sits next to `<name>.json`, take the mixes and
  GF from it when the JSON lacks them. The FIT alone goes through
  `parsers/garmin.py`, which needs its Suunto product ids mapped (the
  roadmap's "Suunto FIT logs" item; needs one real file).

### 3.2 Format detection (`parsers/registry.py`)

- New keys `SUUNTO_JSON`, `SUUNTO_SML`, `SUUNTO_DM_XML`; `.json` and `.sml`
  added to `LOG_EXTENSIONS` and `LOG_FILE_FILTER` ("Suunto (*.json *.sml
  *.xml)").
- `.json`: a Suunto log only when the head contains `"DeviceLog"`; any other
  JSON is not a log (the app has many JSON files: settings, plans, overlay
  documents - folder scans must not pick them up).
- `.sml`: by extension, confirmed by the `<sml` root.
- `.xml`: add `Suunto.Diving.Dal` → `SUUNTO_DM_XML` before the "any other
  `.xml`" fallback; also `<sml` in an `.xml` (renamed files).

### 3.3 Model fields

- `Waypoint.heading` (degrees) for the DM XML samples and any JSON that has
  one; unit to verify (the SBEM heading may be radians × 10⁴). Drives a future
  compass page; nothing draws it in the first round.
- `Dive.device` set to the marketing name ("EON Core", "EON Steel Black",
  "Nautic"), mapping internal names (`Vaasa` → Nautic) in the parser.
- Bookmarks as `dive_alerts` entries, no new field.
- Nothing else is new: everything else maps to existing Waypoint fields.

### 3.4 Rules and notices (`hud_rules.json`, `utils/hud_rules_engine.py`, `utils/hud_notices.py`)

A `Suunto` brand block with model overrides, each row cited in
`hud_rules_sources.md`:

- NDL colours: EON green; Nautic white value, yellow at ≤ 5 min.
- Safety stop: 2.4-6 m window, 3 min default, voluntary yellow / mandatory
  red (EON); amber pill, `STOP DONE` cyan (Nautic).
- Deepstop (EON): > 20 m, half the max depth, ±1.5 m.
- Ceiling window states: in window (white ▼▲ EON / yellow Nautic), safe
  margin 0.6 m (yellow), broken (red); `locked` after 3 min (EON RGBM),
  `CEILING BROKEN` bar (EON Bühlmann), `ALGORITHM DEVIATION!` (Nautic).
  The roadmap already lists a `locked` state for the Garmin; do it once.
- Ascent bar: 2 m/min steps and the per-model colour bands above.
- Tank: red below 50 bar (fixed), yellow below the user alarm (assumed 70
  bar, not in any log); gas time red at 0.
- pO2 > 1.6 red; CNS 80 / 100 %, OTU 250 / 300.
- Notices from the log's own events where they exist (Change gas, PO2 High,
  Tank Pressure, Setpoint switched, Bookmark saved), in the EON's
  yellow-bordered pop-up and the Nautic's cyan switch-window panel; derived
  from values where the log has no event (as the Garmin pages do).

### 3.5 Dive computers (`utils/dive_computers.py`)

- Three entries: "Suunto EON Core", "Suunto EON Steel Black", "Suunto
  Nautic" (manufacturer "Suunto"), so the Dive Profile Builder can pose as
  them and `computer_label_for()` picks their templates from a log's device
  name.
- Matching: "EON Steel" (non-Black, same screen) → EON Steel Black;
  "EON Core" → EON Core; "Vaasa" / "Nautic" / "Nautic S" → Nautic. A
  third-party export may name the model its own way ("Suunto EON Core");
  test it.
- The Builder's writers (UDDF, FIT, SSRF) name the device so the parsers find
  it again. A Suunto JSON writer is **not** planned unless the owner wants
  synthetic Suunto files to round-trip through the new parser (useful for
  tests, see § 5).

### 3.6 Rendering elements (`gui` / HUD renderer, Overlay Designer)

New element types, each usable from the Overlay Designer:

1. **`arc`**: a circular arc (start / sweep angles, track colour, value
   colour from the rules, thickness), filled by a field over a range (NDL
   0-100 min, tank 0-250 bar, stop time over its length), with a label and a
   value inside. Covers the EON Prominent and Graphical arcs; the roadmap's
   freedive `ring` and the Mk3i arcs are the same element.
2. **`segment_bar`**: a vertical stack of N segments with a colour per band,
   filled by a field (ascent rate up from the bottom, NDL / tank on the
   EON's right edge, the Nautic's tank gauge and thin tissue bar).
   `ascent_chevrons` stays for the Garmin; check whether the Nautic's
   chevron column is a `segment_bar` with a chevron glyph or the existing
   element restyled.
3. **Pill / filled box behind a text field**: a background colour and corner
   radius on text elements (the Nautic stop timer, `STOP DONE`, the filled
   user-alarm fields). Check `badge` first; it may already be this.
4. **Prime-mark time formats**: `24′` (minutes), `2′50` (m′ss, smaller
   seconds), `24'05` (Nautic), `>99′`. Added as field formats beside the
   existing ones.

Not in the first round: compass rings (no heading yet), the analog timer
watch (EON Gauge), the Nautic tissues graph and Δ+5 / @5 (what-if values).

### 3.7 Templates (`overlays/templates/suunto/`)

Font: a condensed sans in all three; Roboto Condensed (bundled) unless a
photo shows it is clearly wrong. Every manifest gets the
`verified / assumed / not_shown` notes block the X50i has.

**`eon_core/`** (Prominent is its default):

| Page | Content |
|---|---|
| `prominent` | depth, dive time, temperature, NDL arc (asc. time / stop arc in states), switch window, top strip with stop text, ascent bar |
| `prominent_tank` | the same with the blue tank arc |
| `classic` | 3 x 2 grid, NDL / tank bar right edge |
| `graphical` | central semicircle arc |
| `ccr` | classic with `CC` / `SP 1.3`, pO2 after bailout |
| `gauge` | timer view: depth, dive time with seconds, max, gas, tank |

**`eon_steel_black/`**: the same pages with Classic first (its default), on its
own skin and geometry, plus the silver EON Steel housing as a second skin. If the two screens turn out to differ only in size,
one set of layouts with two skins (the Perdix 3 sidemount's `"skin"`
override) instead of copies.

**`nautic/`**:

| Page | Content |
|---|---|
| `main` | depth, dive time, NO DECO / DECO cell, stop row with pill, ascent column, switch window Double (gas / tank), status strip |
| `main_ndl_tts` | the NDL + TTS deco-cell variant |
| `large` | switch window Large (tank pressure with its gauge bar) |
| `gf` | switch window GF99 / Surf GF and GF settings |
| `multigas` | active gas + ppO2 / MOD |
| `sidemount` (variant of `main`) | the two horizontal tank bars, the `SIDEMOUNT` switch panel |

Skins: the PNG background per page, as the other brands have, drawn from the
manuals' figures first and replaced by photo-measured ones when real screens
are on hand.

## 4. Order of work

Progress: step 2 done 2026-11-14 (`parsers/suunto.py`, `tests/test_suunto.py`;
built on the D5 / Ocean sample exports, EON and Nautic files still to check).
Step 3 done 2026-11-14: `arc` and `segment_bar` elements, a text element's
`box_color`, the `minutes_prime` / `m'ss` formats (`gui/hud_renderer.py`,
Overlay Designer add / inspector support). Not done: a pill-shaped box
behind a value with a small suffix (the box only goes behind plain text).
Step 4 done 2026-11-14: the `Suunto` block in `hud_rules.json` (EON rules
at brand level, `Nautic` model block), cited in `hud_rules_sources.md`;
gauges take the brand's ascent-rate bands; the logged ceiling is the stop.
Not modelled: the mandatory (red, longer) safety stop, deepstops, the EON
lock / Ceiling broken bar and the Nautic's Algorithm deviation panel, the
highlighted-red ascent bar after 5 s. Template model names must be
"EON Core", "EON Steel Black" and "Nautic" to pick up these rules.
Step 5, first round done 2026-11-14: `overlays/templates/suunto/`
`eon_steel_black` and `eon_core` (Classic, Classic (CCR)) and `nautic`
(Main Screen), skins from the cleaned product photos, positions measured on
the Steel Black and Nautic photos (the EON Core's mapped from the Steel
Black's); the three computers in `utils/dive_computers.py`; golden images
and sweep entries. Renderer additions: `safety_stop_depth`, `uppercase`,
`small_suffix_align: baseline`, the m'ss stop timer, page `badge_states`
overrides. Still to do: the EON Prominent and Graphical styles (arc pages),
the gauge / timer pages, the Nautic's other switch-window views and
sidemount, compass pages once a log carries a heading.
Step 5, second round done 2026-11-14: EON Prominent (no deco, tank),
Graphical and Gauge timer pages from the manual figures (EON Core p.30-31,
Steel Black p.54); the layout sweep checks text against an arc's band, and
an arc's bounds are its drawn band.
Step 5, third round done 2026-11-14: the Nautic Main Screen corrected from
the manual's dive-screen figures (p.22, p.35, p.51-53) and split into
single-tank and sidemount variants; a NDL / TTS, ppO2 / MOD page; horizontal
segment bars; NDL zero shown in a page's own format ("0′"). Still to do:
compass pages (a heading in a log), the Nautic's large switch-window views
(tissues, stopwatch), GF99 / Δ+5 fields, STOP DONE and the Algorithm
deviation panel. Step 5 is otherwise done; steps 6-7 (SML / DM5 XML, the
paired FIT) wait on real files.

1. **Inputs** (owner): real logs and screen photos (§ 6). Without at least one
   real JSON per family, step 2 is built on the sample exports in
   `test_data/` (local only, never in git; see § 5).
2. **Suunto JSON parser + detection + device mapping**, with the deco pass
   keeping logged values. The Log Viewer and Builder show Suunto dives;
   existing generic templates already work on them.
3. **Elements**: `arc`, `segment_bar`, filled text background, prime-mark
   formats; Overlay Designer support and renderer tests.
4. **Suunto rules and notices** in `hud_rules.json`, sourced.
5. **EON Core templates** (Prominent first), then **EON Steel Black**, then
   **Nautic**; dive-computer entries with each.
6. **SML parser** (reuses the JSON builder), then **DM XML parser** + heading.
7. **Paired FIT / Suunto FIT** when a real file is on hand.
8. Docs and record: `docs/` pages that list supported logs and computers,
   `hud_rules_sources.md` (manuals table, Suunto rules), `roadmap.md` (tick the
   Suunto parts of "New computers" and "Suunto FIT logs"; add what is left),
   `CHANGELOG.md` per round.

## 5. Tests and test data

- Parser unit tests per format: units (K, Pa, m³/s), sparse-key carry
  forward, duplicate timestamps, gas switches, sidemount `Pressure2`, non-dive
  JSON rejected, time zone handling, internal name mapping.
- Detection tests: Suunto JSON vs other JSON, SML in `.xml`, DM XML vs
  the other XML logs UWMedia reads.
- **Fixtures in git are synthetic**: small hand-written JSON / SML / XML
  files with made-up serials, no GPS and no transmitter IDs. Real exports
  stay in `test_data/` (the no-dive-logs-in-git rule covers these formats;
  they carry the device serial, transmitter IDs, GPS route and heart-rate
  data).
- Sample Suunto app exports are in
  `test_data/dive_computers/suunto/suunto_json_samples/` (13 `.json`): D5
  and Ocean, cut-down real
  dives covering deco, deep-stop and safety-stop alarms, tank pressure, heart
  rate, a header-only file and a non-dive activity. Good for the first
  parser and detection tests, before an EON or Nautic file is on hand.
  Several still carry serial numbers and GPS, so they stay local as well;
  the synthetic fixtures for git can copy their shapes.
- Rendering: golden images for each new element and each Suunto page in
  `tests/fixtures/overlay_golden/`; the template sweep picks up the new
  templates.
- `tests/run_tests.sh 1` before each round is called done.

## 6. Open questions for the owner

1. **Which logs are on hand?** One real Suunto app JSON (with its FIT) from
   an EON and from a Nautic would settle most "to verify" items; an EON
   compass dive settles the heading; a CCR-mode EON dive the setpoint
   events.
2. **Screen references:** the product photos (§ 1.0) give the skins and one
   screen each. For the other pages, photos or screenshots of each computer
   underwater (as `test_data/dive_computers/screen_shots` holds for the
   X50i) would still settle the geometry; the manual figures are 110-208 px
   wide.
3. **SML and DM XML priority:** DM5 has been dead since 2020 and the Nautic
   never had it. Keep them in this plan (after the JSON), or drop them unless
   a real old log turns up?
4. **EON pages:** all three styles (Classic, Prominent, Graphical), or the two
   defaults (Steel Black Classic, Core Prominent) first?
5. **Nautic S:** the manual does not cover it. Treat it as a Nautic, or leave
   it out?
6. **RGBM dives:** show the device's own NDL / TTS / ceiling only and mark the
   stop depth / time as Bühlmann-approximated, as proposed in § 3.1?
