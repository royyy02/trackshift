import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import configs first
import config.vehicle_config as vc
import config.regulation_config as rc

# Apply Fleet configuration (Electric Delivery 2/3 Wheeler)
vc.VEHICLE_MASS_KG = 300
vc.ICE_POWER_KW = 0.0
vc.CDA = 0.6
vc.CLA = 0.0
vc.PEAK_LATERAL_ACCELERATION_G = 0.8
vc.PEAK_LONGITUDINAL_DECELERATION_G = 0.8

rc.DEPLOYMENT_CURVE = [
    {"speed_kmh": 0, "power_kw": 5.0},
    {"speed_kmh": 40, "power_kw": 5.0},
    {"speed_kmh": 45, "power_kw": 0}
]
rc.LIMITED_POWER_MODE_CURVE = [
    {"speed_kmh": 0, "power_kw": 2.5},
    {"speed_kmh": 30, "power_kw": 2.5},
    {"speed_kmh": 35, "power_kw": 0}
]
rc.ENERGY_STORE_CAP_MJ = 10.0
rc.MAX_MGU_K_DEPLOY_POWER_KW = 5.0
rc.MAX_MGU_K_REGEN_POWER_KW = 2.0

# Now import the simulation core
from core.simulator import Simulator
from core.forecaster import Forecaster
from core.optimizer import MPCOptimizer

def run_fleet_delivery():
    print("=== EV Fleet Delivery Scenario ===")
    sim = Simulator()
    # A single lap represents a delivery route
    sim.load_track("Technical", laps=1, seed=101, target_length_m=3000.0)
    
    forecaster = Forecaster(sim)
    optimizer = MPCOptimizer(sim, forecaster)
    
    steps = 0
    # Simulate a mid-route traffic detour (speed cap)
    event_injected = False
    
    while not sim.is_finished and steps < 5000:
        if not event_injected and sim.distance_m > 1500:
            print(f"[Traffic Alert] Injecting detour / traffic speed limit at {sim.distance_m:.1f} m")
            sim.inject_disturbance("safety_car", active=True)
            sim.safety_car_speed_cap_m_s = 5.0 # Slow traffic (18 km/h)
            event_injected = True
            
        deploy_kw, regen_kw = optimizer.get_action(sim)
        sim.step(1.0, deploy_kw, regen_kw)
        steps += 1
        
    print(f"Delivery completed in {sim.time_s:.1f} s")
    print(f"Distance covered: {sim.distance_m:.1f} m")
    print(f"Final SOC: {sim.battery.soc_mj:.2f} MJ (out of {rc.ENERGY_STORE_CAP_MJ})")
    print(f"Constraint Violations: {'Yes' if sim.battery.soc_mj < 0 else 'No'}")
    
if __name__ == "__main__":
    run_fleet_delivery()
