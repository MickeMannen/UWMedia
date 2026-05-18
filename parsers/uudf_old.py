#
# https://www.streit.cc/resources/UDDF/v3.2.3/en/index.html
# https://www.streit.cc/resources/UDDF/v3.2.3/en/index.html
#
import copy
import os
import re
from datetime import datetime, time, timedelta
from typing import Dict, Tuple
import xml.etree.ElementTree as ET
from data.common import (string_to_int, str_to_int_rounded, convert_k_to_c, convert_pa_to_bar,
                         internal_datetime_format, date_time_formats, is_offset_aware, remove_offset)
from typing import Optional, Dict, Any, TypeVar, Type
from data.dive_profile import DiveProfile
from pathlib import Path


T = TypeVar("T", int, float, str)

def parse_uddf(filename: Path) -> DiveProfile:

    prefix = "uddf"
    tree = ET.parse(str(filename))
    root = tree.getroot()
    data = {}
    data["filename"] = filename.name

    def get_namespace_map(root: ET.Element) -> Dict[str, str] | None:
        """
        Return a namespace map like {'uddf': 'http://...'} if root.tag is namespaced,
        otherwise return an empty dict.
        """
        tag = root.tag
        if isinstance(tag, str) and tag.startswith("{"):
            uri = tag[1:].split("}", 1)[0]
            return {prefix: uri}
        return None

    ns = get_namespace_map(root=root)

    # ns = {'uddf': root.tag.split('}')[0].strip('{')}  # Extract namespace

    def translate_path(path):
        # datetime
        # dive/datetime
        segments = [seg for seg in path.split("/") if seg]
        if ns:
            ns_path = ".//" + "//".join(f"{prefix}:{s}" for s in segments)
            return ns_path
        else:
            fallback_path = ".//" + "//".join(segments)
            return fallback_path

    def get_element_text(element: ET.Element, path: str, data_type: Type[T] = str, default=None):

        path = translate_path(path)
        elem = element.find(path, ns)

        if bool(elem is not None and elem.text and elem.text.strip()):
            elem_value = elem.text.strip()
            if data_type is int:
                return string_to_int(elem_value)
            elif data_type is float:
                return float(elem_value)
            else:
                return str(elem.text.strip())

        return default

    def get_element_attrib(element, attr_name, element_sub=None, data_type: Type[T] = str, default=None):
        if element_sub is not None:
            element = _find(elem=element, path=element_sub)
            if element is None:
                return default
        # if i change elent to elem it breaks or ???????
        attr = element.attrib.get(attr_name, None)
        if attr is not None:
            # attr_value = attr.strip()
            if data_type is int:
                return string_to_int(attr)
            elif data_type is float:
                return float(attr)
            else:
                return str(attr.strip())

        return default

    def _find(elem, path):
        path = translate_path(path)
        return elem.find(path, ns)

    def _findall(elem, path):
        path = translate_path(path)
        for f in elem.findall(path, ns):
            yield f
        # return elem.find(path, ns)

    start_time_str = get_element_text(root, 'dive/datetime')

    if start_time_str is not None:
        try:
            start_time = None
            for d_reg, d_format in date_time_formats:
                if d_reg.match(start_time_str):
                    start_time = datetime.strptime(start_time_str, d_format)
            if start_time is None:
                raise SystemError(f"Failed to parse start date time in UDDF file: {start_time_str}")
        except ValueError as e:
            raise SystemError(f"Failed to parse start date time in UDDF file: {e.args}")
    else:
        raise SystemError("Failed to find start date time in UDDF file")

    if is_offset_aware(start_time):
        start_time = remove_offset(start_time)

    data["start_time"] = start_time
    # device_elem = root.find('.//uddf:divecomputer//uddf:name', ns)
    device = get_element_text(root, 'divecomputer/name')
    if device is not None:
        data["device"] = device
    else:
        raise SystemError("Failed to find start date time in UDDF file")

    # Gas mixes
    # gas_mixes_xml = root.find('uddf:gasdefinitions', ns)
    gas_mixes_xml = _find(elem=root, path='gasdefinitions')
    gas_mixes_dict = {}
    for gas_mix in _findall(elem=gas_mixes_xml, path='mix'):
        ref = get_element_attrib(gas_mix, 'id')

        if ref is not None:
            name = get_element_text(gas_mix, 'name', data_type=str)

            o2 = get_element_text(element=gas_mix, path='o2', data_type=float)
            if o2 is not None:
                o2 = int(o2 * 100)
            else:
                o2 = 21

            he = get_element_text(element=gas_mix, path='he', data_type=float)
            if he is not None:
                he = int(he * 100)
            else:
                he = 0
            gas_mixes_dict[name] = {"name": name, "ref": ref, "o2": o2, "he": he}

    # Parse samples
    value_mix_active = None
    samples = _findall(elem=root, path='waypoint')
    data["waypoints"] = {}
    waypoint_dict = {"datetime": start_time,
                     "ndl": 5940,
                     "depth": 0,
                     "cns": 0,
                     "temp": 0,
                     "po2": 1.2,
                     "tankpressure": {},
                     "divemode": "opencircuit",
                     "gf": 0,
                     "divetime": 0,
                     "switchmix": 21,
                     "battery": 0}

    for i, waypoint in enumerate(samples):

        # waypoint_dict = {}
        # value = waypoint.find('uddf:nodecotime', ns)
        value = get_element_text(element=waypoint, path='nodecotime', data_type=float)
        if value is not None:
            waypoint_dict["ndl"] = value
            # td = timedelta(seconds=waypoint_dict["ndl"])
            # total_minutes = td.seconds // 60
            # waypoint_dict["ndl_str"] = f"{total_minutes}:{td.seconds % 60:02}"
            # waypoint_dict["ndl_str"] = f"{total_minutes}"

        value = get_element_text(element=waypoint, path='depth', data_type=float)
        if value is not None:
            waypoint_dict["depth"] = round(value, 1)

        value = get_element_text(element=waypoint, path='cns', data_type=int)
        if value is not None:
            waypoint_dict["cns"] = value

        value = get_element_text(element=waypoint, path='heading', data_type=int)
        if value is not None:
            waypoint_dict["heading"] = value

        value = get_element_text(element=waypoint, path='temperature', data_type=float)
        if value is not None:
            waypoint_dict["temp"] = int(convert_k_to_c(value))

        value = get_element_text(element=waypoint, path='calculatedpo2', data_type=float)
        if value is not None:
            waypoint_dict["po2"] = round(value, 2)

        #  <tankpressure ref="T1">21097964</tankpressure>
        # need to test with multi gas tanks - this is only single tank
        value_pressure = get_element_text(element=waypoint, path='tankpressure', data_type=float)
        value_mix = get_element_attrib(element=waypoint, attr_name='ref', element_sub='switchmix', data_type=str)

        if value_mix is None and value_mix_active is not None:
            value_mix = value_mix_active

        waypoint_dict["tankpressure"] = {}
        if value_pressure is not None and value_mix is not None:
            for gas in gas_mixes_dict.values():
                if gas["ref"] == value_mix:
                    value_mix_active = value_mix
                    # gasmix_dict = gas
                    waypoint_dict["tankpressure"][gas["name"]] = {"name": gas["name"],
                                                          "bar": convert_pa_to_bar(value_pressure),
                                                           "o2": gas["o2"],
                                                           "he": gas["he"],
                                                           "mode": gas["name"]}

        value = get_element_attrib(element=waypoint, attr_name="type", element_sub="divemode", data_type=str)
        if value is not None:
            waypoint_dict["divemode"] = value

        # value = waypoint.find('uddf:gradientfactor', ns)
        value = get_element_text(element=waypoint, path='gradientfactor', data_type=int)
        if value is not None:
            waypoint_dict["gf"] = value

        # dive time is in seconds from start
        # value = waypoint.find('uddf:divetime', ns)
        value = get_element_text(element=waypoint, path='divetime', data_type=int)
        if value is not None:
            waypoint_dict["divetime"] = value
            # HH:MM
            td = timedelta(seconds=value)
            # total_minutes = td.seconds // 60
            # waypoint_dict["divetime_str"] = f"{total_minutes}:{td.seconds % 60:02}"
            waypoint_dict["datetime"] = start_time + td

        # value = waypoint.find('uddf:batterychargecondition', ns)
        value = get_element_text(element=waypoint, path='batterychargecondition', data_type=float)
        if value is not None:
            waypoint_dict["battery"] = value

        data["waypoints"][waypoint_dict["datetime"]] = waypoint_dict

        waypoint_dict = copy.deepcopy(waypoint_dict)

    # dive_duration = root.findall('.//uddf:informationafterdive//uddf:diveduration', ns)
    value = get_element_text(element=root, path='informationafterdive/diveduration', data_type=int)
    if value is not None:
        data["duration"] = value

    if data.get("end_time", None) is None and data.get("duration", None) is not None:
        data["end_time"] = data["start_time"] + timedelta(seconds=data.get("duration", 0))
    d = DiveProfile(**data)
    return d
