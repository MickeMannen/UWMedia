import pytest
from datetime import datetime
from pathlib import Path
from parsers.base import BaseParser
from parsers.garmin import GarminParser
from models.dive import Waypoint, Dive, TankData


class TestGarmin:

    def test_load(self):
        file = Path(__file__).parent.parent / "test_data" / "logs" / "fit" / "488 Phuket, Camera Bay.fit"
        dives = GarminParser().parse(file_path=file)

        assert len(dives) > 0
        dive = dives[0]
        assert dive.start_time is not None
        assert len(dive.waypoints) > 0
        assert dive.device is not None
        
        # Check first waypoint
        wp = dive.waypoints[0]
        assert wp.depth >= 0
        assert wp.temp != 0
        
        # Verify tanks
        # We expect 2 tanks as per user report and debug output
        assert len(wp.tanks) == 2
        print(f"Found {len(wp.tanks)} tanks: {list(wp.tanks.keys())}")

    def test_n2_tissue_load_field(self):
        # n2_tissue_load is Garmin's own tissue-load percentage (not bounded to
        # 0-100 - see its docstring in models/dive.py), not the
        # Subsurface/UDDF-computed current GF that used to share the "n2" name -
        # see rework_hud.md Phase 2 item 12).
        file = Path(__file__).parent.parent / "test_data" / "logs" / "fit" / "488 Phuket, Camera Bay.fit"
        dives = GarminParser().parse(file_path=file)
        wp = dives[0].waypoints[0]
        assert wp.n2_tissue_load is not None
        assert not hasattr(wp, "n2")

    def test_dive_alerts_parsed_from_events(self):
        # This fixture's event_mesgs carries real dive_alert markers, including
        # deco-related ones not present in the other sample logs.
        file = Path(__file__).parent.parent / "test_data" / "logs" / "fit" / "garmin_2023-10-21-12-13-38.fit"
        dives = GarminParser().parse(file_path=file)
        dive = dives[0]

        all_alerts = {alert for wp in dive.waypoints for alert in wp.dive_alerts}
        assert "approaching_first_deco_stop" in all_alerts
        assert "deco_ceiling_broken" in all_alerts
        assert "ndl_reached" in all_alerts

        # This alert fires exactly once in the log - confirm it lands on exactly
        # one waypoint (no duplication, no loss)
        wps_with_alert = [wp for wp in dive.waypoints if "approaching_first_deco_stop" in wp.dive_alerts]
        assert len(wps_with_alert) == 1

        # deco_ceiling_broken fires 9 times in this log - every occurrence should
        # be captured (not collapsed/lost), even if several share a waypoint bucket
        deco_break_hits = sum(wp.dive_alerts.count("deco_ceiling_broken") for wp in dive.waypoints)
        assert deco_break_hits == 9


def test_garmin_ascent_rate_is_reported_in_m_per_min_positive_when_ascending():
    from pathlib import Path
    from parsers.garmin import GarminParser
    dives = GarminParser().parse(Path("test_data/logs/fit/413 Phuket Single-Gas Dive_ mk3i.fit"))
    wps = dives[0].waypoints
    rates = [w.ascent_rate for w in wps if w.ascent_rate is not None]
    assert 5.0 < max(rates) < 30.0          # a recreational ascent peaks well above 5 m/min, never 30 (m/s would be ~0.26)
    shallower = [b.ascent_rate for a, b in zip(wps, wps[1:]) if a.depth is not None and b.depth is not None and b.depth < a.depth - 0.3]
    assert sum(shallower) / len(shallower) > 0
