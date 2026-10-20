# Roadmap

The one list of what is still to do. Finished work is in `CHANGELOG.md`;
the reasoning behind a bigger item lives in its design note where one
exists (`redesign.md`, `local_ci.md`, `hud_rules_sources.md`). Items are
grouped by area and ordered by value within each group; "needs" names the
thing that blocks an item.

## 1. Processing: from CLI subprocess to a worker (`redesign.md`)

Decided 2026-10-16: processing stays in a child process, driven by a JSON
job spec with JSON progress messages; no scripting tool is supported from
now on; every platform ships one GUI-only app.

Before the implementation plan (redesign.md §6):
- [ ] Inventory the CLI options in use and how `args` flows through `cli_main.py`.
- [ ] Inventory every print to stdout / stderr in the pipeline.
- [ ] List what the three backends parse today (statuses, errors, timing, summary).
- [ ] Choose the message channel (extra pipe, local socket or passed fd) and check it on all three platforms, source and packaged.
- [ ] Find everywhere external processes are started, for the process-tree Stop.
- [ ] List the tests that drive the CLI and how they move to the worker.
- [ ] Verify Windows Stop (ffmpeg left running?), the Windows console question for a GUI-subsystem build, and that a pipe survives the packaged macOS launcher.
- [ ] Measure child start-up time; then decide one worker per session or per run.

Then, in order (redesign.md §7):
1. Fix Stop on every platform (process tree kill).
2. Drop the macOS Terminal installer and the scripting docs (`docs/cli.md`, the CLI examples in the README and getting-started).
3. Job spec, worker entry point, message channel, with tests.
4. Move Color, then Overlay Generator, then Convertion to the worker; remove each old path after.
5. Remove `cli_main.py` and move the render tests to the worker.
6. Windows / Linux become the plain `uwmedia` GUI build; drop the hidden-console relaunch.

## 2. Overlays: workflow

- [x] **Sync by eye** (2026-10-17): a clock offset on the Color page, set on the preview by typing the dive time the computer shows or by nudging; the Overlay Generator leaves the alignment to the editor. A camera-profile version that saved the offset per camera from the Overlay Designer was tried and dropped the same day as unusable.
- [x] **Transparent overlay export** (2026-10-17): ProRes 4444 by default, PNG sequence, or the video on black. Left for later: a VP9 with alpha for editors without ProRes, and exporting only a chosen range of a log-only render.
- [ ] **Suunto FIT logs.** The FIT parser maps Garmin products; a Suunto FIT file (Nautic, Ocean, D5) may carry the same record messages with other ids and no tank pods. Needs: one real Suunto FIT file.
- [ ] Vertical video: a 9:16 frame scales overlays by width today, so they come out small on phone footage. Needs a portrait design size and anchors against the short side.
- [ ] Brand-free overlay families (lower third, side rail, corner stack, minimal, vertical stack) as bundled generic templates; also the natural templates for freediving and for computers without a skin.
- [ ] A soft text shadow as an alternative to the outline.
- [ ] Multi-layer compositing: a profile graph over a device template without copying the element into a modified template.

## 3. Overlays: fidelity and decisions still open

Owner decisions:
- [ ] Setting-relative rules (tank reserve, Low NDL alert, ppO2 limits): template knobs with manufacturer defaults, or hard-coded defaults?
- [ ] Units per run in the Overlay Generator (a psi computer, a metric app)? Follow a log's own device units automatically?
- [ ] Garmin NDL colour bands (assumed; the manual only gives the 10 and 5 minute alerts): keep, or white?

Facts read but not in the rules yet:
- [ ] Garmin OTU colours, the NO COMMS transceiver display, lock-out after three minutes above the ceiling, a `locked` state.
- [ ] Shearwater "Better Gas" notice and gas-name colours (need the gas list), Teric / Tern persistent warnings overlay.
- [ ] Garmin sidemount switch pressure default (30 bar assumed), Garmin reserve / critical defaults (50 / 25 bar assumed), tissue-load bands.
- [ ] What-if values (Shearwater `@+5` / `Δ+5`, Garmin `NDL Δ 3M`): only if a page needs them.

Pages and fields:
- [x] Teric and Mk3i Standard layouts (3b).
- [x] Garmin X50i dynamic-depth page (3b; checked against the manual's p.21 figure only, not against `x50i_dive_graph.bmp` or an in-water screenshot).
- [ ] Garmin three-tank layout (the device's transceiver screen). Needs: a log with three live tanks.
- [ ] Freediving. (a) A session parser: a FIT apnea activity holds every dive of the session with a summary per lap; split it into dives with dive number, surface interval, last dive time and depth, vertical speed, and match media shot in a surface interval to the session. (b) A `ring` element: a circular track with an arc from 12 o'clock for elapsed time over the dive, depth over max depth, or depth over a target, with a value in the centre; also the arc gauge later computers need. (c) Depth interpolated per frame between samples so the number counts smoothly, and an optional zero-based start and end when the log begins underwater. (d) Templates: a generic Freedive family (big depth with unit, time ring centred), then Teric / Tern Freedive mode and the Mk3i apnea screen from their manuals, whole metres by default. Needs: a real freediving log.
- [x] CCR: what `gasmix` means for a CCR waypoint (the breathed gas), per-cell PO2 fields - see 3b; a colourable divider line (red on bailout) is open there.
- [ ] Compass heading as a field (no source format carries one yet).
- [ ] New computers (Suunto D5 / EON Core, Mares Quad family, Scubapro G2 / G3, Cressi Goa / Donatello, Aqualung i330R / i770R), deferred 2026-10-16. Each needs a real log, the manual and a clean screen reference; segment-display and arc elements come with the first of them.

Verification gaps (built, not checked against real data):
- [ ] Teric, Tern and Peregrine: a real export each (field set, PO2 / NDL population, no tank pressure on the Teric).
- [ ] Perdix 3: a sharp device photo for the Big, Standard and Tec pages.
- [ ] Perdix 2: a sidemount export and a dive that clears a stop, to see the real "clear" transition.
- [ ] A CCR Subsurface log with live cylinder pressure.
- [ ] One end-to-end video encode of each template checked by eye, not only single frames.

## 3b. CCR and the manuals' standard pages (started 2026-10-20)

Owner decisions 2026-10-20: CCR pages for Petrel 3 (cells and setpoint),
Perdix 3, Teric, Garmin Mk3i and X50i, and Perdix 2 with an assumed look
(its Technical Modes manual is not on hand); the standard pages listed below;
the Shearwater Cloud database is not read; the Builder and the Log Viewer get
full CCR support. Test logs come from the Builder, never copied from other
projects' sample dives. Manual pages: `hud_rules_sources.md`.

1. Data and parsers
- [x] Waypoint: setpoint, the breathed gas and the diluent apart from the tanks; circuit (CC / OC / BO / SC), diluent PO2; a dive-level CCR flag.
- [x] UDDF and Garmin: a tank keeps its own mix where the file links one; the setpoint and diluent per waypoint.
- [x] Subsurface: `dctype`, `modechange`, `cylinder use=`, `po2=` as the setpoint on the loop, no tank-key collisions.
- [x] A CCR dive is not taken for sidemount. CC screens are pages of their own (the manuals treat CC as its own screen; the Overlay Generator composes its layout before it knows the dive, so a per-dive variant would need the pipeline reworked).
- [ ] Shearwater Cloud XML / CSV on the loop: the setpoint, cell (mV) and PPO2-mode columns. Needs: a real CC export (none on hand; the CC branch of `_divemode` is unconfirmed).
- [ ] The tanks of a Shearwater CCR UDDF (its tankdata links no mix, so the O2 cylinder shows the diluent's mix). Needs: a way to tell which transmitter is the O2 (the app's transmitter names are only in its database).
2. Rules and rendering
- [x] PPO2 formats per element; CC / BO / OC labels (OC on a Descent); CC limits (0.40 / 1.60), DilPO2 limits; cell voting colours; setpoint high / low colours; `hide_in_circuits`.
- [x] Notices: Garmin "Switched to high/low setpoint."; Teric "Auto SP Up"; Shearwater LOW / HIGH PPO2 on the loop. ("Diluent PO2 is low." only flashes the value: the FIT alert's name is not in the logs on hand.)
- [x] A CCR sample dive for the Overlay Designer; golden renders of the CCR pages at its CCR moments.
- [x] A CCR-aware deco recompute for logs (loop gas at the setpoint, OC after bailout).
- [ ] "VOTING FAILED" alternating with the cell readings (Petrel 3 Tech p.67); the Mk3 red dividing lines on a bailout (p.28) on a page that has lines; the Shearwater persistent red PPO2 box (Petrel 3 Tech p.24) on the loop.
3. Dive Profile Builder
- [x] Separate down / up setpoint switch depths, cells in the written logs, Garmin setpoint-switch alerts and no record PO2 in a CCR FIT, Petrel 3 in the computer list, setpoints and switch depths imported from a log.
4. Log Viewer
- [x] PO2, setpoint and cells in a strip under the profile and in the table, the circuit, bailout and setpoint events, a Rebreather line in the dive fields.
5. Pages
- [x] CCR: Petrel CC (setpoint) and CC (3 cells), Perdix 3 CC, Teric CC (Standard), Perdix 2 CC (assumed), Mk3i CCR (Big Numbers) and CCR (standard), X50i CCR and Dynamic depth (CCR).
- [x] Teric and Tern Standard; Mk3i standard, transceiver and gases; X50i dynamic depth (profile, ceiling, MAX, TTS).
- [x] Shearwater info screens, one page per info screen (owner 2026-10-20): every model, the screens the logs can drive (not LAST DIVE, Compass, TISSUES, DET / Δ+5 / @+5 / CEIL what-ifs, SERIAL).
- [x] Gauge mode pages (every Shearwater, Mk3i, X50i), with `avg_depth`, `min_temp`, no deco colours.
- [ ] Battery on the info / gauge pages: Shearwater XML / CSV log volts, UDDF a charge level, the Teric / Tern / X50i screens a percentage - a volts-to-percent conversion needs the battery type, which no log names.
- [ ] Info screens' small extras: the CONSERV level name (Low / Med / High) above the GFs, the battery type text, the TISSUES graph (needs a tissue-graph element), the Shearwater stopwatch's own start / reset (no log records it: the gauge stopwatch is the dive time).
- [ ] X50i dynamic depth's @+5 / Δ+5 / STOPS row and planned ascent; Mk3i tissue and ascent-rate arcs. Needs: what-if deco values for logs; an arc element.
- [ ] Freedive pages and compass pages. Needs: a freediving session parser and a real freedive log (section 3); a heading in a log (no format carries one).
- [x] Peregrine TX (2026-10-20): sidemount main and AI row, mini-display page, ascent arrows and N2 bar on every page; named "Peregrine TX" in the template list and the Builder.
- [x] Perdix 3 sidemount (2026-10-20): Tec page T1 | SurfGF | T2 with the switch box, Info: AI T1 | GTR / SM / SAC | T2.
- [x] Perdix 3 sidemount on the Main Screen and Standard pages (2026-10-21): a variant can carry its own skin (`"skin"` in the overlay); theirs has no T1 slot, MAX moves there and the AI row takes the info row.
- [ ] Peregrine TX extras: three or four transmitters on one row (T1-T4, p.41), RTR, Gas Density, the No Comms / Low Bat transmitter warnings (the readers drop the transmitter status), the am / pm clock. Needs: more than two tanks in the overlay; a real Peregrine TX export.
- [x] Fix `hud_rules_sources.md`: the Perdix 3 pages cited are printed pages (PDF page = printed + 2) - noted in the manuals table.

## 4. App and UI

- [ ] Sidebar renames agreed long ago, never shipped: Convertion → Resolution, Tag Editor → Exif Editor, Advanced → Settings.
- [ ] A visual pass over the pages that never got one (Resolution, Exif Editor, Settings, Color Tuning, Log Viewer, Dive Profile Builder, Activity, About); batch with the renames.
- [ ] Color page "Output filename" combo: scope what is wrong with the owner first.
- [ ] Light theme: never exercised.
- [ ] A What's New dialog per release, from the changelog, with a "show me" that opens the page.
- [ ] An update check.

## 5. Packaging and distribution

Signed and notarised macOS `.dmg` and `.pkg`, a Windows `.msi` and an
Ubuntu `.deb` ship with every release through the Release Build workflow,
with ffmpeg and exiftool bundled on all three. What is left:

- [ ] One recorded smoke test per installer on a clean machine with no ffmpeg, exiftool or perl installed: a colour run and a metadata write succeed, and the About screen names the bundled versions.
- [ ] Remove the two stale `# UNVERIFIED` comments on the Windows and Linux blocks in `pyproject.toml`.
- GUI-only Windows and Linux builds: see §1, step 6.

## 6. Tests and CI (`local_ci.md`)

- [ ] Local runners, phases 0 to 6: Gitea reachable and the pending pushes done; Linux runner; macOS host-mode runner; Windows VM with nightly rollback; the test-data share and a nightly Everything run with failure mail; ephemeral macOS clones; installer smoke builds.
- [ ] Owner decisions: macOS runner host, Windows licence, nightly time, whether `gitea_setup.md` folds into `local_ci.md`.
- [ ] Re-plan the three xfail Subsurface deco references with no dive before them.
- [ ] Dive Profile Builder: should a pinned gas on the last waypoint override the deco gas on End dive?

## 7. Mobile app (on hold since 2026-10-16)

A Flutter rewrite was investigated; the notes are local. Before it can
start: the mobile media-engine decision (an ffmpeg build on the phone
versus native engines), a check of the Dart FIT library against our logs,
golden fixtures generated from the Python code, and the four code issues
flagged there (sharpness dropped on video, blink never alternating, no
waypoint-match distance limit, dead Sony XMP mapping). Logs reach a phone
through the document picker and "open with", plus an in-app page with the
vendors' export recipes; downloading straight from the computer over
Bluetooth is a later milestone.
