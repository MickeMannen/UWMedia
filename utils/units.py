"""Unit systems for everything the app shows (simulator.md §7).

Every value in the data model stays SI: metres, bar, °C (the parsers write
SI, the rules compare SI). Only the display converts, here. The active
system comes from, in this order: a one-off override (the CLI's --units),
the app setting `units` (Advanced page), else metric. A template may pin
its own system with a top-level `units` key (a skin drawn for a psi
screen): resolve_units(layout).

Display rounding follows the computers: a Shearwater shows whole feet but
one decimal in metres (Perdix 2 manual p.12), the Teric one decimal in both
(p.23), a Descent whole feet (Mk3 manual p.8 figures); pressures are whole
bar / psi, temperatures whole degrees. Those per-brand decimals live in
hud_rules.json (`display.depth_decimals`); this module only converts.
"""
import contextlib
import contextvars
from typing import Any, Dict, Optional

METRIC = "metric"
IMPERIAL = "imperial"
UNIT_SYSTEMS = (METRIC, IMPERIAL)
UNIT_LABELS = {METRIC: "Metric (m, bar, °C)", IMPERIAL: "Imperial (ft, psi, °F)"}

FT_PER_M = 3.280839895
PSI_PER_BAR = 14.5037738
CUFT_PER_L = 0.0353146667

_override: contextvars.ContextVar = contextvars.ContextVar("uwmedia_units_override", default=None)
_setting_cache: Dict[str, Optional[str]] = {"units": None}


def normalize(value: Any) -> str:
    value = str(value or "").strip().lower()
    return IMPERIAL if value in (IMPERIAL, "ft", "feet", "psi", "us") else METRIC


def current_units() -> str:
    """The unit system in force: the override, else the app setting."""
    override = _override.get()
    if override:
        return override
    if _setting_cache["units"] is None:
        try:
            from utils.app_settings import load_settings
            _setting_cache["units"] = normalize(load_settings().get("units"))
        except Exception:
            _setting_cache["units"] = METRIC
    return _setting_cache["units"]


def set_units(value: Any) -> str:
    """Persist the app setting and make it current."""
    units = normalize(value)
    from utils.app_settings import update_settings
    update_settings(units=units)
    _setting_cache["units"] = units
    return units


def reload_units() -> None:
    """Forget the cached setting (tests, or after settings.json changed)."""
    _setting_cache["units"] = None


def set_units_override(value: Optional[str]) -> None:
    """A process-wide choice that wins over the setting (the CLI's --units)."""
    _override.set(normalize(value) if value else None)


@contextlib.contextmanager
def units_override(value: Optional[str]):
    token = _override.set(normalize(value) if value else None)
    try:
        yield
    finally:
        _override.reset(token)


def resolve_units(layout: Optional[Dict[str, Any]] = None) -> str:
    """The system a layout renders in: its own `units` key, else the current one."""
    if isinstance(layout, dict) and layout.get("units"):
        return normalize(layout["units"])
    return current_units()


# --- conversions (SI in, display units out) ---------------------------------

def depth(metres: float, units: Optional[str] = None) -> float:
    return metres * FT_PER_M if (units or current_units()) == IMPERIAL else metres


def pressure(bar: float, units: Optional[str] = None) -> float:
    return bar * PSI_PER_BAR if (units or current_units()) == IMPERIAL else bar


def temperature(celsius: float, units: Optional[str] = None) -> float:
    return celsius * 1.8 + 32.0 if (units or current_units()) == IMPERIAL else celsius


def volume_rate(litres_per_min: float, units: Optional[str] = None) -> float:
    """Volumetric SAC: L/min, or cuft/min in imperial."""
    return litres_per_min * CUFT_PER_L if (units or current_units()) == IMPERIAL else litres_per_min


def depth_to_metres(value: float, units: Optional[str] = None) -> float:
    return value / FT_PER_M if (units or current_units()) == IMPERIAL else value


def pressure_to_bar(value: float, units: Optional[str] = None) -> float:
    return value / PSI_PER_BAR if (units or current_units()) == IMPERIAL else value


def temperature_to_celsius(value: float, units: Optional[str] = None) -> float:
    return (value - 32.0) / 1.8 if (units or current_units()) == IMPERIAL else value


def stop_depth(metres: float, units: Optional[str] = None) -> float:
    """A stop depth as the computers label it: whole metres, or the feet
    stop level - 3 m stops are 10 ft stops (Perdix 2 manual p.28, Mk3 p.10),
    the 5 m safety stop is 15 ft (Mk3 p.10), so 4.5-5.5 m rounds to 15 ft
    and everything else to the nearest 10 ft."""
    if (units or current_units()) != IMPERIAL:
        return round(metres)
    if 4.4 <= metres <= 5.6:
        return 15.0
    return float(max(10, round(metres * FT_PER_M / 10.0) * 10))


# --- labels -------------------------------------------------------------------

def depth_label(units: Optional[str] = None) -> str:
    return "ft" if (units or current_units()) == IMPERIAL else "m"


def pressure_label(units: Optional[str] = None, upper: bool = True) -> str:
    label = "psi" if (units or current_units()) == IMPERIAL else "bar"
    return label.upper() if upper else label


def temperature_label(units: Optional[str] = None) -> str:
    return "°F" if (units or current_units()) == IMPERIAL else "°C"


def sac_label(units: Optional[str] = None) -> str:
    return "psi/min" if (units or current_units()) == IMPERIAL else "bar/min"


def volume_rate_label(units: Optional[str] = None) -> str:
    return "cuft/min" if (units or current_units()) == IMPERIAL else "L/min"


def depth_rate_label(units: Optional[str] = None) -> str:
    return "ft/min" if (units or current_units()) == IMPERIAL else "m/min"


def unit_label(kind: str, units: Optional[str] = None) -> str:
    """The label for a `unit:<kind>` field: depth, pressure, pressure_lower,
    temp, sac, volume_rate, depth_rate."""
    return {
        "depth": depth_label, "pressure": pressure_label, "temp": temperature_label, "sac": sac_label,
        "volume_rate": volume_rate_label, "depth_rate": depth_rate_label,
        "pressure_lower": lambda u=None: pressure_label(u, upper=False),
    }.get(kind, lambda u=None: "")(units)


def depth_decimals(display_rule: Optional[Dict[str, Any]], units: Optional[str] = None) -> int:
    """How many decimals a brand shows on a depth in `units` (its
    `display.depth_decimals` rule: {"metric": 1, "imperial": 0} by default)."""
    units = units or current_units()
    rule = display_rule.get("depth_decimals") if isinstance(display_rule, dict) else None
    if isinstance(rule, dict) and units in rule:
        return int(rule[units])
    return 1 if units == METRIC else 0


def format_depth(metres: Optional[float], units: Optional[str] = None, decimals: Optional[int] = None, display_rule: Optional[Dict[str, Any]] = None) -> str:
    if metres is None:
        return "--"
    units = units or current_units()
    d = decimals if decimals is not None else depth_decimals(display_rule, units)
    return f"{depth(metres, units):.{d}f}"


def format_pressure(bar: Optional[float], units: Optional[str] = None) -> str:
    return "--" if bar is None else str(int(round(pressure(bar, units))))


def format_temperature(celsius: Optional[float], units: Optional[str] = None, decimals: int = 0) -> str:
    return "--" if celsius is None else f"{temperature(celsius, units):.{decimals}f}"
