"""utils/units.py: one unit system for everything the app shows; the data
stays SI (simulator.md §7)."""
import pytest

from utils import units as U


def test_conversions_match_the_manuals_pairs():
    with U.units_override("imperial"):
        assert round(U.depth(11.0)) == 36 and round(U.depth(10.67)) == 35      # 11 m / 35 ft (Perdix 2 p.27)
        assert round(U.pressure(50.0)) == 725                                  # 50 bar / 725 psi (p.57)
        assert round(U.pressure(21.0)) == 305 and round(U.pressure(20.7)) == 300  # 21 bar / 300 psi
        assert U.temperature(27.0) == pytest.approx(80.6)
        assert U.stop_depth(6.0) == 20 and U.stop_depth(3.0) == 10 and U.stop_depth(9.0) == 30  # 10 ft stop levels (p.28)
        assert U.stop_depth(5.0) == 15 and U.stop_depth(4.5) == 15             # the 5 m safety stop is 15 ft (Mk3 p.10)
        assert U.depth_label() == "ft" and U.pressure_label() == "PSI" and U.pressure_label(upper=False) == "psi"
        assert U.temperature_label() == "°F" and U.sac_label() == "psi/min" and U.volume_rate_label() == "cuft/min"
        assert U.depth_to_metres(U.depth(12.3)) == pytest.approx(12.3)
        assert U.pressure_to_bar(U.pressure(207)) == pytest.approx(207)
        assert U.temperature_to_celsius(U.temperature(27)) == pytest.approx(27)
    with U.units_override("metric"):
        assert U.depth(11.0) == 11.0 and U.stop_depth(6.0) == 6 and U.depth_label() == "m" and U.pressure_label() == "BAR"


def test_formatting_follows_the_brands_decimals():
    rule = {"depth_decimals": {"metric": 1, "imperial": 0}}
    assert U.format_depth(45.3, "metric", display_rule=rule) == "45.3"
    assert U.format_depth(13.72, "imperial", display_rule=rule) == "45"                       # Perdix 2 p.12: whole feet
    assert U.format_depth(31.58, "imperial", display_rule={"depth_decimals": {"imperial": 1}}) == "103.6"  # Teric p.23
    assert U.format_depth(None) == "--"
    assert U.format_pressure(207.0, "imperial") == "3002" and U.format_pressure(207.0, "metric") == "207"
    assert U.format_temperature(27.0, "imperial") == "81" and U.format_temperature(27.0, "metric") == "27"


def test_resolution_order_override_then_layout_then_setting(monkeypatch):
    U.reload_units()
    monkeypatch.setattr("utils.app_settings.load_settings", lambda: {"units": "imperial"})
    U.reload_units()
    assert U.current_units() == "imperial"
    assert U.resolve_units({"units": "metric"}) == "metric"  # a template pins its own system
    with U.units_override("metric"):
        assert U.current_units() == "metric" and U.resolve_units({}) == "metric"
    assert U.normalize("FT") == "imperial" and U.normalize(None) == "metric" and U.normalize("psi") == "imperial"
    U.reload_units()
