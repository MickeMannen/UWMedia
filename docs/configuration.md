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
NDL turning yellow below 5 min, PO2 red from 1.6, tank pressure red below
60 bar, and how each computer shows its safety and deco stops:

```json
{
  "Shearwater": {
    "ndl": [ { "max": 5, "color": "#FFFF00" }, { "min": 5, "color": "#FFFFFF" } ],
    "ndl_zero": "#FF0000",
    "po2": [ { "min": 1.6, "color": "#FF0000" } ],
    "safety_stop": { "trigger_max_depth": 11.0, "duration_sec": 180, "start_below": 6.0,
                     "count_range": [2.4, 8.3],
                     "adapt": { "deep_m": 30.0, "low_ndl_sec": 300, "duration_sec": 300 } },
    "deco_stop": { "approach_m": 5.1, "at_stop_m": 1.5 },
    "deco_clear": { "count_up": true },
    "badge_states": {
      "safety_stop": { "label": "SAFETY STOP", "color": "#00ADED", "value_color": "#FFFFFF",
                       "counting_color": "#00C800", "paused_value_color": "#FFFF00",
                       "check_mark": true, "show_depth": false, "timer_format": "m:ss",
                       "value_align": "center" },
      "deco": { "label": "DECO STOP", "color": "#FF0000", "value_color": "#FFFFFF",
                "approach_color": "#FFFF00", "at_stop_color": "#00C800",
                "check_mark": true, "inline": true, "timer_format": "min" },
      "clear": { "label": "CLEAR", "color": "#00C800", "value_color": "#FFFFFF" }
    },
    "Perdix 2": {
      "tank_pressure": [ { "max": 60, "color": "#FF0000" } ]
    }
  }
}
```

The safety-stop rule comes in two dialects: Shearwater's (`start_below`,
`count_range`, `adapt`: the counter shows the planned time from
`trigger_max_depth` on, counts down under `start_below` while inside
`count_range`, pauses outside it) and Garmin's (`stop_depth`,
`start_window`, `pause_above`: shown only while counting). `deco_stop`
sets where the stop title turns yellow (approaching) and green with a
check mark (at the stop); `deco_clear` adds the count-up shown after the
last stop. A `badge_states` entry styles the stop badge for a state: a
`<phase>_color` recolours the title in that phase (pending, counting,
paused, complete, approach, at_stop, violation), `value_color` the depth
and timer lines, `inline` puts "6m↑ 2min" on one line, `show_depth: false`
drops the depth line, `check_mark` adds ✓ while counting or at the stop,
and `timer_format` is `m:ss`, `mm:ss` or `min`. `<phase>_value_color` and
`<phase>_value_text` restyle or replace the timer in a phase (the Teric's
green "CLEAR"), `<phase>_label` swaps the title (the Perdix 3's "PAUSED")
and `title_box` draws the title in a filled box of its colour with black
text. `value_align: "center"` centres the timer under the title, the way
a Perdix shows the safety-stop time under "SAFETY STOP"; an element's own
`value_align` key overrides it. A label of `""` draws no title (the
Descent Mk3 style).

`sidemount_switch` (`threshold_bar`, `color`, `text_color`) is the Perdix's
tank-switch notification: a text element with `"tank_switch_highlight":
"primary"` or `"secondary"` gets a filled box behind it while that tank is
the one to breathe from, i.e. holds more than the threshold above the other.

`ascent_rate` bands colour a lit ascent chevron by m/min (`blink: true`
flashes the band's colour against the unlit grey - the Perdix's red), and
`ascent_chevrons` (`up_count`, `down_count`, `bar`, `m_per_min_per_chevron`)
is the brand's indicator shape: the Perdix 2's six arrows with no bar, one
arrow per 3 m/min, against Garmin's four over a bar with one below.

A rule is looked up in the computer's own section first, then the brand's,
then the brand's `default` section, then a top-level `default` section.
`badge_states` is the one rule that merges instead: a computer's entry only
lists the keys that differ from the brand's (the Teric says `"label":
"SAFETY"` and `"check_mark": null` over the Perdix family's "SAFETY STOP"
with its check mark). Templates saved under a computer in the
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
