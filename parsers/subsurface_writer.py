import zlib
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from lxml import etree

from models.dive_plan import DiveProfilePlan
from parsers.plan_embed import SUBSURFACE_NOTES_MARK, add_subsurface_plan
from parsers.uddf_writer import NDL_CAP_SEC, log_start_time
from utils.dive_computers import dive_computer
from utils.dive_plan_engine import SimulatedSample

# Subsurface's own event type number for a gas change (SAMPLE_EVENT_GASCHANGE2).
GASCHANGE_EVENT_TYPE = 25


def _mmss(seconds: int) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d} min"


def _hex_id(text: str) -> str:
    """Stable 8-hex-digit id, the shape Subsurface uses for deviceid/diveid."""
    return f"{zlib.crc32(text.encode()) & 0xFFFFFFFF:08x}"


def write_subsurface(
    plan: DiveProfilePlan,
    samples: List[SimulatedSample],
    file_path: Path,
    start_time: Optional[datetime] = None,
) -> None:
    """Writes `samples` (from utils.dive_plan_engine.simulate) as a
    Subsurface XML divelog (.ssrf) - attribute formats matched against real
    Subsurface files (test_data/logs/submersion_dives/*.ssrf.xml) closely
    enough that parsers/subsurface.py's SubsurfaceParser reads it back (see
    tests/test_log_writers.py).

    One <cylinder> per tank (DiveProfilePlan.tank_specs), described by its
    tank ref so the parser keys tank pressures the same as the UDDF/FIT
    writers do; every sample carries every cylinder's pressureN. Gas and
    sidemount tank switches are gaschange events, a CCR dive is
    dctype='CCR' with modechange events around any bailout, like
    Subsurface's own CCR logs.
    """
    if not samples:
        raise ValueError("No samples to write - run utils.dive_plan_engine.simulate() first")
    start_time = log_start_time(plan, start_time)
    computer = dive_computer(plan.computer)
    serial = plan.computer_serial or "0"

    root = etree.Element("divelog", program="subsurface", version="3")
    etree.SubElement(root, "settings")
    etree.SubElement(root, "divesites")
    dives = etree.SubElement(root, "dives")

    duration = samples[-1].time_sec
    dive = etree.SubElement(
        dives, "dive",
        number="1",
        date=start_time.strftime("%Y-%m-%d"),
        time=start_time.strftime("%H:%M:%S"),
        duration=_mmss(duration),
    )
    notes = etree.SubElement(dive, "notes")
    notes.text = f"{plan.name} - synthetic profile from the {SUBSURFACE_NOTES_MARK}, not a real dive"

    tanks = plan.tank_specs()
    tank_index = {t.ref: i for i, t in enumerate(tanks)}
    end_pressures = samples[-1].tank_pressures
    for tank in tanks:
        attrs = {
            "size": f"{tank.size_l:.1f} l",
            "workpressure": f"{tank.start_pressure_bar:.1f} bar",
            "description": tank.ref,
            "o2": f"{tank.o2_percent:.1f}%",
        }
        if tank.he_percent:
            attrs["he"] = f"{tank.he_percent:.1f}%"
        attrs["start"] = f"{tank.start_pressure_bar:.1f} bar"
        attrs["end"] = f"{end_pressures.get(tank.ref, tank.start_pressure_bar):.1f} bar"
        if tank.role != "oc":
            attrs["use"] = tank.role
        etree.SubElement(dive, "cylinder", **attrs)

    dc_attrs = {
        "model": computer.label,
        "deviceid": _hex_id(f"{computer.label}_{serial}"),
        "diveid": _hex_id(f"{computer.label}_{serial}_{start_time.isoformat()}"),
    }
    if plan.is_ccr:
        dc_attrs["dctype"] = "CCR"
    divecomputer = etree.SubElement(dive, "divecomputer", **dc_attrs)
    depths = [s.depth_m for s in samples]
    etree.SubElement(
        divecomputer, "depth",
        max=f"{max(depths):.1f} m", mean=f"{sum(depths) / len(depths):.3f} m",
    )
    etree.SubElement(divecomputer, "temperature", water=f"{plan.water_temp_c:.1f} C")
    etree.SubElement(divecomputer, "extradata", key="Serial", value=serial)
    etree.SubElement(divecomputer, "extradata", key="Deco model", value=f"GF {plan.gf_low:g}/{plan.gf_high:g}")
    # The plan itself, so the builder can open this file again (plan_embed).
    add_subsurface_plan(divecomputer, plan)

    last_tank = None
    last_mode = None
    for i, s in enumerate(samples):
        if plan.is_ccr and s.divemode != last_mode:
            if last_mode is not None:
                etree.SubElement(
                    divecomputer, "event", time=_mmss(s.time_sec), type="8", name="modechange",
                    divemode="CCR" if s.divemode == "closedcircuit" else "OC",
                )
            last_mode = s.divemode
        if s.tank_ref != last_tank:
            idx = tank_index[s.tank_ref]
            etree.SubElement(
                divecomputer, "event", time=_mmss(s.time_sec), type=str(GASCHANGE_EVENT_TYPE),
                flags=str(idx + 1), name="gaschange", cylinder=str(idx),
            )
            last_tank = s.tank_ref

        attrs = {"time": _mmss(s.time_sec), "depth": f"{s.depth_m:.2f} m"}
        if i == 0:
            attrs["temp"] = f"{plan.water_temp_c:.1f} C"
        for tank in tanks:
            if tank.ref in s.tank_pressures:
                attrs[f"pressure{tank_index[tank.ref]}"] = f"{s.tank_pressures[tank.ref]:.1f} bar"
        if s.ceiling_m > 0:
            attrs["in_deco"] = "1"
            attrs["stopdepth"] = f"{s.stop_depth_m:.1f} m"
            attrs["stoptime"] = _mmss(s.stop_duration_sec)
        else:
            attrs["ndl"] = _mmss(s.ndl_sec if s.ndl_sec is not None else NDL_CAP_SEC)  # None = unbounded, "99+"
        attrs["tts"] = _mmss(s.tts_sec)
        attrs["cns"] = f"{int(s.cns_pct)}%"
        attrs["po2"] = f"{s.po2:.2f} bar"
        etree.SubElement(divecomputer, "sample", **attrs)

    etree.ElementTree(root).write(str(file_path), pretty_print=True, xml_declaration=False, encoding="utf-8")
