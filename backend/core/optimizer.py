import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from core.simulator import Simulator
from config.regulation_config import DEPLOYMENT_CURVE

class MPCOptimizer:
    """
    Receding-horizon optimizer (PRD Section 16 & 17).
    """
    def __init__(self, simulator: Simulator, forecaster, horizon_steps: int = 5):
        self.simulator = simulator
        self.forecaster = forecaster
        self.horizon_steps = horizon_steps

        # _solve_sequence's reserve requirement is a closed-form greedy allocation now (see its
        # docstring), not an SLSQP objective/penalty -- no lambda weights needed for it.
        
    def get_max_deploy_power(self, velocity_kmh: float, limited_power_mode: bool = False) -> float:
        from config.regulation_config import DEPLOYMENT_CURVE, LIMITED_POWER_MODE_CURVE
        curve = LIMITED_POWER_MODE_CURVE if limited_power_mode else DEPLOYMENT_CURVE
        
        if velocity_kmh <= curve[0]["speed_kmh"]: return curve[0]["power_kw"]
        if velocity_kmh >= curve[-1]["speed_kmh"]: return curve[-1]["power_kw"]
        for i in range(len(curve) - 1):
            p1, p2 = curve[i], curve[i+1]
            if p1["speed_kmh"] <= velocity_kmh <= p2["speed_kmh"]:
                ratio = (velocity_kmh - p1["speed_kmh"]) / (p2["speed_kmh"] - p1["speed_kmh"])
                return p1["power_kw"] + ratio * (p2["power_kw"] - p1["power_kw"])
        return 0.0

    def _max_useful_deploy_kw(self, simulator_state, horizon_steps: int, dt_s: float,
                               reference_deploy_kw=None) -> np.ndarray:
        """
        Returns, for each horizon step, the maximum battery deploy power (kW) that would
        actually translate into extra force/speed -- not just whatever `max_deploy_power`
        (the regulatory deployment-curve cap) allows. f_drive = min(P_total/v, f_traction_max)
        caps *combined* (ICE + battery) force at the traction ceiling regardless of how much
        power was requested beyond that point, and Simulator.step() still discharges the full
        requested amount even when none of it turned into acceleration -- so deploying more
        than the traction ceiling allows, or deploying at all once already at the current
        segment's corner-speed cap, is pure waste.

        `reference_deploy_kw`, if given, is a previous deployment plan to advance the
        reference trajectory with (instead of ICE-only) -- see _solve_deployment_plan's
        fixed-point refinement for why: this method's own ceiling is evaluated *along* a
        velocity trajectory, but that trajectory depends on how much gets deployed and when,
        which is exactly what's being solved for. An ICE-only reference is the only option on
        the first pass, but it goes stale once a real plan spreads meaningful deployment across
        the horizon (the real car reaches each segment sooner, at a higher speed, than an
        ICE-only guess predicts) -- feeding the previous pass's plan back in here keeps the
        ceiling evaluated against a trajectory much closer to the one the solve actually
        produces.

        The ceiling at each step is the *force* headroom above what ICE alone already demands
        (f_traction_max - ice_power_w/v), converted back to a power figure at that step's speed
        (P = F * v) -- not a binary "capped or not" flag, because that headroom is continuous:
        e.g. at moderate speed, ICE alone can sit comfortably under the traction ceiling while
        ICE + a full 350kW deploy request blows well past it, wasting most of that deployment
        even though ICE alone wasn't the thing capping it. The P = F * v conversion also
        naturally shrinks the ceiling to ~0 right at a dead stop (v -> 0), without needing a
        separate low-speed special case: any fixed *force* headroom corresponds to vanishingly
        little usable *power* headroom when velocity itself is near zero.

        Evaluated by cloning `simulator_state` and stepping the clone forward with zero
        deployment, reusing the real simulator's own corner-lookup/track-position physics
        exactly rather than re-deriving a parallel approximation of it. Cheap: one clone plus
        `horizon_steps` plain steps, done once per solve (not once per SLSQP iteration -- there
        is no iterative solver here any more).

        [Fix, history] Earlier versions of this were a binary mask -- first only checking the
        traction-limited launch phase at the very start of a race (v=0), which fixed dumping
        the whole deployment budget into a traction-wasted launch but not the general version
        of the same problem across a full lap's several acceleration zones. Then checking
        whether the ICE-only reference trajectory was still gaining speed at all, which
        mistook a car cruising at *ICE-alone's own* drag-equilibrium terminal velocity for
        "capped" even though extra deploy power would still raise that equilibrium point --
        starving the online MPC's short horizon, which spends most of its 5 steps at or near
        steady cruising speed. Then checking whether *ICE alone* saturates the traction ceiling
        -- true near a dead stop, but false well before the ceiling is actually reached for the
        *combined* power a full deploy request represents, so front-loading kept concentrating
        most of a race's energy into the first ~10 seconds after any corner exit regardless,
        which measurably lost to baselines that spread smaller deployments across every
        acceleration zone on tracks with several of them. This continuous, combined-power
        version is the one that actually matches what Simulator.step() does with the request.
        """
        import copy
        sim_clone = copy.deepcopy(simulator_state)
        ice_power_w = self._ice_power_w()
        ceiling_kw = np.zeros(horizon_steps)

        for i in range(horizon_steps):
            v = sim_clone.velocity_m_s
            vehicle = sim_clone.vehicle
            forces = vehicle.calculate_forces(v)
            f_traction_max = vehicle.mu_longitudinal * (vehicle.mass * 9.81 + forces["f_downforce"])
            f_from_ice = ice_power_w / max(v, 0.1)
            force_headroom_n = max(0.0, f_traction_max - f_from_ice)
            useful_kw = (force_headroom_n * v) / 1000.0

            corner_capped = False
            if sim_clone.track:
                segment = sim_clone.track[sim_clone.current_segment_idx]
                limit = vehicle.get_corner_speed_limit(segment.radius_m)
                if sim_clone.is_raining:
                    limit *= 0.8
                corner_capped = v >= limit - 1e-6

            # [Fix] Also anticipate an *upcoming* corner, not just the current segment's own
            # limit -- mirrors MPCOptimizer.get_action()'s live corner-approach check
            # (dist_to_next <= braking_dist + margin), which the Oracle's pre-solved-and-
            # replayed sequence otherwise never gets. Without this, the water-filling
            # allocation happily accelerates right up to a corner it's about to be
            # *instantly* clamped at by Simulator.step()'s hard corner-speed cap -- discarding
            # real kinetic energy for free (no regen recovered, since these deployment plans
            # never request any) and then spending more battery re-accelerating from the
            # clamped-down speed. A car that never overshoots a corner doesn't pay that cost.
            # Measured on a corner-heavy track: this was the difference between a repeated
            # "accelerate hard, get clamped, re-accelerate" sawtooth losing outright to a
            # baseline that simply never approached any corner fast enough to trigger it.
            approaching_corner = False
            if sim_clone.track:
                dist_to_next, next_limit = sim_clone.get_next_corner()
                if v > next_limit:
                    max_decel = vehicle.get_max_braking_deceleration()
                    braking_dist = (v ** 2 - next_limit ** 2) / (2 * max_decel)
                    approaching_corner = dist_to_next <= braking_dist + 15.0

            ceiling_kw[i] = 0.0 if (corner_capped or approaching_corner) else useful_kw
            # Advance the reference trajectory using the previous pass's plan (if any) rather
            # than always ICE-only, so later refinement passes evaluate the ceiling against a
            # velocity profile close to what this deployment actually produces.
            step_deploy_kw = reference_deploy_kw[i] if reference_deploy_kw is not None else 0.0
            sim_clone.step(dt_s, step_deploy_kw, 0.0)

        return ceiling_kw

    @staticmethod
    def _ice_power_w() -> float:
        import config.vehicle_config as vehicle_config
        return vehicle_config.ICE_POWER_KW * 1000.0

    def estimate_horizon_steps(self, simulator_state, dt_s: float, max_steps: int) -> int:
        """
        Returns how many time-steps it actually takes to cover the remaining race distance
        from `simulator_state`'s current position -- determined by cloning the simulator and
        stepping it forward on ICE power alone (no battery deployment) until the race finishes
        or `max_steps` is hit, rather than assuming a fixed constant average speed.

        [Fix] The previous estimate a caller here used (`max(10.0, velocity_m_s or 60.0)` as a
        flat average-speed guess) was off by 30-40%+ in practice -- measured real average
        speeds of 85-93 m/s for a car starting from rest, against a 60 m/s guess. That matters
        a great deal for _solve_deployment_plan's horizon-length parameter: a plan that spreads
        its energy budget evenly across an *overestimated* horizon strands whatever it
        allocated to the steps beyond where the real race actually ends -- measured as ~30% of
        the Oracle's energy budget left unused at the reserve floor instead of spent, which was
        indistinguishable, from the outside, from the plan simply being wrong about how useful
        deployment was later in the race (it wasn't -- it just never got to execute).

        ICE-only is a deliberately conservative (i.e. slower than reality) reference -- actual
        deployment only speeds the car up further, never slows it down -- so this slightly
        overestimates the true horizon rather than risking the costlier failure of
        underestimating it, which would leave the back half of the race with no plan at all
        (coasting on ICE alone by construction, once the solved sequence runs out).
        """
        import copy
        sim_clone = copy.deepcopy(simulator_state)
        steps = 0
        while steps < max_steps and not sim_clone.is_finished:
            sim_clone.step(dt_s, 0.0, 0.0)
            steps += 1
        return max(1, steps)

    def _solve_deployment_plan(self, simulator_state, horizon_steps, max_deploy_power, sim_soc_start,
                                e_req, r_safety, dt_s, refinement_passes: int = 3) -> np.ndarray:
        """
        Solves for the deployment sequence via _solve_sequence, refining the per-step
        usefulness ceiling (_max_useful_deploy_kw) against the plan's *own* resulting
        trajectory a few times -- a small fixed-point iteration, since that ceiling is
        evaluated along a velocity trajectory that itself depends on the deployment plan being
        solved for. The first pass has no better option than an ICE-only reference; each
        subsequent pass re-evaluates the ceiling by advancing the reference trajectory with the
        *previous* pass's plan instead, which stays accurate once the solve spreads meaningful
        deployment across the horizon rather than concentrating it where an ICE-only guess
        happens to still hold.
        """
        u_sequence = np.zeros(horizon_steps)  # first pass: equivalent to an ICE-only reference
        for _ in range(max(1, refinement_passes)):
            max_useful_deploy_kw = self._max_useful_deploy_kw(
                simulator_state, horizon_steps, dt_s, reference_deploy_kw=u_sequence
            )
            u_sequence = self._solve_sequence(
                horizon_steps, max_deploy_power, sim_soc_start, e_req, r_safety, dt_s,
                max_useful_deploy_kw=max_useful_deploy_kw,
            )
        return u_sequence

    def _solve_sequence(self, horizon_steps, max_deploy_power, sim_soc_start, e_req, r_safety, dt_s,
                         max_useful_deploy_kw=None):
        """
        Solves for the deployment-power sequence over `horizon_steps` that spreads the
        available energy budget as evenly as possible across every step where it's actually
        useful (each step capped at `max_useful_deploy_kw[i]`, see _max_useful_deploy_kw --
        power beyond what a traction- or corner-capped car can use is wasted there), without
        projecting SOC below the reserve requirement. Factored out so both the receding-horizon
        get_action() (short horizon, re-solved every call) and OracleOptimizer's one-shot
        full-race solve (long horizon, solved once) share one implementation.

        [Fix, history] This went through several designs, each fixing a real bug the previous
        one had:

        1. Originally an SLSQP solve penalizing reserve violations as a soft cost, comparing
           sim_soc against `e_req` -- the energy needed for the *entire* remaining race,
           computed once before the horizon started -- unchanged at every step instead of
           decaying it as more of that same distance gets simulated *within* the horizon. On a
           long horizon (the Oracle's one-shot full-race solve) that made the model think it
           still owed the *whole race's* budget a few steps from the finish line, starving
           deployment almost everywhere. Fixed by decaying `e_req` proportionally to how much
           of the horizon remains at each step (`remaining_fractions` below) and converting the
           penalty into a real SLSQP constraint.

        2. The reserve constraint is a bound on *cumulative* discharge by each step, so many
           time-distributions of the same total energy score identically on a "maximize total
           deployment" objective -- SLSQP, from a flat initial guess, landed on a flat/spread
           solution that, in practice, stranded energy: `horizon_steps` is only an *estimate*
           of the real race length (see _solve_full_race's nominal_speed_m_s guess), and
           whatever a flat plan allocated past where the real race actually finished never
           executed (measured: ~1.5 MJ of 4 MJ left unused). This got "fixed" by replacing
           SLSQP with a closed-form greedy allocation that front-loads -- spend the maximum
           possible as *early* as possible -- which does use the full budget reliably.

        3. Front-loading turned out to be the wrong shape for a different reason: `f_drive =
           P/v` means the marginal speed benefit of extra power shrinks as speed rises, so
           blowing the whole budget in one early burst reaches a high peak speed briefly, then
           leaves nothing for the rest of a long race -- while a smaller, *sustained* boost
           spread across the entire race raises the car's cruising speed (well above its
           ICE-only drag-equilibrium terminal velocity, not something a traction/corner check
           alone flags) for the whole remaining distance. Measured head-to-head with identical
           total energy (3.50 MJ front-loaded vs. 3.52 MJ spread at ~47 kW average): the spread
           allocation finished a lap 7 seconds faster. This is what actually drove the Oracle
           losing to simpler baselines (Aggressive, Fixed Heuristic) that deploy continuously
           rather than front-loading -- not a numerical bug, a genuinely wrong allocation shape.

        The fix spreads the budget with a water-filling allocation: start from a uniform rate
        across every step, and wherever that rate would exceed a step's own usefulness cap,
        pin that step at its cap and raise the rate for the remaining steps to compensate,
        repeating until the whole budget is placed (or every step is capped). This is exactly
        the "even as possible, but never wasted on a capped step" shape #3 calls for, still
        computed once in closed form -- no iterative solver, and it uses the full budget for
        the same reason the front-loaded version did (this only targets the aggregate budget
        bound by the tightest point in the horizon, which is exact whenever the reserve ceiling
        is flat across the horizon -- i.e. whenever e_req is ~0, true for every case measured
        so far now that the Forecaster's negative-rate bug is fixed; see `ceiling` below).
        """
        # [Fix] kW -> MJ discharged per step, matching how the real simulator actually spends
        # SOC: Simulator.step() converts requested_power_kw straight to MJ (`* 0.001 * dt_s`,
        # no efficiency factor), and BatteryModel.update_soc() only applies round-trip
        # efficiency loss to *regen* (`net_regen_mj = self.regen_efficiency * e_regen_mj`) --
        # discharge is modeled as lossless in this MVP battery model. This used to divide by
        # discharge_efficiency (sqrt of the regen round-trip figure), which doesn't correspond
        # to anything the real physics does on the discharge side; it just made this method
        # believe every kW cost ~5.4% more stored energy than it actually does, so the greedy
        # allocation below hit its ceiling and stopped early, leaving real energy unused.
        discharge_coef = 0.001 * dt_s
        remaining_fractions = (horizon_steps - np.arange(horizon_steps)) / horizon_steps
        e_req_remaining = e_req * remaining_fractions

        # Max cumulative discharge allowed by step i, so that SOC at step i still covers the
        # (decaying) remaining requirement plus the safety reserve.
        ceiling = sim_soc_start - e_req_remaining - r_safety

        # `ceiling` is monotonic in i (linear in e_req_remaining, which is itself linear in i),
        # but whether it's non-increasing or non-decreasing depends on the sign of e_req -- so
        # the constraint that actually matters *by* step i is the tightest one from i onward,
        # not just ceiling[i] itself. A reverse running-minimum gets this right regardless of
        # which direction `ceiling` slopes (or if e_req is ~0 and it's flat).
        effective_ceiling = np.minimum.accumulate(ceiling[::-1])[::-1]

        if max_useful_deploy_kw is None:
            max_useful_deploy_kw = np.full(horizon_steps, max_deploy_power)
        per_step_cap_kw = np.minimum(max_deploy_power, max_useful_deploy_kw)

        # Total usable budget across the horizon: the tightest point in `effective_ceiling`
        # (its first entry, since it's non-decreasing -- see the comment above). Using a single
        # aggregate figure rather than enforcing every intermediate ceiling individually is
        # exact whenever `ceiling` is flat (e_req ~= 0, the common case per this method's
        # docstring); if e_req is meaningfully non-zero the water-filling below could in
        # principle front-run a tighter *intermediate* ceiling than this final aggregate
        # allows, which isn't caught here.
        total_budget_mj = max(0.0, np.min(effective_ceiling))

        # Water-filling: start every step at an equal share of the budget, and wherever that
        # share would exceed a step's own usefulness cap, pin that step at its cap and raise
        # the shared rate for the remaining steps to absorb what it couldn't take -- the
        # "spread as evenly as possible without wasting any of it on a capped step" allocation
        # shape #3 above calls for. Each pass caps at least one more step, so this converges in
        # at most `horizon_steps` passes.
        u_sequence = np.zeros(horizon_steps)
        active = np.ones(horizon_steps, dtype=bool)
        remaining_mj = total_budget_mj
        for _ in range(horizon_steps):
            active_idx = np.flatnonzero(active)
            if active_idx.size == 0 or remaining_mj <= 1e-12:
                break
            rate_kw = remaining_mj / (active_idx.size * discharge_coef) if discharge_coef > 0 else 0.0
            over_cap = active_idx[per_step_cap_kw[active_idx] <= rate_kw]
            if over_cap.size == 0:
                u_sequence[active_idx] = rate_kw
                break
            u_sequence[over_cap] = per_step_cap_kw[over_cap]
            remaining_mj -= np.sum(per_step_cap_kw[over_cap]) * discharge_coef
            active[over_cap] = False

        return u_sequence

    def get_action(self, simulator_state, dt_s=1.0) -> tuple[float, float]:
        """
        Runs the MPC optimization over the horizon to find the optimal deployment sequence.
        Returns the first action of the optimal sequence (u_deploy, u_regen).
        """
        v_kmh = simulator_state.velocity_m_s * 3.6
        max_deploy_current = self.get_max_deploy_power(v_kmh, simulator_state.limited_power_mode)

        # -------------------------------------------------------------
        # Corner Braking / Regen Logic
        # -------------------------------------------------------------
        dist_to_next, limit_m_s = simulator_state.get_next_corner()
        current_v = simulator_state.velocity_m_s
        
        if current_v > limit_m_s:
            max_decel = simulator_state.vehicle.get_max_braking_deceleration()
            # Braking distance required to reach limit_m_s
            braking_dist = (current_v**2 - limit_m_s**2) / (2 * max_decel)
            
            # If we are within the braking zone (plus a small safety margin), apply full regen
            if dist_to_next <= braking_dist + 15.0:
                from config.regulation_config import MAX_MGU_K_REGEN_POWER_KW
                return (0.0, float(MAX_MGU_K_REGEN_POWER_KW))

        # Distance remaining for full-race prediction
        distance_remaining_m = simulator_state.distance_remaining_m
        e_req, sig_e = self.forecaster.predict_energy_required(distance_remaining_m)
        # [Fix] Was a hardcoded local `0.10 + 2.0 * sig_e` -- a *different* R_base (0.10) than
        # the canonical R_base=0.5 every other policy in the comparison actually uses
        # (Forecaster.get_strategic_reserve itself, OracleOptimizer._solve_full_race, and
        # baselines.py's RESERVE_FLOOR_MJ, which explicitly documents matching this same
        # constant). That meant the live "Proposed System (MPC)" -- the flagship policy this
        # whole dashboard races -- was actually holding back *less* safety margin than the
        # Oracle and baselines it's being compared against, and less than what the dashboard's
        # own telemetry panel displays as "Required Reserve" (dashboard_server.py computes that
        # display value via this same shared method, so it never matched what get_action() had
        # actually used internally to decide how much to deploy).
        r_safety = self.forecaster.get_strategic_reserve(e_req, sig_e)

        # Soft-then-hard reserve logic (Section 16.4 & 16.5)
        # In MVP, we keep it hard if reserve is tight
        deployable_mj = simulator_state.battery.soc_mj - e_req - r_safety
        if deployable_mj <= 0:
            max_deploy_current = 0.0 # Force conserve

        u_sequence = self._solve_deployment_plan(
            simulator_state, self.horizon_steps, max_deploy_current, simulator_state.battery.soc_mj,
            e_req, r_safety, dt_s,
        )

        optimal_u_0 = u_sequence[0]
        return (optimal_u_0, 0.0)

    def evaluate_overtake_opportunity(self, simulator_state) -> dict | None:
        """
        Dynamically evaluates the risk/reward of overtaking on an upcoming straight.
        Returns a dict with assessment details if an opportunity is detected, else None.
        """
        if not simulator_state.track:
            return None
            
        current_segment = simulator_state.track[simulator_state.current_segment_idx]
        
        # Only consider overtakes on straights longer than 400m
        if current_segment.segment_type != 'straight' or current_segment.length_m < 400:
            return None
            
        # If we are near the end of the straight, don't trigger (e.g. less than 150m left)
        dist_remaining_in_seg = (simulator_state.segment_start_m + current_segment.length_m) - simulator_state.lap_relative_m
        if dist_remaining_in_seg < 150:
            return None
            
        # --- Dynamic Cost Calculation ---
        # Need a speed delta to overtake (e.g. +15 km/h = ~4.17 m/s)
        delta_v_m_s = 15.0 / 3.6
        overtake_v = simulator_state.velocity_m_s + delta_v_m_s
        
        # Estimate power required to maintain this speed against drag
        # Drag force = 0.5 * rho * CdA * v^2
        # [Fix] CdA and the rolling-resistance coefficient were hardcoded (1.0, 0.015) instead
        # of read from the vehicle's actual live config (CDA=0.95 by default -- see
        # config/vehicle_config.py -- and crr=0.0135, both of which also change under tuning
        # sliders or rain, which multiplies crr by 1.2). A hardcoded figure here silently
        # stopped tracking the real car being simulated, most visibly during rain: the assessed
        # overtake cost wouldn't reflect the actual higher rolling resistance the car is
        # experiencing at that moment.
        rho = 1.225
        drag_force = 0.5 * rho * simulator_state.vehicle.cda * (overtake_v ** 2)
        rolling_res = simulator_state.vehicle.crr * simulator_state.vehicle.mass * 9.81
        total_force = drag_force + rolling_res
        
        # Power = Force * Velocity
        power_w = total_force * overtake_v
        
        # Time to complete overtake (e.g. over 300m)
        time_to_overtake_s = 300.0 / max(1.0, overtake_v)
        
        # Energy cost (Joules -> MJ)
        energy_cost_mj = (power_w * time_to_overtake_s) / 1_000_000.0
        
        # Add a baseline MGU-K override cost to simulate the burst
        energy_cost_mj += 0.2
        
        # Determine Deployable Energy
        distance_remaining_m = simulator_state.distance_remaining_m
        e_req, sig_e = self.forecaster.predict_energy_required(distance_remaining_m)
        # Same fix as get_action() above -- use the canonical shared reserve formula instead of
        # a separately-hardcoded (and inconsistent) R_base.
        r_safety = self.forecaster.get_strategic_reserve(e_req, sig_e)
        deployable_mj = simulator_state.battery.soc_mj - e_req - r_safety
        
        # Evaluate Risk
        if deployable_mj > energy_cost_mj + 0.2:
            risk = "LOW"
            recommendation = "ATTACK"
        elif deployable_mj > 0:
            risk = "MARGINAL"
            recommendation = "DRIVER DISCRETION"
        else:
            risk = "HIGH"
            recommendation = "HOLD"
            
        # Expected time gain
        time_gain_s = 300.0 / max(1.0, simulator_state.velocity_m_s) - time_to_overtake_s
        
        return {
            "cost_mj": round(energy_cost_mj, 2),
            "reward_s": round(max(0.1, time_gain_s), 2),
            "risk": risk,
            "recommendation": recommendation,
            "deployable_mj": round(deployable_mj, 2)
        }


if __name__ == "__main__":
    from core.forecaster import Forecaster

    sim = Simulator()
    sim.load_track("Balanced", laps=1, seed=1)
    sim.velocity_m_s = 40.0
    forecaster = Forecaster(sim)
    optimizer = MPCOptimizer(sim, forecaster, horizon_steps=5)

    u_deploy, u_regen = optimizer.get_action(sim, dt_s=1.0)
    print(f"At v={sim.velocity_m_s} m/s, SOC={sim.battery.soc_mj} MJ: "
          f"deploy={u_deploy:.1f} kW, regen={u_regen:.1f} kW")
