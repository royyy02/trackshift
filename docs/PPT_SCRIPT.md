# PPT Script — TrackShift BMS Idea Submission Deck

12 slides, built for a technical judging panel (Plaksha x Mphasis x Toyota Gazoo Racing Haas F1). Each entry lists what goes ON the slide, what screenshot/image to capture, and speaker notes (what to say if this deck is presented live, or narration if it doubles as the video script's visual track).

**Where to get each screenshot**: run `python backend/dashboard_server.py`, open `http://localhost:8001`, start a race, and capture at the moments noted. Use browser zoom ~100% at a desktop-sized window (≥1400px wide) so the HUD isn't in its collapsed mobile layout.

---

### Slide 1 — Title

**Content:**
- Title: **TrackShift BMS**
- Subtitle: *Predictive Energy Deployment for Hybrid F1 Powertrains*
- Team name, event name (Plaksha x Mphasis Foundation x Toyota Gazoo Racing Haas F1), date
- Small tagline strip: "MPC-driven battery strategy · Live 3D simulation · Benchmarked against optimal"

**Image:** The app's own logo mark (red rounded-square bolt icon + "TRACKSHIFT BMS" wordmark) — screenshot the header logo at high zoom, or re-export it: it's drawn as a vector `drawLogo()` function in `frontend/app.js`, also embossed on every exported PDF's first page. Use the PDF's title-page logo for the cleanest crop.

**Speaker notes:**
"TrackShift BMS is a real-time energy strategy system for FIA-2026-regulation hybrid F1 cars — it decides, every second of a race, how much electric power to deploy versus hold in reserve, the same call a race engineer makes live over the radio."

---

### Slide 2 — The Problem

**Content (bullets, no image needed, or a simple diagram):**
- 2026 F1 regulations shift power balance dramatically toward electrical deployment (near-50/50 ICE/MGU-K split)
- The battery is capacity-capped and recharges mainly from braking (regen) — not free energy
- Deploy too early/aggressively → run dry before the straight or overtake window that actually needs it
- Deploy too conservatively → leave lap time on the table every single lap
- This is a **sequential decision problem under uncertainty**: track profile, traffic, weather, safety cars

**Image (optional):** a simple 2-box diagram — "Too aggressive → stranded" / "Too conservative → slow" — can be built directly in PowerPoint, no screenshot needed.

**Speaker notes:**
"Under 2026 rules the electrical side of the powertrain roughly doubles in importance. That turns energy deployment into a genuine optimization problem — not just a dial a driver sets once — because the right amount of deployment right now depends on what the rest of the race still demands."

---

### Slide 3 — Our Approach (High-Level)

**Content:**
- One-line framing: *"We built the race engineer's decision process as a closed-loop control system, not a black box."*
- 4-stage pipeline diagram (build as SmartArt/boxes, left→right):
  1. **Forecast** — predict total energy required to finish (Ê) and its uncertainty (σ_Ê)
  2. **Reserve** — compute a safety margin that grows under rain/safety-car/power-loss
  3. **Optimize** — MPC water-fills the deployable budget across remaining track
  4. **Benchmark** — every decision is scored live against an Oracle (optimal) and 4 baselines

**Image:** None required — this is a diagram slide. If you want a real screenshot anchor, use the dashboard's **Strategy panel** (Energy to Finish / σ_Ê / Required Reserve / Deployable readouts) as a small inset in the corner.

**Speaker notes:**
"Four stages, re-run every simulation tick: forecast how much energy the rest of the race needs, size a safety reserve that automatically grows if it starts raining or a safety car comes out, optimize deployment across the remaining track with a water-filling allocation, and continuously benchmark that decision against both a theoretical-optimal Oracle and simpler baseline strategies — so we always know exactly how good 'good' is."

---

### Slide 4 — Live 3D Dashboard (Hero Shot)

**Content:** Minimal text — this is a visual slide. Maybe one caption: *"A full race engineering terminal, live in the browser."*

**Image:** Full-window screenshot of the dashboard mid-race — chase camera active, car visibly on-track, HUD panel + minimap visible on the right, left dock (Setup) open or closed (closed looks cleaner for a hero shot), telemetry gauges showing non-zero speed/SOC. This is your single best "wow" image — spend time getting a clean angle (chase cam, car mid-corner or on a straight with visible speed).

**Speaker notes:**
"Everything you're about to see is live and interactive, not a mockup — this is the actual dashboard running the actual physics simulation."

---

### Slide 5 — Vehicle & Battery Physics

**Content (bullets, technical but concise):**
- Point-mass vehicle model: drag, downforce-assisted cornering grip, traction-limited drive force, rolling resistance
- Corner-speed limit derived from lateral-grip vs. centripetal-force balance (with downforce assist)
- Battery: energy-conserving regen (kinetic-energy-based, not force-approximated), SOC tracking, regulation-capped regen power
- Integration substeped to ≤0.1s internally regardless of external tick rate, for numerical accuracy

**Image:** Screenshot of the in-app **"How It Works" documentation overlay** (the 7th dock-rail icon), scrolled to the **Vehicle Model** and **Battery Model** sections — shows the actual formulas rendered in the UI. This doubles as proof the math is real and inspectable, not just claimed in a slide.

**Speaker notes:**
"Rather than approximate deceleration with a fudge-factor, regen is derived directly from kinetic energy removed — energy conservation isn't just tested, it's structurally guaranteed by how the equations are written."

---

### Slide 6 — The MPC Optimizer & Strategic Reserve

**Content:**
- Show the strategic reserve formula prominently: **R_safety(t) = R_base + k·σ_Ê(t) + R_event_contingency(t)**
- Explain water-filling: deployable budget spread across remaining corners/straights so no single high-value moment is starved
- Note: reserve automatically inflates under rain / safety car / reduced power — same formula used everywhere in the system (fixed a real inconsistency bug where the live optimizer and the displayed reserve had drifted apart)

**Image:** Screenshot of the **Strategy panel** mid-race showing the action box (Attack/Coast/Harvest/Conserve) with its colored left-border, plus Energy-to-Finish, σ_Ê, Required Reserve, Deployable readouts all populated with real numbers. Optionally pair with the **docs overlay's MPC Optimizer / Oracle** sections.

**Speaker notes:**
"This one formula is the safety backbone of the whole system — the base reserve, plus a term that scales with how uncertain our energy forecast currently is, plus an explicit contingency that grows the moment conditions get worse. It's the same number everywhere in the app, which we treat as a correctness invariant, not a nice-to-have."

---

### Slide 7 — Overtake Intelligence

**Content:**
- The optimizer doesn't just conserve — it actively evaluates overtake opportunities in real time
- Weighs the energy cost of an attack move against current reserve margin before recommending it
- Uses live vehicle parameters (aero, rolling resistance) so tuning or rain changes the calculation, not a hardcoded constant

**Image:** Screenshot of the **Overtake panel** when it's active/visible during a race (trigger by racing until an overtake window appears, or by describing the panel if it isn't visually triggered easily — otherwise use the docs overlay's "Overtake Assessment" section as a fallback).

**Speaker notes:**
"Strategy isn't only about not running out of energy — it's about spending energy on the moments that are actually worth it. This panel is where that trade-off becomes visible."

---

### Slide 8 — Benchmarking Against Optimal

**Content:**
- Explain the Oracle: a full-race, perfect-hindsight solve — the theoretical best possible outcome for a given track/seed
- Explain the 4 baselines: No-Optimization, rule-based Conserve, greedy Deploy, regulation-aware Balanced
- Every MPC run is scored as a **% gap to Oracle-optimal**, not a subjective "seems fine"

**Image:** Screenshot of the **Baseline comparison table** in the dashboard (or in an exported PDF) showing MPC vs. Oracle vs. the four baselines side by side with real finish times/energy numbers.

**Speaker notes:**
"This is what separates a strategy system from a strategy demo — we don't just show a number, we show exactly how close that number is to the best it could possibly be, every single run."

---

### Slide 9 — Disturbance Robustness

**Content:**
- Judges/users can inject Rain, Safety Car, or MGU-K power limitation live, mid-race
- Reserve visibly inflates, deployment visibly de-rates, action recommendation changes in real time
- Stress-tested: 60+ automated races across track classes/seeds/disturbance combinations — zero permanently-stalled races after fixing a regen/ICE-suppression edge case

**Image:** Two side-by-side screenshots — dashboard with a disturbance button active (e.g. rain toggled, button highlighted) showing the strategy panel numbers shifting, vs. a clean baseline shot for contrast.

**Speaker notes:**
"You can break the race on purpose — that's the point. Every disturbance button is a live perturbation to the optimizer's inputs, and we've stress-tested that the system always keeps racing, never silently hangs."

---

### Slide 10 — Procedural Tracks & Full Race Export

**Content:**
- Tracks are procedurally generated per "track class" with curvature-feasibility and closed-loop (Dubins-style) closure — no fixed dataset, every run is a fresh, seeded, reproducible scenario
- Full race report exported client-side as a PDF: summary stats, baseline table, lap times, action breakdown, full event timeline, energy/speed graphs, branded

**Image:** A page from a generated **race-report PDF** (the summary page and/or the graphs page look best) alongside a top-down minimap screenshot of a generated track.

**Speaker notes:**
"Because tracks are generated, not fixed, this isn't a system that's been overfit to one circuit — and every race is fully exportable as a shareable report, which matters for something judges and engineers will actually want to review after the fact."

---

### Slide 11 — Validation Summary

**Content (checklist style):**
- ✅ Automated pytest suite: energy conservation, regen physics limits, reserve-formula consistency
- ✅ Optimality gap measured against Oracle every run
- ✅ 60+ stress races across track classes × seeds × disturbances — zero stalled races
- ✅ Substeped integration cross-checked against original step size
- ✅ Responsive/cross-viewport tested (desktop → phone), zero console errors

**Image:** None required — a clean checklist slide. Optionally a small terminal screenshot of `pytest` passing.

**Speaker notes:**
"None of this is 'trust us' — it's backed by an automated test suite and empirical stress testing, and the whole thing is a live tool a judge can go break themselves in the next five minutes."

---

### Slide 12 — Closing / What's Next

**Content:**
- Recap in one sentence: *"A physically-grounded, explainable MPC strategy engine for hybrid F1 energy deployment — benchmarked, stress-tested, and live."*
- Future directions (pick 2-3, be honest about scope): multi-car/traffic modeling, real telemetry ingestion instead of procedural tracks, learned forecaster component layered on top of the MPC's guaranteed-safe constraints, driver-in-the-loop mode
- Thank you / contact / GitHub link: `https://github.com/royyy02/trackshift`

**Image:** Reuse the title slide's logo for visual bookending.

**Speaker notes:**
"We deliberately chose explainable optimal control over a black-box model because race strategy has to be provably safe — but the architecture leaves room to layer learned components on top without losing that guarantee. Thanks — happy to take it live."

---

## General deck notes

- Keep the technical slides (5, 6, 7, 8) formula-forward but not formula-only — one formula or diagram per slide, not a wall of math. The in-app docs overlay is the "proof it's real" backup if a judge wants more depth.
- Every screenshot should come from an actual running session, not a mockup — this project's biggest credibility asset is that the dashboard *is* the demo.
- Recommended slide count for a strict time limit: if you need to cut, merge 6+7 (Optimizer + Overtake) and merge 9+10 (Robustness + Export), landing at 10 slides.
