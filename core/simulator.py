from core.vehicle_model import VehicleModel
from core.battery_model import BatteryModel
from core.track_generator import TrackGenerator

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
        
    def load_track(self, track_class: str = "Balanced"):
        self.track_generator = TrackGenerator(track_class=track_class)
        self.track = self.track_generator.generate_track()
        
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
        # Actual power delivered in W
        actual_power_w = (actual_discharge_mj * 1000000.0) / dt_s if dt_s > 0 else 0.0
        
        net_a = self.vehicle.get_net_acceleration(self.velocity_m_s, actual_power_w)
        
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
        self.distance_m += self.velocity_m_s * dt_s
        self.time_s += dt_s
