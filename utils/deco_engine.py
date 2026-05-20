import copy
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from pydantic import BaseModel, Field

# --- 1. Data Models ---

@dataclass(frozen=True)
class CompartmentConstants:
    """ZH-L16B constants for a single tissue compartment."""
    n2_half_life: float
    n2_a: float
    n2_b: float
    he_half_life: float
    he_a: float
    he_b: float

@dataclass
class CompartmentState:
    """Current partial pressures of inert gases in a tissue compartment."""
    p_n2: float
    p_he: float

class TTSDataPoint(BaseModel):
    """Pydantic model for calculated decompression data at a specific time."""
    timestamp: datetime
    depth: float
    tts_seconds: int = Field(description="Total Time to Surface")
    ceiling_meters: float = Field(description="Current decompression ceiling")
    active_gas: str
    gf_current: float
    cns: float = Field(default=0.0, description="Cumulative CNS toxicity percentage")
    po2: float = Field(default=0.0, description="Partial pressure of oxygen")

# --- 2. Bühlmann ZH-L16 Engine Implementation ---

class BuhlmannEngine:
    """
    Core decompression engine implementing the Bühlmann ZH-L16 algorithm.
    Uses ZH-L16B coefficients (typical for dive computers).
    """
    
    # ZH-L16B coefficients (N2 and He)
    # Format: (N2 HalfLife, N2 A, N2 B, He HalfLife, He A, He B)
    COEFFICIENTS = [
        CompartmentConstants(4.0, 1.2599, 0.5050, 1.51, 1.7424, 0.4245),
        CompartmentConstants(8.0, 1.0000, 0.5659, 3.03, 1.3830, 0.4902),
        CompartmentConstants(12.5, 0.8618, 0.6122, 4.72, 1.1919, 0.5404),
        CompartmentConstants(18.5, 0.7562, 0.6469, 6.99, 1.0458, 0.5818),
        CompartmentConstants(27.0, 0.6667, 0.6751, 10.21, 0.9220, 0.6171),
        CompartmentConstants(38.3, 0.5933, 0.6972, 14.48, 0.8205, 0.6453),
        CompartmentConstants(54.3, 0.5282, 0.7154, 20.53, 0.7305, 0.6693),
        CompartmentConstants(77.0, 0.4701, 0.7303, 29.11, 0.6502, 0.6901),
        CompartmentConstants(109.0, 0.4187, 0.7424, 41.20, 0.5789, 0.7081),
        CompartmentConstants(146.0, 0.3798, 0.7523, 55.19, 0.5251, 0.7233),
        CompartmentConstants(187.0, 0.3497, 0.7603, 70.69, 0.4835, 0.7366),
        CompartmentConstants(239.0, 0.3223, 0.7680, 90.34, 0.4457, 0.7490),
        CompartmentConstants(305.0, 0.2971, 0.7760, 115.29, 0.4109, 0.7612),
        CompartmentConstants(390.0, 0.2737, 0.7850, 147.42, 0.3785, 0.7753),
        CompartmentConstants(498.0, 0.2523, 0.7950, 188.24, 0.3489, 0.7891),
        CompartmentConstants(635.0, 0.2327, 0.8060, 240.03, 0.3219, 0.8034),
    ]

    def __init__(self, surface_pressure_bar: float = 1.01325):
        self.surface_pressure = surface_pressure_bar
        # Initialize tissues with partial pressures of Air at surface
        self.tissues = [
            CompartmentState(p_n2=(surface_pressure_bar - 0.00627) * 0.79, p_he=0.0)
            for _ in range(16)
        ]
        self.cns = 0.0

    def update(self, depth_meters: float, time_seconds: float, f_o2: float, f_he: float) -> None:
        """Updates tissue pressures using the Schreiner Equation and calculates CNS."""
        ambient_pressure = self.surface_pressure + (depth_meters / 10.0)
        po2 = ambient_pressure * f_o2
        
        # 1. Update CNS (NOAA Table Based)
        self.cns += self._calculate_cns_increment(po2, time_seconds)
        
        # 2. Update Tissues
        f_n2 = 1.0 - f_o2 - f_he
        pi_n2 = (ambient_pressure - 0.00627) * f_n2
        pi_he = (ambient_pressure - 0.00627) * f_he
        
        time_minutes = time_seconds / 60.0

        for i, tissue in enumerate(self.tissues):
            coeffs = self.COEFFICIENTS[i]
            # Update Nitrogen
            tissue.p_n2 = self._schreiner(tissue.p_n2, pi_n2, time_minutes, coeffs.n2_half_life)
            # Update Helium
            tissue.p_he = self._schreiner(tissue.p_he, pi_he, time_minutes, coeffs.he_half_life)

    def _calculate_cns_increment(self, po2: float, time_seconds: float) -> float:
        """Returns CNS percentage increment for a given PO2 and time using NOAA limits."""
        if po2 <= 0.5:
            return 0.0
            
        # NOAA CNS limits in minutes
        # Using a simplified linear interpolation between points
        limits = [
            (0.6, 720), (0.7, 570), (0.8, 450), (0.9, 360), (1.0, 300),
            (1.1, 240), (1.2, 210), (1.3, 180), (1.4, 150), (1.5, 120), (1.6, 45)
        ]
        
        time_limit = None
        if po2 >= 1.6:
            time_limit = 45
        else:
            # Interpolate
            for i in range(len(limits) - 1):
                p1, l1 = limits[i]
                p2, l2 = limits[i+1]
                if p1 <= po2 <= p2:
                    # Linear interpolation of the limit
                    fraction = (po2 - p1) / (p2 - p1)
                    time_limit = l1 + fraction * (l2 - l1)
                    break
        
        if time_limit:
            # Increment in % (100 / limit_in_seconds * time_seconds)
            return (100.0 / (time_limit * 60.0)) * time_seconds
        return 0.0

    def _schreiner(self, p_initial: float, p_inspired: float, time: float, half_life: float) -> float:
        k = math.log(2) / half_life
        return p_inspired + (p_initial - p_inspired) * math.exp(-k * time)

    def get_ceiling(self, gf: float) -> float:
        """Calculates the current decompression ceiling in meters for a given Gradient Factor."""
        max_ceiling_bar = 0.0
        
        for i, tissue in enumerate(self.tissues):
            coeffs = self.COEFFICIENTS[i]
            p_total = tissue.p_n2 + tissue.p_he
            
            # Weighted A and B coefficients
            a = (coeffs.n2_a * tissue.p_n2 + coeffs.he_a * tissue.p_he) / p_total
            b = (coeffs.n2_b * tissue.p_n2 + coeffs.he_b * tissue.p_he) / p_total
            
            # Bühlmann formula with GF: M = (P_amb / b) + a
            # Ceiling P_amb = (P_tissue - a * GF) / (GF / b + 1 - GF)
            # This is the standard GF-adjusted M-value crossover
            denom = (gf / b) + (1.0 - gf)
            ceiling_bar = (p_total - a * gf) / denom
            
            if ceiling_bar > max_ceiling_bar:
                max_ceiling_bar = ceiling_bar
        
        ceiling_meters = (max_ceiling_bar - self.surface_pressure) * 10.0
        return max(0.0, ceiling_meters)

    def clone(self) -> 'BuhlmannEngine':
        return copy.deepcopy(self)

# --- 3. TTS Processor and Look-Ahead Simulation ---

@dataclass
class GasDefinition:
    name: str
    f_o2: float
    f_he: float
    mod_meters: float

class DiveDecompressor:
    """
    Orchestrates decompression calculations for a dive profile.
    Includes interpolation and look-ahead simulation.
    """
    
    def __init__(self, gf_low: float = 0.30, gf_high: float = 0.70, simulation_interval: int = 10):
        self.engine = BuhlmannEngine()
        self.gf_low = gf_low
        self.gf_high = gf_high
        self.sim_interval = simulation_interval
        self.ascent_rate_mps = 0.15 # 9m/min
        self.safety_stop_time_left = 180.0
        self.safety_stop_triggered = False

    def process_waypoints(self, waypoints: List[dict], gases: List[GasDefinition]) -> Dict[int, TTSDataPoint]:
        """
        Processes raw waypoints and returns a time-series dictionary of TTS results.
        Expected input: list of dicts with {'divetime': sec, 'depth': m, 'datetime': dt}
        """
        if not waypoints:
            return {}

        # 1. Normalize/Interpolate to 1s ticks
        interpolated = self._interpolate_profile(waypoints)
        results: Dict[int, TTSDataPoint] = {}
        
        # Track master state
        last_tts = 0
        last_ceiling = 0.0
        running_max_depth = 0.0
        
        for sec, data in interpolated.items():
            depth = data['depth']
            timestamp = data['datetime']
            running_max_depth = max(running_max_depth, depth)
            
            # Safety Stop Timer Logic (1s resolution)
            if running_max_depth > 10.0:
                self.safety_stop_triggered = True
                if 3.0 <= depth <= 6.0:
                    self.safety_stop_time_left = max(0.0, self.safety_stop_time_left - 1.0)
                elif depth < 3.0:
                    # If diver goes shallower than stop before it's done, some computers cancel, 
                    # others pause. We'll pause/reset if they surface.
                    if depth < 1.0: self.safety_stop_triggered = False 
            
            # Find current gas (simplification: pick best available gas for current depth)
            active_gas = self._get_best_gas(depth, gases)
            
            # Update master tissue state (1 second)
            self.engine.update(depth, 1.0, active_gas.f_o2, active_gas.f_he)
            
            # 2. Stateful TTS Look-Ahead Simulation
            if sec % self.sim_interval == 0:
                tts, ceiling = self._simulate_tts(depth, active_gas, gases, max_depth=running_max_depth)
                last_tts = tts
                last_ceiling = ceiling
            else:
                # Basic decrement for TTS in between intervals if we are at stop
                if 3.0 <= depth <= 6.0 and last_tts > 0:
                    last_tts = max(0, last_tts - 1)
            
            results[sec] = TTSDataPoint(
                timestamp=timestamp,
                depth=depth,
                tts_seconds=last_tts,
                ceiling_meters=last_ceiling,
                active_gas=active_gas.name,
                gf_current=self.gf_high, # Placeholder
                cns=self.engine.cns,
                po2=(self.engine.surface_pressure + (depth / 10.0)) * active_gas.f_o2
            )
            
        return results

    def _interpolate_profile(self, waypoints: List[dict]) -> Dict[int, dict]:
        """Ensures the profile has data points for every 1-second interval."""
        sorted_wps = sorted(waypoints, key=lambda x: x['divetime'])
        max_time = sorted_wps[-1]['divetime']
        
        full_timeline = {}
        wp_idx = 0
        
        for s in range(max_time + 1):
            # Find surrounding waypoints
            while wp_idx < len(sorted_wps) - 1 and sorted_wps[wp_idx+1]['divetime'] <= s:
                wp_idx += 1
            
            p1 = sorted_wps[wp_idx]
            if wp_idx < len(sorted_wps) - 1:
                p2 = sorted_wps[wp_idx+1]
                # Linear interpolation
                dt = p2['divetime'] - p1['divetime']
                if dt > 0:
                    fraction = (s - p1['divetime']) / dt
                    depth = p1['depth'] + (p2['depth'] - p1['depth']) * fraction
                else:
                    depth = p1['depth']
            else:
                depth = p1['depth']
                
            full_timeline[s] = {
                'depth': depth,
                'datetime': p1['datetime'] # Approximate
            }
        return full_timeline

    def _simulate_tts(self, current_depth: float, current_gas: GasDefinition, all_gases: List[GasDefinition], max_depth: float = 0.0) -> Tuple[int, float]:
        """
        Runs a virtual ascent to calculate TTS and current ceiling.
        """
        # Clone current engine state to avoid modifying master tissues
        sim_engine = self.engine.clone()
        current_ceiling = sim_engine.get_ceiling(self.gf_high)
        
        if current_depth <= 0.1:
            return 0, 0.0

        total_time = 0
        sim_depth = current_depth
        sim_gas = current_gas
        
        # Use state from the master decompressor for safety stop
        needs_safety_stop = self.safety_stop_triggered and self.safety_stop_time_left > 0
        safety_stop_done = False

        # 1. Ascent to first stop
        while sim_depth > 0:
            # Determine mandated stop depth (multiples of 3m)
            target_ceiling = sim_engine.get_ceiling(self.gf_low)
            
            # If we are deeper than the ceiling, ascend at 9m/min
            if sim_depth > target_ceiling and sim_depth > 0:
                # Special check for safety stop depth (5m)
                # Only add if we haven't already passed it in the simulation
                if needs_safety_stop and not safety_stop_done and sim_depth <= 5.0:
                    # Add REMAINING safety stop time
                    rem_time = self.safety_stop_time_left
                    total_time += int(rem_time)
                    safety_stop_done = True
                    # Update tissues during safety stop
                    sim_engine.update(5.0, rem_time, sim_gas.f_o2, sim_gas.f_he)
                
                asc_step = min(sim_depth, self.ascent_rate_mps)
                sim_depth -= asc_step
                total_time += 1
                
                # Update simulation state
                sim_gas = self._get_best_gas(sim_depth, all_gases)
                sim_engine.update(sim_depth, 1.0, sim_gas.f_o2, sim_gas.f_he)
            else:
                # Mandatory Deco Stop Logic
                stop_depth = math.ceil(sim_depth / 3.0) * 3.0
                if stop_depth < 3.0: stop_depth = 0.0
                
                if stop_depth == 0:
                    break # Surface reached
                
                # Stay at stop until ceiling allows ascent to next 3m increment
                # Calculate GF for this stop depth (slope between GF Low and High)
                # gf_slope = (sim_depth / current_depth) # simplified
                
                # For look-ahead, we step through time at the stop
                while True:
                    # Check ceiling at next stop (stop_depth - 3)
                    next_stop_ceiling = sim_engine.get_ceiling(self.gf_high)
                    if next_stop_ceiling <= (stop_depth - 3.0):
                        break # Can move to next stop
                    
                    sim_engine.update(stop_depth, 10.0, sim_gas.f_o2, sim_gas.f_he)
                    total_time += 10
                    if total_time > 10000: break # Safety exit
                
                sim_depth = stop_depth - 3.0
                total_time += 20 # Time to move between stops
                
        return total_time, current_ceiling

    def _get_best_gas(self, depth: float, gases: List[GasDefinition]) -> GasDefinition:
        """Selects the richest available gas (highest O2) that is within MOD."""
        # Filter gases by MOD
        available = [g for g in gases if g.mod_meters >= depth]
        if not available:
            # Fallback to air if nothing else fits
            return GasDefinition("AIR", 0.21, 0.0, 100.0)
        # Sort by O2 content descending
        return sorted(available, key=lambda x: x.f_o2, reverse=True)[0]

# --- 4. Example Usage ---
def main():
    # Mock Waypoints
    waypoints = [
        {'divetime': 0, 'depth': 0, 'datetime': datetime.now()},
        {'divetime': 120, 'depth': 40, 'datetime': datetime.now()},
        {'divetime': 1200, 'depth': 40, 'datetime': datetime.now()},
        {'divetime': 1500, 'depth': 20, 'datetime': datetime.now()},
    ]
    
    # Gas Definitions
    gases = [
        GasDefinition("Bottom", 0.21, 0.0, 60.0),
        GasDefinition("Deco 50%", 0.50, 0.0, 21.0),
        GasDefinition("O2", 1.0, 0.0, 6.0)
    ]

    processor = DiveDecompressor(gf_low=0.30, gf_high=0.70, simulation_interval=10)
    results = processor.process_waypoints(waypoints, gases)
    
    # Print some results
    for sec in [600, 1200, 1400]:
        if sec in results:
            print(f"Time {sec}s: Depth {results[sec].depth:.1f}m, TTS {results[sec].tts_seconds//60}min, Ceiling {results[sec].ceiling_meters:.1f}m")

if __name__ == "__main__":
    main()
