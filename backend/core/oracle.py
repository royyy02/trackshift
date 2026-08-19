import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.optimizer import MPCOptimizer

# Upper bound on the one-shot solve's dimensionality, so a very long remaining distance
# (or a very small dt_s) can't blow up solve time; the Oracle's own horizon then just
# covers a coarser step size beyond this many decisions.
MAX_ORACLE_HORIZON_STEPS = 300


class OracleOptimizer(MPCOptimizer):
    """
    Offline optimizer with full future knowledge (PRD Section 18).

    The Oracle is defined as a single offline solve over the *entire* remaining race with
    zero forecast uncertainty -- not a receding-horizon controller. It therefore solves once
    (lazily, on the first get_action() call) over a horizon sized to the remaining race
    distance, caches the resulting deployment sequence, and replays it on every subsequent
    call.

    [Correction] The previous implementation reused MPCOptimizer.get_action's receding-
    horizon re-solve directly, just with a large horizon_steps. That re-solved a ~100-variable
    SLSQP problem from scratch on *every single simulated timestep* (~0.7s/call measured),
    which for a multi-hundred-step race is tens of minutes per policy -- it made the Oracle
    baseline (required for §18's baseline hierarchy and §26's Monte Carlo runs) effectively
    unusable, and contradicts the PRD's own definition of Oracle as a single offline solve.
    """

    def __init__(self, simulator, forecaster, max_deploy_power_kw: float = 350.0):
        super().__init__(simulator, forecaster, horizon_steps=1)
        self.max_deploy_power_kw = max_deploy_power_kw
        self._solved_sequence = None
        self._solved_index = 0

    def _solve_full_race(self, simulator_state, dt_s: float):
        remaining_m = simulator_state.distance_remaining_m
        nominal_speed_m_s = max(10.0, simulator_state.velocity_m_s or 60.0)
        horizon_steps = max(1, min(MAX_ORACLE_HORIZON_STEPS, int(remaining_m / (nominal_speed_m_s * dt_s))))

        # Oracle has full future knowledge, i.e. zero forecast uncertainty.
        e_req, _sig_e = self.forecaster.predict_energy_required(remaining_m)
        r_safety = self.forecaster.get_strategic_reserve(e_req, 0.0)

        self._solved_sequence = self._solve_sequence(
            horizon_steps, self.max_deploy_power_kw, simulator_state.battery.soc_mj,
            e_req, r_safety, dt_s,
        )
        self._solved_index = 0

    def get_action(self, simulator_state, dt_s: float = 1.0) -> tuple[float, float]:
        if self._solved_sequence is None:
            self._solve_full_race(simulator_state, dt_s)
        solved_sequence = self._solved_sequence

        if solved_sequence is not None and self._solved_index < len(solved_sequence):
            u_kw = solved_sequence[self._solved_index]
        else:
            # Race outlasted the solved horizon (e.g. resampled bounds); coast rather than
            # silently deploying past what was ever optimized for.
            u_kw = 0.0
        self._solved_index += 1

        if u_kw < 10.0:
            # True coast, not a brake request -- see MPCOptimizer.get_action's matching fix
            # note for why requesting regen here silently disabled the ICE.
            return (0.0, 0.0)
        return (u_kw, 0.0)


if __name__ == "__main__":
    import time
    from core.simulator import Simulator
    from core.forecaster import Forecaster

    sim = Simulator()
    sim.load_track("Balanced", laps=1, seed=1)
    forecaster = Forecaster(sim)
    oracle = OracleOptimizer(sim, forecaster)

    t0 = time.time()
    u_deploy, u_regen = oracle.get_action(sim, dt_s=1.0)
    print(f"First call (triggers one-shot full-race solve): {time.time() - t0:.3f}s "
          f"-> deploy={u_deploy:.1f} kW, regen={u_regen:.1f} kW")

    t0 = time.time()
    for _ in range(100):
        oracle.get_action(sim, dt_s=1.0)
    print(f"Next 100 calls (cached replay): {time.time() - t0:.4f}s")
