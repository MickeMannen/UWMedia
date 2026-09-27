# Configuration files

UWMedia ships default versions of these files. `color.yaml` and
`config.yaml` are saved as your own copies in the app's data folder (see
[Getting started](getting-started.md#where-your-files-live)), which take
precedence, so updates never overwrite your changes. `hud_rules.json` is read
from the app's own files (or the working folder when running from source).

## color.yaml

The colour-correction profiles. Each top-level key is a profile name
(`default`, `vivid`, `subtle`, …) with the parameters the
[Color Tuning](color-tuning.md) sliders edit:

```yaml
default:
  cifval: 1.0          # Blend Weight
  red_threshold: 0.3
  red_scale: 0.2
  blue_threshold: 0.3
  blue_scale: 0.6
  # ... white balance, de-haze, exposure and hue parameters ...
  sharpness: 0.47
  darkness: -0.26
```

The easiest way to edit it is Color Tuning's **Save Profile** / **Save As
New**. Use a profile with `--color <name>` or the Color page's profile list.

## hud_rules.json

Colour and warning rules for overlays, per brand and per dive computer - e.g.
NDL turning yellow below 30 min and red below 10, PO2 red from 1.6, tank
pressure red below 60 bar, and when to show the safety-stop badge:

```json
{
  "Shearwater": {
    "ndl": [
      { "max": 10, "color": "#FF0000" },
      { "min": 10, "max": 30, "color": "#FFFF00" },
      { "min": 30, "color": "#FFFFFF" }
    ],
    "po2": [ { "min": 1.6, "color": "#FF0000" } ],
    "safety_stop": { "text": "SAFETY STOP", "color": "#FFFF00",
                     "trigger_max_depth": 10.0, "min_depth": 3.0, "max_depth": 6.0 },
    "Perdix 2": {
      "tank_pressure": [ { "max": 60, "color": "#FF0000" } ]
    }
  }
}
```

A rule is looked up in the computer's own section first, then the brand's,
then the brand's `default` section, then a top-level `default` section. Templates saved under a computer in the
[Overlay Designer](overlay-designer.md) use that computer's rules.

## config.yaml

Friendly names for Garmin tank transmitters, keyed by serial number:

```yaml
tanks:
  "2504425624": "Left"
  "3578142604": "Right"
```

Edit it on [Advanced → Sensor names](advanced.md#sensor-names), or create it
from a log folder with the CLI's `--create-config`.

## settings.json

Written by the app itself - you normally don't edit it. It holds the folder
and tool paths from [Advanced](advanced.md), your custom filename formats,
and the last-used value of form fields (source/output folders, the Dive
Profile Builder's dive settings, …) so they're filled in next time.
