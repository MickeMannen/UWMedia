import json
import os
from pathlib import Path
from typing import Dict, Any, Optional

_rules_cache = None

def load_rules_json() -> Dict[str, Any]:
    global _rules_cache
    if _rules_cache is not None:
        return _rules_cache

    # Find the rules JSON file
    possible_paths = [
        Path(__file__).parent.parent / "hud_rules.json",
        Path("hud_rules.json"),
        Path(__file__).parent / "hud_rules.json"
    ]
    
    for path in possible_paths:
        if path.exists():
            try:
                with open(path, 'r') as f:
                    _rules_cache = json.load(f)
                    return _rules_cache
            except Exception as e:
                print(f"Error loading rules from {path}: {e}")

    # Fallback to hardcoded default rules if file is missing
    print("Warning: Could not find hud_rules.json, using hardcoded default rules.")
    _rules_cache = {
        "default": {
            "ndl": [
                {"max": 10, "color": "#FF0000"},
                {"min": 10, "max": 30, "color": "#FFFF00"},
                {"min": 30, "color": "#FFFFFF"}
            ],
            "tank_pressure": [
                {"max": 60, "color": "#FF0000"},
                {"max": 70, "color": "#FFA500"}
            ],
            "safety_stop": {
                "text": "SAFETY STOP",
                "color": "#FFFF00",
                "trigger_max_depth": 10.0,
                "min_depth": 3.0,
                "max_depth": 6.0
            }
        }
    }
    return _rules_cache

def get_rule_config(manufacturer: Optional[str], model: Optional[str], rule_key: str) -> Any:
    rules = load_rules_json()
    
    # 1. Try finding rule in manufacturer -> model
    if manufacturer and manufacturer in rules:
        mfg_block = rules[manufacturer]
        if model and model in mfg_block:
            model_block = mfg_block[model]
            if isinstance(model_block, dict) and rule_key in model_block:
                return model_block[rule_key]
        
        # 2. Try finding rule directly under manufacturer
        if rule_key in mfg_block:
            return mfg_block[rule_key]
            
        # 3. Try finding rule under manufacturer -> default
        if "default" in mfg_block:
            mfg_default = mfg_block["default"]
            if isinstance(mfg_default, dict) and rule_key in mfg_default:
                return mfg_default[rule_key]
                
    # 4. Try finding rule in global default
    global_default = rules.get("default", {})
    if rule_key in global_default:
        return global_default[rule_key]
        
    return None

def get_dynamic_color(manufacturer: Optional[str], model: Optional[str], field: str, value: Any, default_color: str) -> str:
    if value is None:
        return default_color

    # Normalize field name to match JSON keys
    rule_key = None
    if field == "ndl":
        rule_key = "ndl"
    elif field == "primary_tank_pressure" or field.startswith("tank_pressure:"):
        rule_key = "tank_pressure"
    elif field == "safety_stop":
        rule_key = "safety_stop"
        
    if not rule_key:
        return default_color

    config = get_rule_config(manufacturer, model, rule_key)
    if not config:
        return default_color
        
    if rule_key == "safety_stop":
        if isinstance(config, dict):
            return config.get("color", "#FFFF00")
        return "#FFFF00"

    rules_list = config
    if not isinstance(rules_list, list):
        return default_color
        
    if rule_key == "ndl":
        try:
            val_mins = float(value) / 60.0
            for rule in rules_list:
                match = True
                if "min" in rule and val_mins < rule["min"]:
                    match = False
                if "max" in rule and val_mins >= rule["max"]:
                    match = False
                if match:
                    return rule["color"]
        except (ValueError, TypeError):
            pass
            
    elif rule_key == "tank_pressure":
        try:
            val_bar = float(value)
            for rule in rules_list:
                match = True
                if "min" in rule and val_bar < rule["min"]:
                    match = False
                if "max" in rule and val_bar >= rule["max"]:
                    match = False
                if match:
                    return rule["color"]
        except (ValueError, TypeError):
            pass

    return default_color

def get_safety_stop_text(manufacturer: Optional[str], model: Optional[str], waypoint: Any) -> str:
    if waypoint is None:
        return ""
        
    safety_stop_config = get_rule_config(manufacturer, model, "safety_stop")
    if not safety_stop_config or not isinstance(safety_stop_config, dict):
        return ""
        
    trigger_max_depth = safety_stop_config.get("trigger_max_depth", 10.0)
    min_depth = safety_stop_config.get("min_depth", 3.0)
    max_depth = safety_stop_config.get("max_depth", 6.0)
    text = safety_stop_config.get("text", "SAFETY STOP")
    
    max_depth_reached = getattr(waypoint, "max_depth", 0.0) or 0.0
    current_depth = getattr(waypoint, "depth", 0.0) or 0.0
    
    if max_depth_reached >= trigger_max_depth and min_depth <= current_depth <= max_depth:
        return text
        
    return ""
