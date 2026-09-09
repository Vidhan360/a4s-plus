# A4S+ — Simulation engine

> This document describes the **only** source of data in A4S+. Nothing in the
> system is measured. The simulation exists to exercise the detection →
> prediction → prevention pipeline with realistically-shaped signals, and every
> value it emits is stamped `source = SIMULATION`.

## 1. Why the simulator is a first-class module, not a fixture

Three reasons, all of which shaped the code:

1. **It is the training data.** `ml/dataset.py` drives the same
   `VitalsSimulator` and `EnvironmentModel` the live app uses, so training and
   inference distributions cannot drift apart.
2. **It is the demo.** The whole product story has to be reproducible on
   demand, from a seed.
3. **It is the hardware seam's proof.** The simulator implements the same
   `DataSource` protocol a real sensor adapter would, so "swap in hardware"
   means writing a sibling class, not rewriting the pipeline.

## 2. The clock

`app/simulation/engine.py` owns a single asyncio task.

| Concept | Default | Meaning |
|---|---|---|
| `tick_seconds` | 2.0 s (5.0 s via the API default) | wall-clock interval between ticks |
| `sim_seconds_per_tick` | 60 s | simulated time advanced per tick |
| `speed` | 1 | multiplier ∈ **1 / 2 / 5 / 10**, applied to the wall interval |

So at 10× with a 2-second tick, one simulated minute elapses every 200 ms.
`sim_clock_seconds` and `tick_count` are persisted on the `simulation_runs` row
on every tick, which is what makes a run resumable and auditable.

**Controls:** `START` (scenario, seed, speed), `PAUSE`, `RESUME`, `STOP`,
`RESET`, plus live `speed` and `scenario` changes — the last of which can target
a single person, so you can push one soldier into an acute event mid-demo
without disturbing the rest of the roster.

`RESET` returns the world to its seeded initial state and clears derived state;
`STOP` closes the run record. UAV commands and fault injection return **422**
while the engine is not `RUNNING`, rather than pretending to have effect.

## 3. Determinism

The same `(seed, scenario, tick count)` triple reproduces the same run, byte
for byte, in the risk scores it produces.

How that is achieved:

- Each person receives an independent RNG seeded from
  `(run_seed, personnel_index)`, so **adding a person does not perturb anyone
  else's trajectory** — essential for reproducible demos and tests.
- The environment model is seeded from `seed ^ 0x5EED`.
- The swarm and terrain generators take explicit seeds, stored on
  `simulation_runs.seed` and `terrain_maps.seed`.
- No wall-clock time enters any model; only `sim_seconds`.

Default seed: **20260909**.

## 4. Physiological model

`app/simulation/vitals.py`. Deterministic and scenario-driven, coupling
altitude, exertion, cold exposure and fatigue to the observable vitals through
simple monotonic relationships plus a first-order lag, so trajectories behave
like continuous physiological signals rather than independent noise draws.

Key couplings:

- **Oxygen availability** falls with altitude as `exp(-altitude / 8400)`,
  which drives SpO₂ down and respiratory rate up.
- **Exertion** is an ordinal map from activity level
  (`RESTING 0.05 → EXTREME 0.95`) and raises heart rate, respiratory rate and
  temperature while accelerating fatigue accumulation.
- **Cold exposure** uses an environmental lapse rate of ≈6.5 °C per 1 000 m and
  wind chill, pulling core temperature down and blood pressure up.
- **Fatigue** integrates exertion over time and decays with rest, then feeds
  back into heart-rate recovery.
- **First-order lag** on every channel, so nothing steps discontinuously.

**Explicitly not a validated physiological model.** It is not derived from
clinical data and has no diagnostic meaning. That statement is in the module
docstring, in the API's provenance fields and on every screen that shows the
data.

## 5. Environment model

`app/simulation/environment.py`: a diurnal temperature cycle plus slow-moving
synthetic weather fronts with a random phase and a 1.5–3-hour period, producing
`base_temp_c`, `wind_kph`, `front_intensity` (0–1) and `visibility_km`. Wind
carries autocorrelated noise so gusts persist across ticks. Front intensity
feeds the terrain `weather_risk` layer, which in turn changes A\* route costs —
so weather visibly moves the safe route during a run.

## 6. The five scenarios (plus one deployment profile)

| Code | Label | What it demonstrates |
|---|---|---|
| `NORMAL` | Normal patrol | Acclimatised personnel on a routine patrol; vitals stay inside individual baselines and risk should remain LOW. The control case. |
| `GRADUAL_DETERIORATION` | Gradual deterioration | Slow-onset hypoxia and fatigue over hours. **This is the money scenario:** it is designed so the LSTM flags elevated risk before the rule engine crosses its threshold. |
| `ACUTE_EVENT` | Acute emergency | Sudden collapse — SpO₂ falls sharply with tachycardia and raised respiratory rate. Escalates to CRITICAL within a few ticks; exercises alert escalation and the critical-alert path. |
| `ALTITUDE_STRESS` | Altitude sickness (AMS-like) | Rapid ascent beyond acclimatisation: rising heart and respiratory rate with falling SpO₂. |
| `RECOVERY` | Recovery after descent | Starts elevated and improves after descent and rest — shows risk decreasing and alerts auto-resolving, which is the state most demos never show. |
| `MIXED` | Mixed deployment | Not a physiology profile: a **deployment profile** that assigns a deterministic spread of the five across the roster. The recommended demo setting. |

`MIXED` uses a fixed rotation so the same seed always puts the same people into
the same scenarios.

## 7. Per-tick pipeline

```
tick
 ├─ EnvironmentModel.step(sim_seconds)         → EnvironmentState
 ├─ for each person: VitalsSimulator.step()    → VitalSample
 │    └─ IngestionService.ingest()
 │         ├─ persist vital_readings (source=SIMULATION, run id, scenario)
 │         ├─ RiskEngine.assess()      → risk_assessments (+ per-factor JSONB)
 │         ├─ AlertEngine.evaluate()   → health_alerts (dedupe/cooldown/escalate)
 │         ├─ TwinService.update()     → digital_twin_states
 │         └─ PredictionService (every Nth tick, if ≥24 readings)
 │                                     → health_predictions
 ├─ SwarmSimulator.step()                      → drones, drone_events
 ├─ decay any active jamming / spoofing injections
 └─ EventBus.publish(...) for every affected topic
```

## 8. Risk engine (the "detection" half)

`app/services/risk_engine.py` produces a **0–100** score with per-factor
attribution. It is deterministic, weighted and entirely inspectable — which is
what lets the "WHY THIS RISK?" panel be exact rather than approximate for the
rule path.

Weighted factors (default weights, all editable at runtime via
`/api/v1/config`):

| Factor | Weight | Factor | Weight |
|---|---|---|---|
| SpO₂ level | 26.0 | Fatigue level | 9.0 |
| SpO₂ trend | 12.0 | Respiratory rate | 9.0 |
| Heart rate level | 14.0 | Body temperature | 8.0 |
| Heart rate trend | 8.0 | Multi-system involvement | 8.0 |
| Altitude | 7.0 | Environment (cold/wind) | 6.0 |
| Altitude gain rate | 5.0 | Blood pressure | 5.0 |
| Fatigue trend | 4.0 | | |

Trend factors are measured over a configurable analysis window (default 20
minutes). Category cuts: **LOW ≥ 0, MODERATE ≥ 40, HIGH ≥ 65, CRITICAL ≥ 85.**

Every assessment stores the `config_version` that produced it, so a historical
score can always be re-explained under the weights that were in force at the
time — not under today's weights.

## 9. Alert engine (the "prevention" half)

`app/services/alert_engine.py`:

- **Deduplication** on a `dedup_key` derived from `(personnel, alert_type,
  severity band)`. A repeat increments `occurrence_count` and updates
  `last_triggered_at` instead of creating a second row.
- **Cooldown** per alert type, so a fluttering threshold cannot produce a
  hundred alerts a minute.
- **Escalation**: if the same condition worsens into a higher severity band,
  the existing alert is escalated and `escalated_from` records where it came
  from — the history is preserved rather than replaced.
- **Prediction-triggered alerts** fire when the model's elevated-risk
  probability exceeds `prediction_probability_threshold` (default 0.65), and
  are labelled as predicted rather than observed.
- **Auto-resolution** after `auto_resolve_after_minutes` (default 120) once the
  condition clears, which is what makes the RECOVERY scenario legible.
- **Cap** of `max_open_alerts_per_person` (default 8), so one deteriorating
  person cannot bury the whole queue.

Every alert carries `reason`, `recommended_action` and the `triggering_data`
that produced it, so an operator sees evidence rather than a red dot.

## 10. UAV swarm model

`app/simulation/swarm.py`. Kinematic only — waypoint following at a commanded
speed, with battery drain, altitude hold, heading, and a link budget that
degrades with distance and terrain.

- **Formations:** `LINE`, `WEDGE`, `COLUMN`, `DIAMOND`.
- **Commands:** `LAUNCH`, `LAND`, `HOLD`, `RESUME_PATROL`, `RETURN_TO_BASE`
  (with short aliases accepted by the API).
- **Jamming injection** drives `signal_strength` down and `comms_status` to a
  degraded/lost state; a drone that loses the link long enough falls back to
  autonomous waypoint following, which is the resilience behaviour being
  demonstrated.
- **Spoofing injection** is the more interesting one: the drone keeps flying
  its *true* path (`grid_x/grid_y`) while its *reported* position
  (`reported_grid_x/y`) diverges. The UI can therefore draw both and the
  security monitor can raise a positional-inconsistency event — which is what a
  real detector would do.

Both injections expire after `duration_seconds` and write `drone_events` and
`security_events` rows with `origin = INJECTED`, so a demo injection is never
confusable with a genuine detection.

**No radio, autopilot, MAVLink, airspace or collision-avoidance logic exists.**

## 11. Terrain generation

`app/algorithms/terrain_gen.py` builds a deterministic map from a seed:
fractal value noise for elevation, slope derived from the elevation field, and
hazard layers (`avalanche_risk`, `crevasse_risk`, `weather_risk`,
`difficulty`) computed from slope, aspect, elevation band and the current
weather front. Cells above configured hazard cut-offs (default 0.85 avalanche
or crevasse) are marked `blocked`.

**This is procedural noise, not a DEM survey.** `terrain_maps.is_synthetic` is
`true` for every map, and the UI says so on the terrain page. Real avalanche
forecasting uses snowpack observation, weather history and expert judgement;
none of that is modelled.

## 12. Route planning over the simulated grid

`app/algorithms/astar.py`: A\* with an admissible octile-distance heuristic over
a cost function combining `base_cost`, ascent/descent penalties
(0.030 / 0.012 per metre) and hazard weights (avalanche 26, crevasse 30,
weather 14, difficulty 9). Two profiles: `SAFEST` uses the hazard weights,
`SHORTEST` zeroes them, and the UI shows the trade-off explicitly — usually a
longer, slower path with materially lower peak exposure.

`GET /routes/verify-optimality` re-solves the same grid with Dijkstra and
compares total cost and expansion counts. It is a genuine check that can fail;
the heuristic is admissible precisely so that it does not.

## 13. Observability of the simulation itself

| Endpoint | Answers |
|---|---|
| `GET /simulation/status` | run id, scenario, seed, speed, tick count, simulated clock |
| `GET /simulation/snapshot` | the whole current world in one payload |
| `GET /simulation/runs` | run history, each with its seed for replay |
| `GET /simulation/scenarios` | the catalogue above, with descriptions |
| `GET /simulation/data-source` | provenance, capabilities, and adapters declared but not implemented |

The last one is the honesty endpoint, and the frontend surfaces it as a
permanent "Data source" panel on the dashboard and the admin System page — so a
viewer can never lose track of where the numbers came from.
