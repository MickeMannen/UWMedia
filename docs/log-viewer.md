# Log Viewer

Browse your dive logs the way UWMedia reads them - to check what an overlay
will show before rendering.

Supported logs: **Garmin** `.fit`, **Shearwater** `.uddf`, **Subsurface**
`.xml`/`.ssrf`/`.csv`, **Shearwater Cloud** `.xml`/`.csv` exports (and logs
from the [Dive Profile Builder](dive-profile-builder.md)).

## Using it

1. **Open files…** or **Open folder…**. The dives of every log are added to
   the **Dives** list, sorted by start time. Opening more adds to the list;
   a dive that is already there is skipped. A file that can't be read is
   named in a warning at the top. The dialogs open in the folder you used
   last.
2. Click a dive (or move with ↑/↓). The **Dive** card shows what the log
   holds - fields it doesn't have are left out:
   - start, end, time zone, duration, max and average depth, water
     temperature, dive computer and the GPS positions;
   - **Tanks / sensors**: each tank or transmitter with its mix and its start
     and end pressure;
   - the **depth profile** (with the deco ceiling when the log has one);
   - which data the log carries ("logged: NDL, TTS, ppO₂, heart rate…");
   - **Events**: dive alerts and gas changes, at their dive time.
3. **Samples** → **Show** opens the full sample table: time, depth,
   temperature, NDL, TTS, gas and tank pressures. **Filter** narrows it down.

**Remove** (or Delete / Backspace) takes the selected dive off the list and
**Clear** empties it. Neither touches the files.

## Adjust time (Garmin)

If your Garmin's clock was wrong before a dive (not yet synced after a
battery change or a trip), the log's times won't match your photos and
videos. Select the dive and click **Adjust time…** at the top of its **Dive**
card:

- **Start (local time)**: when the dive really started, in the dive site's
  local time, e.g. `2026-03-05 14:23:07`.
- **Time zone (UTC offset)**: the dive site's time zone, e.g. `+07:00` or
  `-05:30`.

**Save** asks where to put the corrected copy (it suggests
`<name> (adjusted).fit` next to the original) and adds it to the list. Every
sample moves by the same amount and all other data stays as logged; the
original file is never changed. This is for Garmin `.fit` logs only.

## Merge dives (Garmin)

Sometimes a dive computer splits one dive into two logs: a short surface
stop ends the first log and a second one starts when you descend again.
Open both logs, select the first dive and click **Merge…** at the top of
its **Dive** card (it is enabled when a later Garmin dive in the list starts
within 2 hours of the selected one's end):

- **Merge with**: the later dive, when there is more than one to choose from.
- **Keep the real times**: the second dive's samples keep their clock times
  and the surface interval is filled with the first dive's last sample.
  Photos and videos from both dives still line up with the merged log, and
  the dive time runs on through the interval.
- **Close the gap**: the second dive moves back so it follows the first
  without a break, as one continuous dive. Its photos and videos no longer
  match the log.

**Save** asks where to put the merged log (it suggests `<name> (merged).fit`
next to the first one) and adds it to the list. The merged dive starts when
the first did and ends when the second did, lists the gases of both, carries
the tank readings of both and the GPS, heart rate and other data Garmin
logged. The original files are never changed. Garmin `.fit` logs only.

Garmin Connect treats the merged log as the first dive (same start time and
device), so delete both original dives there before uploading it.

## Tank sensors

The **Tanks / sensors** table shows the serial number of each Garmin tank
transmitter next to its name. Give them friendly names (e.g. "Left",
"Stage") under [Advanced → Sensor names](advanced.md#sensor-names) so
overlays show the name instead of the serial.

CLI equivalent: `--export-json DIR` writes each parsed log as JSON - see [CLI](cli.md).
