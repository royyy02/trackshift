# Video Script — TrackShift BMS Live Demo

Target length: **3-4 minutes** (typical hackathon demo-video limit). Timestamps are approximate — pace to how it actually feels when you rehearse, don't pad. Written as a single-narrator screen-recording script: what's on screen, what you say, in sync.

**Setup before recording:**
1. `python backend/dashboard_server.py`, open `http://localhost:8001` in a clean, maximized browser window (desktop width, so the full layout shows).
2. Have a screen recorder ready (OBS or similar) at 1080p+, with system audio off and mic on.
3. Do one dry-run race beforehand so you know roughly when overtake windows / interesting moments happen — you want to time your narration to real events, not talk over a blank straight.
4. Close unrelated tabs/notifications.

---

### 0:00–0:15 — Cold open, title

**Screen:** Dashboard idle, car sitting on the grid, clean shot (chase cam, nothing started yet).

**Say:**
"This is TrackShift BMS — a real-time energy deployment strategy system for FIA-2026-regulation hybrid F1 cars. Every second of a race, it decides how much electric power to deploy versus hold in reserve — the same call a race engineer makes live. I'm going to start a race and show you exactly how it thinks."

*(Optional: overlay a title card "TrackShift BMS" for the first 2 seconds if editing afterward — not required if presenting live-narrated.)*

---

### 0:15–0:35 — The problem, fast

**Screen:** Stay on the idle dashboard, maybe hover the Strategy panel.

**Say:**
"Under 2026 rules, electrical deployment is roughly half the powertrain's output — but the battery is capacity-capped and mostly recharges from braking. Deploy too hard early, you run dry exactly when you need power most. Too conservative, and you're just slow. That's a real optimization problem, not a dial you set once."

---

### 0:35–1:10 — Start the race, narrate the live strategy panel

**Screen:** Click Start. Let the car accelerate off the line. Point out (cursor hover or just talk to it) the Strategy panel: Energy-to-Finish, σ_Ê (uncertainty), Required Reserve, Deployable, and the action box (Attack/Coast/Harvest/Conserve).

**Say:**
"I'll hit start. Every tick, the system forecasts total energy required to finish the race — that's this number here — along with how uncertain that forecast currently is. From that it computes a safety reserve, and water-fills whatever's left over across the remaining track so the car never strands itself but also doesn't leave performance on the table. This action box — Attack, Coast, Harvest, Conserve — is the live output of that decision, updating every second."

*(Let the race run in the background under the next few beats — don't stop it.)*

---

### 1:10–1:40 — Physics under the hood

**Screen:** Open the "How It Works" docs overlay (7th dock-rail icon) briefly, scroll past the Vehicle Model / Battery Model sections, then close it and return to the live race.

**Say:**
"Under the hood this isn't a lookup table — it's a real point-mass vehicle and battery simulation: drag, downforce-assisted cornering grip, traction-limited drive force, and — this mattered a lot during development — energy-conserving regen, meaning the energy the battery recovers under braking is derived directly from the kinetic energy removed from the car, not approximated. We wrote this whole reference doc into the app itself so it's inspectable, not just claimed."

---

### 1:40–2:15 — Inject a disturbance live

**Screen:** Click the Rain (or Safety Car) disturbance button. Point at the button lighting up, and the Strategy panel numbers visibly shifting (Required Reserve increasing, action possibly changing to Conserve).

**Say:**
"Now watch what happens if I make conditions worse — I'll turn on rain." *(click)* "Grip drops, the reserve requirement immediately grows to cover the added risk, and you can see the recommended action adapt in real time. Same thing happens with a safety car or a simulated MGU-K power loss — the whole strategy re-plans itself, live, off the same formula every time."

---

### 2:15–2:45 — Overtake + benchmarking

**Screen:** If an overtake window is visible, show the Overtake panel. Then switch to the Baseline comparison table (or open it if it's in a tab/dock).

**Say:**
"It's not just defensive, either — the optimizer actively evaluates overtake opportunities, weighing the energy cost of an attack against how much reserve margin we can afford to spend. And critically, every strategy this system produces is benchmarked live against an Oracle — a full-race, perfect-hindsight optimal solve — plus four baseline policies, so we always know exactly how close to optimal we actually are, not just that it 'seems smart.'"

---

### 2:45–3:10 — Tuning + responsiveness

**Screen:** Open the Setup/tuning panel, adjust the mass or downforce slider/number input live while the race continues, show the strategy react.

**Say:**
"Everything's also tunable live — mass, downforce, battery capacity — and the optimizer adapts on the fly. This whole dashboard runs the same on a laptop or a phone, and every camera angle, chart, and panel is fully interactive, not a canned animation."

---

### 3:10–3:35 — Finish + export

**Screen:** Let the race finish (or fast-forward if your recording setup allows skipping ahead / cut in editing). Show the finish overlay, then click Export and show the generated PDF opening (summary page, graphs page).

**Say:**
"When the race finishes, the full run — every lap, every strategy decision, the entire event timeline — exports as a branded PDF report, generated entirely client-side. Graphs, tables, timeline, all of it."

---

### 3:35–3:50 — Close

**Screen:** Return to a clean dashboard shot, maybe the title/logo.

**Say:**
"TrackShift BMS: a physically-grounded, explainable energy strategy engine — benchmarked against optimal, stress-tested against disturbances, and fully live. Thanks for watching."

*(End card, if editing: project name + GitHub link — `github.com/royyy02/trackshift`.)*

---

## Filming notes

- **Don't pause the race to talk** — the whole pitch of this project is that it's live and reactive; dead air over a frozen screen undercuts that. If you need more time to explain something, let the car keep driving in the background.
- **Pre-plan when to trigger the disturbance** — do a dry run first to know roughly what lap/second an overtake window or an interesting corner sequence happens, so your narration lands on something visually relevant.
- **Cut ruthlessly in editing** if you go over 4 minutes — the physics section (1:10–1:40) and the tuning section (2:45–3:10) are the two safest to trim if needed; the disturbance-injection and benchmarking beats are the strongest "wow" moments and should stay.
- **Audio**: record narration live over the actual screen recording if you can pace it — it reads far more authentic than a separately-recorded voiceover dropped over silent footage, and the sync effort isn't worth it for a demo this interactive.
