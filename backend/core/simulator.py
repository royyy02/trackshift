import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.vehicle_model import VehicleModel
from core.battery_model import BatteryModel
from core.track_generator import TrackGenerator, total_length_m
from config.vehicle_config import ICE_POWER_KW

class Simulator:
    """
    Fast simulator core loop (PRD Section 5.1).
    """

    def __init__(self):
        self.vehicle = VehicleModel()
        self.battery = BatteryModel()
        self.track_generator = TrackGenerator()
        self.track = []
        self.lap_length_m = 0.0
        self.laps_total = 1
        self.lap = 1

        self.time_s = 0.0
        self.velocity_m_s = 0.0
        self.distance_m = 0.0

        self.cumulative_e_discharge_mj = 0.0
        self.cumulative_e_regen_mj = 0.0

        self.current_segment_idx = 0
        self.segment_start_m = 0.0
        self.lap_relative_m = 0.0
        
        # Scenario states
        self.is_raining = False
        self.safety_car_active = False
        self.limited_power_mode = False
        self.safety_car_speed_cap_m_s = 30.0 # ~108 km/h

    def load_track(self, track_class: str = "Balanced", laps: int = 1, seed: int = 42,
                    target_length_m: float = 5000.0):
        """
        Loads a fresh procedural track (PRD Section 9) and configures the race as `laps`
        trips around it, so the simulator's `lap(t)` / `distance_remaining(t)` state
        (PRD Section 16.1) is meaningful rather than a single one-shot distance traverse.
        """
        self.track_generator = TrackGenerator(track_class=track_class, seed=seed)
        self.track = self.track_generator.generate_track(target_length_m=target_length_m)
        self.lap_length_m = total_length_m(self.track)
        self.laps_total = max(1, laps)
        self.lap = 1
        self.current_segment_idx = 0
        self.segment_start_m = 0.0

    @property
    def total_race_distance_m(self) -> float:
        return self.lap_length_m * self.laps_total

    @property
    def distance_remaining_m(self) -> float:
        return max(0.0, self.total_race_distance_m - self.distance_m)

    @property
    def is_finished(self) -> bool:
        return self.lap_length_m > 0 and self.distance_m >= self.total_race_distance_m

    def _update_track_position(self):
        """
        Recomputes lap number and current segment index/start from absolute distance
        travelled, so lap wrap-around (the closed-circuit behavior described in
        core/track_generator.py's docstring) is handled by re-deriving position rather than
        by incrementally walking segments and needing separate wrap-around logic.
        """
        if not self.track or self.lap_length_m <= 0:
            return

        laps_completed = int(self.distance_m // self.lap_length_m)
        self.lap = min(self.laps_total, laps_completed + 1)
        self.lap_relative_m = self.distance_m - laps_completed * self.lap_length_m

        cumulative = 0.0
        for idx, segment in enumerate(self.track):
            if idx == len(self.track) - 1 or cumulative + segment.length_m > self.lap_relative_m:
                self.current_segment_idx = idx
                self.segment_start_m = cumulative
                return
            cumulative += segment.length_m

    def get_next_corner(self) -> tuple[float, float]:
        """
        Returns (distance_to_corner_start, corner_speed_limit_m_s).
        On the final lap, lookahead stops at the finish line (no wrap past it); on earlier
        laps it wraps into the next lap's opening segments, matching the closed-circuit
        semantics.
        """
        self._update_track_position()
        if not self.track:
            return float('inf'), float('inf')

        current_segment = self.track[self.current_segment_idx]
        dist_to_end = (self.segment_start_m + current_segment.length_m) - self.lap_relative_m

        dist_to_next = dist_to_end
        idx = self.current_segment_idx + 1
        wrapped = False
        while True:
            if idx >= len(self.track):
                if wrapped or self.lap >= self.laps_total:
                    # Already searched a full lap, or no further laps to wrap into.
                    return float('inf'), float('inf')
                idx = 0
                wrapped = True
                continue

            segment = self.track[idx]
            if segment.radius_m != float('inf'):
                # Rain reduces corner grip (lower mu_lateral implies lower limit)
                limit = self.vehicle.get_corner_speed_limit(segment.radius_m)
                if self.is_raining:
                    limit *= 0.8 # approx 36% less cornering grip (sqrt(0.64))
                return dist_to_next, limit
            dist_to_next += segment.length_m
            idx += 1
            
    def inject_disturbance(self, event_type: str, active: bool = True):
        """
        Inject a disturbance (PRD Section 19).
        Types: 'rain', 'safety_car', 'limited_power'
        """
        if event_type == 'rain':
            self.is_raining = active
            # Rain also increases rolling resistance and reduces braking
            if active:
                self.vehicle.crr *= 1.2
                self.vehicle.mu_longitudinal *= 0.8
                self.vehicle.mu_lateral *= 0.8
            else:
                # Naive reset, real implementation would save base values
                self.vehicle.crr /= 1.2
                self.vehicle.mu_longitudinal /= 0.8
                self.vehicle.mu_lateral /= 0.8
        elif event_type == 'safety_car':
            self.safety_car_active = active
        elif event_type == 'limited_power':
            self.limited_power_mode = active

    def step(self, dt_s: float, requested_power_kw: float, requested_regen_kw: float):
        """
        Simulate a single time step.
        """
        # --- Battery interaction ---
        # Convert kW to MJ/s * dt = MJ
        # 1 kW = 0.001 MW = 0.001 MJ/s
        requested_discharge_mj = requested_power_kw * 0.001 * dt_s
        requested_regen_mj = requested_regen_kw * 0.001 * dt_s

        # Check against available battery bounds
        actual_discharge_mj = min(requested_discharge_mj, self.battery.soc_mj)

        # For simulation simplicity in MVP step, we accept requested regen if physical bounds allow.
        # Physics bound: can't regen more kinetic energy than we have
        kinetic_energy_mj = 0.5 * self.vehicle.mass * (self.velocity_m_s ** 2) / 1000000.0
        actual_regen_mj = min(requested_regen_mj, kinetic_energy_mj)

        self.battery.update_soc(actual_discharge_mj, actual_regen_mj)

        self.cumulative_e_discharge_mj += actual_discharge_mj
        self.cumulative_e_regen_mj += actual_regen_mj

        # --- Vehicle dynamics ---
        # Actual MGU-K power delivered in W
        actual_power_w = (actual_discharge_mj * 1000000.0) / dt_s if dt_s > 0 else 0.0

        # Add ICE power (only suppressed while regen is *physically* occurring, not merely
        # requested -- gating on the request alone meant any policy that asked for regen as
        # a "not deploying" fallback, even at near-zero speed where no energy can actually be
        # recaptured, silently lost its 400 kW ICE for the rest of the run)
        ice_power_w = (ICE_POWER_KW * 1000.0) if actual_regen_mj <= 0.0 else 0.0
        total_propulsion_w = actual_power_w + ice_power_w

        net_a = self.vehicle.get_net_acceleration(self.velocity_m_s, total_propulsion_w)

        # Braking / Regen deceleration
        if actual_regen_mj > 0:
            regen_power_w = (actual_regen_mj * 1000000.0) / dt_s if dt_s > 0 else 0.0
            # Force = Power / Velocity
            brake_force = regen_power_w / max(1.0, self.velocity_m_s)
            regen_a = - (brake_force / self.vehicle.mass)
            net_a += regen_a

        # Update state
        self.velocity_m_s += net_a * dt_s
        self.velocity_m_s = max(0.0, self.velocity_m_s)

        self._update_track_position()
        if self.track:
            limit = self.vehicle.get_corner_speed_limit(self.track[self.current_segment_idx].radius_m)
            if self.is_raining:
                limit *= 0.8
            # Physical driver limit - driver won't exceed corner grip
            self.velocity_m_s = min(self.velocity_m_s, limit)
            
        if self.safety_car_active:
            self.velocity_m_s = min(self.velocity_m_s, self.safety_car_speed_cap_m_s)

        self.distance_m += self.velocity_m_s * dt_s
        self.distance_m = min(self.distance_m, self.total_race_distance_m)
        self.time_s += dt_s


if __name__ == "__main__":
    sim = Simulator()
    sim.load_track("Balanced", laps=1, seed=1)
    print(f"Loaded track: {sim.lap_length_m:.1f} m x {sim.laps_total} lap(s)")

    steps = 0
    while not sim.is_finished and steps < 20000:
        sim.step(dt_s=1.0, requested_power_kw=200.0, requested_regen_kw=0.0)
        steps += 1

    print(f"Finished in {steps} steps / {sim.time_s:.1f}s, "
          f"final SOC={sim.battery.soc_mj:.2f} MJ, lap={sim.lap}")
