import time
from core.simulator import Simulator
from core.baselines import Baseline0_NoOptimization, Baseline1_Aggressive, Baseline2_Conservative, Baseline3_FixedHeuristic
from core.forecaster import Forecaster
from core.optimizer import MPCOptimizer
from core.oracle import OracleOptimizer

def run_simulation(policy, track_class="Balanced", seed=42, max_steps=1000, dt_s=1.0):
    sim = Simulator()
    sim.load_track(track_class=track_class) # Simplified loading (generator doesn't currently take seed in Simulator interface, but for MVP it's okay)
    
    steps = 0
    while steps < max_steps and sim.distance_m < 5000.0: # Arbitrary track length 5km
        deploy_kw, regen_kw = policy.get_action(sim)
        sim.step(dt_s, deploy_kw, regen_kw)
        steps += 1
        
    return {
        "time_s": sim.time_s,
        "final_soc_mj": sim.battery.soc_mj,
        "distance_m": sim.distance_m
    }

def main():
    print("Running Monte Carlo sweeps...")
    # Just a small sample for MVP
    # Initialize forecaster for optimizers
    sim_for_setup = Simulator()
    forecaster = Forecaster(sim_for_setup)
    
    policies = {
        "Baseline 0 (No Opt)": Baseline0_NoOptimization(),
        "Baseline 1 (Aggressive)": Baseline1_Aggressive(),
        "Baseline 2 (Conservative)": Baseline2_Conservative(0.6),
        "Baseline 3 (Fixed Heuristic)": Baseline3_FixedHeuristic(),
        "Proposed (MPC)": MPCOptimizer(sim_for_setup, forecaster),
        "Oracle": OracleOptimizer(sim_for_setup, forecaster)
    }
    
    for name, policy in policies.items():
        start_time = time.time()
        result = run_simulation(policy)
        elapsed = time.time() - start_time
        
        print(f"[{name}] Completed in {elapsed:.3f}s")
        print(f"  Race Time: {result['time_s']:.2f} s")
        print(f"  Final SOC: {result['final_soc_mj']:.2f} MJ")
        print(f"  Distance:  {result['distance_m']:.2f} m")

if __name__ == "__main__":
    main()
