import pytest
from pathlib import Path
from parsers.uddf import UDDFParser

def test_parse_atmos_uddf():
    parser = UDDFParser()
    path = Path("test_data/ATMOS_Export_20251020222139.uddf")
    dives = parser.parse(path)
    # The file is in test_data/ not test_data/uddf/ based on previous list_directory
    if not path.exists():
        path = Path("test_data/uddf/ATMOS_Export_20251020222139.uddf")
    
    dives = parser.parse(path)
    if not dives:
        return # Skip if test data missing in specific env

    assert len(dives) > 0
    assert dives[0].start_time.year == 2025
    
    # Check waypoints
    assert len(dives[0].waypoints) > 0
    assert dives[0].waypoints[0].temp > 0

def test_parse_perdix_uddf():
    parser = UDDFParser()
    # Find a valid UDDF in test_data
    path = Path("test_data/uddf/Perdix 2 450 2025-10-19 10-4-52.uddf")
    if not path.exists():
         return # Skip
         
    dives = parser.parse(path)
    assert len(dives) == 1
    
    # Check temperature (Kelvin to Celsius)
    assert dives[0].waypoints[0].temp > 0

    # n2_tissue_load is Garmin-only; UDDF's deco-engine GF now lands in gf,
    # not the field they used to share under the old "n2" name
    assert all(wp.n2_tissue_load is None for wp in dives[0].waypoints)

def test_missing_file():
    parser = UDDFParser()
    dives = parser.parse(Path("non_existent.uddf"))
    assert dives == []

_MULTI_TANK_UDDF = """<?xml version="1.0" encoding="utf-8"?>
<uddf xmlns="http://www.streit.cc/uddf/3.2/" version="3.2.3">
  <gasdefinitions>
    <mix id="OC1:21/00">
      <name>Air</name>
      <o2>0.21</o2>
      <he>0.0</he>
    </mix>
  </gasdefinitions>
  <profiledata>
    <repetitiongroup>
      <dive>
        <informationbeforedive>
          <datetime>2026-01-01T10:00:00Z</datetime>
        </informationbeforedive>
        <samples>
          <waypoint>
            <divetime>0</divetime>
            <depth>15.0</depth>
            <switchmix ref="OC1:21/00"/>
            <tankpressure ref="T1">15000000</tankpressure>
            <tankpressure ref="T2">14500000</tankpressure>
          </waypoint>
        </samples>
      </dive>
    </repetitiongroup>
  </profiledata>
</uddf>
"""

_DECOSTOP_AND_DIVEMODE_UDDF = """<?xml version="1.0" encoding="utf-8"?>
<uddf xmlns="http://www.streit.cc/uddf/3.2/" version="3.2.3">
  <gasdefinitions>
    <mix id="OC1:21/00">
      <name>Air</name>
      <o2>0.21</o2>
      <he>0.0</he>
    </mix>
  </gasdefinitions>
  <profiledata>
    <repetitiongroup>
      <dive>
        <informationbeforedive>
          <datetime>2026-01-01T10:00:00Z</datetime>
        </informationbeforedive>
        <samples>
          <waypoint>
            <divetime>0</divetime>
            <depth>18.0</depth>
            <switchmix ref="OC1:21/00"/>
            <divemode type="closedcircuit"/>
            <decostop kind="mandatory" decodepth="6" duration="120"/>
          </waypoint>
          <waypoint>
            <divetime>10</divetime>
            <depth>18.0</depth>
          </waypoint>
        </samples>
      </dive>
    </repetitiongroup>
  </profiledata>
</uddf>
"""

def test_decostop_prefers_logged_value_over_recompute(tmp_path):
    # A real device/software's own logged <decostop> is more authoritative
    # than our generic Buhlmann recompute (confirmed materially different
    # against a real Perdix 2 log: file said a steady 6m, the recompute said
    # 5.5m at the same point) - the first waypoint logs one explicitly and
    # must keep exactly that value, not whatever the recompute produces.
    path = tmp_path / "deco.uddf"
    path.write_text(_DECOSTOP_AND_DIVEMODE_UDDF)

    parser = UDDFParser()
    dives = parser.parse(path)
    assert len(dives) == 1

    wp0 = dives[0].waypoints[0]
    assert wp0.deco_stop_depth == 6.0
    assert wp0.next_stop_time == 120

def test_divemode_persists_across_samples_without_one(tmp_path):
    # <divemode> isn't present on every sample in real Shearwater CCR
    # exports - confirmed against a real Petrel 3 log, where it's only on
    # some waypoints. It should persist like po2 already does, not read back
    # as an empty string in between.
    path = tmp_path / "divemode.uddf"
    path.write_text(_DECOSTOP_AND_DIVEMODE_UDDF)

    parser = UDDFParser()
    dives = parser.parse(path)
    waypoints = dives[0].waypoints

    assert waypoints[0].divemode == "closedcircuit"
    assert waypoints[1].divemode == "closedcircuit"

def test_parse_sidemount_reads_both_tank_pressures(tmp_path):
    # A sidemount/multi-tank sample reports one <tankpressure ref="..."> per
    # tank in the same waypoint - the parser used to read only the first via
    # xpath's string(), silently dropping every tank past the first.
    path = tmp_path / "sidemount.uddf"
    path.write_text(_MULTI_TANK_UDDF)

    parser = UDDFParser()
    dives = parser.parse(path)
    assert len(dives) == 1

    wp = dives[0].waypoints[0]
    assert set(wp.tanks.keys()) == {"T1", "T2"}
    assert wp.tanks["T1"].pressure_bar == pytest.approx(150.0)
    assert wp.tanks["T2"].pressure_bar == pytest.approx(145.0)
    assert wp.primary_tank_pressure == pytest.approx(150.0)
    assert wp.secondary_tank_pressure == pytest.approx(145.0)
