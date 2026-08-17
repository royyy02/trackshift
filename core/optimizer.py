import numpy as np
import math
from scipy.optimize import minimize
from core.simulator import Simulator
from config.regulation_config import DEPLOYMENT_CURVE, MAX_MGU_K_REGEN_POWER_KW
from config.battery_config import DRIVE_REGEN_ROUND_TRIP_EFFICIENCY

class MPCOptimizer:
    """
    Receding-horizon optimizer (PRD Section 16 & 17).
    """
    def __init__(self, simulator: Simulator, forecaster, horizon_steps: int = 5):
        self.simulator = simulator
        self.forecaster = forecaster
        self.horizon_steps = horizon_steps
        
        # Penalties (Section 16.5)
        self.lambda_reserve = 100.0  # tuned down from 1000.0
        self.lambda_stability = 0.5  # tuned down from 10.0
        self.discharge_efficiency = math.sqrt(DRIVE_REGEN_ROUND_TRIP_EFFICIENCY)
        
    def get_max_deploy_power(self, velocity_kmh: float) -> float:
        if velocity_kmh <= DEPLOYMENT_CURVE[0]["speed_kmh"]: return DEPLOYMENT_CURVE[0]["power_kw"]
        if velocity_kmh >= DEPLOYMENT_CURVE[-1]["speed_kmh"]: return DEPLOYMENT_CURVE[-1]["power_kw"]
        for i in range(len(DEPLOYMENT_CURVE) - 1):
            p1, p2 = DEPLOYMENT_CURVE[i], DEPLOYMENT_CURVE[i+1]
            if p1["speed_kmh"] <= velocity_kmh <= p2["speed_kmh"]:
                ratio = (velocity_kmh - p1["speed_kmh"]) / (p2["speed_kmh"] - p1["speed_kmh"])
                return p1["power_kw"] + ratio * (p2["power_kw"] - p1["power_kw"])
        return 0.0

    def get_action(self, simulator_state, dt_s=1.0) -> tuple[float, float]:
        """
        Runs the MPC optimization over the horizon to find the optimal deployment sequence.
        Returns the first action of the optimal sequence (u_deploy, u_regen).
        """
        v_kmh = simulator_state.velocity_m_s * 3.6
        max_deploy_current = self.get_max_deploy_power(v_kmh)
        
        # Distance proxy for prediction
        horizon_m = self.horizon_steps * max(10.0, simulator_state.velocity_m_s) * dt_s 
        e_req, sig_e = self.forecaster.predict_energy_required(horizon_m)
        r_safety = self.forecaster.get_strategic_reserve(e_req, sig_e)
        
        def objective(u_sequence):
            cost = 0.0
            sim_soc = simulator_state.battery.soc_mj
            
            for i, u_kw in enumerate(u_sequence):
                # Maximize speed = minimize -u_kw
                cost -= u_kw 
                
                # Penalize chattering (λ_stability · |u(t) − u(t−1)|)
                if i > 0:
                    cost += self.lambda_stability * abs(u_kw - u_sequence[i-1])
                
                # Simple SOC update proxy (now accounting for discharge efficiency)
                sim_soc -= (u_kw * 0.001 * dt_s) / self.discharge_efficiency
                
                # Soft penalty for reserve violations
                deployable_energy = sim_soc - e_req - r_safety
                if deployable_energy < 0:
                    cost += self.lambda_reserve * abs(deployable_energy)
                    
            return cost
            
        u0 = np.full(self.horizon_steps, max_deploy_current * 0.5)
        bounds = [(0, max_deploy_current) for _ in range(self.horizon_steps)]
        
        res = minimize(objective, u0, bounds=bounds, method='SLSQP')
        optimal_u_0 = res.x[0] if res.success else 0.0
        
        if optimal_u_0 < 10.0:
            return (0.0, MAX_MGU_K_REGEN_POWER_KW)
        return (optimal_u_0, 0.0)
