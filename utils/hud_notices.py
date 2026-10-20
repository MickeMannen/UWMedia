"""Device notifications an overlay can show: the messages a dive computer
puts on its screen (a Perdix's yellow "FAST ASCENT" across the bottom row,
a Teric's "MISSED STOP" banner, a Descent's "Approaching NDL" alert).

Which messages exist, their exact wording and what triggers them come from
each brand's `notices` list in hud_rules.json (every entry cites its manual
page in hud_rules_sources.md); the list order is the priority order, and
only the highest-priority active notice is shown, as on the devices.

A real computer keeps a notification up until a button is pressed; a log
does not record that press, so a notice stays on the overlay for
`show_seconds` after it triggers (the brand's `notice_style.show_seconds`,
10 s unless set) - an assumption, documented in hud_rules_sources.md.

Conditions (`when`), with their parameters:
  fit_alert           alert: the Garmin FIT dive_alert name on the waypoint
  tank_critical       the tank pressure is below the critical pressure
                      (tank_reserve rule); {tank} in the text is its name
  stop_violation      shallower than the deco stop (or the ceiling) for
                      `seconds`
  po2_above           po2 above `bar` for `seconds`
  po2_below           po2 below `bar`
  cns_at_least        CNS at or above `percent`
  ascent_faster_than  ascent faster than `m_per_min` for `seconds`
  ndl_at_most         NDL at or below `minutes` (not in deco); re-arms once
                      the NDL is `rearm_minutes` above it again
  depth_deeper_than   deeper than `metres`; re-arms `rearm_m` shallower
  time_longer_than    dive time longer than `minutes` (once per dive)
  deco_required       the HUD state becomes 'deco'
  deco_cleared        the HUD state leaves 'deco'
  safety_started      the safety stop starts counting
  safety_complete     the safety stop countdown ends
  mod_exceeded        deeper than the breathed gas's MOD (utils.hud_gas)
  sidemount_switch    the two sidemount tanks differ by more than the
                      brand's sidemount_switch threshold; {tank} is the
                      one to breathe from (Descent "Breathe from %1.")
  near_mod            within `metres` above the MOD
  setpoint_up         a rebreather's setpoint rises (Teric "Auto SP Up")
  setpoint_down       a rebreather's setpoint falls
Any entry may name `circuits` (["CC", "SC"], ["OC", "BO"]): it only holds
while the waypoint's circuit (models.dive.Waypoint.circuit; a log that
names none counts as "OC") is one of them - a Shearwater's PPO2 limits on
the loop are CC Min / Max, on open circuit the OC ones.
An entry with "enabled": false is kept for the record (a device alert that
is off by default) and never fires.

A brand's `persistent_notices` list (Perdix 2 manual p.23: shown left of the
NDL for as long as the condition lasts - MOD exceeded, Near MOD, High CNS)
uses the same conditions but never times out; a notice element with
"source": "persistent" shows the first one that holds.
"""
from typing import Any, Dict, List, Optional, Tuple

from utils.hud_rules_engine import (
    _cached_timeline,
    _num,
    deco_stop_phase,
    get_rule_config,
    is_annotation_key,
    resolve_state,
    safety_stop_phase,
    tank_pressure_state,
)

DEFAULT_SHOW_SECONDS = 10
_INSTANT = {"fit_alert", "tank_critical", "po2_below", "cns_at_least", "ndl_at_most", "depth_deeper_than", "time_longer_than"}


def notice_rules(manufacturer: Optional[str], model: Optional[str]) -> List[Dict[str, Any]]:
    """The brand's (or model's) `notices` list, annotation entries left out."""
    rules = get_rule_config(manufacturer, model, "notices")
    if not isinstance(rules, list):
        return []
    return [r for r in rules if isinstance(r, dict) and r.get("id") and r.get("text") and r.get("enabled", True)]


def notice_style(manufacturer: Optional[str], model: Optional[str]) -> Dict[str, Any]:
    """How the brand draws a notice: `style` ("text": the message in its colour
    under a caption, Perdix; "banner": a filled band with black text, Teric),
    `color`, `caption_color`, `text_color`, `confirm_text`, `show_seconds`."""
    style = get_rule_config(manufacturer, model, "notice_style")
    return {k: v for k, v in style.items() if not is_annotation_key(k)} if isinstance(style, dict) else {}


def _format(text: str, context: Dict[str, Any]) -> str:
    out = text
    for key, value in context.items():
        out = out.replace("{" + key + "}", str(value))
    return out


def _render(rule: Dict[str, Any], style: Dict[str, Any], context: Dict[str, Any], since: int) -> Dict[str, Any]:
    return {
        "id": rule["id"],
        "text": _format(str(rule["text"]), context),
        "caption": rule.get("caption", ""),
        "color": rule.get("color") or style.get("color", "#FFFF00"),
        "text_color": rule.get("text_color") or style.get("text_color"),
        "icon": rule.get("icon") or style.get("icon"),  # box style: "none" drops the warning triangle (Descent "Breathe from")
        "since": since,
    }


def _ascent_rate(wp: Any, prev: Any) -> Optional[float]:
    rate = _num(getattr(wp, "ascent_rate", None))
    if rate is not None:
        return rate
    if prev is None:
        return None
    d0, d1 = _num(getattr(prev, "depth", None)), _num(getattr(wp, "depth", None))
    t0, t1 = _num(getattr(prev, "time_since_start", None)), _num(getattr(wp, "time_since_start", None))
    if None in (d0, d1, t0, t1) or t1 <= t0:
        return None
    return (d0 - d1) / (t1 - t0) * 60.0


def _critical_tank(manufacturer, model, wp) -> Optional[str]:
    tanks = getattr(wp, "tanks", None) or {}
    for name, tank in tanks.items():
        if tank_pressure_state(manufacturer, model, getattr(tank, "pressure_bar", None)) == "critical":
            return str(name)
    return None


def _condition_now(rule: Dict[str, Any], manufacturer, model, wp, prev, waypoints) -> Tuple[bool, Dict[str, Any]]:
    """(true now, text context) for the conditions that can be read off one
    waypoint; duration and edge conditions are handled by the timeline."""
    when = rule.get("when")
    ctx: Dict[str, Any] = {}
    circuits = rule.get("circuits")
    if circuits and (getattr(wp, "circuit", None) or "OC") not in circuits:
        return False, ctx
    if when in ("setpoint_up", "setpoint_down"):
        now_sp, prev_sp = _num(getattr(wp, "setpoint", None)), _num(getattr(prev, "setpoint", None)) if prev is not None else None
        if now_sp is None or prev_sp is None:
            return False, ctx
        ctx["setpoint"] = f"{now_sp:.1f}"
        return (now_sp > prev_sp) if when == "setpoint_up" else (now_sp < prev_sp), ctx
    cns = _num(getattr(wp, "cns", None))
    if cns is not None:
        ctx["cns"] = int(cns)  # "{cns}" in a text (Garmin "CNS toxicity at %1%.")
    stop = _num(getattr(wp, "next_stop_depth", None)) or _num(getattr(wp, "deco_stop_depth", None))
    if stop:
        from utils import units as U
        ctx["stop"] = f"{U.stop_depth(stop):.0f} {U.depth_label()}"  # Garmin X50i "DESCEND TO %1"
    if when == "fit_alert":
        return rule.get("alert") in set(getattr(wp, "dive_alerts", None) or []), ctx
    if when == "tank_critical":
        tank = _critical_tank(manufacturer, model, wp)
        if tank is not None:
            ctx["tank"] = tank
        return tank is not None, ctx
    if when == "po2_below":
        po2 = _num(getattr(wp, "po2", None))
        return po2 is not None and po2 < float(rule.get("bar", 0.18)), ctx
    if when == "po2_above":
        po2 = _num(getattr(wp, "po2", None))
        return po2 is not None and po2 > float(rule.get("bar", 1.61)), ctx
    if when == "cns_at_least":
        return cns is not None and cns >= float(rule.get("percent", 90)), ctx
    if when == "ascent_faster_than":
        rate = _ascent_rate(wp, prev)
        return rate is not None and rate > float(rule.get("m_per_min", 10)), ctx
    if when == "ndl_at_most":
        ndl = _num(getattr(wp, "ndl", None))
        if ndl is None or ndl <= 0:
            return False, ctx
        if resolve_state(manufacturer, model, wp, waypoints) == "deco":
            return False, ctx
        return ndl <= float(rule.get("minutes", 5)) * 60.0, ctx
    if when == "depth_deeper_than":
        depth = _num(getattr(wp, "depth", None))
        return depth is not None and depth > float(rule.get("metres", 40)), ctx
    if when == "time_longer_than":
        t = _num(getattr(wp, "dive_time", None))
        if t is None:
            t = _num(getattr(wp, "time_since_start", None))
        return t is not None and t > float(rule.get("minutes", 60)) * 60.0, ctx
    if when in ("mod_exceeded", "near_mod"):
        from utils.hud_gas import mod_metres
        mod = mod_metres(manufacturer, model, wp)
        depth = _num(getattr(wp, "depth", None))
        if mod is None or depth is None:
            return False, ctx
        from utils import units as U
        ctx["mod"] = f"{U.depth(mod):.0f}{U.depth_label()}"  # "34m" / "112ft" in the system in force
        if when == "mod_exceeded":
            return depth > mod, ctx
        return mod - float(rule.get("metres", 1.9)) <= depth <= mod, ctx
    if when == "stop_violation":
        return deco_stop_phase(manufacturer, model, wp) in ("violation", "ceiling_violation"), ctx
    if when == "sidemount_switch":
        from utils.hud_rules_engine import sidemount_switch_target
        target = sidemount_switch_target(manufacturer, model, wp)
        if target is None:
            return False, ctx
        tanks = list((getattr(wp, "tanks", None) or {}).items())
        key, tank = tanks[0 if target == "primary" else 1]
        ctx["tank"] = getattr(tank, "name", None) or key
        return True, ctx
    if when in ("deco_required", "deco_cleared"):
        return resolve_state(manufacturer, model, wp, waypoints) == "deco", ctx
    if when in ("safety_started", "safety_complete"):
        phase = safety_stop_phase(manufacturer, model, wp, waypoints)
        phase = phase[0] if phase else None
        return (phase == "complete") if when == "safety_complete" else (phase in ("counting", "warn")), ctx
    return False, ctx


def _rearmed(rule: Dict[str, Any], manufacturer, model, wp, prev, waypoints) -> bool:
    """For the latched conditions: has the situation gone away enough for the
    device to raise the alert again?"""
    when = rule.get("when")
    if when == "ndl_at_most":
        ndl = _num(getattr(wp, "ndl", None))
        return ndl is not None and ndl >= (float(rule.get("minutes", 5)) + float(rule.get("rearm_minutes", 3))) * 60.0
    if when == "depth_deeper_than":
        depth = _num(getattr(wp, "depth", None))
        return depth is not None and depth < float(rule.get("metres", 40)) - float(rule.get("rearm_m", 2))
    if when in ("cns_at_least", "time_longer_than"):
        return False  # once per dive
    now, _ = _condition_now(rule, manufacturer, model, wp, prev, waypoints)
    return not now


def _build_timeline(manufacturer, model, waypoints) -> Dict[int, Optional[Dict[str, Any]]]:
    rules = notice_rules(manufacturer, model)
    style = notice_style(manufacturer, model)
    default_show = int(style.get("show_seconds", DEFAULT_SHOW_SECONDS))
    timeline: Dict[int, Optional[Dict[str, Any]]] = {}
    if not rules:
        return timeline
    # Per rule: armed (may fire), since (condition first true, for durations),
    # until (display end), ctx (text substitutions at trigger time).
    state = [{"armed": True, "since": None, "until": -1, "ctx": {}} for _ in rules]
    prev = None
    for wp in waypoints:
        t = int(getattr(wp, "time_since_start", 0) or 0)
        for rule, st in zip(rules, state):
            now, ctx = _condition_now(rule, manufacturer, model, wp, prev, waypoints)
            when = rule.get("when")
            edge = when in ("deco_required", "deco_cleared", "safety_started", "safety_complete", "setpoint_up", "setpoint_down")
            if edge:
                # fires on the transition into (or, for the *_cleared / complete kinds, out of) the condition
                into = when in ("deco_required", "safety_started", "safety_complete", "setpoint_up", "setpoint_down")
                fired = (now and not st["ctx"].get("_was")) if into else (not now and st["ctx"].get("_was"))
                st["ctx"]["_was"] = now
                if fired and (when != "deco_cleared" or prev is not None):
                    st["until"] = t + int(rule.get("show_seconds", default_show))
                    st["ctx"].update(ctx)
                continue
            if not now:
                st["since"] = None
                if not st["armed"] and _rearmed(rule, manufacturer, model, wp, prev, waypoints):
                    st["armed"] = True
                continue
            if st["since"] is None:
                st["since"] = t
            held = t - st["since"]
            needed = float(rule.get("seconds", 0)) if when in ("po2_above", "ascent_faster_than", "stop_violation") else 0.0
            if st["armed"] and held >= needed:
                st["armed"] = False
                st["until"] = t + int(rule.get("show_seconds", default_show))
                st["ctx"].update(ctx)
        active = None
        for rule, st in zip(rules, state):
            if st["until"] > t:
                active = _render(rule, style, {k: v for k, v in st["ctx"].items() if not k.startswith("_")}, st["until"] - int(rule.get("show_seconds", default_show)))
                break
        timeline[t] = active
        prev = wp
    return timeline


def notice_timeline(manufacturer: Optional[str], model: Optional[str], waypoints: Optional[List[Any]]) -> Optional[Dict[int, Optional[Dict[str, Any]]]]:
    """{time_since_start: notice or None} for the whole dive, cached per
    waypoint list like the other timelines."""
    if not waypoints:
        return None
    return _cached_timeline("notice", manufacturer, model, waypoints, lambda: _build_timeline(manufacturer, model, waypoints))


def persistent_notice_rules(manufacturer: Optional[str], model: Optional[str]) -> List[Dict[str, Any]]:
    rules = get_rule_config(manufacturer, model, "persistent_notices")
    if not isinstance(rules, list):
        return []
    return [r for r in rules if isinstance(r, dict) and r.get("id") and r.get("text") and r.get("enabled", True)]


def active_persistent_notice(manufacturer: Optional[str], model: Optional[str], waypoint: Any, waypoints: Optional[List[Any]] = None) -> Optional[Dict[str, Any]]:
    """The persistent notification the computer would be showing now: the
    first `persistent_notices` entry whose condition holds at `waypoint`
    (no history, no time-out - it stays while the situation lasts)."""
    if waypoint is None:
        return None
    style = notice_style(manufacturer, model)
    for rule in persistent_notice_rules(manufacturer, model):
        now, ctx = _condition_now(rule, manufacturer, model, waypoint, None, waypoints)
        if now:
            return _render(rule, style, ctx, int(getattr(waypoint, "time_since_start", 0) or 0))
    return None


def active_notice(manufacturer: Optional[str], model: Optional[str], waypoint: Any, waypoints: Optional[List[Any]] = None) -> Optional[Dict[str, Any]]:
    """The notice the computer would be showing at `waypoint`: from the dive's
    timeline when the whole dive is at hand, otherwise from what this one
    waypoint says (the conditions that need no history; the Overlay Designer's
    forced states use this)."""
    if waypoint is None:
        return None
    timeline = notice_timeline(manufacturer, model, waypoints)
    if timeline is not None:
        return timeline.get(int(getattr(waypoint, "time_since_start", 0) or 0))
    style = notice_style(manufacturer, model)
    for rule in notice_rules(manufacturer, model):
        if rule.get("when") not in _INSTANT and rule.get("when") not in ("po2_above", "ascent_faster_than", "stop_violation", "mod_exceeded", "near_mod"):
            continue
        now, ctx = _condition_now(rule, manufacturer, model, waypoint, None, None)
        if now:
            return _render(rule, style, ctx, int(getattr(waypoint, "time_since_start", 0) or 0))
    return None
