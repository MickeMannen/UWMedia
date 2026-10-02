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
**Clear** empties it. Neither touches the files: the Log Viewer never writes
anything.

## Tank sensors

The **Tanks / sensors** table shows the serial number of each Garmin tank
transmitter next to its name. Give them friendly names (e.g. "Left",
"Stage") under [Advanced → Sensor names](advanced.md#sensor-names) so
overlays show the name instead of the serial.

CLI equivalent: `--export-json DIR` writes each parsed log as JSON - see [CLI](cli.md).
