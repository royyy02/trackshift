import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.regulation_config import ENERGY_STORE_CAP_MJ, MAX_MGU_K_REGEN_POWER_KW
from config.battery_config import DRIVE_REGEN_ROUND_TRIP_EFFICIENCY

class BatteryModel:
    """
    MVP battery model per PRD Section 11.1.
    """
    
    def __init__(self, initial_soc_mj: float = ENERGY_STORE_CAP_MJ):
        self.capacity_mj = ENERGY_STORE_CAP_MJ
        self.soc_mj = min(max(initial_soc_mj, 0.0), self.capacity_mj)
        self.regen_efficiency = DRIVE_REGEN_ROUND_TRIP_EFFICIENCY
        self.max_regen_power_kw = MAX_MGU_K_REGEN_POWER_KW
        
    def update_soc(self, e_discharge_mj: float, e_regen_mj: float):
        """
        Update SOC based on energy deployed and regenerated.
        SOC_{t+1} = SOC_t - E_discharge(t) + n_regen * E_regen(t)
        """
        # Ensure we don't discharge more than we have
        actual_discharge_mj = min(e_discharge_mj, self.soc_mj)
        
        # Apply efficiency to regen
        net_regen_mj = self.regen_efficiency * e_regen_mj
        
        self.soc_mj = self.soc_mj - actual_discharge_mj + net_regen_mj
        self.soc_mj = min(max(self.soc_mj, 0.0), self.capacity_mj)
        
    def get_available_energy_mj(self) -> float:
        """Return currently available SOC in MJ."""
        return self.soc_mj


if __name__ == "__main__":
    battery = BatteryModel()
    print(f"Capacity: {battery.capacity_mj} MJ, starting SOC: {battery.soc_mj} MJ")
    battery.update_soc(e_discharge_mj=1.5, e_regen_mj=0.0)
    print(f"After discharging 1.5 MJ: SOC = {battery.get_available_energy_mj():.3f} MJ")
    battery.update_soc(e_discharge_mj=0.0, e_regen_mj=0.5)
    print(f"After regenerating 0.5 MJ (at {battery.regen_efficiency:.0%} efficiency): "
          f"SOC = {battery.get_available_energy_mj():.3f} MJ")
