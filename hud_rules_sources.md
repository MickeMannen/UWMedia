# Where the values in `hud_rules.json` come from

`hud_rules.json` holds the colour bands, safety-stop and deco-stop
definitions, tank reserve rule and badge styles the overlays use, per brand
and model. JSON has no comments, so this file is the citation for every
rule, and `"_source"` / `"_<rule>"` keys inside the JSON (ignored by the
engine, see `is_annotation_key()` in `utils/hud_rules_engine.py`) repeat the
short form next to the rule.

Statuses:

- **verified** - read in the manual named below, page given (PDF page of the
  file in `test_data/dive_computers/`).
- **deduced** - taken from a figure, photo or real log rather than stated in
  the manual's text; the figure or file is named.
- **assumed** - no source; a generic or copied value. Treat as a guess until
  verified.

Rules keep their status until someone opens the manual; when a value
changes, change the row here in the same commit. Audit of 2026-10-16: every
rule below was checked against the manuals listed.

## Manuals on hand (`test_data/dive_computers/`)

| Model | File | Revision |
|---|---|---|
| Shearwater Perdix 2 (recreational modes) | `Perdix-2_RECREATIONAL_Manual_RevC.pdf` | Rev C (2022-06-30) |
| Shearwater Perdix 3 | `Perdix_3_Operating_Instructions_RevB.pdf` | Rev B |
| Shearwater Petrel 3 (recreational) | `Petrel-3_RECREATIONAL_Manual_RevC.pdf` | Rev C |
| Shearwater Petrel 3 (technical) | `Petrel-3_Technical_Manual_RevB.pdf` | Rev B |
| Shearwater Peregrine TX | `Peregrine_TX_Manual_RevC_….pdf` | Rev C (2024-04-23) |
| Shearwater Teric | `Teric_Manual_RevH5.pdf` | Rev H (2024-09-09) |
| Shearwater Tern | `Tern_Manual_Rev_B-1.pdf` | Rev B (2023-11-24) |
| Garmin Descent Mk3 series | `Descent_Mk3_Series_OM_EN-US.pdf` | owner's manual, EN-US (replaced the EN-MY edition on 2026-10-16; Garmin pages cited before that date are the older edition's, e.g. its p.12-14 alert table is now p.35-36) |
| Garmin Descent X50i | `Descent_X50i_OM_EN-US.pdf` | owner's manual, EN-US (replaced the EN-SG edition on 2026-10-16; older page numbers as above, its p.12-13 alert table is now p.26-27) |

To re-read a passage: `pdftotext -layout <file> out.txt`, then `grep`; a
figure: `pdftoppm -f N -l N -r 100 -png <file> page` and open the PNG.

## Shearwater (brand level)

| Rule key | Value | Source | Status |
|---|---|---|---|
| `ndl` | yellow below 5 min, white above | Perdix 2 p.17 ("Displays in Yellow when the NDL is less than the low NDL limit (Default 5 minutes)"); p.24 Low NDL Alert: value yellow at or below the alert value, re-arms 3 min above it. Teric p.16 and Tern p.15 say "less than (or equal to) 5 minutes" | verified |
| `ndl_zero` | red | Perdix 2 p.33 (NDL "0" shown in red in deco) | verified |
| `po2` | red at or above 1.61 bar | Perdix 2 p.19 "Displays in Flashing Red when outside PPO2 limits"; p.62 Adv. Config 2: OC Min 0.18, OC MOD 1.40, OC Deco 1.61 (defaults). 1.61 (deco limit) is the band so a deco gas is not flagged; the bottom gas's 1.40 limit needs the gas list (`simulator.md` A2). Flashing not drawn yet | verified (threshold choice: see note) |
| `po2_limits` | min 0.18, mod 1.40, deco 1.61 | Perdix 2 p.62 | verified (not used by the engine yet) |
| `safety_stop` trigger 11 m, countdown below 6 m, window 2.4-8.3 m, 180 s, paused outside the window with the time in yellow, reset below 11 m, "Complete" | Perdix 2 p.27; identical on Peregrine TX p.26, Petrel 3 Rec p.26, Teric p.25, Tern p.24, Perdix 3 p.58-59 | verified |
| `safety_stop.adapt` 5 min deeper than 30 m or NDL under 5 min | Perdix 2 p.17 (Adapt option) and p.27 | verified |
| `deco_stop` approach 5.1 m, at-stop window 1.5 m deeper | Perdix 2 p.28; Petrel 3 Rec p.27 | verified |
| `deco_clear.count_up` | Perdix 2 p.28 (Deco Clear counter counts up from zero); Teric p.26; Perdix 3 p.60 | verified |
| `sidemount_switch` 21 bar, green box with black text | Perdix 2 p.42 (notification) and p.57 (SM Switch 21 bar) | verified |
| `tank_reserve` reserve 50 bar default, critical = max(21 bar, half the reserve); reserve = value on a yellow box (black text), critical = value on a red box (white text) | Perdix 2 p.57 (defaults, range 28-137 bar, thresholds, worked examples 48 → 24 and 27 → 21); p.40 figure (colours). Same text: Perdix 3 p.154, Peregrine TX p.56, Petrel 3 Rec p.56, Teric p.74 (figure p.50). Until the renderer can fill a box behind a value (A2) the colour is applied to the digits | verified |
| `ascent_rate` white under 9 m/min, yellow 9-18, flashing red over 18; `ascent_chevrons` 6 arrows, 1 per 3 m/min | Perdix 2 p.12; Teric p.14; Tern p.13 | verified |
| `tissue_load` green under 80 %, amber 80-100, red above | none: copied from the Garmin table. The N2 loading bar's colour steps are not given as percentages (Perdix 2 p.17) | assumed |
| `tank_pressure_fill` red under 50 bar, yellow under 70, white | none; p.40 only says the bar graph scales to the rated pressure. With the reserve rule the bar should follow the box colour (A5) | assumed |
| `badge_states.safety_stop` SAFETY STOP, blue title; green counting with check mark; yellow paused; green Complete | Perdix 2 p.27 and figures; real photo `test_data/perdix2/Perdix_2_1.webp` | verified |
| `badge_states.deco` DECO STOP red; yellow approach; green at stop with check mark; red violation; inline depth and minutes | Perdix 2 p.28, p.33 | verified |
| `badge_states.clear` CLEAR green, m:ss | Perdix 2 p.28 | verified |

## Shearwater, per model

| Model | Rule key | Value | Source | Status |
|---|---|---|---|---|
| Perdix 2 | `tank_pressure` | removed 2026-10-16 (was red ≤ 60, orange ≤ 70, unsourced); the brand's `tank_reserve` applies | Perdix 2 p.57 | verified |
| Peregrine TX | `tank_pressure` | removed, as above | Peregrine TX p.56 (same text, same 50 bar default) | verified |
| Teric | `badge_states` | SAFETY in a boxed green title while counting; SAFETY / PAUSED in yellow; SAFETY / CLEAR (cyan title, green CLEAR) when done; DECO red; no check mark, no approach colour; stop info yellow when shallower than the stop but deeper than the ceiling; flashing red above the ceiling | Teric p.25-26 figures. The ceiling-violation colour needs the ceiling phase (A2) | verified |
| Tern | `badge_states` | same as Teric | Tern p.24-25 figures | verified |
| Perdix 3 | `badge_states` | SAFETY in a green box, PAUSED yellow, SAFETY / CLEAR when done; DECO blue label over depth and minutes | Perdix 3 p.58-60 | verified |
| Petrel | (brand defaults) | | Petrel 3 Rec p.26-27 and p.56 give the same safety stop, deco stop and reserve rules as the Perdix 2 | verified |
| Tern | (no tank rules) | the Tern has no air integration | Tern manual: no AI section | verified |

## Garmin (brand level)

| Rule key | Value | Source | Status |
|---|---|---|---|
| `ndl` | red under 10 min, yellow 10-30, white above | none. The manuals only give "Approaching NDL" alerts at 10 and 5 min (Mk3 p.13, X50i p.12 "10 minutes to NDL" / "5 minutes to NDL"); the real screenshots in `test_data/dive_computers/garmin_mk3i` and `garmin_x50i` show the NDL white at 99+ | assumed |
| `tank_reserve` reserve 50 bar, critical 25 bar (both assumed); value yellow below the reserve, flashing red below critical | Mk3 p.14 / X50i p.13 transceiver alerts ("The tank pressure value turns yellow" / "flashes red"); Reserve Pressure "sets the threshold values for reserve pressure and critical pressure alerts" (Mk3 p.6, X50i p.5). Defaults are not in the manuals | colours verified, defaults assumed |
| `tank_pressure` | removed 2026-10-16 (was red ≤ 60, orange ≤ 70, unsourced) | | |
| `tank_pressure_fill` | red under 50 bar, yellow under 70 | none; the gauge is scaled by the working pressure (Mk3 p.6), colours not given | assumed |
| `po2` | yellow at or above 1.4 bar, red at or above 1.6 | Mk3 p.4 / X50i p.4 "Setting PO2 Thresholds" (PO2 Warning, PO2 Critical); the value flashes yellow above Warning and red above Critical (Mk3 p.13-14, X50i p.12-13). Defaults not in the manual; 1.4 / 1.6 match a real mk3i FIT `dive_settings` record | thresholds assumed, colours verified |
| `safety_stop` trigger 11 m, stop 5 m, timer starts within 1 m, pauses more than 3 m above, resets below 11 m, 180 s | Mk3 p.10 / X50i p.9-10 "Performing a Safety Stop"; "Safety Stop Started: you ascended above 6 m" (Mk3 p.14, X50i p.13) for `max_depth` 6 | verified |
| `safety_stop.warn_above_m` 2 m | Mk3 p.13 / X50i p.12: "Descend to complete safety stop" more than 2 m above the ceiling, depth and stop depth turn yellow (not drawn yet, A2) | verified |
| `safety_stop.min_depth` 1.2 m | none (surface threshold of the timeline) | assumed |
| `deco_stop` approach 3 m, at-stop 0.6 m, violation more than 0.6 m above | Mk3 p.10 and p.13 / X50i p.10 and p.12: "Approaching Deco Stop" within one stop interval (3 m); stay within 0.6 m of the ceiling; above that the depth and ceiling flash red and the timer pauses | verified |
| `ceiling_broken` margin 0.6 m, red | Mk3 p.10 / X50i p.10 | verified |
| `lockout` 3 min above the ceiling | Mk3 p.13 / X50i p.12 (decompression lockout; not modelled yet, A2) | verified |
| `badge_states` STOP green, DECO orange (also for clear) | X50i p.10 figure (stop box) | deduced |
| `tissue_load` green under 80 %, yellow 80-99, red 100 % or more | Mk3 p.7-8, X50i p.7 | verified |
| `ascent_rate` green under 7.9 m/min, yellow 7.9-10.1, red over 10.1 | Mk3 p.7-8, X50i p.7; alert "Ascending too fast" over 9.1 m/min for 5 s (Mk3 p.13) | verified |

## Garmin, per model

| Model | Rule key | Value | Source | Status |
|---|---|---|---|---|
| mk3i | `badge_states` | empty labels, white | real Mk3i screenshots (`test_data/dive_computers/garmin_mk3i/`) | deduced |

## default (no brand)

Generic values with no source; they only apply to Custom templates that
borrow no brand profile. All **assumed**.

## Notices (`notice_style`, `notices`)

The texts, triggers and colours of the device notifications a Notice
element shows (`utils/hud_notices.py`). Every entry in `hud_rules.json`
carries its own `_source`; the table is the summary.

| Brand / model | Item | Value | Source | Status |
|---|---|---|---|---|
| Shearwater | `notice_style` | message in yellow under a "Warning" (or "Alert", "Error") caption with "Confirm" at the right, across the bottom row | Perdix 2 p.22 and p.24-26 figures; Peregrine TX p.21; Petrel 3 Rec p.24 | verified |
| Shearwater | `show_seconds` 10 | none: the device keeps a notification until a button is pressed, which a log does not record | assumed |
| Shearwater | `LOW PPO2` below the OC Min limit (0.18) | Perdix 2 p.25, p.62 | verified |
| Shearwater | `HIGH PPO2` above the limit for more than 30 s (1.61 used) | Perdix 2 p.22, p.25 | verified (limit choice: see `po2`) |
| Shearwater | `MISSED DECO STOP` after a "significant" violation; 30 s used | Perdix 2 p.25, p.28 (no figure for "significant") | wording verified, 30 s assumed |
| Shearwater | `FAST ASCENT` sustained faster than 10 m/min; 10 s used | Perdix 2 p.25 (no duration given) | wording verified, 10 s assumed |
| Shearwater | `VERY HIGH CNS` 150 %, `HIGH CNS` 90 % | Perdix 2 p.25 | verified |
| Shearwater | `Low NDL Alert` at 5 min, re-arms 3 min above; `Depth Alert` at 40 m, re-arms 2 m shallower; `Time Alert` 60 min off by default | Perdix 2 p.24-25 | verified |
| Shearwater | `T1 CRITICAL PRES` below the critical pressure | Perdix 2 p.26, p.57 | verified |
| Shearwater | priority order | first column of the p.25-26 table, then the second | deduced |
| Teric, Tern | `notice_style` banner: filled band, caption small above the message in black, CLEAR tab; yellow warnings, green Deco Clear, cyan info | Teric p.25-26, Tern p.24-25 figures | verified |
| Teric, Tern | `MISSED STOP` (WARNING), `Deco Needed`, `Deco Clear`, `Safety Stop` (INFO) | Teric p.25-26, Tern p.24-25 | verified |
| Teric, Tern | `HIGH PPO2` banner wording | Teric p.23 lists HIGH PPO2 in the warnings overlay; the banner text is taken from the Perdix 2's | deduced |
| Garmin | `notice_style` white text, no caption | the manuals give the alert texts only | assumed |
| Garmin | alert texts, driven by the FIT `dive_alert` events of the same name | Mk3 p.12-14 (Mk3i wording), X50i p.12-13 (x50i wording) | verified |
| Garmin | priority order | deduced (dangerous first; the manual lists alphabetically) | deduced |
| Garmin | depth and stop badge yellow more than 2 m above the safety stop ceiling (`warn_above_m`, phase `warn`) | Mk3 p.13, X50i p.12 | verified |
| Garmin | `sidemount_switch` the tank to breathe from highlighted in blue when the two tanks differ by more than the Switch Pressure threshold; the notice "Breathe from %1." with the tank's name | Mk3 EN-US p.24 (Enabling Sidemount Setup: "an alert appears to remind you to breathe from the tank with the higher pressure", "The recommended breathing tank is highlighted in blue"), p.36 alert table; X50i EN-US p.13, p.27 | verified (threshold: a setting, 30 bar assumed - the owner's) |
| Garmin | `clear_blink_depth`: on Decompression Cleared the stop depth line flashes red | Mk3 EN-US p.35 / X50i EN-US p.27 alert table: "The current depth and stop depth flash red" | verified |
| Garmin | NDL under a minute shows "00"; "99+" only above 99 minutes | real screenshots show 99+ at the top end; the last minute is the formatter's own choice | deduced |
| Petrel | ascent rate: six arrows next to the depth, 1 per 3 m/min, no bar (the skin's painted arrows and a stray tick were removed 2026-10-16) | Petrel 3 Rec manual p.11 | verified |
| X50i | alert box fills the top-right cell of the grid (from the column divider to the right edge, the first row's height), dark with a border in the alert's colour; a warning has the triangle in a left column, an information alert (Breathe from ...) a blue border, no triangle and centred text; the cell's own fields step aside | real screenshots `x50i_deco_required_trimix_o2_17_he_40.png`, `x50i_sidemount_change_tank.png`, `x50i_safety_stop.png` | verified (from the photos) |
| X50i | the glass starts at 0.213 of the skin PNG's height (the bezel above it is dark too) | measured in `overlays/templates/garmin/x50i/main/normal.png` | verified |
| mk3i | ascent rate: three chevrons up, a bar, one down, lit green / yellow / red by the `ascent_rate` bands | real screenshot `mk3i_main_sidemount.BMP` (the shape); Mk3 EN-US p.23 (the colours) | verified |

## Units (`display.depth_decimals`, `simulator.md` §7)

| Brand / model | Rule | Source | Status |
|---|---|---|---|
| Shearwater | depth: one decimal in metres, whole feet | Perdix 2 manual p.12 (figures) | verified |
| Shearwater Teric, Tern | depth: one decimal in both | Teric manual p.23; Tern p.11 ("Displayed to one decimal place in feet or meters", figure 125.6 ft) | verified |
| Garmin | depth: one decimal in metres, whole feet | Mk3 p.15 figure 57 ft; X50i p.12 figures 30 ft, 40 ft, MAX. DEPTH 51 ft; metric screenshots 0.0 m | verified |
| Shearwater | where the unit sits: Big / Standard / Rec layouts show the depth with small decimals and the cyan "m" under them ("15.7 m", Perdix 2 p.12 figure), whole feet with the "ft" after the number ("45 ft", same page), and the unit small after the MAX value ("21.0m", "31.6 m"); the Tec layouts' top-row DEPTH has no unit at all, only the value ("54.0", "220"), while a MAX slot keeps its unit | Perdix 2 p.11-12, p.16; Perdix 3 p.22, p.32, p.37-38; Petrel 3 Tec p.10-11; Teric p.11, p.35; Tern p.10-11; Peregrine p.10, p.13 | verified |
| Garmin | where the unit sits: small grey ft / m right after the value for depth and MAX. DEPTH ("30 ft", "51 ft"); the Mk3i Big Numbers page puts the m under the decimal | X50i p.12 figures; Mk3 p.15 figure; real Mk3i screenshot `mk3i_main_single_tank.BMP` | verified |
| all | stops at 10 / 20 / 30 ft for 3 / 6 / 9 m, the 5 m safety stop at 15 ft; pressures whole psi; temperatures whole degrees | Perdix 2 p.28, Mk3 p.10 | verified |

## Display passes (`simulator.md` A5)

| Template | Item | Source | Status |
|---|---|---|---|
| Perdix 2 main | zones, depth with small decimals, ascent arrows, NDL colours, safety stop pending with the NDL demoted below it | Rec manual p.12-13 figures | verified |
| Perdix 2 main | check mark in front of the value ("✓2:59", "20ft ✓2min"), up arrow only while approaching, down arrow above the stop, "Complete" in green under a blue title when the countdown ends | p.27-28 figures | verified |
| Perdix 2 main | Deco Clear counter look (green CLEAR, m:ss) | no figure in the recreational manual | assumed |
| Perdix 2 / Petrel Tec | top row DEPTH / TIME / STOP / TIME with whole minutes and whole metres; once deco clears the STOP / TIME columns become a CLEAR count-up | Petrel 3 Technical manual Rev B p.24-25 (the Perdix 2's Tec layout is the same screen; its own technical manual is not on hand) | verified |
| Teric, Tern | boxed green CLEAR counter over the green count-up; SAFETY / CLEAR | Teric p.13, Tern p.12 figures | verified |
| X50i main | the stop box takes the NDL corner and the tissue bar disappears; the alert sits in a bordered box top right over the tank name; alerts of two lines as the table prints them | real screenshots `test_data/dive_computers/garmin_x50i/x50i_safety_stop.png`, `x50i_deco_required_trimix_o2_17_he_40.png` (night mode, so the colours are not read from them); manual p.12-13 | verified (layout), assumed (box colours) |
| mk3i main | Big Numbers layout | real screenshots `test_data/dive_computers/garmin_mk3i`; manual p.8 figure | verified |

## Differential check against the simulator (`simulator.md` A7, 2026-10-16)

Two scripted dives (the dummy-dive profile; a 36 m / 18 min Nx32 dive
following the Perdix 2's stops with a 40 s violation and a paused safety
stop) run in the simulator and through UWMedia's state machine on the same
depths and stop data. Results, second by second:

| Item | Result | Action |
|---|---|---|
| Deco phases (far / approach / at stop / violation), Perdix 2 | agree within 1 s | none |
| Safety stop after deco, Perdix 2 | the simulator (and Perdix 2 p.28, Perdix 3 p.60) counts the safety stop down after the stops clear; UWMedia ran the deco-clear counter | `deco_clear.count_up` false at brand level; Tec pages set it true in their layout `rules` |
| Safety stop duration | simulator 3 min (its default); UWMedia 5 min (Adapt: past 30 m) | 3 min fixed is the default; `adapt.enabled` turns the 5 min rule on. The manual (p.55) offers 3 min / Adapt / CntUp and names no default: assumed |
| Safety stop timing (pending, counting, paused, resumed, complete) | identical after the change | none |
| Garmin safety-stop window | identical (start within 1 m of 5 m, 3 min) | none |
| Garmin safety stop after deco | the simulator shows one; UWMedia none (a real Mk3i log raised no safety-stop event after its deco) | kept: the real log wins |
| GTR (Shearwater formula) | within 1 min over the whole dive | none; the GTR slot now reads "deco" during stops (p.26) rather than "wait" |
| GF99 / SurfGF | within 2-6 points (different tissue bookkeeping) | none |
| Low NDL alert | same second | none |
| MISSED DECO STOP timing | the simulator raises its CEILING alarm at once; our notice after 30 s (assumed) | still assumed |

## Computed values and persistent notifications (`simulator.md` A6)

| Rule key | Value | Source | Status |
|---|---|---|---|
| Shearwater `gf_colors` | GF99 and SurGF yellow above the GF High setting, red above 100 %; GF high from the log's deco model when it has one, else 85 (Med) | Perdix 2 p.20; p.~55 Conservatism defaults | verified (default GF high: Med 40/85 per p.55) |
| Shearwater `gas_time` | GTR = (Ptank - Preserve - Pascent) / (SAC x Pamb), SAC over the last two minutes at 1 ATA, 10 m/min direct ascent, reserve default 50 bar, "wait" until two minutes of data, no GTR in deco | Perdix 2 p.44-45, p.57, p.26 | verified; Pascent = SAC x ascent minutes x mean ambient is our reading of "the pressure used for the ascent" |
| Shearwater `persistent_notices` | High CNS (CNS limit reached), MOD go up (red box, up arrow) past the gas's MOD, Near MOD (yellow) within 1.9 m below it; p.13 figure for the box | Perdix 2 p.23, p.13 | verified; "MOD switch gas" and "Better Gas" need the gas list (not modelled) |
| MOD | (MOD ppO2 / fO2 - 1) x 10 m with the brand's `po2_limits.mod` (Shearwater 1.40) | Perdix 2 p.62 | verified |
| GF99 / SurfGF | leading compartment's supersaturation over ambient as a share of the Bühlmann M-value gradient, at depth and at surface pressure; 0 when on-gassing ("On Gas" on the device) | Perdix 2 p.20 definitions | verified (the "On Gas" wording is not drawn) |

## Facts read but not yet in the rules

- Shearwater persistent notifications shown left of the NDL (Perdix 2
  p.23): `High CNS`, `MOD, go up`, `MOD, switch gas`, `Near MOD` (within
  1.9 m below the MOD), `Better Gas` (only when deco stops are needed). Gas
  name in yellow when a better gas is available, flashing red past its MOD
  (p.18). Needs the MOD (A6) and the gas list.
- Teric / Tern persistent warnings overlay listing the active alerts
  (Teric p.23).
- Garmin: `Decompression Cleared` flashes the stop depth and time blue for
  five seconds (Mk3 p.12); OTU colours green / yellow / red at 250 and 300
  (X50i p.10); transceiver NO COMMS (dashes, value flashes red after 60 s);
  lock-out after 3 min above the ceiling (`lockout`, what the watch shows
  is not described).
