# Log Viewer

Browse your dive logs the way UWMedia reads them - to check what an overlay
will show before rendering.

Supported logs: **Garmin** `.fit`, **Shearwater** `.uddf`, **Subsurface**
`.xml`/`.ssrf` (and logs from the [Dive Profile Builder](dive-profile-builder.md)).

## Using it

1. **Select Log Directory**.
2. Pick a **Dive**. The **Dive summary** shows the device, start and end
   time, duration, max depth, number of samples, and the GPS position and
   timezone when the log has them.
3. The table lists every sample: time, depth, temperature, NDL, TTS, gas and
   tank pressures. **Filter** narrows it down.

## Tank sensors

**Tank sensors found** lists the serial numbers of Garmin tank transmitters in
the log. Give them friendly names (e.g. "Left", "Stage") under
[Advanced → Sensor names](advanced.md#sensor-names) so overlays show the name
instead of the serial.

CLI equivalent: `--export-json DIR` writes each parsed log as JSON - see [CLI](cli.md).
