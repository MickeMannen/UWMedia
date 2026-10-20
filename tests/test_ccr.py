"""Rebreather (CCR) support outside the parsers: the Waypoint's circuit,
diluent PO2 and breathed gas, the dive-level CCR flag and page variant,
the CC colour rules (loop PPO2 limits, cell voting, DilPO2, setpoint high /
low, CC / BO badges, a Garmin's red bailout gas), the notices on the loop
and the loop-aware deco recompute. Manual pages: hud_rules_sources.md;
values are invented."""
from datetime import datetime, timedelta

import pytest

from models.dive import Dive, TankData, Waypoint
from utils.deco_engine import DiveDecompressor, GasDefinition
from utils.hud_gas import gas_o2_fraction
from utils.hud_notices import notice_timeline
from utils.hud_rules_engine import ccr_style, failed_cells, resolve_tank_variant

START = datetime(2026, 1, 1, 10)


def _wp(t, depth, **kw):
    return Waypoint(timestamp=START + timedelta(seconds=t), depth=depth, time_since_start=t, dive_time=t, **kw)


def _dive(waypoints):
    return Dive(start_time=waypoints[0].timestamp, end_time=waypoints[-1].timestamp, waypoints=waypoints)


LOOP = dict(divemode="closedcircuit", diluent_o2_percent=21.0, diluent_he_percent=0.0, gas_o2_percent=21.0, gas_he_percent=0.0)


def test_circuit_labels_and_the_ccr_flag():
    loop, bailout = _wp(0, 10, **LOOP), _wp(60, 10, divemode="opencircuit", gas_o2_percent=50.0)
    dive = _dive([loop, bailout])
    assert dive.is_ccr and (loop.circuit, bailout.circuit) == ("CC", "BO")
    oc = _dive([_wp(0, 10, divemode="opencircuit")])
    assert not oc.is_ccr and oc.waypoints[0].circuit == "OC"
    assert _wp(0, 10).circuit == "OC" and _wp(0, 10, divemode="semiclosedcircuit").circuit == "SC"  # no mode logged: OC


def test_breathed_gas_and_diluent_po2_apart_from_the_tanks():
    tanks = {"O2": TankData(pressure_bar=180, o2_percent=100.0), "T1": TankData(pressure_bar=190, o2_percent=18.0, he_percent=45.0)}
    wp = _wp(0, 30, tanks=tanks, divemode="closedcircuit", gas_o2_percent=18.0, gas_he_percent=45.0, diluent_o2_percent=18.0)
    assert wp.gasmix == "18/45"  # not the O2 cylinder listed first
    assert gas_o2_fraction(wp) == pytest.approx(0.18)  # the MOD is the diluent's (Petrel 3 Tech p.18)
    assert wp.diluent_po2 == 0.72
    assert _wp(0, 30, tanks=tanks).gasmix == "Nx100"  # no gas named: the first tank, as before
    assert _wp(0, 30).diluent_po2 is None


def test_a_ccr_dive_is_not_sidemount():
    tanks = {"O2": TankData(pressure_bar=180, o2_percent=100.0), "T1": TankData(pressure_bar=190)}
    assert resolve_tank_variant(_dive([_wp(0, 10, tanks=tanks, **LOOP)])) == "single_tank"
    assert resolve_tank_variant(_dive([_wp(0, 10, tanks=tanks)])) == "sidemount"


def test_cell_vote():
    assert failed_cells({0: 1.20, 1: 1.25, 2: 0.80}) == {2}
    assert failed_cells({0: 1.20, 1: 1.22, 2: 1.18}) == set()
    assert failed_cells({0: 1.2, 1: 0.6}) == {0, 1}  # two cells apart: neither can be trusted
    assert failed_cells({0: 0.3}) == set()


def test_shearwater_cc_colours():
    wp = _wp(0, 20, po2=1.7, po2_1=1.25, po2_2=1.26, po2_3=0.30, **LOOP)
    assert ccr_style("Shearwater", "Petrel", "po2", wp, 1.7, "#FFFFFF", elapsed=0)["color"] == "#FF0000"
    assert ccr_style("Shearwater", "Petrel", "po2", wp, 1.3, "#FFFFFF", elapsed=0) is None
    assert ccr_style("Shearwater", "Petrel", "po2_1", wp, 1.25, "#FFFFFF") is None
    assert ccr_style("Shearwater", "Petrel", "po2_3", wp, 0.30, "#FFFFFF")["color"] == "#FF0000"  # failed and below 0.4
    wp.po2_3 = 0.9
    assert ccr_style("Shearwater", "Petrel", "po2_3", wp, 0.9, "#FFFFFF")["color"] == "#FFFF00"  # failed, in range
    # 1.7 on open circuit is the OC rules' business, not the loop's
    oc = _wp(0, 20, divemode="opencircuit")
    assert ccr_style("Shearwater", "Petrel", "po2", oc, 1.7, "#FFFFFF") is None
    assert ccr_style("Shearwater", "Petrel", "diluent_po2", wp, 0.10, "#FFFFFF", elapsed=0)["color"] == "#FF0000"


def test_badges_setpoint_colours_and_garmin_bailout_gas():
    dive = _dive([_wp(0, 3, setpoint=0.7, **LOOP), _wp(60, 30, setpoint=1.3, **LOOP), _wp(120, 20, divemode="opencircuit")])
    low, high, bo = dive.waypoints
    assert ccr_style("Shearwater", "Perdix 3", "setpoint", high, 1.3, "#FFFFFF")["color"] == "#00C800"
    assert ccr_style("Shearwater", "Teric", "setpoint", low, 0.7, "#FFFFFF")["color"] == "#FF00FF"
    assert ccr_style("Shearwater", "Petrel", "setpoint", high, 1.3, "#FFFFFF") is None  # Petrel: main colour
    assert ccr_style("Shearwater", "Perdix 3", "circuit", low, "CC", "#FFFFFF") == {"box": "#00C800", "color": "#000000"}
    assert ccr_style("Shearwater", "Petrel", "circuit", bo, "BO", "#FFFFFF") == {"box": "#FFFF00", "color": "#000000"}
    assert ccr_style("Shearwater", "Petrel", "circuit", low, "CC", "#FFFFFF") is None
    assert ccr_style("Garmin", "x50i", "gasmix", bo, "Nx50", "#FFFFFF") == {"color": "#FF0000"}
    assert ccr_style("Garmin", "x50i", "gasmix", low, "AIR", "#FFFFFF") is None


def test_ppo2_notices_follow_the_circuit():
    """1.5 bar is fine on the loop (CC Max 1.60) but HIGH PPO2 on open circuit
    (OC Deco 1.61 is the limit there, so 1.62 then)."""
    loop = [_wp(t, 30, po2=1.5, **LOOP) for t in range(0, 120, 5)]
    assert not any(notice_timeline("Shearwater", "Perdix 2", loop).values())
    high = [_wp(t, 30, po2=1.65, **LOOP) for t in range(0, 120, 5)]
    shown = {n["id"] for n in notice_timeline("Shearwater", "Perdix 2", high).values() if n}
    assert shown == {"high_ppo2_cc"}
    low = [_wp(t, 2, po2=0.35, **LOOP) for t in range(0, 60, 5)]
    assert {n["id"] for n in notice_timeline("Shearwater", "Perdix 2", low).values() if n} == {"low_ppo2_cc"}


def test_teric_auto_setpoint_and_garmin_setpoint_switch_notices():
    wps = [_wp(t, 20, setpoint=0.7 if t < 60 else 1.3, **LOOP) for t in range(0, 120, 5)]
    tl = notice_timeline("Shearwater", "Teric", wps)
    assert tl[55] is None and tl[60]["text"] == "Auto SP Up" and tl[60]["caption"] == "INFO"
    garmin = [_wp(t, 20, dive_alerts=["setpoint_switch_auto_high"] if t == 60 else [], **LOOP) for t in range(0, 120, 5)]
    assert notice_timeline("Garmin", "x50i", garmin)[60]["text"] == "Switched to high setpoint."


def test_the_deco_recompute_follows_the_loop():
    """On the loop the PO2 is the setpoint and the tissues load the loop's
    gas: a 30 m dive on a 1.3 setpoint carries less inert gas than on air,
    so its ceiling is shallower."""
    wps = [{"divetime": t, "datetime": START, "depth": 30.0 if 120 <= t <= 1800 else 0.0 if t == 0 else 15.0} for t in (0, 120, 1800, 1900)]
    air = [GasDefinition("AIR", 0.21, 0.0, 56.0)]
    oc = DiveDecompressor().process_waypoints(wps, air)
    loop_wps = [dict(w, setpoint=1.3, diluent_o2_percent=21.0, diluent_he_percent=0.0) for w in wps]
    cc = DiveDecompressor().process_waypoints(loop_wps, air)
    assert cc[1800].po2 == 1.3
    assert cc[1800].ceiling_meters < oc[1800].ceiling_meters
    assert cc[1800].tts_seconds < oc[1800].tts_seconds
