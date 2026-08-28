# 🏎️ TrackShift Energy Intelligence

TrackShift Energy Intelligence is a hackathon project built for the Plaksha University x Mphasis Foundation x Toyota Gazoo Racing Haas F1 Team collaboration.

It simulates a reduced-order, FIA-2026-regulation-grounded F1 car and battery. The system uses a Model Predictive Control (MPC) optimizer and an energy forecaster to dynamically deploy energy around a procedurally generated track, adapting to real-time physics and environmental disturbances.

## ✨ Features

- **Live 3D Dashboard**: A beautifully designed, full-screen "Glassmorphism" telemetry dashboard that feels like a real F1 engineering terminal.
- **Real-Time Physics Tuning**: Instantly adjust Vehicle Mass, Downforce (ClA), and Battery Capacity mid-race and watch the MPC optimizer adapt its strategy on the fly.
- **Dynamic Environment Disturbances**: Inject Rain, Safety Cars, or MGU-K Failures to test the robustness of the energy deployment strategy.
- **Cinematic 3D Visualization**: Built with Three.js. Features an automatic Chase Cam (with scroll-to-zoom) and a free-roaming Orbit Cam to watch the car race around the generated track.
- **Advanced Telemetry**: Live energy prediction charts and readouts for Speed, Power, State of Charge (SOC), and Deployment Action (Attack, Coast, Harvest, Conserve).

## 🚀 How to Run

1. **Install Dependencies**:
   Ensure you have Python installed, then install the required packages:
   ```bash
   pip install fastapi "uvicorn[standard]" numpy scipy pytest
   ```

2. **Start the Server**:
   Run the dashboard server from the root directory:
   ```bash
   python backend/dashboard_server.py
   ```

3. **Open the Dashboard**:
   Open your browser and navigate to:
   **http://localhost:8001**

## 📂 Project Structure

- **`backend/`**: Contains the Python simulation core (`simulator.py`, `vehicle_model.py`, `optimizer.py`, etc.), configurations, and the FastAPI `dashboard_server.py`.
- **`frontend/`**: Contains the web assets (`index.html`, `style.css`, `app.js`, and the 3D car model). 

## 🛠️ How to Use the Dashboard

- **Start/Pause/Reset**: Use the buttons in the top right to control the simulation loop.
- **Camera Controls**: The default mode is **Orbit Cam**. Left-click and drag to rotate around the car, right-click to pan, and scroll to zoom. Switch to **Chase Cam** for a cinematic trailing view.
- **Sidebars**: If the sidebars get in the way of the track, click the hamburger (`☰`) icons in the top corners to collapse them!
