import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from core.simulator import Simulator

class Forecaster:
    """
    Short-horizon energy/speed forecaster (PRD Section 13 & 14).
    Physics-based extrapolation with explicit uncertainty.
    """
    def __init__(self, simulator: Simulator):
        self.simulator = simulator
        self.history = [] # tuples of (distance, net_energy)
        
    def predict_energy_required(self, distance_remaining_m: float) -> tuple[float, float]:
        """
        Predicts the required energy to finish the horizon under a baseline-competitive profile.
        Returns:
            (Ê_required_mj, σ_Ê_mj) : Mean point forecast and uncertainty std dev
        """
        current_dist = self.simulator.distance_m
        current_net = self.simulator.cumulative_e_discharge_mj - self.simulator.cumulative_e_regen_mj
        
        self.history.append((current_dist, current_net))
        # Keep last ~2000m of history
        while len(self.history) > 0 and current_dist - self.history[0][0] > 2000.0:
            self.history.pop(0)
            
        if current_dist > 100.0:
            cum_rate = current_net / current_dist
            
            if len(self.history) >= 2 and current_dist - self.history[0][0] > 500.0:
                recent_dist = current_dist - self.history[0][0]
                recent_net = current_net - self.history[0][1]
                recent_rate = recent_net / recent_dist
                
                # Uncertainty spikes if recent rate deviates from cumulative rate
                rate_diff = abs(recent_rate - cum_rate)
            else:
                rate_diff = abs(cum_rate) * 0.1
                
            # [Fix] Was unclamped (`rate = cum_rate` directly). Early in a lap -- e.g. right
            # after a heavy-regen opening corner, before much cumulative discharge has
            # accumulated -- cum_rate (net discharge / distance so far) can transiently go
            # negative, which fed the exact same "car will net *gain* energy over the rest of
            # the race" nonsense into e_required_mj that the prior/cold-start branch below was
            # already fixed for (see that branch's comment). A negative e_req doesn't just
            # under-predict here: it *inflates* the deployment budget downstream (optimizer.py's
            # water-filling ceiling subtracts e_req_remaining, so a negative value adds to what
            # looks safe to deploy), which is the more dangerous direction to be wrong in.
            rate = max(0.0, cum_rate) # Use cumulative for stability
            sigma_rate = rate_diff * 2.0 # Amplify the difference for uncertainty
        else:
            # Prior: physical estimate of net energy per meter
            f_roll = self.simulator.vehicle.mass * 9.81 * self.simulator.vehicle.crr
            # Assume ~30 m/s for F1, ~15 m/s for EV fleet
            v_guess = 30.0 if self.simulator.vehicle.mass > 500 else 15.0
            f_drag = 0.5 * 1.225 * self.simulator.vehicle.cda * (v_guess**2)
            
            # Regen estimate: F1 regens ~8.5 MJ / 5km = 0.0017 MJ/m. EV fleet regens ~0.
            regen_guess = 0.0017 if self.simulator.vehicle.mass > 500 else 0.0

            # [Fix] For any realistic F1 vehicle config, (f_roll + f_drag)/1e6 comes out well
            # under 0.0017 MJ/m (~0.0006-0.0007 MJ/m for the default parameters) -- so this
            # subtraction used to push `rate` *negative*, predicting the car would net *gain*
            # energy over the remaining race. That's not physically possible for a vehicle
            # continuously overcoming drag and rolling resistance: regen_guess is the
            # regulatory *cap* on recoverable energy per lap (from active braking events
            # only), not a continuous per-meter credit that applies while cruising, so it can
            # reduce the net rate but should never flip its sign. This is exactly the estimate
            # a full-knowledge Oracle solves against at t=0 (before real telemetry accumulates
            # and the cum_rate/recent_rate branch above takes over), so a negative rate here
            # was feeding a nonsensical "you have surplus energy" signal straight into the
            # Oracle's one-shot optimization.
            rate = max(0.0, ((f_roll + f_drag) / 1_000_000.0) - regen_guess)
            sigma_rate = abs(rate) * 0.5
            
        e_required_mj = rate * distance_remaining_m
        
        # Uncertainty is sigma_rate * distance, bounded
        sigma_e_mj = sigma_rate * distance_remaining_m
        sigma_e_mj = max(sigma_e_mj, 0.05 * abs(e_required_mj)) # At least 5% uncertainty
        
        return e_required_mj, sigma_e_mj

    def get_strategic_reserve(self, e_required_mj: float, sigma_e_mj: float) -> float:
        """
        Calculates dynamic safety reserve based on uncertainty (PRD Section 15).
        R_safety(t) = R_base + k * σ_Ê(t) + R_event_contingency(t)
        """
        R_base = 0.5  # Fixed floor MJ
        k = 2.0       # 2 sigma for 95% confidence
        R_event_contingency = self._event_contingency_mj()

        return R_base + (k * sigma_e_mj) + R_event_contingency

    def _event_contingency_mj(self) -> float:
        """
        [Fix] Was a hardcoded 0.0, with a comment noting it "could be updated externally if
        safety car expected" -- nothing ever did. There's no random/probabilistic disturbance
        process in this simulator to forecast against (rain/safety-car/limited-power are only
        ever user-triggered from the dashboard, not sampled), so a genuinely *predictive* event
        probability isn't meaningful here. What is meaningful and directly readable from the
        simulator: whichever disturbances are *actively in effect right now* make the near-term
        energy picture less certain than the base uncertainty term alone accounts for --
        - Safety car: pace resumes unpredictably once it ends (a restart can demand a burst of
          deployment with little warning), so hold extra margin while one is active.
        - Rain: reduces grip and raises rolling resistance (see Simulator.inject_disturbance),
          which the Forecaster's rate-based prediction partially captures already, but rain also
          makes lap-to-lap energy consumption noisier than dry running -- worth a smaller margin
          on top, not a full re-derivation of the rate model.
        - Limited power mode: a lower deployment ceiling makes it harder to recover from a
          shortfall once one appears, raising the cost of being wrong in the "needed more than
          predicted" direction specifically.
        Purely additive and small relative to R_base (0.5 MJ) -- this nudges the reserve while
        multiple disturbances stack, it doesn't replace R_base or the sigma_e term as the
        primary drivers of the reserve.
        """
        sim = self.simulator
        contingency = 0.0
        if getattr(sim, "safety_car_active", False):
            contingency += 0.15
        if getattr(sim, "is_raining", False):
            contingency += 0.10
        if getattr(sim, "limited_power_mode", False):
            contingency += 0.05
        return contingency


if __name__ == "__main__":
    sim = Simulator()
    sim.load_track("Balanced", laps=1, seed=1)
    forecaster = Forecaster(sim)

    for horizon_m in (500.0, 2000.0, sim.lap_length_m):
        e_req, sig_e = forecaster.predict_energy_required(horizon_m)
        reserve = forecaster.get_strategic_reserve(e_req, sig_e)
        print(f"horizon={horizon_m:8.1f} m -> e_req={e_req:6.2f} MJ, "
              f"sigma={sig_e:5.2f} MJ, reserve={reserve:5.2f} MJ")
