import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.regulation_config import DEPLOYMENT_CURVE, MAX_MGU_K_REGEN_POWER_KW

def get_max_deploy_power(velocity_kmh: float) -> float:
    """Interpolate max deployment power from the regulatory curve based on speed."""
    if velocity_kmh <= DEPLOYMENT_CURVE[0]["speed_kmh"]:
        return DEPLOYMENT_CURVE[0]["power_kw"]
    if velocity_kmh >= DEPLOYMENT_CURVE[-1]["speed_kmh"]:
        return DEPLOYMENT_CURVE[-1]["power_kw"]
        
    for i in range(len(DEPLOYMENT_CURVE) - 1):
        p1 = DEPLOYMENT_CURVE[i]
        p2 = DEPLOYMENT_CURVE[i+1]
        if p1["speed_kmh"] <= velocity_kmh <= p2["speed_kmh"]:
            ratio = (velocity_kmh - p1["speed_kmh"]) / (p2["speed_kmh"] - p1["speed_kmh"])
            return p1["power_kw"] + ratio * (p2["power_kw"] - p1["power_kw"])
    return 0.0

class BaselinePolicy:
    def get_action(self, simulator_state) -> tuple[float, float]:
        """
        Returns (requested_power_kw, requested_regen_kw)
        """
        raise NotImplementedError

class Baseline0_NoOptimization(BaselinePolicy):
    """
    Fixed maximum deployment until depleted, then forced near-zero.
    """
    def get_action(self, simulator_state) -> tuple[float, float]:
        v_kmh = simulator_state.velocity_m_s * 3.6
        max_deploy = get_max_deploy_power(v_kmh)
        max_regen = MAX_MGU_K_REGEN_POWER_KW
        
        # Determine if we are braking based on track corner limits
        # Simplified: if we are over the upcoming corner speed, we should brake/regen.
        # However, baselines need a simple heuristic for when to regen.
        # Let's say if we aren't deploying, we are regenerating.
        # But for Baseline 0, we just deploy if we have SOC.
        if simulator_state.battery.soc_mj > 0.1:
            return (max_deploy, 0.0)
        else:
            return (0.0, max_regen)

class Baseline1_Aggressive(BaselinePolicy):
    """
    u = u_deploy_max whenever SOC > 0, ignoring reserve.
    """
    def get_action(self, simulator_state) -> tuple[float, float]:
        v_kmh = simulator_state.velocity_m_s * 3.6
        max_deploy = get_max_deploy_power(v_kmh)

        # [Fix] Previously requested full regen simultaneously with max deploy on every
        # step (nonsensical -- floor it and brake at once) and again once depleted, which
        # walled off the ICE for the rest of the run (see core/simulator.py's ICE gate).
        # This baseline has no corner-approach awareness, so it should coast (not brake)
        # when it isn't deploying; the corner-speed cap already enforces safety physically.
        if simulator_state.battery.soc_mj > 0.0:
            return (max_deploy, 0.0)
        return (0.0, 0.0)

class Baseline2_Conservative(BaselinePolicy):
    """
    u capped well below max at all times.
    """
    def __init__(self, cap_fraction=0.5):
        self.cap_fraction = cap_fraction

    def get_action(self, simulator_state) -> tuple[float, float]:
        v_kmh = simulator_state.velocity_m_s * 3.6
        max_deploy = get_max_deploy_power(v_kmh) * self.cap_fraction

        if simulator_state.battery.soc_mj > 0.0:
            return (max_deploy, 0.0)
        return (0.0, 0.0)

class Baseline3_FixedHeuristic(BaselinePolicy):
    """
    Predetermined per-lap schedule set once at race start from average-case forecast.
    """
    def __init__(self, energy_budget_per_lap_mj=2.0):
        self.energy_budget_per_lap_mj = energy_budget_per_lap_mj
        self.lap_energy_used = 0.0
        self.current_lap = 0

    def get_action(self, simulator_state) -> tuple[float, float]:
        # Track lap changes to reset budget (needs lap tracking in simulator)
        # For now, simplistic budget checking
        v_kmh = simulator_state.velocity_m_s * 3.6
        max_deploy = get_max_deploy_power(v_kmh)

        # If we have budget, deploy a conservative amount, else coast (see Baseline1's fix note)
        if simulator_state.battery.soc_mj > 0.5:
            return (max_deploy * 0.7, 0.0)
        return (0.0, 0.0)


if __name__ == "__main__":
    from core.simulator import Simulator

    sim = Simulator()
    sim.load_track("Balanced", laps=1, seed=1)
    sim.velocity_m_s = 40.0

    policies = {
        "Baseline 0 (No Opt)": Baseline0_NoOptimization(),
        "Baseline 1 (Aggressive)": Baseline1_Aggressive(),
        "Baseline 2 (Conservative)": Baseline2_Conservative(0.6),
        "Baseline 3 (Fixed Heuristic)": Baseline3_FixedHeuristic(),
    }
    for name, policy in policies.items():
        deploy_kw, regen_kw = policy.get_action(sim)
        print(f"{name:28s} -> deploy={deploy_kw:6.1f} kW, regen={regen_kw:6.1f} kW")
