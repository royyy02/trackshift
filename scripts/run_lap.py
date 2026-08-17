import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import matplotlib.pyplot as plt
from core.simulator import Simulator
from core.optimizer import MPCOptimizer
from config.regulation_config import MAX_MGU_K_REGEN_POWER_KW

class MockForecaster:
    def predict_energy_required(self, horizon_m: float):
        return (0.0, 0.0)
    
    def get_strategic_reserve(self, e_req, sig_e):
        return 0.0

def run_lap():
    sim = Simulator()
    sim.load_track("Balanced")
    
    total_length_m = sum(segment.length_m for segment in sim.track)
    print(f"Loaded track with length {total_length_m:.1f} m")
    
    optimizer = MPCOptimizer(sim, MockForecaster(), horizon_steps=5)
    
    dt_s = 0.1
    
    history_distance = []
    history_velocity = []
    history_soc = []
    history_power = []
    
    print("Simulating lap...")
    
    while sim.distance_m < total_length_m:
        dist_to_corner, corner_limit = sim.get_next_corner()
        
        braking_distance = 0.0
        if corner_limit < sim.velocity_m_s:
            max_decel = sim.vehicle.get_max_braking_deceleration()
            # d = (v^2 - u^2) / (2a)
            braking_distance = (sim.velocity_m_s**2 - corner_limit**2) / (2 * max_decel)
        
        # 10% safety margin on braking distance
        if dist_to_corner <= braking_distance * 1.1:
            u_deploy = 0.0
            u_regen = MAX_MGU_K_REGEN_POWER_KW
        else:
            u_deploy, u_regen = optimizer.get_action(sim, dt_s)
            
        sim.step(dt_s, u_deploy, u_regen)
        
        history_distance.append(sim.distance_m)
        history_velocity.append(sim.velocity_m_s * 3.6) # km/h
        history_soc.append(sim.battery.soc_mj)
        history_power.append(u_deploy - u_regen)
        
        if sim.time_s > 600:
            print("Simulation timeout (10 minutes).")
            break
            
    print(f"Lap completed in {sim.time_s:.2f} seconds!")
    
    fig, axs = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
    
    axs[0].plot(history_distance, history_velocity, color='blue')
    axs[0].set_ylabel('Speed (km/h)')
    axs[0].set_title('Lap Telemetry')
    axs[0].grid(True)
    
    axs[1].plot(history_distance, history_soc, color='green')
    axs[1].set_ylabel('SOC (MJ)')
    axs[1].grid(True)
    
    axs[2].plot(history_distance, history_power, color='red')
    axs[2].set_ylabel('MGU-K Power (kW)')
    axs[2].set_xlabel('Distance (m)')
    axs[2].grid(True)
    
    plt.tight_layout()
    plt.savefig('lap_telemetry.png')
    print("Saved lap telemetry to lap_telemetry.png")

if __name__ == "__main__":
    run_lap()
