import numpy as np
from core.simulator import Simulator

class Forecaster:
    """
    Short-horizon energy/speed forecaster (PRD Section 13 & 14).
    Physics-based extrapolation with explicit uncertainty.
    """
    def __init__(self, simulator: Simulator):
        self.simulator = simulator
        # For a simple regression/learning, we could store recent telemetry history
        self.history_e_discharge = []
        self.history_e_regen = []
        
    def predict_energy_required(self, horizon_m: float) -> tuple[float, float]:
        """
        Predicts the required energy to finish the horizon under a baseline-competitive profile.
        Returns:
            (Ê_required_mj, σ_Ê_mj) : Mean point forecast and uncertainty std dev
        """
        # A simple physics-based prediction:
        # Assuming average speed and average power consumption based on recent laps/steps
        # Since we might not have history at t=0, we use a heuristic based on track
        avg_power_kw_estimate = 200.0  # Assumed average deploy power
        avg_speed_m_s_estimate = 60.0  # Assumed average speed (216 km/h)
        
        # Time to cover horizon
        estimated_time_s = horizon_m / avg_speed_m_s_estimate
        
        # Energy required = Power * time
        e_required_mj = (avg_power_kw_estimate * 0.001) * estimated_time_s
        
        # Uncertainty: base it on a fixed percentage for physics-extrapolation
        # In a real model, this would spike after a disturbance
        sigma_e_mj = e_required_mj * 0.05  # 5% uncertainty
        
        return e_required_mj, sigma_e_mj

    def get_strategic_reserve(self, e_required_mj: float, sigma_e_mj: float) -> float:
        """
        Calculates dynamic safety reserve based on uncertainty (PRD Section 15).
        R_safety(t) = R_base + k * σ_Ê(t) + R_event_contingency(t)
        """
        R_base = 0.5  # Fixed floor MJ
        k = 2.0       # 2 sigma for 95% confidence
        R_event_contingency = 0.0 # Could be updated externally if safety car expected
        
        return R_base + (k * sigma_e_mj) + R_event_contingency
