import sys
import os
import time
import asyncio
import json
import random
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.simulator import Simulator
from core.forecaster import Forecaster
from core.optimizer import MPCOptimizer
from core.oracle import OracleOptimizer
from core.baselines import (
    Baseline0_NoOptimization,
    Baseline1_Aggressive,
    Baseline2_Conservative,
    Baseline3_FixedHeuristic,
)
from core.track_generator import TRACK_CLASSES

app = FastAPI()

# Mount static files (now in ../frontend)
static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def root():
    return FileResponse(os.path.join(static_dir, "index.html"))

BASE_TICK_INTERVAL_S = 0.1  # wall-clock delay between telemetry messages at 1x speed

# Policy factories for the finish-screen baseline comparison. "Proposed (MPC)" is deliberately
# excluded -- it's exactly the race that was just run live, so its real result is already
# known (self.sim.time_s) and re-simulating it would just reproduce the same number for the
# cost of another full solve.
BASELINE_POLICY_FACTORIES = {
    "Baseline 0 (No Optimization)": lambda sim, forecaster: Baseline0_NoOptimization(),
    "Aggressive Baseline": lambda sim, forecaster: Baseline1_Aggressive(),
    "Conservative Baseline": lambda sim, forecaster: Baseline2_Conservative(0.6),
    "Fixed Heuristic": lambda sim, forecaster: Baseline3_FixedHeuristic(),
    "Oracle (Perfect Future Knowledge)": lambda sim, forecaster: OracleOptimizer(sim, forecaster),
}


def _run_baseline_race(policy_factory, track_class: str, seed: int, laps: int) -> float:
    """
    Runs one full baseline/Oracle race under the same track/seed/laps as the race that was
    just displayed live, and returns its total time. This mirrors scripts/run_monte_carlo.py's
    run_simulation() -- reused here instead of imported since that script's version prints
    progress and isn't structured as a return-a-single-number helper.

    Deliberately does NOT replay whatever rain/safety-car/MGU-K-failure the user triggered
    live: those are interactive and not reproducible from (track_class, seed, laps) alone, so
    this is a clean-conditions comparison against the same circuit -- which is what the
    frontend's "Performance vs. Baselines" panel labels it as, not a disturbance-for-
    disturbance replay of the exact live run.
    """
    sim = Simulator()
    sim.load_track(track_class=track_class, laps=laps, seed=seed)
    forecaster = Forecaster(sim)
    policy = policy_factory(sim, forecaster)

    max_steps = 20000  # generous upper bound; a real race finishes in a few hundred steps
    steps = 0
    while steps < max_steps and not sim.is_finished:
        deploy_kw, regen_kw = policy.get_action(sim)
        sim.step(1.0, deploy_kw, regen_kw)
        steps += 1

    return sim.time_s


class RaceRunner:
    def __init__(self):
        self.sim = None
        self.forecaster = None
        self.optimizer = None
        self.is_running = False
        self.is_paused = False
        self.speed_multiplier = 1.0
        self.track_class = "Balanced"
        self.seed = 42
        self.action_counts = {}
        self.lap_start_time_s = 0.0
        self.lap_being_timed = 1

    def setup_race(self, track_class: str = "Balanced", laps: int = 5, seed: int = 42):
        self.sim = Simulator()
        self.sim.load_track(track_class, laps=laps, seed=seed)
        self.forecaster = Forecaster(self.sim)
        self.optimizer = MPCOptimizer(self.sim, self.forecaster)
        self.is_running = False
        self.is_paused = False
        self.track_class = track_class
        self.seed = seed
        self.action_counts = {}
        self.lap_start_time_s = 0.0
        self.lap_being_timed = 1

    async def run(self, websocket: WebSocket, track_class: str = "Balanced", laps: int = 5, seed: int = 42):
        self.setup_race(track_class, laps, seed)
        self.is_running = True

        # Send track geometry
        track_data = []
        for segment in self.sim.track:
            track_data.append({
                "type": segment.segment_type,
                "length": segment.length_m,
                "radius": segment.radius_m if segment.radius_m != float('inf') else -1,
                "direction": segment.direction,
            })
        # The dashboard's speed/power gauges need to know what "full scale" means, and that's
        # mode-dependent -- an EV delivery vehicle's ~45 km/h / ~5 kW range would render as an
        # invisible sliver on gauges scaled for an F1 car's 380 km/h / 350 kW. Reading the
        # currently-active regulation config here (rather than hard-coding F1 numbers into the
        # frontend, as it previously did) keeps the gauges correct for whichever mode is live,
        # the same way soc_capacity_mj already does for the SOC gauge.
        import config.regulation_config as regulation_config
        max_speed_kmh = regulation_config.DEPLOYMENT_CURVE[-1]["speed_kmh"]
        max_power_kw = max(point["power_kw"] for point in regulation_config.DEPLOYMENT_CURVE)

        try:
            await websocket.send_json({
                "type": "track_geometry",
                "track": track_data,
                "track_class": track_class,
                "seed": seed,
                "laps_total": self.sim.laps_total,
                "lap_length_m": self.sim.lap_length_m,
                "max_speed_kmh": max_speed_kmh,
                "max_power_kw": max_power_kw,
            })
        except Exception:
            pass

        while self.is_running and not self.sim.is_finished:
            if self.is_paused:
                await asyncio.sleep(0.5)
                continue

            deploy_kw, regen_kw = self.optimizer.get_action(self.sim)

            # Predict
            dist_remaining = self.sim.distance_remaining_m
            e_req, sig_e = self.forecaster.predict_energy_required(dist_remaining)
            r_safety = self.forecaster.get_strategic_reserve(e_req, sig_e)
            deployable = self.sim.battery.soc_mj - e_req - r_safety

            # Action string for dashboard
            action_str = "NORMAL"
            if deploy_kw > 200: action_str = "ATTACK"
            elif deploy_kw < 50 and regen_kw == 0: action_str = "COAST"
            elif regen_kw > 0: action_str = "HARVEST"
            if deployable < 0.1: action_str = "CONSERVE - LOW MARGIN"
            if deployable < 0 and self.sim.battery.soc_mj - e_req < 0: action_str = "INFEASIBLE - MAX CONSERVATION"
            self.action_counts[action_str] = self.action_counts.get(action_str, 0) + 1

            self.sim.step(1.0, deploy_kw, regen_kw)

            # A lap just completed if the simulator's lap counter moved on. Report the split
            # before the telemetry tick that carries the new lap number, so the client's lap
            # table updates in the same beat the lap number on the HUD ticks over.
            while self.lap_being_timed < self.sim.lap:
                lap_time_s = self.sim.time_s - self.lap_start_time_s
                try:
                    await websocket.send_json({
                        "type": "lap_complete",
                        "lap": self.lap_being_timed,
                        "lap_time_s": lap_time_s,
                    })
                except Exception:
                    pass
                self.lap_start_time_s = self.sim.time_s
                self.lap_being_timed += 1

            tick_interval_s = BASE_TICK_INTERVAL_S / max(0.01, self.speed_multiplier)

            # Send telemetry
            state = {
                "type": "telemetry",
                "time": self.sim.time_s,
                "distance": self.sim.distance_m,
                "velocity_kmh": self.sim.velocity_m_s * 3.6,
                "soc_mj": self.sim.battery.soc_mj,
                "soc_capacity_mj": self.sim.battery.capacity_mj,
                "lap": self.sim.lap,
                "total_laps": self.sim.laps_total,
                "e_req": e_req,
                "sig_e": sig_e,
                "r_safety": r_safety,
                "deployable": deployable,
                "action": action_str,
                "deploy_kw": deploy_kw,
                "regen_kw": regen_kw,
                "raining": self.sim.is_raining,
                "safety_car": self.sim.safety_car_active,
                "limited_power": self.sim.limited_power_mode,
                "tick_interval_s": tick_interval_s,
                "overtake_assessment": self.optimizer.evaluate_overtake_opportunity(self.sim)
            }
            try:
                await websocket.send_json(state)
            except WebSocketDisconnect:
                break

            await asyncio.sleep(tick_interval_s)

        if self.sim.is_finished:
            # The final lap never ticks self.sim.lap past laps_total (it's capped there), so
            # its split has to be flushed separately instead of falling out of the loop above.
            final_lap_time_s = self.sim.time_s - self.lap_start_time_s
            try:
                await websocket.send_json({
                    "type": "lap_complete",
                    "lap": self.lap_being_timed,
                    "lap_time_s": final_lap_time_s,
                })
            except Exception:
                pass

            avg_speed_kmh = (self.sim.distance_m / self.sim.time_s * 3.6) if self.sim.time_s > 0 else 0.0
            try:
                await websocket.send_json({
                    "type": "finished",
                    "total_time_s": self.sim.time_s,
                    "total_laps": self.sim.laps_total,
                    "final_soc_mj": self.sim.battery.soc_mj,
                    "avg_speed_kmh": avg_speed_kmh,
                    "action_counts": self.action_counts,
                    "track_class": self.track_class,
                })
            except Exception:
                pass

            # Real baseline/Oracle races (not fabricated multipliers of the live result) --
            # run in a thread since each is a genuine physics simulation (the Oracle also
            # solves one SLSQP problem), so this doesn't block the websocket event loop while
            # it computes. Sent as a separate follow-up message so the main finish stats above
            # appear immediately instead of waiting on this.
            try:
                baselines = [{"name": "Proposed System (MPC)", "time_s": self.sim.time_s}]
                for name, factory in BASELINE_POLICY_FACTORIES.items():
                    time_s = await asyncio.to_thread(
                        _run_baseline_race, factory, self.track_class, self.seed, self.sim.laps_total
                    )
                    baselines.append({"name": name, "time_s": time_s})
                await websocket.send_json({
                    "type": "baseline_results",
                    "baselines": baselines,
                })
            except Exception:
                pass

runner = RaceRunner()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    await websocket.send_json({"type": "status", "message": "Connected. Ready to start."})
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            if msg["command"] == "start":
                if not runner.is_running:
                    track_class = msg.get("track_class", "Balanced")
                    if track_class not in TRACK_CLASSES:
                        track_class = "Balanced"
                    laps = max(1, min(20, int(msg.get("laps", 5))))
                    seed = int(msg.get("seed", random.randint(1, 999999)))
                    asyncio.create_task(runner.run(websocket, track_class=track_class, laps=laps, seed=seed))
            elif msg["command"] == "reset":
                runner.is_running = False
            elif msg["command"] == "pause":
                runner.is_paused = not runner.is_paused
            elif msg["command"] == "inject_rain":
                if runner.sim: runner.sim.inject_disturbance("rain", not runner.sim.is_raining)
            elif msg["command"] == "inject_sc":
                if runner.sim: runner.sim.inject_disturbance("safety_car", not runner.sim.safety_car_active)
            elif msg["command"] == "inject_power":
                if runner.sim: runner.sim.inject_disturbance("limited_power", not runner.sim.limited_power_mode)
            elif msg["command"] == "set_speed":
                runner.speed_multiplier = max(0.01, float(msg.get("value", 1.0)))
            elif msg["command"] == "set_tune":
                if runner.sim:
                    param = msg.get("param")
                    val = float(msg.get("value", 0))
                    if param == "mass": runner.sim.vehicle.mass = val
                    elif param == "cla": runner.sim.vehicle.cla = val
                    elif param == "capacity": runner.sim.battery.capacity_mj = val
            elif msg["command"] == "set_mode":
                import config.vehicle_config as vc
                import config.regulation_config as rc
                mode = msg.get("mode", "f1")
                if mode == "fleet":
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
                else:
                    # Restore F1 defaults -- must match config/vehicle_config.py's actual
                    # module-level values. [Fix] CDA/CLA here were 1.0/4.5, not the real
                    # defaults (0.95/2.5) -- so toggling to Fleet mode and back permanently
                    # left the "F1" car's aero parameters wrong (until server restart) for the
                    # rest of the session, off by ~5% drag and ~80% downforce from the
                    # documented config values.
                    vc.VEHICLE_MASS_KG = 800
                    vc.ICE_POWER_KW = 400.0
                    vc.CDA = 0.95
                    vc.CLA = 2.5
                    vc.PEAK_LATERAL_ACCELERATION_G = 5.0
                    vc.PEAK_LONGITUDINAL_DECELERATION_G = 5.5
                    rc.DEPLOYMENT_CURVE = [
                        {"speed_kmh": 0, "power_kw": 350},
                        {"speed_kmh": 290, "power_kw": 350},
                        {"speed_kmh": 355, "power_kw": 0}
                    ]
                    rc.LIMITED_POWER_MODE_CURVE = [
                        {"speed_kmh": 0, "power_kw": 250},
                        {"speed_kmh": 310, "power_kw": 250},
                        {"speed_kmh": 340, "power_kw": 100},
                        {"speed_kmh": 345, "power_kw": 0}
                    ]
                    rc.ENERGY_STORE_CAP_MJ = 4.0
                    rc.MAX_MGU_K_DEPLOY_POWER_KW = 350
                    rc.MAX_MGU_K_REGEN_POWER_KW = 350
                
                # If race is running, reset it so new configs take effect
                runner.is_running = False
    except WebSocketDisconnect:
        runner.is_running = False

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
