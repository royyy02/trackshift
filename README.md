# Trackshift: 2026 F1 Energy Management Simulator

Trackshift is a reduced-order point-mass simulator and Model Predictive Control (MPC) optimizer for predicting and managing optimal energy deployment strategies under the upcoming 2026 FIA Formula 1 Technical Regulations.

## Architecture

The project is structured into four main components:
- `config/`: Contains the physical bounds and regulatory rules (`vehicle_config.py`, `battery_config.py`, `regulation_config.py`).
- `core/`: The core physics and simulation engine, including the `Simulator`, `VehicleModel`, `BatteryModel`, and `MPCOptimizer`. It also includes procedural circuit generation (`TrackGenerator`).
- `scripts/`: Executable scripts to run scenarios, such as the full lap simulation (`run_lap.py`) or monte carlo analyses.
- `tests/`: Automated test suite for verifying physics and energy conservation bounds using `pytest`.

## Setup Instructions

1. **Clone the repository.**
2. **Set up a Python virtual environment:**
   ```bash
   python -m venv .venv
   ```
3. **Activate the environment:**
   - **Windows:** `.\.venv\Scripts\activate`
   - **Mac/Linux:** `source .venv/bin/activate`
4. **Install dependencies:**
   The project requires the following primary dependencies:
   ```bash
   pip install numpy scipy pytest matplotlib
   ```

## Running the Simulator

To simulate a complete lap with MPC energy deployment, braking logic, and procedural track generation, run the lap script from the root directory:

```bash
python scripts/run_lap.py
```

This will run the simulator over a dynamically generated track and output a telemetry plot (`lap_telemetry.png`) showing Speed, SOC, and MGU-K Power over the course of the lap.

## Running Tests

To run the suite of energy conservation and physics tests, simply execute:

```bash
pytest
```
