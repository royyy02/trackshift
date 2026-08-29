# 🏎️ TrackShift BMS

TrackShift BMS is a hackathon project built for the Plaksha University x Mphasis Foundation x Toyota Gazoo Racing Haas F1 Team collaboration.

It's a real-time battery management and energy-deployment strategy engine for a reduced-order, FIA-2026-regulation-grounded hybrid F1 car. A Model Predictive Control (MPC) optimizer and an energy forecaster dynamically decide how much electrical power to deploy versus hold in reserve around a procedurally generated track, adapting live to physics, environmental disturbances, and mid-race tuning — and every decision is benchmarked in real time against a perfect-hindsight Oracle and four baseline strategies.

## ✨ Features

- **Live 3D Dashboard**: A full-screen, glassmorphism telemetry dashboard styled like a real F1 engineering terminal — responsive from desktop down to phone.
- **MPC Strategy Engine**: Live energy forecasting, a statistically-grounded strategic reserve (`R_safety = R_base + k·σ_Ê + R_event_contingency`), water-filling deployment allocation, and live overtake-opportunity evaluation.
- **Optimality Benchmarking**: Every race is scored live against an Oracle (full-race optimal solve) and four baseline policies (no-optimization, conserve, greedy-deploy, regulation-aware balanced).
- **Real-Time Physics Tuning**: Instantly adjust Vehicle Mass, Downforce (CLA), and Battery Capacity mid-race — via typable inputs or sliders — and watch the optimizer adapt on the fly.
- **Dynamic Environment Disturbances**: Inject Rain, Safety Cars, or MGU-K power limitations to test the robustness of the deployment strategy; the reserve and recommended action visibly react.
- **Cinematic 3D Visualization**: Built with Three.js. Automatic Chase Cam (scroll-to-zoom) and a free-roaming Orbit Cam, custom-styled UI dropdowns (no native browser selects).
- **Full Race PDF Export**: One click exports a branded, client-side-generated race report — summary stats, baseline comparison table, lap times, action breakdown, full event timeline, and energy/speed graphs.
- **In-App Documentation**: A "How It Works" tab explaining every formula and system (vehicle model, battery model, forecaster, MPC, Oracle, baselines, track generation, simulation engine, overtake assessment) directly in the dashboard.

## 🚀 How to Run

1. **Install Dependencies**:
   Ensure you have Python 3.11+ installed, then install the required packages:
   ```bash
   pip install fastapi "uvicorn[standard]" numpy pytest
   ```

2. **Start the Server**:
   Run the dashboard server from the root directory:
   ```bash
   python backend/dashboard_server.py
   ```

3. **Open the Dashboard**:
   Open your browser and navigate to:
   **http://localhost:8001**

4. **Run the tests** (optional):
   ```bash
   pytest backend/tests
   ```

## 📂 Project Structure

- **`backend/`**: Python simulation core (`simulator.py`, `vehicle_model.py`, `battery_model.py`, `forecaster.py`, `optimizer.py`, `oracle.py`, `baselines.py`, `track_generator.py`), regulation/vehicle/battery configs, the FastAPI + WebSocket `dashboard_server.py`, and the `pytest` suite (`backend/tests/`).
- **`frontend/`**: Web assets (`index.html`, `style.css`, `app.js`) and the 3D car model (`f1_car.fbx`). No build step — vanilla JS + Three.js/Chart.js/jsPDF via CDN.
- **`docs/`**: Submission materials — [`SUBMISSION_ANSWERS.md`](docs/SUBMISSION_ANSWERS.md) (idea-submission form answers), [`PPT_SCRIPT.md`](docs/PPT_SCRIPT.md) (slide-by-slide pitch deck script), [`VIDEO_SCRIPT.md`](docs/VIDEO_SCRIPT.md) (demo video narration script).

## 🛠️ How to Use the Dashboard

- **Start/Pause/Reset**: Use the buttons in the top right to control the simulation loop — Reset fully restores all UI and telemetry state.
- **Camera Controls**: The default mode is **Orbit Cam**. Left-click and drag to rotate around the car, right-click to pan, and scroll to zoom. Switch to **Chase Cam** for a cinematic trailing view.
- **Sidebars**: If the sidebars get in the way of the track, click the hamburger (`☰`) icons in the top corners to collapse them!
- **Docs**: Click the book icon in the left dock rail to open the in-app "How It Works" reference for the full math and physics behind the simulation.
- **Export**: Click the export icon in the header at any point (or after finishing) to download a full PDF race report.
