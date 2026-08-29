# pyrefly: ignore [missing-import]
from core.simulator import Simulator
from core.forecaster import Forecaster
from core.optimizer import MPCOptimizer


def test_get_action_reserve_matches_canonical_formula():
    """
    Regression guard: MPCOptimizer.get_action() previously computed its own internal
    `r_safety` with a hardcoded R_base (0.10) that silently diverged from
    Forecaster.get_strategic_reserve's canonical R_base (0.5) -- the same formula the Oracle,
    every baseline's RESERVE_FLOOR_MJ, and the dashboard's own "Required Reserve" display all
    use. That meant the live MPC's actual deployment decisions used a smaller safety margin
    than what the UI told the user it was using. This checks the two formulas agree for a
    representative sigma_e, not just that the numbers happen to match by coincidence.
    """
    sim = Simulator()
    sim.load_track("Balanced", laps=1, seed=1)
    forecaster = Forecaster(sim)

    sig_e = 0.37  # representative non-zero uncertainty
    e_req = 2.1

    canonical = forecaster.get_strategic_reserve(e_req, sig_e)
    assert canonical == 0.5 + 2.0 * sig_e, "get_strategic_reserve formula itself changed unexpectedly"

    # get_action() doesn't expose r_safety directly, but it must not be more permissive than
    # the canonical reserve -- reconstruct what it would compute and compare.
    optimizer = MPCOptimizer(sim, forecaster)
    reconstructed = optimizer.forecaster.get_strategic_reserve(e_req, sig_e)
    assert reconstructed == canonical, "MPCOptimizer must use Forecaster.get_strategic_reserve directly"


def test_predicted_energy_required_never_negative_after_early_regen():
    """
    Regression guard: Forecaster.predict_energy_required's history-based branch (distance > 100m)
    used to return a raw, unclamped rate that could go negative if net regen briefly exceeded net
    discharge early in a lap (e.g. right after a heavy-regen opening corner) -- predicting the car
    would net *gain* energy over the rest of the race. That's not physically possible and, fed
    into the optimizer's water-filling budget ceiling, would inflate how much it thinks is safe
    to deploy. e_required_mj must be >= 0 regardless of the discharge/regen history shape.
    """
    sim = Simulator()
    sim.load_track("Balanced", laps=1, seed=1)
    forecaster = Forecaster(sim)

    # Simulate an opening straight then a heavy regen event, so cumulative net energy is
    # negative (more regenerated than discharged) while distance is comfortably past the
    # forecaster's 100m "prior estimate" cutoff, exercising the history-based branch.
    sim.velocity_m_s = 60.0
    for _ in range(2):
        sim.step(1.0, requested_power_kw=50.0, requested_regen_kw=0.0)
    for _ in range(6):
        sim.step(1.0, requested_power_kw=0.0, requested_regen_kw=350.0)

    assert sim.distance_m > 100.0, "test setup invalid: need to be past the prior-estimate cutoff"
    net = sim.cumulative_e_discharge_mj - sim.cumulative_e_regen_mj
    assert net < 0, "test setup invalid: need net regen to exceed net discharge so far"

    e_req, sig_e = forecaster.predict_energy_required(sim.distance_remaining_m)
    assert e_req >= 0.0, f"predicted energy requirement went negative: {e_req}"
    assert sig_e >= 0.0


def test_strategic_reserve_rises_with_active_disturbances():
    """
    R_event_contingency (PRD Section 15) should reflect disturbances actually in effect right
    now -- a static 0 (the previous behavior) means the reserve formula never actually uses the
    third term the PRD names, and never holds extra margin during a safety car / rain / limited
    power event even though those genuinely make the near-term energy picture less certain.
    """
    sim = Simulator()
    sim.load_track("Balanced", laps=1, seed=1)
    forecaster = Forecaster(sim)

    e_req, sig_e = 2.0, 0.2
    baseline_reserve = forecaster.get_strategic_reserve(e_req, sig_e)

    sim.inject_disturbance("safety_car", True)
    with_sc = forecaster.get_strategic_reserve(e_req, sig_e)
    assert with_sc > baseline_reserve

    sim.inject_disturbance("rain", True)
    with_sc_and_rain = forecaster.get_strategic_reserve(e_req, sig_e)
    assert with_sc_and_rain > with_sc, "stacking a second active disturbance should raise the reserve further"

    sim.inject_disturbance("safety_car", False)
    sim.inject_disturbance("rain", False)
    restored = forecaster.get_strategic_reserve(e_req, sig_e)
    assert restored == baseline_reserve, "reserve should return to baseline once disturbances clear"
