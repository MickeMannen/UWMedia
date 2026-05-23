import pytest
from unittest.mock import MagicMock
from utils.hud_rules_engine import get_dynamic_color, get_safety_stop_text, get_rule_config

def test_rules_loading_and_hierarchical_fallback():
    # 1. Exact model-level override check (Shearwater Perdix2 has its own tank_pressure)
    perdix_tp = get_rule_config("Shearwater", "Perdix2", "tank_pressure")
    assert perdix_tp is not None
    
    # 2. Manufacturer-level fallback (Shearwater has ndl, but Perdix2 block doesn't)
    perdix_ndl = get_rule_config("Shearwater", "Perdix2", "ndl")
    assert perdix_ndl is not None
    
    # 3. Global fallback (Shearwater has no generic tank_pressure, nor does a generic model, so fallback to default)
    fallback_tp = get_rule_config("Shearwater", "UnknownModel", "tank_pressure")
    assert fallback_tp is not None
    assert isinstance(fallback_tp, list)
    
    # 4. Unknown manufacturer completely falls back to default
    unknown_ndl = get_rule_config("UnknownMfg", "Model", "ndl")
    assert unknown_ndl is not None

    # 5. Generic manufacturer with empty model falls back to default
    generic_ndl = get_rule_config("Generic", "", "ndl")
    assert generic_ndl is not None

def test_ndl_dynamic_colors():
    # 35 minutes = 2100 seconds (above 30) -> #FFFFFF
    assert get_dynamic_color("Shearwater", "Perdix2", "ndl", 2100, "#BLUE") == "#FFFFFF"
    
    # 20 minutes = 1200 seconds (10 to 30) -> #FFFF00
    assert get_dynamic_color("Shearwater", "Perdix2", "ndl", 1200, "#BLUE") == "#FFFF00"
    
    # 5 minutes = 300 seconds (below 10) -> #FF0000
    assert get_dynamic_color("Shearwater", "Perdix2", "ndl", 300, "#BLUE") == "#FF0000"

def test_tank_pressure_dynamic_colors():
    # 150 bar -> default_color
    assert get_dynamic_color("Shearwater", "Perdix2", "primary_tank_pressure", 150, "#BLUE") == "#BLUE"
    
    # 65 bar (below 70, but not below 60) -> #FFA500
    assert get_dynamic_color("Shearwater", "Perdix2", "primary_tank_pressure", 65, "#BLUE") == "#FFA500"
    
    # 50 bar (below 60) -> #FF0000
    assert get_dynamic_color("Shearwater", "Perdix2", "primary_tank_pressure", 50, "#BLUE") == "#FF0000"

def test_safety_stop_text():
    wp_no_trigger = MagicMock()
    wp_no_trigger.max_depth = 5.0
    wp_no_trigger.depth = 5.0
    assert get_safety_stop_text("Shearwater", "Perdix2", wp_no_trigger) == ""
    
    wp_triggered_and_in_range = MagicMock()
    wp_triggered_and_in_range.max_depth = 12.0
    wp_triggered_and_in_range.depth = 5.0
    assert get_safety_stop_text("Shearwater", "Perdix2", wp_triggered_and_in_range) == "SAFETY STOP"
