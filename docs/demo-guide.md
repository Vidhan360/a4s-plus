# A4S+ — Demo guide

A 10-minute walkthrough that touches every subsystem, in an order that tells
the story: **detection → prediction → prevention**.

> Open with the disclaimer, not as an apology but as a credibility move: every
> number on screen is simulated, and the system says so on every page. Judges
> trust a system that knows its own limits.

## 0. Before you start (2 min)

```bash
# terminal 1
cd backend && alembic upgrade head && python -m seeds.seed --history 90
uvicorn app.main:app --host 127.0.0.1 --port 8000

# terminal 2
cd frontend && npm run dev
```

`--history 90` matters: it back-fills 90 minutes of readings so the LSTM has
its 24-step window immediately. Without it your first prediction honestly says
"insufficient history", which is correct but a weak opening.

Open `http://127.0.0.1:3000`, sign in as **commander@a4s.local**.

---

## 1. Frame it (30 s) — Dashboard

Point at three things before touching anything:

1. The persistent **SOFTWARE PROTOTYPE · SIMULATED DATA · NOT CLINICALLY
   VALIDATED** banner.
2. The **Data source** panel — it names the active source, its provenance, and
   the hardware adapters that are *declared but not implemented*.
3. The stream indicator in the topbar: currently connected, nothing moving.

> "Nothing is moving because nothing is pretending to. There is no sensor. Let
> me start the simulation."

## 2. Start the world (1 min) — Simulation

Go to **Simulation**. Show the five scenarios and their descriptions, then:

- Scenario **MIXED**, seed **20260909**, speed **5×** → **Start**.

Say why the seed is on screen: *the same seed reproduces the same run exactly*,
so this demo is repeatable and so are the tests.

Demonstrate **PAUSE**, **RESUME**, and a speed change to **10×**. Watch the tick
counter and the simulated clock diverge from wall time.

Return to the **Dashboard**. Now the risk distribution fills, the live feed
streams over WebSocket, and the watchlist populates. Mention that the feed is
push, not polling.

## 3. Detection (1.5 min) — Personnel

**Personnel** → open the highest-risk person.

- Risk score with **per-factor attribution** — SpO₂ level, SpO₂ trend, heart
  rate, fatigue, altitude, environment. Each with its weight and contribution.
- Point out that the score stores the **config version** that produced it, so a
  historical score can be re-explained under the weights in force at the time.

> "This is the detection half, and it is completely transparent. No model, no
> black box. If it says 71, you can see all thirteen numbers that made 71."

## 4. Prediction (2 min) — the centrepiece

Same page: **Run prediction**.

- Probability, predicted category 30 minutes ahead, per-class probabilities,
  and `inference_ms` measured on the spot.
- Open **WHY THIS RISK?** — the top contributions, and the method *named*:
  `OCCLUSION_SENSITIVITY`. Explain it in one sentence: each of the 16 channels
  is replaced by its training mean, the model is re-run, and the change in the
  elevated-risk logit is the contribution.

> "We do not show SHAP values, because we do not run SHAP. What is on this
> screen is what we actually computed."

Then **Compare models**. Three rows: rule baseline, LSTM, gradient boosting —
each with its measured metrics.

**Say the uncomfortable thing out loud:**

> "Gradient boosting beat our LSTM — 0.914 versus 0.891 accuracy. We are
> showing you that instead of hiding it. Both learned models beat the
> persistence baseline by a wide margin, which is the claim that matters. The
> LSTM stays default because it is the architecture that will benefit from real
> noisy sensor data, and because its explanations are per-timestep."

That paragraph earns more credibility than a fabricated 99 % ever would.

## 5. Digital twin (45 s)

**Personnel → [person] → Twin.** The full state vector: physiology, position,
activity, environment, open alerts, staleness, and the twin's current
prediction with its explanation. One row per person in the database, updated
every tick — which is what makes the roster view cheap.

## 6. Prevention (1.5 min) — Alerts

**Alerts.** Explain the engine while pointing at rows:

- **Deduplication** — `occurrence_count` on a repeat, not a hundred new rows.
- **Escalation** — `escalated_from` preserves the history when a condition
  worsens.
- **Evidence** — every alert carries `reason`, `recommended_action` and the
  `triggering_data` that fired it.

**Acknowledge** one. **Resolve** another with a note.

Now the trick that makes the pipeline click: go back to **Simulation**, set one
person's scenario to **ACUTE_EVENT**, return to **Alerts**, and watch a
CRITICAL alert appear within a few ticks. Then set them to **RECOVERY** and
watch alerts auto-resolve as the condition clears.

## 7. Terrain and safe routing (1.5 min)

**Terrain** — toggle elevation, avalanche, crevasse, weather and difficulty
layers. Click a cell to inspect it. Note the honest label: procedurally
generated from a seed, **not** a DEM survey.

**Routes** — plan a route across the map:

- **SAFEST** vs **SHORTEST** side by side, with the delta: distance, minutes,
  mean risk, peak risk.
- The explanation panel: which hazards were avoided and at what cost.
- **Verify optimality** — this re-solves the same grid with Dijkstra and
  compares total cost and node expansions. It is a real check that could fail.

> "A\* with an admissible heuristic, and we prove it rather than assert it."

## 8. UAV swarm and resilience (1 min)

**UAV.** Drones on the swarm map, formation, battery, link strength, mission.
Change formation to **DIAMOND**.

Then **Inject spoofing** on one drone. Watch its *reported* position diverge
from its *true* position while it keeps flying its real path, and a security
event appear. **Inject jamming** on another: signal degrades, comms status
drops, and after enough time without a link it falls back to autonomous
waypoint following.

> "The reported-versus-true position split is the whole point. That divergence
> is what a real spoofing detector would look for."

Mention that both injections write events with `origin = INJECTED`, so a demo
can never be confused with a real detection.

## 9. Security (1 min)

**Security.**

- The event feed, with `SYSTEM` versus `INJECTED` origin.
- The control catalogue, with each control's honest status:
  `IMPLEMENTED` / `DEMONSTRATION_ONLY` / `OUT_OF_SCOPE` / `NOT_IMPLEMENTED`.
- The **crypto** tab: type a sentence, run AES-256-GCM, see ciphertext, nonce
  and tag — then watch the tamper test fail decryption.

> "Integrity, not just confidentiality. And note what the panel says about
> itself: this is a demonstration of a primitive. It is not what protects this
> application, and we never call it military-grade."

## 10. Governance (1 min) — Audit, Analytics, Admin

- **Audit** — every state-changing action, with actor, result and request id.
  Point at the **immutability** block: append-only, enforced by a database
  trigger, and tested.
- **Analytics** — risk over time, per-person breakdown, factor correlation, and
  the measured model metrics.
- **Admin → Users** — the full **permission matrix**: 5 roles, 36 permissions.
- **Admin → Config** — change a risk weight, save it, note the version bump and
  the audit entry, then **Reset to default**.
- **Admin → System** — the capability declaration. Every hardware capability is
  shown *crossed out*: no real sensors, no real UAV control, no clinical
  validation, no encryption at rest.

## 11. The RBAC party trick (30 s)

Sign out. Sign in as **viewer@a4s.local**.

Navigation shrinks. Simulation controls disappear. Acknowledge buttons are
gone. Try a forbidden URL directly — the API returns 403 and the UI explains
which permission is missing instead of showing a broken page.

> "The frontend renders from the permission list the server returns. Adding a
> sixth role tomorrow needs zero frontend changes."

---

## Closing line

> "A4S+ is a software prototype on simulated data, and it is not clinically
> validated. What we are claiming is narrower and, we think, more useful: the
> detection → prediction → prevention pipeline is buildable, explainable and
> testable end to end — 321 backend tests, 46 frontend tests, 44 end-to-end
> tests — and it has exactly one seam where real sensors plug in."

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Dashboard empty, nothing streaming | Simulation not started | Simulation → Start |
| "Insufficient history" on prediction | fewer than 24 readings | seed with `--history 90`, or let the sim run ~24 ticks |
| UAV command returns 422 | engine not `RUNNING` | Start the simulation — this is intentional |
| Model comparison empty | no training run on disk | `python -m ml.train --subjects 480 --epochs 30` |
| Login says account locked | 5 failed attempts | wait 15 min, or `POST /users/{id}/unlock` as admin |
| Frontend calls the wrong API host | `NEXT_PUBLIC_*` is inlined at build time | fix `.env.local` and **rebuild** |
| JSONB errors on insert | database is not UTF-8 | recreate with `createdb -E UTF8 -T template0` |
