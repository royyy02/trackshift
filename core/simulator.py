from core.vehicle_model import VehicleModel
from core.battery_model import BatteryModel
from core.track_generator import TrackGenerator
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
        
        self.time_s = 0.0
        self.velocity_m_s = 0.0
        self.distance_m = 0.0
        
        self.cumulative_e_discharge_mj = 0.0
        self.cumulative_e_regen_mj = 0.0
        
        self.current_segment_idx = 0
        self.segment_start_m = 0.0
        
    def load_track(self, track_class: str = "Balanced"):
        self.track_generator = TrackGenerator(track_class=track_class)
        self.track = self.track_generator.generate_track()
        self.current_segment_idx = 0
        self.segment_start_m = 0.0
        
    def _update_track_position(self):
        if not self.track or self.current_segment_idx >= len(self.track):
            return
            
        current_segment = self.track[self.current_segment_idx]
        if self.distance_m >= self.segment_start_m + current_segment.length_m:
            self.segment_start_m += current_segment.length_m
            self.current_segment_idx += 1
            
    def get_next_corner(self) -> tuple[float, float]:
        """
        Returns (distance_to_corner_start, corner_speed_limit_m_s).
        """
        self._update_track_position()
        if not self.track or self.current_segment_idx >= len(self.track):
            return float('inf'), float('inf')
            
        current_segment = self.track[self.current_segment_idx]
        dist_to_end = (self.segment_start_m + current_segment.length_m) - self.distance_m
        
        dist_to_next = dist_to_end
        for i in range(self.current_segment_idx + 1, len(self.track)):
            segment = self.track[i]
            if segment.radius_m != float('inf'):
                limit = self.vehicle.get_corner_speed_limit(segment.radius_m)
                return dist_to_next, limit
            dist_to_next += segment.length_m
            
        return float('inf'), float('inf')
        
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
        
        # Add ICE power (only applied if not actively braking/regenerating)
        ice_power_w = (ICE_POWER_KW * 1000.0) if requested_regen_kw <= 0.0 else 0.0
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
        if self.track and self.current_segment_idx < len(self.track):
            limit = self.vehicle.get_corner_speed_limit(self.track[self.current_segment_idx].radius_m)
            # Physical driver limit - driver won't exceed corner grip
            self.velocity_m_s = min(self.velocity_m_s, limit)
            
        self.distance_m += self.velocity_m_s * dt_s
        self.time_s += dt_s
