import pytest
from datetime import datetime
from models.dive import Waypoint, Dive, TankData

def test_waypoint_model():
    wp = Waypoint(
        timestamp=datetime.now(),
        depth=10.5,
        temp=24.0,
        time_since_start=60,
        tanks={"1": TankData(pressure_bar=200, o2_percent=21.0)}
    )
    assert wp.depth == 10.5
    assert wp.tanks["1"].pressure_bar == 200

def test_primary_secondary_tank_properties():
    wp_no_tanks = Waypoint(timestamp=datetime.now(), time_since_start=0)
    assert wp_no_tanks.primary_tank_name is None
    assert wp_no_tanks.secondary_tank_pressure is None
    assert wp_no_tanks.secondary_tank_name is None

    wp_single = Waypoint(
        timestamp=datetime.now(), time_since_start=0,
        tanks={"Micke01": TankData(pressure_bar=200, o2_percent=21.0, name="Micke01")},
    )
    assert wp_single.primary_tank_name == "Micke01"
    assert wp_single.secondary_tank_pressure is None
    assert wp_single.secondary_tank_name is None

    wp_sidemount = Waypoint(
        timestamp=datetime.now(), time_since_start=0,
        tanks={
            "Left": TankData(pressure_bar=180, o2_percent=21.0, name=None),
            "Right": TankData(pressure_bar=190, o2_percent=21.0, name="Right Tank"),
        },
    )
    # name falls back to the dict key when the tank has no configured name
    assert wp_sidemount.primary_tank_name == "Left"
    assert wp_sidemount.secondary_tank_name == "Right Tank"
    assert wp_sidemount.secondary_tank_pressure == 190

def test_ccr_and_gas_switch_fields_default_to_none():
    # New Shearwater CCR/gas-switch fields - inert until a parser populates
    # them (no source data yet to verify real UDDF field names against)
    wp = Waypoint(timestamp=datetime.now(), time_since_start=0)
    assert wp.cleared_gas_mix is None
    assert wp.po2_1 is None
    assert wp.po2_2 is None
    assert wp.po2_3 is None

    wp_ccr = Waypoint(
        timestamp=datetime.now(), time_since_start=0,
        cleared_gas_mix="EAN50", po2_1=1.2, po2_2=1.21, po2_3=1.19,
    )
    assert wp_ccr.cleared_gas_mix == "EAN50"
    assert wp_ccr.po2_1 == 1.2
    assert wp_ccr.po2_2 == 1.21
    assert wp_ccr.po2_3 == 1.19

def test_dive_duration():
    start = datetime(2023, 10, 1, 10, 0, 0)
    end = datetime(2023, 10, 1, 11, 0, 0)
    dive = Dive(start_time=start, end_time=end, waypoints=[])
    assert dive.duration == 3600
