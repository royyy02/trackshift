import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import math
from scipy.optimize import minimize
from core.simulator import Simulator
from config.regulation_config import DEPLOYMENT_CURVE
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
        
    def get_max_deploy_power(self, velocity_kmh: float, limited_power_mode: bool = False) -> float:
        from config.regulation_config import DEPLOYMENT_CURVE, LIMITED_POWER_MODE_CURVE
        curve = LIMITED_POWER_MODE_CURVE if limited_power_mode else DEPLOYMENT_CURVE
        
        if velocity_kmh <= curve[0]["speed_kmh"]: return curve[0]["power_kw"]
        if velocity_kmh >= curve[-1]["speed_kmh"]: return curve[-1]["power_kw"]
        for i in range(len(curve) - 1):
            p1, p2 = curve[i], curve[i+1]
            if p1["speed_kmh"] <= velocity_kmh <= p2["speed_kmh"]:
                ratio = (velocity_kmh - p1["speed_kmh"]) / (p2["speed_kmh"] - p1["speed_kmh"])
                return p1["power_kw"] + ratio * (p2["power_kw"] - p1["power_kw"])
        return 0.0

    def _solve_sequence(self, horizon_steps, max_deploy_power, sim_soc_start, e_req, r_safety, dt_s):
        """
        Solves for the cost-minimizing deployment-power sequence over `horizon_steps`,
        returning the full optimal sequence (kW per step). Factored out so both the
        receding-horizon get_action() (short horizon, re-solved every call) and
        OracleOptimizer's one-shot full-race solve (long horizon, solved once) share a
        single objective/constraint implementation rather than two copies drifting apart.
        """
        def objective(u_sequence):
            cost = 0.0
            sim_soc = sim_soc_start

            for i, u_kw in enumerate(u_sequence):
                # Maximize speed = minimize -u_kw
                cost -= u_kw

                # Penalize chattering (λ_stability · |u(t) − u(t−1)|)
                if i > 0:
                    cost += self.lambda_stability * abs(u_kw - u_sequence[i - 1])

                # Simple SOC update proxy (now accounting for discharge efficiency)
                sim_soc -= (u_kw * 0.001 * dt_s) / self.discharge_efficiency

                # Soft penalty for reserve violations (convert MJ to kW-equivalent)
                deployable_energy = sim_soc - e_req - r_safety
                if deployable_energy < 0:
                    cost += self.lambda_reserve * (abs(deployable_energy) * 1000.0 / dt_s)

            return cost

        u0 = np.full(horizon_steps, max_deploy_power * 0.5)
        bounds = [(0, max_deploy_power) for _ in range(horizon_steps)]

        res = minimize(objective, u0, bounds=bounds, method='SLSQP')
        return res.x if res.success else np.zeros(horizon_steps)

    def get_action(self, simulator_state, dt_s=1.0) -> tuple[float, float]:
        """
        Runs the MPC optimization over the horizon to find the optimal deployment sequence.
        Returns the first action of the optimal sequence (u_deploy, u_regen).
        """
        v_kmh = simulator_state.velocity_m_s * 3.6
        max_deploy_current = self.get_max_deploy_power(v_kmh, simulator_state.limited_power_mode)

        # -------------------------------------------------------------
        # Corner Braking / Regen Logic
        # -------------------------------------------------------------
        dist_to_next, limit_m_s = simulator_state.get_next_corner()
        current_v = simulator_state.velocity_m_s
        
        if current_v > limit_m_s:
            max_decel = simulator_state.vehicle.get_max_braking_deceleration()
            # Braking distance required to reach limit_m_s
            braking_dist = (current_v**2 - limit_m_s**2) / (2 * max_decel)
            
            # If we are within the braking zone (plus a small safety margin), apply full regen
            if dist_to_next <= braking_dist + 15.0:
                from config.regulation_config import MAX_MGU_K_REGEN_POWER_KW
                return (0.0, float(MAX_MGU_K_REGEN_POWER_KW))

        # Distance remaining for full-race prediction
        distance_remaining_m = simulator_state.distance_remaining_m
        e_req, sig_e = self.forecaster.predict_energy_required(distance_remaining_m)
        r_safety = 0.10 + 2.0 * sig_e
        
        # Soft-then-hard reserve logic (Section 16.4 & 16.5)
        # In MVP, we keep it hard if reserve is tight
        deployable_mj = simulator_state.battery.soc_mj - e_req - r_safety
        if deployable_mj <= 0:
            max_deploy_current = 0.0 # Force conserve

        u_sequence = self._solve_sequence(
            self.horizon_steps, max_deploy_current, simulator_state.battery.soc_mj,
            e_req, r_safety, dt_s,
        )

        optimal_u_0 = u_sequence[0]
        return (optimal_u_0, 0.0)

    def evaluate_overtake_opportunity(self, simulator_state) -> dict | None:
        """
        Dynamically evaluates the risk/reward of overtaking on an upcoming straight.
        Returns a dict with assessment details if an opportunity is detected, else None.
        """
        if not simulator_state.track:
            return None
            
        current_segment = simulator_state.track[simulator_state.current_segment_idx]
        
        # Only consider overtakes on straights longer than 400m
        if current_segment.segment_type != 'straight' or current_segment.length_m < 400:
            return None
            
        # If we are near the end of the straight, don't trigger (e.g. less than 150m left)
        dist_remaining_in_seg = (simulator_state.segment_start_m + current_segment.length_m) - simulator_state.lap_relative_m
        if dist_remaining_in_seg < 150:
            return None
            
        # --- Dynamic Cost Calculation ---
        # Need a speed delta to overtake (e.g. +15 km/h = ~4.17 m/s)
        delta_v_m_s = 15.0 / 3.6
        overtake_v = simulator_state.velocity_m_s + delta_v_m_s
        
        # Estimate power required to maintain this speed against drag
        # Drag force = 0.5 * rho * CdA * v^2
        rho = 1.225
        CdA = 1.0 # From engineering assumptions
        drag_force = 0.5 * rho * CdA * (overtake_v ** 2)
        rolling_res = 0.015 * simulator_state.vehicle.mass * 9.81
        total_force = drag_force + rolling_res
        
        # Power = Force * Velocity
        power_w = total_force * overtake_v
        
        # Time to complete overtake (e.g. over 300m)
        time_to_overtake_s = 300.0 / max(1.0, overtake_v)
        
        # Energy cost (Joules -> MJ)
        energy_cost_mj = (power_w * time_to_overtake_s) / 1_000_000.0
        
        # Add a baseline MGU-K override cost to simulate the burst
        energy_cost_mj += 0.2
        
        # Determine Deployable Energy
        distance_remaining_m = simulator_state.distance_remaining_m
        e_req, sig_e = self.forecaster.predict_energy_required(distance_remaining_m)
        r_safety = 0.10 + 2.0 * sig_e
        deployable_mj = simulator_state.battery.soc_mj - e_req - r_safety
        
        # Evaluate Risk
        if deployable_mj > energy_cost_mj + 0.2:
            risk = "LOW"
            recommendation = "ATTACK"
        elif deployable_mj > 0:
            risk = "MARGINAL"
            recommendation = "DRIVER DISCRETION"
        else:
            risk = "HIGH"
            recommendation = "HOLD"
            
        # Expected time gain
        time_gain_s = 300.0 / max(1.0, simulator_state.velocity_m_s) - time_to_overtake_s
        
        return {
            "cost_mj": round(energy_cost_mj, 2),
            "reward_s": round(max(0.1, time_gain_s), 2),
            "risk": risk,
            "recommendation": recommendation,
            "deployable_mj": round(deployable_mj, 2)
        }


if __name__ == "__main__":
    from core.forecaster import Forecaster

    sim = Simulator()
    sim.load_track("Balanced", laps=1, seed=1)
    sim.velocity_m_s = 40.0
    forecaster = Forecaster(sim)
    optimizer = MPCOptimizer(sim, forecaster, horizon_steps=5)

    u_deploy, u_regen = optimizer.get_action(sim, dt_s=1.0)
    print(f"At v={sim.velocity_m_s} m/s, SOC={sim.battery.soc_mj} MJ: "
          f"deploy={u_deploy:.1f} kW, regen={u_regen:.1f} kW")
