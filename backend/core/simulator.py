import sys
import os
import math
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.vehicle_model import VehicleModel
from core.battery_model import BatteryModel
from core.track_generator import TrackGenerator, total_length_m
import config.vehicle_config as vehicle_config

# [Fix] Simulator.step() previously applied one Euler update per caller-requested dt_s directly
# -- every call site in this codebase uses dt_s=1.0s, which is coarse relative to how fast this
# vehicle model's own dynamics move: at low speed under full traction (mu_longitudinal * g),
# net acceleration is on the order of 50+ m/s^2, so a single 1.0s Euler step from a standing
# start could jump velocity by ~54 m/s in one shot despite the true (nonlinear, power-limited)
# curve rising much more gradually -- and the corner-speed/safety-car clamps, track-position
# update, and regen bounds were all only re-evaluated once per full second rather than as the
# car actually moved through the interval. step() now subdivides internally into substeps of at
# most this length; the public dt_s contract (advance by exactly dt_s, same cumulative-energy
# accounting) is unchanged, this only makes what happens *within* that interval more accurate.
# 0.1s balances that accuracy gain against cost: it's a 10x increase in step() 's internal work,
# which is still cheap (no per-step allocations or heavy math) relative to what the optimizer's
# own clone-and-simulate calls already do per solve.
MAX_SUBSTEP_S = 0.1

class Simulator:
    """
    Fast simulator core loop (PRD Section 5.1).
    """

    def __init__(self):
        self.vehicle = VehicleModel()
        self.battery = BatteryModel()
        self.track_generator = TrackGenerator()
        self.track = []
        self.lap_length_m = 0.0
        self.laps_total = 1
        self.lap = 1

        self.time_s = 0.0
        self.velocity_m_s = 0.0
        self.distance_m = 0.0

        self.cumulative_e_discharge_mj = 0.0
        self.cumulative_e_regen_mj = 0.0

        self.current_segment_idx = 0
        self.segment_start_m = 0.0
        self.lap_relative_m = 0.0
        
        # Scenario states
        self.is_raining = False
        self.safety_car_active = False
        self.limited_power_mode = False
        self.safety_car_speed_cap_m_s = 30.0 # ~108 km/h

    def load_track(self, track_class: str = "Balanced", laps: int = 1, seed: int = 42,
                    target_length_m: float = 5000.0):
        """
        Loads a fresh procedural track (PRD Section 9) and configures the race as `laps`
        trips around it, so the simulator's `lap(t)` / `distance_remaining(t)` state
        (PRD Section 16.1) is meaningful rather than a single one-shot distance traverse.
        """
        self.track_generator = TrackGenerator(track_class=track_class, seed=seed)
        self.track = self.track_generator.generate_track(target_length_m=target_length_m)
        self.lap_length_m = total_length_m(self.track)
        self.laps_total = max(1, laps)
        self.lap = 1
        self.current_segment_idx = 0
        self.segment_start_m = 0.0

    @property
    def total_race_distance_m(self) -> float:
        return self.lap_length_m * self.laps_total

    @property
    def distance_remaining_m(self) -> float:
        return max(0.0, self.total_race_distance_m - self.distance_m)

    @property
    def is_finished(self) -> bool:
        return self.lap_length_m > 0 and self.distance_m >= self.total_race_distance_m

    def _update_track_position(self):
        """
        Recomputes lap number and current segment index/start from absolute distance
        travelled, so lap wrap-around (the closed-circuit behavior described in
        core/track_generator.py's docstring) is handled by re-deriving position rather than
        by incrementally walking segments and needing separate wrap-around logic.
        """
        if not self.track or self.lap_length_m <= 0:
            return

        laps_completed = int(self.distance_m // self.lap_length_m)
        self.lap = min(self.laps_total, laps_completed + 1)
        self.lap_relative_m = self.distance_m - laps_completed * self.lap_length_m

        cumulative = 0.0
        for idx, segment in enumerate(self.track):
            if idx == len(self.track) - 1 or cumulative + segment.length_m > self.lap_relative_m:
                self.current_segment_idx = idx
                self.segment_start_m = cumulative
                return
            cumulative += segment.length_m

    def get_next_corner(self) -> tuple[float, float]:
        """
        Returns (distance_to_corner_start, corner_speed_limit_m_s).
        On the final lap, lookahead stops at the finish line (no wrap past it); on earlier
        laps it wraps into the next lap's opening segments, matching the closed-circuit
        semantics.
        """
        self._update_track_position()
        if not self.track:
            return float('inf'), float('inf')

        current_segment = self.track[self.current_segment_idx]
        dist_to_end = (self.segment_start_m + current_segment.length_m) - self.lap_relative_m

        dist_to_next = dist_to_end
        idx = self.current_segment_idx + 1
        wrapped = False
        while True:
            if idx >= len(self.track):
                if wrapped or self.lap >= self.laps_total:
                    # Already searched a full lap, or no further laps to wrap into.
                    return float('inf'), float('inf')
                idx = 0
                wrapped = True
                continue

            segment = self.track[idx]
            if segment.radius_m != float('inf'):
                # Rain reduces corner grip (lower mu_lateral implies lower limit)
                limit = self.vehicle.get_corner_speed_limit(segment.radius_m)
                if self.is_raining:
                    limit *= 0.8 # approx 36% less cornering grip (sqrt(0.64))
                return dist_to_next, limit
            dist_to_next += segment.length_m
            idx += 1
            
    def inject_disturbance(self, event_type: str, active: bool = True):
        """
        Inject a disturbance (PRD Section 19).
        Types: 'rain', 'safety_car', 'limited_power'
        """
        if event_type == 'rain':
            self.is_raining = active
            # Rain also increases rolling resistance and reduces braking
            if active:
                self.vehicle.crr *= 1.2
                self.vehicle.mu_longitudinal *= 0.8
                self.vehicle.mu_lateral *= 0.8
            else:
                # Naive reset, real implementation would save base values
                self.vehicle.crr /= 1.2
                self.vehicle.mu_longitudinal /= 0.8
                self.vehicle.mu_lateral /= 0.8
        elif event_type == 'safety_car':
            self.safety_car_active = active
        elif event_type == 'limited_power':
            self.limited_power_mode = active

    def step(self, dt_s: float, requested_power_kw: float, requested_regen_kw: float):
        """
        Simulate a time step of length dt_s -- internally subdivided into substeps of at most
        MAX_SUBSTEP_S for numerical accuracy (see MAX_SUBSTEP_S's comment), while the external
        contract (advance by exactly dt_s, same cumulative-energy accounting) is unchanged.
        """
        if dt_s <= 0:
            return
        n_substeps = max(1, math.ceil(dt_s / MAX_SUBSTEP_S))
        sub_dt_s = dt_s / n_substeps

        # [Fix, history] This flag has been through three designs:
        #
        # 1. Gate on actual_regen_mj (whether regen is *actually* extracting energy right now),
        #    re-evaluated every substep. Broke the moment substeps existed: once a substep fully
        #    drained the car's kinetic energy mid-macro-step, the *next* substep saw zero KE,
        #    concluded "not braking," and re-enabled the ICE -- which generated fresh KE for the
        #    substep after *that* to harvest all over again. An energy-generating oscillation
        #    within a single sustained regen request.
        #
        # 2. Gate on the raw request alone (requested_regen_kw > 0), decided once per macro-step,
        #    with no velocity check. Fixes #1, but creates a worse failure: Baseline0's
        #    depleted-battery fallback (baselines.py) requests regen indefinitely, forever, once
        #    SOC crosses the reserve floor. With no velocity check, once the car coasts to a
        #    stop under that sustained request, the ICE never gets a chance to re-engage again --
        #    the car stalls at v=0 permanently and the race never finishes (confirmed empirically:
        #    a Balanced/seed=7 race hit the 20000-step cap still stuck at distance 0).
        #
        # 3. Gate on the request AND current velocity (> 0), decided once per macro-step. Some
        #    real corner-approach braking that happens to reach exactly v=0 while the caller is
        #    still requesting regen (rare -- most corner limits aren't 0, so the caller's own
        #    braking-distance check in optimizer.py naturally stops requesting regen before the
        #    car fully stops) will still see the same oscillation as #1, one macro-step at a
        #    time instead of one substep at a time -- but critically, each oscillation cycle
        #    still covers real distance (confirmed: a synthetic sustained-full-stop-regen test
        #    kept advancing rather than freezing), so it can never hang a race. Between "loses a
        #    little energy to an occasional resume/re-brake cycle in a rare edge case" and "the
        #    race doesn't finish," this is the only one of the three that's actually safe to run
        #    unattended (e.g. the dashboard's background baseline comparison races).
        suppress_ice = requested_regen_kw > 0.0 and self.velocity_m_s > 0.0
        for _ in range(n_substeps):
            self._substep(sub_dt_s, requested_power_kw, requested_regen_kw, suppress_ice)

    def _substep(self, dt_s: float, requested_power_kw: float, requested_regen_kw: float,
                 suppress_ice: bool):
        """
        The single-substep physics update -- `dt_s` here is one substep's length (see step()
        above), not the length the caller originally requested. `suppress_ice` is decided once
        per macro-step by step() (see its comment for why).
        """
        # --- Battery interaction ---
        # Convert kW to MJ/s * dt = MJ
        # 1 kW = 0.001 MW = 0.001 MJ/s
        requested_discharge_mj = requested_power_kw * 0.001 * dt_s
        requested_regen_mj = requested_regen_kw * 0.001 * dt_s

        # Check against available battery bounds
        actual_discharge_mj = min(requested_discharge_mj, self.battery.soc_mj)

        # For simulation simplicity in MVP step, we accept requested regen if physical bounds allow.
        # Physics bound: can't regen more kinetic energy than we have
        kinetic_energy_mj = 0.5 * self.vehicle.mass * (self.velocity_m_s ** 2) / 1000000.0
        # [Fix] Regen was only ever bounded by available kinetic energy, never by the
        # regulatory MGU-K regen power cap (BatteryModel.max_regen_power_kw, sourced from
        # regulation_config.MAX_MGU_K_REGEN_POWER_KW) -- so nothing here actually enforced that
        # cap the way get_max_deploy_power's DEPLOYMENT_CURVE is enforced on the discharge side.
        # No current caller happens to request more than the cap today, so this wasn't an
        # active bug, but the simulator is meant to be the authoritative physics executor (the
        # same role it already plays for the deploy-side cap and the corner-speed clamp) rather
        # than something that only stays correct because every caller happens to self-limit.
        regen_cap_mj = self.battery.max_regen_power_kw * 0.001 * dt_s
        actual_regen_mj = min(requested_regen_mj, kinetic_energy_mj, regen_cap_mj)

        self.battery.update_soc(actual_discharge_mj, actual_regen_mj)

        self.cumulative_e_discharge_mj += actual_discharge_mj
        self.cumulative_e_regen_mj += actual_regen_mj

        # --- Vehicle dynamics ---
        # Actual MGU-K power delivered in W
        actual_power_w = (actual_discharge_mj * 1000000.0) / dt_s if dt_s > 0 else 0.0

        # Add ICE power (suppressed for the whole macro-step -- see step()'s comment for the
        # `suppress_ice` decision and its history)
        ice_power_w = 0.0 if suppress_ice else (vehicle_config.ICE_POWER_KW * 1000.0)
        total_propulsion_w = actual_power_w + ice_power_w

        net_a = self.vehicle.get_net_acceleration(self.velocity_m_s, total_propulsion_w)

        # Update state (propulsion/drag only -- regen is applied separately below via direct
        # energy conservation, not folded into this acceleration).
        self.velocity_m_s += net_a * dt_s
        self.velocity_m_s = max(0.0, self.velocity_m_s)

        # [Fix] Regen deceleration used to be computed independently from `actual_regen_mj` --
        # as a braking *force* (regen_power_w / v), converted to a deceleration and integrated
        # like any other acceleration term. That's a second, separate calculation of how much
        # kinetic energy gets removed, and nothing tied it back to actually equal
        # `actual_regen_mj` (the amount already credited to the battery, capped above by the
        # car's *total* available kinetic energy). For a single dt_s=1.0s step the two
        # approximately lined up in the common case and this went unnoticed; subdividing step()
        # into finer substeps (see MAX_SUBSTEP_S) exposed it directly: each substep re-checked
        # "is there still enough total KE?" against a velocity that the force-based calculation
        # hadn't actually reduced by the previously-credited amount, so a heavy sustained regen
        # request could get *re-credited* substep after substep and total more energy than the
        # car ever had -- caught by test_regeneration_physical_limit once substeps made it
        # observable. Removing exactly `actual_regen_mj` of kinetic energy directly (rather than
        # deriving a deceleration and hoping it happens to remove the same amount) makes regen
        # energy-conserving by construction, independent of how finely the step is subdivided.
        if actual_regen_mj > 0:
            current_ke_mj = 0.5 * self.vehicle.mass * (self.velocity_m_s ** 2) / 1_000_000.0
            new_ke_mj = max(0.0, current_ke_mj - actual_regen_mj)
            self.velocity_m_s = math.sqrt(2.0 * new_ke_mj * 1_000_000.0 / self.vehicle.mass)

        self._update_track_position()
        if self.track:
            limit = self.vehicle.get_corner_speed_limit(self.track[self.current_segment_idx].radius_m)
            if self.is_raining:
                limit *= 0.8
            # Physical driver limit - driver won't exceed corner grip
            self.velocity_m_s = min(self.velocity_m_s, limit)
            
        if self.safety_car_active:
            self.velocity_m_s = min(self.velocity_m_s, self.safety_car_speed_cap_m_s)

        self.distance_m += self.velocity_m_s * dt_s
        self.distance_m = min(self.distance_m, self.total_race_distance_m)
        self.time_s += dt_s


if __name__ == "__main__":
    sim = Simulator()
    sim.load_track("Balanced", laps=1, seed=1)
    print(f"Loaded track: {sim.lap_length_m:.1f} m x {sim.laps_total} lap(s)")

    steps = 0
    while not sim.is_finished and steps < 20000:
        sim.step(dt_s=1.0, requested_power_kw=200.0, requested_regen_kw=0.0)
        steps += 1

    print(f"Finished in {steps} steps / {sim.time_s:.1f}s, "
          f"final SOC={sim.battery.soc_mj:.2f} MJ, lap={sim.lap}")
