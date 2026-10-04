# Deco reference dives

Subsurface planner output that our deco model (`utils/deco_engine.py`, `utils/dive_plan_engine.py`) is checked against. Every dive here runs in `tests/test_deco_reference.py`.

## Adding a dive

1. Plan the dive in Subsurface with **no dive before it** in the logbook: an empty logbook, or a date far from your other dives. If the plan's title says "surface interval", it may carry tissue loading from an earlier dive and is refused unless a `surface_interval_ok` line says why it can be used.
2. Copy the plan text and paste it, unchanged, into `raw/<name>.txt`. Name it by dive type, gases and settings, e.g.
   - `oc_air_40m30_ean50at15_gf30-75.txt`
   - `oc_trimix_60m20_ean50_o2_gf30-70.txt`
3. Optionally put `key: value` lines above the paste:

   ```
   notes: last stop 3 m, Subsurface defaults otherwise
   ascent_rate: 9
   known_gap: Subsurface switches to EAN50 at 21 m, we can't yet
   tolerance_stop_min: 3
   ```

   Allowed keys:
   - `name`, `notes`
   - `ascent_rate`, `descent_rate`
   - `known_gap`
   - `surface_interval_ok`
   - `tolerance_first_stop_m`, `tolerance_stop_min`, `tolerance_runtime_pct`

4. Convert and compare:

   ```
   python scripts/deco_reference.py convert
   python scripts/deco_reference.py compare
   ```

   `convert` writes `<name>.json`: the dive's gases, bottom and Subsurface's schedule. `compare` prints Subsurface's stops next to ours.

## What is compared

The rows before Subsurface's first ascent (➚) are the bottom. After it, stop rows (-) are deco stops and a level row (➙) is the no-deco safety stop.

Our planner gets the same bottom, GF and gases. Like Subsurface, it goes in a straight line between the bottom's waypoints: a 30 m row 40 minutes after a 15 m row is a 40-minute slope, not a descent and a hold. Each later gas is picked up on the ascent at the depth where Subsurface switched to it.

A dive matches when all three hold (defaults in brackets):
- the first stop is within `tolerance_first_stop_m` of Subsurface's (3 m);
- every stop depth's time is within `tolerance_stop_min` (2 min);
- the total runtime is within `tolerance_runtime_pct` (10 %).

A dive with `known_gap` is expected to fail until the gap is fixed. The test fails when such a dive starts matching, so the line gets removed.

## Subsurface port

`scripts/subsurface_port.py` is a Python port of Subsurface's Bühlmann planner, for single-gas air and nitrox dives. `tests/test_deco_reference.py` checks that our planner matches it on every reference dive's bottom, with fresh tissues. When our planner matches the port but not the pasted plan, the pasted plan is what's different, for example an earlier dive in Subsurface's logbook. To see all three side by side:

```
python scripts/deco_reference.py port
```

Only open-circuit Bühlmann ZHL-16C plans with one bottom gas are supported so far.
