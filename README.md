# A4S+ — AI-Assisted Altitude Safety System

**Team: The Third Eye** · _From detection → prediction → prevention_

> ### Read this first
>
> A4S+ is a **software prototype**. Every physiological reading, GPS fix, UAV
> telemetry frame, terrain cell and weather value in this system is **simulated
> data** produced by the built-in simulation engine. No sensor, wearable,
> aircraft or person is connected to it.
>
> The risk and prediction outputs are **not clinically validated**, are not a
> medical device, and must never be used to make a decision about a real human
> being. The encryption page is a *demonstration* of AES-256-GCM, not the
> transport or storage security of the system.
>
> These statements are enforced in code: `scripts/honesty-scan.sh` fails the
> build if a disclaimer disappears or an unqualified claim appears.

---

## 1. What this is

A4S+ is a command-and-control application for monitoring the health and safety
of personnel operating at high altitude. It takes a stream of vital signs and
environmental context, scores present risk with a transparent rule engine,
forecasts risk **30 simulated minutes ahead** with a trained PyTorch LSTM,
explains every number it shows, and turns the result into action: alerts, a
digital twin per person, an A\*-planned safe route across scored terrain, and a
simulated UAV relay swarm that can be jammed and spoofed to test resilience.

| | |
|---|---|
| Backend | FastAPI · Pydantic v2 · SQLAlchemy 2.0 (async) · Alembic · PostgreSQL 16 · Redis · WebSockets |
| Frontend | Next.js 15 (App Router) · TypeScript · Tailwind CSS · shadcn-style UI · TanStack Query · React Hook Form + Zod · Recharts |
| ML | PyTorch LSTM (trained) vs scikit-learn gradient boosting vs a rule baseline |
| Tests | Pytest (321) · Vitest (46) · Playwright (44) |
| Size | 96 backend source files (~17.8k lines) · 94 frontend TS/TSX files (~13.5k lines) · 23 tables · 89 REST operations + 1 WebSocket |

---

## 2. Feature map

**Operations**
- **Command dashboard** — roster risk distribution, live vitals feed over
  WebSocket, open-alert queue, watchlist, simulation status, data-source
  provenance panel.
- **Personnel management** — CRUD, per-person history, manual vitals ingestion,
  risk trend, alert history, RBAC-gated destructive actions.
- **Digital twin** — per-person state vector (physiology, position, activity,
  environment, staleness) with the twin's current prediction and explanation.
- **Alerts** — deduplication, cooldown, severity escalation, acknowledge and
  resolve workflow, configurable thresholds, rule catalogue.

**Prediction & explainability**
- **Risk engine** — deterministic, weighted, fully transparent scoring.
- **LSTM prediction** — 24-step window → 4-class risk at t+30 min.
- **"WHY THIS RISK?"** — per-feature contributions computed by occlusion
  sensitivity for the LSTM, by transparent weights for the rule engine, and by
  impurity importance for gradient boosting. Each panel names its method; no
  method is claimed that is not actually run.
- **Model comparison** — three models scored side by side on the same held-out
  split, with the measured numbers shown, including where the LSTM loses.

**Terrain & assets**
- **Terrain visualisation** — procedurally generated elevation, avalanche,
  crevasse, weather and difficulty layers on an interactive canvas.
- **Safe-route planner** — A\* over a risk-weighted grid, `SAFEST` vs
  `SHORTEST` profiles, side-by-side comparison, plus an optimality check that
  re-verifies the returned path against Dijkstra.
- **UAV swarm** — simulated relay drones, formations, missions, battery and
  link budget, event log.

**Assurance**
- **Security monitor** — injectable jamming/spoofing/auth-anomaly events,
  severity triage, acknowledgement, posture summary, control catalogue.
- **Authenticated encryption demonstration** — AES-256-GCM over text you
  supply, with tamper detection shown live.
- **Analytics** — risk over time, per-person breakdown, factor correlation,
  model metrics.
- **Audit log viewer** — append-only, immutability evidence, faceted filters.

**Administration** — users, roles and the full permission matrix, editable
system configuration with defaults and reset, system/capability status.

---

## 3. Architecture in one picture

```
Browser (Next.js 15, standalone)
  │  REST /api/v1 (JWT access token, 15 min)
  │  WS   /api/v1/ws?token=…&topics=…
  ▼
FastAPI
  ├── api/v1/*          thin routers: validation, RBAC, HTTP shape
  ├── services/*        business logic (risk, alerts, prediction, security…)
  ├── repositories/*    all SQL lives here
  ├── simulation/*      environment, vitals, swarm, engine (the clock)
  ├── datasources/*     ← THE HARDWARE SEAM (see §11)
  ├── algorithms/*      terrain generation, A*, Dijkstra verifier
  └── ml/*              features, dataset, model, registry, evaluate, train
  │                        │
  ▼                        ▼
PostgreSQL 16 (23 tables)   Redis (rate limiting, cross-worker pub/sub)
```

Full detail: [`docs/architecture.md`](docs/architecture.md).

---

## 4. Quick start

### 4.1 With Docker Compose (unverified — see §9)

```bash
cp .env.example .env          # then set A4S_JWT_SECRET
docker compose up --build
# frontend  http://localhost:3000
# API docs  http://localhost:8000/api/docs
```

### 4.2 Locally, without Docker (this is the path that was actually verified)

**Prerequisites:** Python 3.13, Node 24, PostgreSQL 16, Redis 6+.

```bash
# 1. PostgreSQL — the databases MUST be UTF-8. Several tables use JSONB, and a
#    SQL_ASCII cluster will fail on non-ASCII payloads.
createdb -E UTF8 -T template0 a4s
createdb -E UTF8 -T template0 a4s_test

# 2. Redis
redis-server --port 6379 --save '' --daemonize yes

# 3. Configuration
cp .env.example .env          # edit A4S_DATABASE_URL / A4S_JWT_SECRET

# 4. Backend
cd backend
python -m pip install -r requirements-dev.txt
alembic upgrade head
python -m seeds.seed --history 90     # demo users, roster, terrain, 90 min history
uvicorn app.main:app --host 127.0.0.1 --port 8000

# 5. Frontend (new shell)
cd frontend
cp .env.local.example .env.local      # NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
npm ci
npm run dev                            # http://127.0.0.1:3000
```

`make help` lists every shortcut (`make migrate seed dev-api dev-web verify …`).

> **Nothing moves until you start the simulation.** Open **Simulation**, pick
> the `MIXED` scenario, press **Start**. The dashboard, twins, alerts and UAV
> pages then update live. UAV commands and fault injection deliberately return
> HTTP 422 while the engine is stopped, rather than pretending to work.

### 4.3 Retraining the models

```bash
cd backend
python -m ml.train --subjects 480 --epochs 30      # ~2 min on CPU
```
Writes a new version under `ml/artifacts/<model>/<version>/` plus
`ml/artifacts/last_comparison.json`, then `POST /api/v1/predictions/reload`
picks it up without a restart.

---

## 5. Demo credentials

Created by `python -m seeds.seed`. Passwords come from the `A4S_SEED_*`
environment variables; the values below are the `.env.example` defaults and are
**development-only**.

| Role | Email | Password | Sees |
|---|---|---|---|
| Admin | `admin@a4s.local` | `Adm1n-A4Splus-2026!` | everything, incl. users & config |
| Commander | `commander@a4s.local` | `Cmdr-A4Splus-2026!` | operations, simulation control, routes, UAV |
| Medical officer | `medic@a4s.local` | `Medic-A4Splus-2026!` | personnel, vitals, predictions, alerts |
| Operator | `operator@a4s.local` | `Oper-A4Splus-2026!` | terrain, routes, UAV, security injection |
| Viewer | `viewer@a4s.local` | `View-A4Splus-2026!` | read-only dashboards |

Sign in as more than one role — the navigation, buttons and API responses all
change, because the frontend renders from the permission list the server
returns rather than from a hard-coded assumption.

---

## 6. Machine learning, honestly

Trained on **synthetic data generated by this repository's own simulation
engine**: 480 subjects × 190 minutes, split **by subject** so no subject
appears in both train and test. Labels are the rule engine's risk category
evaluated 30 minutes later, which means the LSTM is learning to *anticipate the
rule engine*, not to diagnose a human.

Measured on the held-out split — 9 864 test windows for the learned models,
4 932 for the persistence baseline (evaluated on every second window):

| Model | Accuracy | Macro F1 | Elevated-risk F1 | Elevated ROC AUC | Brier |
|---|---|---|---|---|---|
| Rule baseline (persistence) | 0.7474 | 0.7024 | 0.8122 | — | — |
| **LSTM** (2×96 + attention, 125 029 params) | **0.8913** | **0.8770** | **0.9357** | **0.9913** | 0.0370 |
| Gradient boosting | **0.9142** | **0.9024** | **0.9448** | **0.9925** | 0.0363 |

**The gradient-boosting model beat the LSTM.** That result is reported as
measured, in the UI and here, rather than quietly dropped. Both learned models
clearly beat the persistence baseline, which is the claim that matters for the
product story; see [`docs/ml.md`](docs/ml.md) for why the sequence model is
still the default and what would likely change the ranking.

No number in this repository is hand-written. No SHAP values are shown, because
SHAP is not run — the explanation methods are named exactly as implemented
(`OCCLUSION_SENSITIVITY`, `TRANSPARENT_WEIGHTS`, `IMPURITY_IMPORTANCE`).

---

## 7. Security posture

Implemented: Argon2id password hashing, short-lived JWT access tokens, rotating
refresh tokens with reuse detection, account lockout after 5 failed logins,
36 fine-grained permissions across 5 roles, per-route rate limiting, strict
Pydantic validation, an append-only audit log protected by a database trigger,
security headers, and CORS confined to configured origins.

Not implemented, and stated as such in the UI: data-at-rest encryption, secret
management, HTTPS termination, multi-factor authentication, and secure
browser-side token storage (tokens live in `localStorage`; the trade-off and the
single-file seam are documented in [`docs/security.md`](docs/security.md)).

The phrase "military-grade" is used nowhere except to disclaim it.

---

## 8. Testing

```bash
make verify        # lint + typecheck + tests + honesty scan, both tiers
```

| Suite | Command | Result |
|---|---|---|
| Backend unit + integration | `cd backend && pytest -q` | **320 passed, 1 skipped** |
| Backend lint | `ruff check . && ruff format --check .` | clean |
| Backend types | `mypy app ml seeds` (strict) | clean, 96 files |
| Frontend unit/component | `cd frontend && npx vitest run` | **46 passed** (8 files) |
| Frontend lint | `npm run lint` | clean |
| Frontend types | `npx tsc --noEmit` | clean |
| Frontend build | `npm run build` | **18 routes**, standalone |
| End-to-end | `npx playwright test` | **44 passed** (5 setup + 39) |
| Dependency audit | `npm audit` | 0 vulnerabilities |
| Honesty scan | `bash scripts/honesty-scan.sh` | pass |

---

## 9. Verification status (what was and was not run)

Being precise about this matters more than looking complete.

**Verified by execution** on Amazon Linux 2023 with Python 3.13, Node 24.14,
PostgreSQL 16.14 and Redis 6: every row in §8, the full migration and seed
path, the training run that produced the metrics in §6, and the end-to-end
suite against a production build of the frontend talking to a live API.

**Written but never executed:** `docker-compose.yml`,
`docker-compose.dev.yml`, `infra/docker/*.Dockerfile` and
`.github/workflows/ci.yml`. The build environment had **no Docker daemon and no
GitHub Actions runner**, so these files are reviewed-but-unverified. Each one
carries that warning in its header. Every *command* inside them was run
directly on the host; the containerisation around those commands has not been
proven.

---

## 10. Limitations

1. All data is simulated. There is no sensor, wearable, GPS, radio or aircraft.
2. Outputs are not clinically validated and carry no medical meaning.
3. Training and test data share one generative process, so the metrics measure
   how well the model learned that process — not real-world accuracy.
4. Terrain is procedurally generated, not a DEM survey; hazard layers are
   plausible-looking noise fields, not measured avalanche risk.
5. Tokens are stored in `localStorage`; an XSS bug would expose a session.
6. Application data is not encrypted at rest.
7. The UAV swarm is a kinematic simulation. No radio, autopilot or airspace
   logic exists.
8. Jamming and spoofing are injected state changes, not real RF effects.
9. Docker and CI are unverified (§9).
10. Single-node deployment. Horizontal scaling of the simulation engine would
    need a distributed clock and leader election.

---

## 11. Path to hardware

The prototype was built so that hardware can be added **without redesign**.
Every reading enters through one interface, `app/datasources/base.py`:

```python
class DataSource(ABC):
    kind: DataSourceKind = DataSourceKind.SIMULATION      # provenance stamp

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def snapshot(self) -> list[VitalSample]: ...     # current reading per entity

    @abstractmethod
    def stream(self) -> AsyncIterator[list[VitalSample]]: ...  # batches as they arrive
```

`VitalSample` carries a mandatory `source` field, so provenance travels with
the data all the way to the UI and simulated values cannot be silently
presented as measured.

`SimulationDataSource` is the only implementation. The adapters a real
deployment would need are **declared and explicitly unimplemented**:
`WearableDataSource` (BLE/LoRa wearable gateway), `UAVDataSource` (UAV
telemetry and relayed beacons) and `EdgeDataSource` (on-site aggregator with
store-and-forward). Constructing any of them raises `NotImplementedError`
immediately rather than returning fabricated "sensor" data, and they appear in
`GET /api/v1/simulation/data-source` and on the admin System page as "declared
but not implemented".

Swapping in hardware means writing an adapter and changing one binding. Full
staged plan, per-signal, with calibration and safety-case notes:
[`docs/hardware-integration-roadmap.md`](docs/hardware-integration-roadmap.md).

---

## 12. Documentation

| Document | Contents |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | Layers, request lifecycle, real-time pipeline, module map |
| [`docs/database.md`](docs/database.md) | All 23 tables, relationships, indexes, migrations |
| [`docs/api.md`](docs/api.md) | All 89 REST operations + WebSocket protocol, error envelope |
| [`docs/ml.md`](docs/ml.md) | Dataset, features, architecture, training, metrics, explainability |
| [`docs/simulation.md`](docs/simulation.md) | Engine, five scenarios, determinism, environment & swarm models |
| [`docs/security.md`](docs/security.md) | Threat model, auth, RBAC, audit, crypto demo, what is missing |
| [`docs/hardware-integration-roadmap.md`](docs/hardware-integration-roadmap.md) | Staged plan from simulation to instrumented deployment |
| [`docs/demo-guide.md`](docs/demo-guide.md) | A 10-minute walkthrough that shows every subsystem |
| [`docs/decisions/`](docs/decisions) | Architecture decision records |

---

## 13. Repository layout

```
a4s-plus/
├── backend/            FastAPI service, ML pipeline, seeds, 321 tests
│   ├── app/{api,core,models,repositories,schemas,services,simulation,
│   │        algorithms,datasources,ws}
│   ├── ml/{features,dataset,model,registry,evaluate,baseline,train}.py
│   ├── alembic/        two migrations
│   └── tests/{unit,integration}
├── frontend/           Next.js 15 app, 18 routes, Vitest + Playwright
│   ├── src/{app,components,hooks,lib}
│   └── e2e/            Playwright specs + auth setup
├── infra/docker/       backend + frontend images, Postgres init
├── docs/               architecture, database, api, ml, simulation, security,
│                       hardware roadmap, demo guide, ADRs
├── scripts/            honesty-scan.sh, claim_scan.py
├── docker-compose.yml  docker-compose.dev.yml  Makefile
└── .github/workflows/ci.yml
```

---

_A4S+ is a student ideathon prototype (COMPOSIT 2026) built by Team The Third
Eye. It exists to show that the detection → prediction → prevention pipeline is
buildable and explainable. It is not a product, not a medical device, and not
fit for deployment to anyone whose safety depends on it._
