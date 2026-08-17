# pyrefly: ignore [missing-import]
import pytest
import math
from core.simulator import Simulator
from config.regulation_config import ENERGY_STORE_CAP_MJ, MAX_MGU_K_REGEN_POWER_KW
from config.battery_config import DRIVE_REGEN_ROUND_TRIP_EFFICIENCY

def test_energy_conservation():
    """
    Test PRD Section 29: Energy conservation.
    cumulative E_discharge - n_regen * E_regen must equal SOC delta.
    """
    sim = Simulator()
    initial_soc = sim.battery.soc_mj
    
    # Run a few steps with discharge and regen
    sim.step(1.0, requested_power_kw=100.0, requested_regen_kw=0.0)
    sim.velocity_m_s = 50.0 # Force some speed to allow regen
    sim.step(1.0, requested_power_kw=0.0, requested_regen_kw=50.0)
    
    final_soc = sim.battery.soc_mj
    
    soc_delta = initial_soc - final_soc
    expected_delta = sim.cumulative_e_discharge_mj - (DRIVE_REGEN_ROUND_TRIP_EFFICIENCY * sim.cumulative_e_regen_mj)
    
    assert math.isclose(soc_delta, expected_delta, abs_tol=1e-6), "Energy conservation violated!"

def test_soc_bounds():
    """
    Test PRD Section 29: SOC bounds.
    0 <= SOC(t) <= ENERGY_STORE_CAP_MJ always.
    """
    sim = Simulator()
    
    # Try to over-discharge
    sim.step(10.0, requested_power_kw=10000.0, requested_regen_kw=0.0)
    assert sim.battery.soc_mj >= 0.0, "SOC dropped below 0!"
    
    # Try to over-charge
    sim.battery.soc_mj = ENERGY_STORE_CAP_MJ - 0.1
    sim.velocity_m_s = 100.0 # high kinetic energy
    sim.step(10.0, requested_power_kw=0.0, requested_regen_kw=10000.0)
    assert sim.battery.soc_mj <= ENERGY_STORE_CAP_MJ, "SOC exceeded capacity!"

def test_regeneration_physical_limit():
    """
    Test PRD Section 29: Regeneration physical limit.
    E_regen(t) never exceeds physically available kinetic energy.
    """
    sim = Simulator()
    sim.velocity_m_s = 10.0 # low speed, low kinetic energy
    
    ke_mj = 0.5 * sim.vehicle.mass * (sim.velocity_m_s ** 2) / 1000000.0
    
    # Request massive regen
    initial_regen = sim.cumulative_e_regen_mj
    sim.step(1.0, requested_power_kw=0.0, requested_regen_kw=50000.0)
    regen_step = sim.cumulative_e_regen_mj - initial_regen
    
    assert regen_step <= ke_mj, "Regenerated more energy than physically available!"
