import sys
import os
import time
import asyncio
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.simulator import Simulator
from core.forecaster import Forecaster
from core.optimizer import MPCOptimizer

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

class RaceRunner:
    def __init__(self):
        self.sim = None
        self.forecaster = None
        self.optimizer = None
        self.is_running = False
        self.is_paused = False
        self.speed_multiplier = 1.0

    def setup_race(self):
        self.sim = Simulator()
        self.sim.load_track("Balanced", laps=5, seed=42)
        self.forecaster = Forecaster(self.sim)
        self.optimizer = MPCOptimizer(self.sim, self.forecaster)
        self.is_running = False
        self.is_paused = False

    async def run(self, websocket: WebSocket):
        self.setup_race()
        self.is_running = True
        
        # Send track geometry
        track_data = []
        for segment in self.sim.track:
            track_data.append({
                "type": segment.segment_type,
                "length": segment.length_m,
                "radius": segment.radius_m if segment.radius_m != float('inf') else -1
            })
        try:
            await websocket.send_json({"type": "track_geometry", "track": track_data})
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
            
            self.sim.step(1.0, deploy_kw, regen_kw)

            tick_interval_s = BASE_TICK_INTERVAL_S / max(0.01, self.speed_multiplier)

            # Send telemetry
            state = {
                "type": "telemetry",
                "time": self.sim.time_s,
                "distance": self.sim.distance_m,
                "velocity_kmh": self.sim.velocity_m_s * 3.6,
                "soc_mj": self.sim.battery.soc_mj,
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
            }
            try:
                await websocket.send_json(state)
            except WebSocketDisconnect:
                break

            await asyncio.sleep(tick_interval_s)
            
        if self.sim.is_finished:
            try:
                await websocket.send_json({"type": "finished"})
            except:
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
                    asyncio.create_task(runner.run(websocket))
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
    except WebSocketDisconnect:
        runner.is_running = False

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
