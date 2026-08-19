import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import math
from config.vehicle_config import (
    VEHICLE_MASS_KG,
    CDA,
    CLA,
    ROLLING_RESISTANCE_COEFFICIENT,
    PEAK_LATERAL_ACCELERATION_G,
    PEAK_LONGITUDINAL_DECELERATION_G
)

# Constants
AIR_DENSITY_KG_M3 = 1.225
GRAVITY_M_S2 = 9.81

class VehicleModel:
    """
    Reduced-order point-mass longitudinal model with a corner-speed cap, 
    as defined in PRD Section 10.
    """
    
    def __init__(self):
        self.mass = VEHICLE_MASS_KG
        self.cda = CDA
        self.cla = CLA
        self.crr = ROLLING_RESISTANCE_COEFFICIENT
        self.mu_lateral = PEAK_LATERAL_ACCELERATION_G
        self.mu_longitudinal = PEAK_LONGITUDINAL_DECELERATION_G
        
    def get_corner_speed_limit(self, radius_m: float) -> float:
        """v_corner_max considering aerodynamic downforce"""
        # Ensure we don't sqrt a negative or zero radius if straight
        if radius_m <= 0 or math.isinf(radius_m):
            return float('inf')
        
        # μ_lateral * (mass * g + 0.5 * rho * CLA * v^2) = mass * v^2 / r
        # v = sqrt( (μ_lateral * mass * g) / (mass / r - μ_lateral * 0.5 * rho * CLA) )
        numerator = self.mu_lateral * self.mass * GRAVITY_M_S2
        aero_term = self.mu_lateral * 0.5 * AIR_DENSITY_KG_M3 * self.cla
        denominator = (self.mass / radius_m) - aero_term
        
        if denominator <= 0:
            return 355.0 / 3.6 # Cap at max deployment speed (98.6 m/s)
            
        calculated_limit = math.sqrt(numerator / denominator)
        return min(calculated_limit, 355.0 / 3.6)
        
    def get_max_braking_deceleration(self) -> float:
        """Maximum physical deceleration from braking"""
        return self.mu_longitudinal * GRAVITY_M_S2
        
    def calculate_forces(self, velocity_m_s: float) -> dict:
        """Calculate drag, downforce, and rolling resistance."""
        f_drag = 0.5 * AIR_DENSITY_KG_M3 * self.cda * (velocity_m_s ** 2)
        f_downforce = 0.5 * AIR_DENSITY_KG_M3 * self.cla * (velocity_m_s ** 2)
        f_roll = self.crr * (self.mass * GRAVITY_M_S2 + f_downforce)
        return {
            "f_drag": f_drag,
            "f_downforce": f_downforce,
            "f_roll": f_roll
        }
        
    def get_net_acceleration(self, velocity_m_s: float, p_available_w: float) -> float:
        """
        Calculate net acceleration given current velocity and available power.
        F_drive = min(P_available(t)/v, F_traction_max)
        """
        forces = self.calculate_forces(velocity_m_s)
        f_drag = forces["f_drag"]
        f_downforce = forces["f_downforce"]
        f_roll = forces["f_roll"]
        
        # Traction limit from longitudinal grip
        f_traction_max = self.mu_longitudinal * (self.mass * GRAVITY_M_S2 + f_downforce)
        
        if velocity_m_s < 0.1:
            f_drive_unlimited = p_available_w / 0.1 # avoid division by 0
        else:
            f_drive_unlimited = p_available_w / velocity_m_s
            
        f_drive = min(f_drive_unlimited, f_traction_max)
        
        net_a = (f_drive - f_drag - f_roll) / self.mass
        return net_a


if __name__ == "__main__":
    vehicle = VehicleModel()
    print(f"Mass: {vehicle.mass} kg, CdA: {vehicle.cda}, ClA: {vehicle.cla}")
    for radius in (15, 30, 60, 100, 150, 250):
        v_limit = vehicle.get_corner_speed_limit(radius)
        print(f"  corner radius {radius:4d} m -> speed limit {v_limit * 3.6:6.1f} km/h")
    print(f"Max braking deceleration: {vehicle.get_max_braking_deceleration():.1f} m/s^2")
    print(f"Net accel at 50 m/s, 400 kW: {vehicle.get_net_acceleration(50.0, 400_000):.2f} m/s^2")
