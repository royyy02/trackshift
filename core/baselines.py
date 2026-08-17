import math
from config.regulation_config import MAX_MGU_K_DEPLOY_POWER_KW, DEPLOYMENT_CURVE, MAX_MGU_K_REGEN_POWER_KW

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
    Similar to Baseline 0 but might be slightly smarter about braking zones.
    """
    def get_action(self, simulator_state) -> tuple[float, float]:
        v_kmh = simulator_state.velocity_m_s * 3.6
        max_deploy = get_max_deploy_power(v_kmh)
        
        # If we need to brake for a corner, we regen instead
        # We need to know upcoming curvature. For now, assume a simple threshold or just max deploy.
        # We'll just max deploy if SOC > 0.
        if simulator_state.battery.soc_mj > 0.0:
            return (max_deploy, MAX_MGU_K_REGEN_POWER_KW) # Sim will cap regen physically
        return (0.0, MAX_MGU_K_REGEN_POWER_KW)

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
            return (max_deploy, MAX_MGU_K_REGEN_POWER_KW)
        return (0.0, MAX_MGU_K_REGEN_POWER_KW)

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
        
        # If we have budget, deploy a conservative amount, else 0
        if simulator_state.battery.soc_mj > 0.5:
            return (max_deploy * 0.7, MAX_MGU_K_REGEN_POWER_KW)
        return (0.0, MAX_MGU_K_REGEN_POWER_KW)
