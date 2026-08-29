# Idea Submission — Form Answers

Drop-in answers for the submission form. Copy each block into its matching field.

---

## Theme

The form's theme dropdown is specific to this hackathon's option list, which isn't visible from here — pick whichever of the listed options best matches. Based on what TrackShift BMS actually does, the closest fits, in order of preference, are:

1. **Energy Management / Battery Management Systems**
2. **AI/ML in Motorsport** or **Motorsport Engineering & Strategy**
3. **Sustainable Mobility / EV Technology**

If the dropdown offers something combining energy optimization with motorsport (e.g. "Smart Energy Systems for Racing"), that is the best single match.

---

## Project Title

```
TrackShift BMS — Predictive Energy Deployment for Hybrid F1 Powertrains
```

Shorter alternative if there's a character limit:

```
TrackShift BMS
```

---

## Describe your proposed solution and what makes it innovative.

```
TrackShift BMS is a real-time battery management and energy-deployment strategy
engine for FIA-2026-regulation hybrid F1 powertrains, built around a Model
Predictive Control (MPC) optimizer that decides, every simulation step, exactly
how much electrical power to deploy from the MGU-K versus how much to hold back
in the battery — the same trade-off race engineers manage live with "attack,"
"coast," "harvest," and "conserve" calls.

The core problem: a 2026-spec F1 car's energy store is regulation-capped and
recharges primarily through braking regeneration, not from the ICE. Deploy too
aggressively early in a lap or a stint and the car runs out of usable electric
power exactly where it matters most — the next straight, the next overtake
window. Deploy too conservatively and you leave lap time on the table. This is
a sequential decision problem under uncertainty (future track demand, traffic,
weather, safety cars), which is precisely what MPC is designed for.

TrackShift's optimizer forecasts the energy required to finish the race (Ê)
from the remaining track profile, computes a statistically-grounded safety
reserve (R_safety = R_base + k·σ_Ê + R_event_contingency, where the
contingency term grows under rain, safety car, or reduced-power conditions),
and then "water-fills" the deployable energy budget across the remaining
corners and straights so that no single high-value opportunity is starved
while the reserve is protected. It also evaluates live overtake windows,
comparing the energy cost of an attack against the reserve margin available
before deciding to greenlight it.

What makes it innovative for a hackathon-scale project is that it isn't a
lookup table or a black-box ML model dressed up as "AI strategy" — it's a
physically-grounded, closed-loop control system: a substeped point-mass
vehicle and battery physics simulator, an energy-conserving regen model, a
procedurally generated FIA-realistic track network, and an MPC optimizer that
is benchmarked in real time against an offline Oracle (a full-race,
perfect-hindsight optimal solution) and four baseline heuristic policies —
so every strategy decision the system makes is provably close to optimal,
not just plausible-looking. The entire pipeline runs live in a 3D dashboard
where a judge can inject rain, a safety car, or an MGU-K power limitation
mid-race and watch the strategy re-plan in real time.
```

---

## What technologies, AI/ML models, tools, and datasets do you plan to use?

```
Backend / simulation core (Python 3.11, FastAPI + Uvicorn, WebSocket streaming):
- A reduced-order point-mass vehicle model (drag, downforce-assisted cornering
  grip, traction-limited drive force, rolling resistance) tuned to FIA 2026
  regulation parameters (mass, CdA, CLA, deployment/regen power caps).
- An energy-conserving battery model (kinetic-energy-based regen, SOC
  tracking, regulatory regen-power capping).
- A Model Predictive Control (MPC) optimizer: a rolling-horizon controller
  that re-solves a constrained energy-allocation problem every step using a
  water-filling algorithm over a forecast demand curve, with a live
  strategic-reserve calculation and overtake-opportunity evaluator.
- An Energy Forecaster that predicts total race energy requirement (Ê) and
  its uncertainty (σ_Ê) from partial-race telemetry, using both a track-model
  prior (cold start) and a running-rate estimator (mid-race).
- An Oracle optimizer — a full-race, non-causal optimal solver used purely
  as an offline upper-bound benchmark for the live MPC.
- Four deterministic baseline policies (no-optimization, rule-based
  conserve, greedy-deploy, and a regulation-aware balanced policy) that the
  MPC is scored against.
- A procedural track generator that produces closed-loop, curvature-feasible
  circuits per "track class" (street/permanent/hybrid-style layouts) using
  Dubins-style closure constraints — this is the "dataset": there is no
  external telemetry dataset, tracks and race conditions are generated
  on-demand so every run is a fresh, reproducible (seeded) scenario.
- pytest test suite covering energy conservation, regen physics limits,
  reserve-formula consistency, and dashboard/session state correctness.

Frontend (vanilla JS, no framework):
- Three.js (r128) for the live 3D track/car visualization, with an FBX-loaded
  car model, chase camera and free-orbit camera (OrbitControls).
- Chart.js for live and exported telemetry graphs (SOC, energy-to-finish,
  speed).
- jsPDF + jspdf-autotable for full client-side race-report PDF export
  (summary stats, baseline comparison table, lap times, event timeline,
  vector-drawn logo, rendered graphs) — no server-side rendering involved.
- A WebSocket client driving all live telemetry, strategy, and event-timeline
  UI state at simulation tick rate.

No pretrained ML models are used. The "intelligence" in the system is a
classical optimal-control / operations-research approach (MPC + water-filling
+ statistical reserve estimation), chosen deliberately over a black-box model
because race-strategy decisions need to be explainable and provably
constraint-safe (the car can never be recommended a strategy that mathematically
strands it energy-negative before the finish) — a guarantee a trained model
cannot give without extensive out-of-distribution testing.
```

---

## How will you validate your solution's performance, feasibility, and effectiveness?

```
1. Physics correctness (automated tests): pytest suite asserts energy
   conservation across the vehicle/battery/simulator pipeline (energy in -
   energy out - losses = 0 within numerical tolerance), that regen respects
   both the kinetic-energy ceiling and the regulatory MGU-K power cap, and
   that the strategic-reserve formula used live by the optimizer matches the
   canonical formula used everywhere else in the system (dashboard display,
   Oracle, baselines) — closing a class of bug we found mid-development
   where the live optimizer and the displayed "required reserve" had quietly
   drifted apart.

2. Optimality benchmarking: every live MPC run is compared against (a) the
   Oracle's full-race optimal-hindsight solution as an upper bound, and
   (b) four baseline heuristic policies as lower/reference bounds, using
   identical track, seed, and disturbance conditions. This turns "is the
   strategy good?" into a measurable percentage gap-to-optimal rather than a
   subjective judgment.

3. Stress testing under disturbance: races are run across multiple track
   classes and RNG seeds with rain, safety car, and reduced-power events
   injected mid-race, checking that (a) no run ever "hangs" (stalls
   permanently at zero velocity — verified across 60+ stress races with zero
   stuck outcomes after fixing a regen/ICE-suppression edge case), and (b)
   the reserve grows correctly and the optimizer visibly de-rates deployment
   under each disturbance type.

4. Numerical integration accuracy: the physics step was substeped (≤0.1s
   internal steps regardless of the external tick rate) and cross-checked
   against the original single-step integration to confirm substepping
   didn't change race outcomes beyond floating-point noise, while exposing
   (and fixing) two previously-latent physics bugs the coarser step had
   been masking.

5. Live/manual validation: the dashboard itself is the validation harness —
   a judge or user can start a race, inject any combination of disturbances,
   retune mass/downforce/battery-capacity mid-race, and visually confirm the
   optimizer's action (Attack/Coast/Harvest/Conserve), deployable energy, and
   reserve numbers respond correctly and immediately, then export a full PDF
   report of the run for offline review.

6. Cross-viewport / UX validation: the dashboard was tested across five
   viewport sizes (desktop through phone) via automated browser testing to
   confirm no layout overflow, correct control behavior, and zero console
   errors, since the deliverable is a live interactive tool judges will use
   themselves, not just a slide deck.
```
