# Dive Profile Builder

> [!CAUTION]
> **DO NOT USE THIS FOR DIVE PLANNING.** The Dive Profile Builder exists to make
> **test data for overlays** - a believable dive log you can render an overlay
> from without having done the dive. The deco model is a simplified Bühlmann
> ZHL-16C implementation that has not been validated against any real planner
> or dive computer. The page shows the same warning in red across the top.

The Dive Profile Builder lets you draw a dive on a chart, simulates it
(depth, gas, PO2, NDL / deco, CNS, tank pressure) and saves it as a dive log -
UDDF, Garmin FIT or Subsurface XML - as if it came from a real dive computer.
Open circuit, sidemount and CCR dives are supported. That log can then be
loaded anywhere UWMedia accepts a real one -
[Overlay Designer](overlay-designer.md), [Overlay Generator](overlay-generator.md),
[Log Viewer](log-viewer.md) or the [CLI](cli.md) `--render-log` option - to
check how an overlay behaves in situations that are hard to capture on a real
dive: deco, gas switches, high PO2, low tank pressure and so on.

## Quick start

1. Click anywhere in the chart. A popup asks for the **max depth** and
   **planned runtime** of the dive - this fixes the chart's scale so a click
   maps to a time and a depth. The waypoint is placed where you clicked.
2. Click to add more waypoints (e.g. the end of the bottom time).
3. Add any deco gases in the **Gases** panel with the depth range they're used
   in (e.g. EAN50 `0`-`21` m, *Ascent/deco*).
4. Press **End dive** - UWMedia adds the ascent: a safety stop, or the deco
   stops with gas switches.
5. Hover over the profile to check NDL, PO2, deco stops etc. at any point.
6. Under **Log details**, pick the dive computer and set the start time to
   match your photos and videos.
7. Press **Save log…** and pick a format.

## The chart

| Action | What it does |
|---|---|
| Click on empty space | Adds a waypoint. Time snaps to whole minutes, depth to whole metres. |
| Drag a waypoint | Moves it. It can't pass the waypoints either side of it. |
| Right-click a waypoint | Deletes it. |
| Click a waypoint | Loads it into the Waypoints editor. |
| Hover | Shows the details box for that point in the dive (see below). |

What you see on the chart:

- The **profile line** is drawn in each gas's colour, with a legend in the
  bottom-right corner.
- The **red shaded area** is the deco ceiling - the shallowest depth you could
  ascend to at that moment (at GF high).
- The **orange shaded area** is the planned deco stops: at each moment, every
  stop an ascent started right then would make, each shading the 3 m level
  above it - darker for longer stops. You can watch stops get added and
  deepen during the bottom time and clear on the way up.
- The **dashed line** is the max depth you entered.
- **Yellow dots** are the waypoints.

The time axis grows by itself when you place a point near its end. Max depth
and planned runtime can also be changed under *Dive settings*.

### Hover details

Moving the mouse over the profile shows, for that point: time, depth, gas,
PO2 (red if above your limit), CNS and tank pressure - every tank of the gas
being breathed, the one in use marked with ▸ on a sidemount dive, plus the O2
cylinder on a CCR loop. A CCR dive also shows the **loop** setpoint, or
*Bailout (OC)*. Then either:

- **NDL** when no deco is needed - how long you could stay at this depth
  before a stop becomes mandatory (the GF high ceiling reaching the surface),
  as a dive computer shows it. 18 m on air at GF 30/70 gives about 40 min - or
- the **ceiling** at GF high and at GF low, the full list of **deco stops**
  needed if you started the ascent right there (including gas switches), and
  the **TTS** (time to surface) for that ascent.

The two ceilings answer different questions. GF high is the shallowest depth
you could go to right now - it decides whether deco is needed at all, and is
the red area. GF low is more conservative and places the **first stop**
(rounded up to a 3 m level) - so the first stop is often deeper than the GF
high ceiling, e.g. ceiling `1.9 m (GF 70) · 4.6 m (GF 30)` with a first stop
at 6 m.

### How waypoints work

Between two waypoints the diver moves to the new depth at the default descent
or ascent rate (or the waypoint's own rate), then stays at that depth until
the waypoint's time. A waypoint therefore means "be at this depth at this
time".

## Dive settings

All of these are remembered between restarts.

| Setting | Meaning |
|---|---|
| Name | Name of the dive; the suggested file name when saving. |
| Dive type | *Open circuit*, *Sidemount* or *CCR* - see [Dive types](#dive-types). |
| GF Low / High | Gradient factors for the deco model (1-100, low ≤ high). |
| Descent / Ascent rate | Default speeds in m/min between waypoints. |
| Water temp | Temperature written into every sample. |
| SAC rate | Surface air consumption in L/min, used for every gas's tank pressure. |
| Max PO2 bottom / deco | The highest PO2 you accept on the bottom and on deco. Sets each gas's MOD. |
| Setpoint low / high, SP switch depth | CCR only - see [CCR](#ccr). |
| O2 cylinder (L / bar) | CCR only - size and start pressure of the O2 cylinder. |
| Switch tanks every (bar) | Sidemount only - see [Sidemount](#sidemount). |
| Max depth / Planned runtime | The chart's scale. |

## Dive types

### Open circuit

Each gas is breathed from its own tank.

### Sidemount

A sidemount dive needs two tanks of the same gas, one row each in the gas
table: one with **Side** set to *Left* and one set to *Right*, usually `T1` and
`T2`. Until both are there the chart stays empty, the status line says what is
missing, and Save log refuses. The dive starts on the left tank and switches
side whenever the one in use is *Switch tanks every* bar (default 30) below
the other, so the two stay balanced. Each tank has its own colour, and the
profile line takes the colour of the tank in use, so every side switch shows;
the legend lists both.

The two tanks count as one gas: waypoints, Auto and End dive pick the left
tank's gas, and the right tank is breathed as part of it, so it isn't offered
in the Waypoints editor. Changing the left or right tank's mix changes the
other's too, and a second Left or Right tank, or a right tank of a different
gas, is refused. Every other tank - e.g. a deco gas - is a *Stage*.

Switching the dive type to Sidemount puts the bottom gas on the left and fills
the gas editor in as its right-hand twin (named `<gas> R`, in the next free
tank), so one **Add** completes the pair. Saved logs record the pair as one
gas in two cylinders, as a sidemount dive computer does; logs saved by older
versions (tanks `T1L`/`T1R`) open as a left and a right tank.

### CCR

The gas ticked **Diluent (the loop)** is the rebreather loop: its PO2 is held
at the **low setpoint** (default 0.7) shallower than the **SP switch depth**
(default 6 m) and at the **high setpoint** (default 1.3) at and below it. Every
other gas is open-circuit **bailout**. Bailout is only used where you pick it
for a waypoint in the Waypoints editor - Auto always stays on the loop, and End
dive ascends on the loop without gas switches. Only one gas can be the diluent;
switching the dive type to CCR makes the first gas the diluent if none is.

The table's *Type* column shows `DIL` / `BAILOUT` on a CCR dive, and on a
sidemount dive the tank column shows each tank's side (`T1 Left`, `T2 Right`).

## Log details

What the saved file says about the dive beyond its profile. The computer and
serial are remembered between restarts; the start time is not.

| Setting | Meaning |
|---|---|
| Dive computer | The computer the log poses as - one per overlay template UWMedia ships (Garmin Descent Mk3i / X50i, Shearwater Perdix 2 / Perdix 3 / Petrel / Peregrine / Teric / Tern). |
| Serial number | Digits only. |
| Start | Local date and time the dive starts, `YYYY-MM-DD HH:MM`. Media is matched to a log by time, so set this to when your photos and videos were taken. Blank uses the time of saving. |

## Gases

Each gas has:

- **Name** and **type** (Air, Nitrox, Trimix), **O2 %** and **He %**.
- A **tank**: name, **volume** (L) and **start pressure** (bar). New gases get
  the next free tank name (T1, T2, …) and default to an AL80 (11.1 L, 207 bar).
  Give each gas its own tank - the saved log records pressures per tank.
- On a CCR dive, **Diluent (the loop)**; on a sidemount dive, **Sidemount
  pair (left/right)** - see [Dive types](#dive-types).
- A **depth range** (*Use from … to … m*) and a **phase**: *Any*,
  *Descent/bottom* or *Ascent/deco*. These decide where the gas is picked
  automatically (see below).
- A **colour** for the profile line. Click the swatch in the table to change
  it, or the swatch next to the type box before adding.

Click a row to select it and edit it with **Update** (renaming is fine -
waypoints follow). **New** clears the selection so **Add** creates a new gas.
**Remove** deletes the selected gas.

The **MOD** column shows each gas's maximum operating depth at your *Max PO2
deco* for Ascent/deco gases and *Max PO2 bottom* for the rest.

### Automatic gas choice

Waypoints you place on the chart use **Auto** gas: at each waypoint UWMedia
picks the gas whose depth range and phase cover it and whose MOD allows it.

- A gas **with a range** beats one without; a gas without a range is the
  fallback everywhere.
- A gas set to the current **phase** beats an *Any* gas.
- Among equals, the **richest** in oxygen wins.
- The **ascent** phase is everything after the first time the dive reaches
  its deepest point. Ascent/deco gases are never picked on the way down.

Example - Air (no range), EAN50 `0-21 m` Ascent/deco, O2 `0-6 m` Ascent/deco:
Air on the descent and bottom, EAN50 from 21 m on the way up, O2 from 6 m.

If no gas can be used at a waypoint's depth (e.g. deeper than every MOD), it
stays on the previous gas and the status line warns about it. To force a gas,
pick it in the Waypoints editor instead of *Auto*; you get a warning if it's
breathed deeper than its MOD.

## End dive

**End dive** adds the ascent from the last waypoint to the surface at the
default ascent rate:

- **No deco needed** → a **3 m / 3 min safety stop**, then the surface.
- **Deco needed** → the deco stops for your GF settings: on 3 m levels (last
  stop at 3 m), each held until the next level is clear, rounded up to whole
  minutes. The GF moves from GF low at the first stop to GF high at the
  surface. The 3 m stop is never shorter than the 3 minute safety stop, even
  when a deco gas clears the deeper stops on the way up.
- **Gas switches** happen as soon as a deco gas's range and MOD allow it, with
  a **1 minute hold** at each switch. A switch at a stop depth counts towards
  that stop.

The result is shown under the button, e.g.
`Deco ascent added: 21m 1min EAN50, 12m 1min, 9m 2min, 6m 3min O2, 3m 3min - surfacing at 39:27`.
The new waypoints can be moved or deleted like any other.

## Gas consumption

Tank pressure drops by `SAC × ambient pressure ÷ tank volume` bar per minute,
so a minute at 20 m (about 3 bar) uses three times as much as at the surface.
For example 20 L/min on an AL80 for 10 min at 20 m uses 54 bar. Gas is treated
as an ideal gas.

On a CCR loop the diluent is drawn at a rough 1 L/min × ambient pressure
(loop top-ups), and the O2 cylinder at 1 L/min whatever the depth (what the
diver metabolises). Bailout is breathed like open circuit.

## Saving

**Save log…** simulates the dive at one-second resolution and writes it in
the format you pick in the save dialog (a typed `.uddf`, `.fit` or `.ssrf`
extension picks it too):

| Format | Modelled on | Notes |
|---|---|---|
| UDDF (`.uddf`) | a Shearwater Cloud export | Every tank's pressure on every sample, gas switches, PO2 and CCR setpoint, CNS, dive mode, deco/NDL, UTC offset. |
| Garmin FIT (`.fit`) | a Garmin Descent export | Garmin computers only. Tanks are tank pods (serials 100001, 100002, … in tank order, named by tank in the file), so an overlay reads them as primary/secondary tank or by those serials - map them to names in `config.yaml` like a real transmitter. |
| Subsurface XML (`.ssrf`) | a Subsurface divelog | One cylinder per tank (named by tank), gas and sidemount tank switches as gas changes, CCR as `dctype='CCR'` with O2/diluent cylinders. |

The saved log's deco data is what a dive computer would show while diving:
the next stop (from GF low, whole minutes, at least 1 min) on the gas being
breathed - it doesn't know about gas switches still to come, unlike End
dive's plan.

Each file names the chosen dive computer the way that computer's own exports
do, and the dive starts at the *Start* time in your computer's time zone.
The files are meant for UWMedia - other logbook apps may read them, but that
isn't tested.

Gases and waypoints are not kept between restarts - save the log when you're
done. The dive settings are kept.

Every saved log also carries the plan itself (gases, waypoints and all the
dive settings), tucked into the format's own slot for application data:
UDDF `<applicationdata>`, a Subsurface `<extradata>` entry, FIT developer
fields. Other software ignores it; **Open log…** uses it.

## Opening a saved log

**Open log…** loads a log the Dive Profile Builder saved, so you can change
it and save it again. Only such logs are accepted - a log from a real dive
computer, or from another program, is refused with a message, since the
builder can only re-plan a dive it built.

- A log saved with the plan inside comes back exactly as it was saved:
  waypoints, gases, GF, SAC, PO2 limits, start time, dive computer - everything.
- A log saved by an earlier UWMedia (before the plan was embedded) is rebuilt
  from what the file holds: gases and tanks, gas switches, GF and the dive
  computer come back as saved, the depth profile is reduced to the few dozen
  waypoints that reproduce it, and settings a log doesn't hold (SAC, ascent
  and descent rates, gas depth ranges) stay as they are in the pane. Check
  the waypoints before saving again - the message under the buttons says
  which of the two happened.

Opening a log replaces the plan in the editor; there is no merge.
