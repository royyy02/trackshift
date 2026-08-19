import sys
import os
import time
import random
import numpy as np

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.simulator import Simulator
from core.baselines import Baseline0_NoOptimization, Baseline1_Aggressive, Baseline2_Conservative, Baseline3_FixedHeuristic
from core.forecaster import Forecaster
from core.optimizer import MPCOptimizer
from core.oracle import OracleOptimizer

def run_simulation(policy_factory, track_class="Balanced", seed=42, laps=1, event_type=None, dt_s=1.0):
    sim = Simulator()
    sim.load_track(track_class=track_class, laps=laps, seed=seed)
    
    forecaster = Forecaster(sim)
    policy = policy_factory(sim, forecaster)
    
    event_injected = False
    
    steps = 0
    max_steps = 10000
    while steps < max_steps and not sim.is_finished:
        # Inject event halfway through the race
        if event_type and not event_injected and sim.lap >= max(1, laps // 2):
            sim.inject_disturbance(event_type, active=True)
            event_injected = True
            
        deploy_kw, regen_kw = policy.get_action(sim)
        sim.step(dt_s, deploy_kw, regen_kw)
        steps += 1
        
    # Check constraints
    constraint_violations = 0
    if sim.battery.soc_mj < 0.0:
        constraint_violations += 1
        
    return {
        "time_s": sim.time_s,
        "final_soc_mj": sim.battery.soc_mj,
        "distance_m": sim.distance_m,
        "violations": constraint_violations
    }

def policy_factory_wrapper(name):
    if name == "Baseline 0 (No Opt)":
        return lambda sim, f: Baseline0_NoOptimization()
    elif name == "Baseline 1 (Aggressive)":
        return lambda sim, f: Baseline1_Aggressive()
    elif name == "Baseline 2 (Conservative)":
        return lambda sim, f: Baseline2_Conservative(0.6)
    elif name == "Baseline 3 (Fixed Heuristic)":
        return lambda sim, f: Baseline3_FixedHeuristic()
    elif name == "Proposed (MPC)":
        return lambda sim, f: MPCOptimizer(sim, f)
    elif name == "Oracle":
        return lambda sim, f: OracleOptimizer(sim, f)
    raise ValueError(f"Unknown policy {name}")

def main():
    print("Running Monte Carlo evaluation suite...")
    
    # UNSEEN TEST Split: 8501-10000 (PRD Section 25)
    test_seeds = random.sample(range(8501, 10001), 2) # Small sample for fast execution
    track_classes = ["Technical", "Balanced"]
    
    policies = [
        "Baseline 3 (Fixed Heuristic)",
        "Proposed (MPC)",
        "Oracle"
    ]
    
    results = {p: {"clean": [], "event": []} for p in policies}
    
    for seed in test_seeds:
        for track_class in track_classes:
            for event in [None, "rain"]:
                event_label = "clean" if event is None else "event"
                print(f"--- Simulating Track: {track_class}, Seed: {seed}, Event: {event} ---")
                
                for p_name in policies:
                    start_t = time.time()
                    res = run_simulation(policy_factory_wrapper(p_name), track_class, seed, laps=2, event_type=event)
                    elapsed = time.time() - start_t
                    
                    results[p_name][event_label].append(res)
                    print(f"[{p_name}] Time: {res['time_s']:.2f}s, Final SOC: {res['final_soc_mj']:.2f} MJ (solved in {elapsed:.2f}s)")
                    
    print("\n=== AGGREGATE RESULTS (UNSEEN TEST SPLIT) ===")
    for p_name in policies:
        print(f"\n{p_name}:")
        for condition in ["clean", "event"]:
            runs = results[p_name][condition]
            if not runs: continue
            avg_time = np.mean([r["time_s"] for r in runs])
            avg_soc = np.mean([r["final_soc_mj"] for r in runs])
            violations = sum(r["violations"] for r in runs)
            print(f"  {condition.capitalize()} Runs (n={len(runs)}):")
            print(f"    Avg Race Time: {avg_time:.2f} s")
            print(f"    Avg Final SOC: {avg_soc:.2f} MJ")
            print(f"    Constraint Violations: {violations}")

if __name__ == "__main__":
    main()
