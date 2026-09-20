from datetime import datetime
from pathlib import Path
from typing import List, Optional

from lxml import etree

from models.dive_plan import DiveProfilePlan, PlannedGas
from utils.dive_plan_engine import SimulatedSample

UDDF_NS = "http://www.streit.cc/uddf/3.2/"
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


def write_uddf(
    plan: DiveProfilePlan,
    samples: List[SimulatedSample],
    file_path: Path,
    start_time: Optional[datetime] = None,
) -> None:
    """Writes `samples` (from utils.dive_plan_engine.simulate) as a
    Shearwater Perdix 2 style UDDF file - structure matched against a real
    export (test_data/logs/submersion_dives/005_oc-trimix-two-deco-gases--perdix2.uddf)
    closely enough that parsers/uddf.py's UDDFParser reads it back correctly
    (see tests/test_uddf_writer.py's round-trip test).

    CCR waypoint fields are a best-effort model - no real Shearwater CCR
    UDDF export was available to confirm the exact structure against,
    unlike the OC path (same caveat this codebase already flags for other
    unverified CCR sources - see shearwater_rework.md Phase 5).
    """
    if not samples:
        raise ValueError("No samples to write - run utils.dive_plan_engine.simulate() first")
    if start_time is None:
        start_time = datetime.now().replace(microsecond=0)

    root = etree.Element(_q("uddf"), nsmap=_NSMAP, version="3.2.3")

    generator = _el(root, "generator")
    _el(generator, "name", "UWMedia Dive Profile Builder")
    _el(generator, "type", "logbook")
    manufacturer = _el(generator, "manufacturer", id="UWMedia")
    _el(manufacturer, "name", "UWMedia")
    _el(generator, "datetime", datetime.now().replace(microsecond=0).isoformat() + "Z")

    diver = _el(root, "diver")
    owner = _el(diver, "owner")
    equipment = _el(owner, "equipment")
    divecomputer = _el(equipment, "divecomputer", id="Perdix 2_00000000")
    _el(divecomputer, "name", "Perdix 2")
    _el(divecomputer, "model", "Perdix 2")
    _el(divecomputer, "serialnumber", "00000000")

    gasdefs = _el(root, "gasdefinitions")
    mix_ids = {}
    for gas in plan.gases:
        mix_id = _gas_mix_id(gas)
        mix_ids[gas.id] = mix_id
        mix = _el(gasdefs, "mix", id=mix_id)
        _el(mix, "name", gas.id)
        _el(mix, "o2", round(gas.f_o2, 4))
        _el(mix, "he", round(gas.f_he, 4))
        _el(mix, "maximumpo2", gas.ccr_setpoint if gas.is_ccr and gas.ccr_setpoint else 1.4)

    decomodel = _el(root, "decomodel")
    buehlmann = _el(decomodel, "buehlmann", id="zhl16c")
    _el(buehlmann, "gradientfactorhigh", int(plan.gf_high))
    _el(buehlmann, "gradientfactorlow", int(plan.gf_low))

    profiledata = _el(root, "profiledata")
    repetitiongroup = _el(profiledata, "repetitiongroup")
    dive = _el(repetitiongroup, "dive", id="1")

    info_before = _el(dive, "informationbeforedive")
    _el(info_before, "datetime", start_time.isoformat() + "Z")
    for gas in plan.gases:
        end_pressure = next(
            (s.tank_pressure_bar for s in reversed(samples) if s.gas_id == gas.id),
            gas.start_pressure_bar,
        )
        tankdata = _el(info_before, "tankdata")
        _el(tankdata, "tankpressurebegin", int(gas.start_pressure_bar * 100000))
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

        gas = plan.gas_by_id(s.gas_id)
        if gas is not None and gas.tank_size_l > 0:
            _el(wp, "tankpressure", int(s.tank_pressure_bar * 100000), ref=gas.tank_ref)

        _el(wp, "calculatedpo2", round(s.po2, 2))
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
        elif s.ndl_sec is not None:
            _el(wp, "nodecotime", s.ndl_sec)

    tree = etree.ElementTree(root)
    tree.write(str(file_path), pretty_print=True, xml_declaration=True, encoding="utf-8")
