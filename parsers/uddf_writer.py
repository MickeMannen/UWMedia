from datetime import datetime
from pathlib import Path
from typing import List, Optional

from lxml import etree

from models.dive_plan import DiveProfilePlan, PlannedGas
from parsers.plan_embed import GENERATOR_NAME, add_uddf_plan
from utils.dive_computers import dive_computer
from utils.dive_plan_engine import SimulatedSample

UDDF_NS = "http://www.streit.cc/uddf/3.2/"
NDL_CAP_SEC = 99 * 60  # "99+" - how an unbounded NDL is logged
_NSMAP = {None: UDDF_NS}


def _q(tag: str) -> str:
    return f"{{{UDDF_NS}}}{tag}"


def _el(parent, tag: str, text=None, **attrs):
    e = etree.SubElement(parent, _q(tag))
    if text is not None:
        e.text = str(text)
    for key, value in attrs.items():
        e.set(key, str(value))
    return e


def _gas_mix_id(gas: PlannedGas) -> str:
    return f"{gas.id}:{round(gas.o2_percent):02d}/{round(gas.he_percent):02d}"


def log_start_time(plan: DiveProfilePlan, start_time: Optional[datetime] = None) -> datetime:
    """The dive's local start for a written log: the explicit argument, else
    the plan's own start_time, else now. Shared by all three log writers."""
    when = start_time or plan.start_time or datetime.now()
    return when.replace(microsecond=0, tzinfo=None)


def utc_offset_minutes(local_start: datetime) -> int:
    """This machine's UTC offset at `local_start` (DST included) - the
    builder has no time zone of its own, so a log is written as if dived
    in the local zone."""
    offset = local_start.astimezone().utcoffset()
    return int(offset.total_seconds() // 60) if offset is not None else 0


def write_uddf(
    plan: DiveProfilePlan,
    samples: List[SimulatedSample],
    file_path: Path,
    start_time: Optional[datetime] = None,
) -> None:
    """Writes `samples` (from utils.dive_plan_engine.simulate) as a
    Shearwater Cloud style UDDF file - structure matched against real
    exports (test_data/logs/submersion_dives/005_oc-trimix-two-deco-gases--perdix2.uddf,
    006_ccr_petrel3_shearwater-cloud-export.uddf) closely enough that
    parsers/uddf.py's UDDFParser reads it back correctly (see
    tests/test_uddf_writer.py's round-trip tests). Like those exports,
    every waypoint lists every tank's pressure, so both sidemount tanks
    (one mix, linked from two tanks) or a CCR's O2/diluent cylinders all
    come through.

    The device is plan.computer (utils.dive_computers); the generator's
    manufacturer is set to the computer's too, since UDDFParser reads a
    dive's manufacturer from there.
    """
    if not samples:
        raise ValueError("No samples to write - run utils.dive_plan_engine.simulate() first")
    start_time = log_start_time(plan, start_time)
    computer = dive_computer(plan.computer)
    serial = plan.computer_serial or "0"

    root = etree.Element(_q("uddf"), nsmap=_NSMAP, version="3.2.3")

    generator = _el(root, "generator")
    _el(generator, "name", GENERATOR_NAME)
    _el(generator, "type", "logbook")
    manufacturer = _el(generator, "manufacturer", id=computer.manufacturer)
    _el(manufacturer, "name", computer.manufacturer)
    _el(generator, "datetime", datetime.now().replace(microsecond=0).isoformat() + "Z")

    diver = _el(root, "diver")
    owner = _el(diver, "owner")
    equipment = _el(owner, "equipment")
    divecomputer = _el(equipment, "divecomputer", id=f"{computer.model}_{serial}")
    _el(divecomputer, "name", computer.model)
    dc_manufacturer = _el(divecomputer, "manufacturer", id=computer.manufacturer)
    _el(dc_manufacturer, "name", computer.manufacturer)
    _el(divecomputer, "model", computer.model)
    _el(divecomputer, "serialnumber", serial)

    gasdefs = _el(root, "gasdefinitions")
    mix_ids = {}
    for gas in plan.breathed_gases():
        mix_id = _gas_mix_id(gas)
        mix_ids[gas.id] = mix_id
        mix = _el(gasdefs, "mix", id=mix_id)
        _el(mix, "name", gas.id)
        _el(mix, "o2", round(gas.f_o2, 4))
        _el(mix, "he", round(gas.f_he, 4))
        _el(mix, "maximumpo2", plan.ccr_high_setpoint if plan.on_loop(gas) else plan.max_po2_bottom)

    decomodel = _el(root, "decomodel")
    buehlmann = _el(decomodel, "buehlmann", id="zhl16c")
    _el(buehlmann, "gradientfactorhigh", int(plan.gf_high))
    _el(buehlmann, "gradientfactorlow", int(plan.gf_low))

    profiledata = _el(root, "profiledata")
    repetitiongroup = _el(profiledata, "repetitiongroup")
    dive = _el(repetitiongroup, "dive", id="1")

    info_before = _el(dive, "informationbeforedive")
    _el(info_before, "datetime", start_time.isoformat() + "Z")
    tanks = plan.tank_specs()
    end_pressures = samples[-1].tank_pressures
    for tank in tanks:
        tankdata = _el(info_before, "tankdata", id=tank.ref)
        if tank.gas_id is not None:
            _el(tankdata, "link", ref=mix_ids[tank.gas_id])
        _el(tankdata, "tankvolume", round(tank.size_l / 1000.0, 4))  # UDDF volumes are in m^3
        _el(tankdata, "tankpressurebegin", int(tank.start_pressure_bar * 100000))
        end_pressure = end_pressures.get(tank.ref, tank.start_pressure_bar)
        _el(tankdata, "tankpressureend", int(end_pressure * 100000))

    samples_el = _el(dive, "samples")
    temp_k = round(plan.water_temp_c + 273.15, 2)
    last_gas_id = None

    for s in samples:
        wp = _el(samples_el, "waypoint")
        if s.gas_id != last_gas_id:
            _el(wp, "switchmix", ref=mix_ids[s.gas_id])
            last_gas_id = s.gas_id

        _el(wp, "depth", round(s.depth_m, 2))
        _el(wp, "divetime", s.time_sec)
        _el(wp, "temperature", temp_k)

        for tank in tanks:
            if tank.ref in s.tank_pressures:
                _el(wp, "tankpressure", int(s.tank_pressures[tank.ref] * 100000), ref=tank.ref)

        _el(wp, "calculatedpo2", round(s.po2, 2))
        if s.divemode == "closedcircuit":
            _el(wp, "setpo2", plan.setpoint_at(s.depth_m), setby="computer")
        if s.cns_pct:
            _el(wp, "cns", int(s.cns_pct))
        _el(wp, "divemode", type=s.divemode)

        if s.ceiling_m > 0:
            _el(
                wp,
                "decostop",
                kind="mandatory",
                decodepth=round(s.stop_depth_m, 1),
                duration=s.stop_duration_sec,
            )
        else:
            # An unbounded NDL (None) is written as the 99-minute cap, so the
            # sample still says "no stop owed" - a waypoint with neither
            # decostop nor nodecotime would leave that open.
            _el(wp, "nodecotime", s.ndl_sec if s.ndl_sec is not None else NDL_CAP_SEC)
        # Time to surface - not a UDDF element (Shearwater exports carry none);
        # UWMedia's own extension, read back by parsers/uddf.py in preference
        # to its generic recompute.
        _el(wp, "tts", s.tts_sec)

    # Read back as Dive.timezone by UDDFParser (its own update_timezone
    # convention: offset in minutes, a direct child of <dive>).
    _el(dive, "timezone", utc_offset_minutes(start_time))
    # The plan itself, so the builder can open this file again (plan_embed).
    add_uddf_plan(dive, plan, UDDF_NS)

    tree = etree.ElementTree(root)
    tree.write(str(file_path), pretty_print=True, xml_declaration=True, encoding="utf-8")
