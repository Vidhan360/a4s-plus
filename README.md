# A4S+ — AI-Assisted Altitude Safety System

**Repository:** [https://github.com/Vidhan360/a4s-plus](https://github.com/Vidhan360/a4s-plus)  
**Team:** The Third Eye · _From detection → prediction → prevention_

> ### ⚠️ Mandatory Educational & Prototype Disclaimer
>
> A4S+ is a **software prototype**. Every physiological reading, GNSS/GPS fix, UAV
> telemetry frame, terrain cell and weather value in this system is **simulated
> data** produced by the built-in scenario simulation engine. No physical sensor, wearable,
> aircraft or human subject is connected to it.
>
> The risk scores and prediction outputs are **not clinically validated**, do not constitute a
> medical device, and must never be used to make decisions regarding real human safety. The encryption page is an educational *demonstration* of authenticated symmetric encryption (AES-256-GCM), not an audit of transport or storage security.
>
> These statements are enforced in code: `scripts/honesty-scan.sh` fails the
> build if any disclaimer is omitted or an unqualified claim appears.

---

## 1. What This Is

A4S+ is an end-to-end command-and-control platform engineered to monitor the physiological safety and operational health of personnel operating in extreme high-altitude environments. It ingests simulated telemetry, evaluates present condition with a transparent deterministic rule engine, forecasts risk **30 simulated minutes ahead** with a trained PyTorch LSTM sequence model and a scikit-learn Gradient Boosting classifier, explains feature contributions mathematically, and drives mitigation actions: automated alert escalation, individual digital twins, terrain-risk-aware A\* route planning, and UAV swarm relay routing under simulated electronic warfare conditions.

### Technology Stack Overview

| Tier | Technologies |
|---|---|
| **Backend** | Python 3.13 · FastAPI 0.115 · Pydantic v2 · SQLAlchemy 2.0 (async) · Alembic · PostgreSQL 16 · Redis 7 · WebSockets |
| **Frontend** | Next.js 15 (App Router, standalone) · TypeScript 5.6 · Tailwind CSS · TanStack Query v5 · Recharts · Lucide Icons |
| **Machine Learning** | PyTorch 2.4+ (CPU) · scikit-learn 1.5 · NumPy · Pandas · Joblib · Custom Occlusion Sensitivity & Feature Attribution |
| **Testing & CI** | Pytest (321 test cases) · Vitest (46 tests) · Playwright E2E (44 specs) · Ruff · Mypy (strict) |
| **Infrastructure** | Docker multi-stage builds · Docker Compose · Genuinely ₹0 Cloud PaaS (Neon + Render + Vercel) |

---

## 2. System Architecture

```mermaid
graph TD
    subgraph Client ["Frontend Tier (Next.js 15 Standalone)"]
        Browser["Web Browser (UI Client)"]
        State["Session Store (localStorage) & TanStack Query"]
        StreamHook["useLiveStream (WebSocket Hook)"]
        Browser --> State
        Browser --> StreamHook
    end

    subgraph Gateway ["FastAPI Gateway & Core Middleware"]
        API["FastAPI /api/v1 Application"]
        Audit["AuditMiddleware & Security Headers"]
        Limiter["Rate Limiting (slowapi / In-Memory Fallback)"]
        Auth["Argon2id + JWT Security Handler"]
        API --> Audit
        API --> Limiter
        API --> Auth
    end

    subgraph Logic ["Domain Services & Simulation Engine"]
        Sim["Simulation Engine (Background Loop)"]
        RiskEng["Deterministic Risk Engine (Current State)"]
        Alerts["Alert Engine (Deduplication & Escalation)"]
        AStar["A* Terrain Route Planner (Optimality Verified via Dijkstra)"]
        Swarm["UAV Swarm Simulator (Kinematics & Link Budget)"]
        Twin["Digital Twin State Aggregator"]
    end

    subgraph Intelligence ["Machine Learning & Explainability Tier"]
        LSTM["PyTorch LSTM (24-step Sequence -> t+30m Risk)"]
        GB["Gradient Boosting Estimator (Scikit-learn)"]
        Explain["Explainable AI (Occlusion Sensitivity & Impurity Importance)"]
        Registry["Model Registry (backend/ml/artifacts)"]
        LSTM --> Explain
        GB --> Explain
        Registry --> LSTM
        Registry --> GB
    end

    subgraph Persistence ["Persistence & Messaging"]
        Postgres[("PostgreSQL 16 (UTF-8, 23 Tables, JSONB)")]
        EventBus["EventBus (Redis Pub/Sub or In-Memory Bus)"]
    end

    Browser -- "REST API (HTTPS)" --> API
    StreamHook -- "WebSocket (WSS)" --> API
    API --> Logic
    API --> Intelligence
    Logic --> Postgres
    Sim --> EventBus
    EventBus --> StreamHook
```

### Core Data Flow
1. **Clock & Simulation:** The simulation engine advances simulated time in deterministic ticks, publishing vital samples via a unified `DataSource` interface.
2. **Deterministic Current Scoring:** Physiological telemetry (SpO2, heart rate, respiration, ambient temperature, altitude) is scored instantly by the rule engine to establish ground-truth current severity (`NORMAL`, `ELEVATED`, `HIGH`, `CRITICAL`).
3. **Sequence Forecasting (ML):** A sliding 24-step historical window (spanning 24 minutes of simulated physiological readings) is normalized and fed into the PyTorch LSTM and Gradient Boosting models to predict the risk category **30 minutes into the future**.
4. **Transparent Explainability:** Predictions compute feature attributions (via occlusion sensitivity for LSTM and tree impurity for GB) so operators see exactly which biomarker drives risk.
5. **Real-time Fan-Out:** Telemetry and risk assessments stream over WebSockets (`/api/v1/ws`) to update the command dashboard, personnel digital twins, and alert queues.

---

## 3. Features & Project Scope

- **Command & Control Dashboard:** Roster risk distribution, real-time WebSocket vitals feed, alert triage queue, watchlist, and simulation controls.
- **Personnel Digital Twins:** Per-soldier state vectors (vitals, geographic position, simulated activity, environmental exposure, data staleness) paired with forward predictions.
- **Explainable AI ("WHY THIS RISK?"):** Exact mathematical attribution of contributing risk factors without obfuscation. Each model panel specifies its exact attribution method (`OCCLUSION_SENSITIVITY`, `TRANSPARENT_WEIGHTS`, or `IMPURITY_IMPORTANCE`).
- **Tactical Terrain & A\* Safe Routing:** Procedural terrain generation (elevation, crevasses, avalanche hazard, weather) with an A\* pathfinder allowing operators to toggle between `SAFEST` and `SHORTEST` profiles, automatically cross-verified against Dijkstra.
- **Resilient UAV Relay Swarm:** Kinematic simulation of multi-drone aerial relays with battery drain models, RF link budget calculations, and fault injection (GPS spoofing, RF jamming).
- **Security & RBAC:** Role-Based Access Control (Admin, Commander, Medical Officer, Operator, Viewer) with 36 fine-grained permissions, Argon2id hashing, rotating JWT tokens, rate limiting, and an append-only audit trail.

---

## 4. Machine Learning & Synthetic Data Methodology

### The Rule Engine vs. ML Predictor Distinction
- **Current Risk Engine (Deterministic):** Evaluates instantaneous health based on clinically inspired physiological boundaries and weighted factor combinations. This is deterministic ground truth in our simulation.
- **Future Risk Engine (Machine Learning):** Anticipates future trajectory 30 minutes ahead ($t+30\text{ min}$) using sequential trends. The ML models are trained to anticipate the rule engine's future output, demonstrating early intervention capability.

### Dataset Provenance & Split
- Generated entirely by this repository's simulation engine (`python -m ml.train`).
- 480 simulated subjects $\times$ 190 minutes of continuous vitals.
- **Subject-disjoint split:** Partitioned strictly by subject ID so no synthetic person appears in both training and test sets.

### Measured Held-Out Evaluation Metrics
Evaluated on 9,864 held-out test windows for learned models and 4,932 for the persistence baseline:

| Model | Accuracy | Macro F1 | Elevated-Risk F1 | Elevated ROC AUC | Brier Score |
|---|---|---|---|---|---|
| **Rule Baseline** (Persistence) | 0.7474 | 0.7024 | 0.8122 | — | — |
| **PyTorch LSTM** (2×96 + Attention, 125k params) | **0.8913** | **0.8770** | **0.9357** | **0.9913** | 0.0370 |
| **Gradient Boosting** (Scikit-learn) | **0.9142** | **0.9024** | **0.9448** | **0.9925** | 0.0363 |

> **Honest Scientific Finding:** The Gradient Boosting model slightly outperformed the LSTM on this structured synthetic dataset. Both clearly outperform the persistence baseline. The LSTM remains the default sequence model because its recurrent hidden state naturally maps to streaming continuous telemetry; see [`docs/ml.md`](docs/ml.md) for full analysis.

---

## 5. Repository Structure

```
a4s-plus/
├── backend/                   # FastAPI application & ML service
│   ├── alembic/               # Database migrations (PostgreSQL 16)
│   ├── app/                   # Core application
│   │   ├── algorithms/        # Terrain procedural generation, A*, Dijkstra
│   │   ├── api/v1/            # 89 REST endpoints + WebSocket router
│   │   ├── core/              # Config, security, events, rate-limiting, database
│   │   ├── datasources/       # Hardware abstraction seam (DataSource ABC)
│   │   ├── models/            # SQLAlchemy 2.0 ORM models (23 tables)
│   │   ├── repositories/      # Encapsulated database query operations
│   │   ├── schemas/           # Pydantic v2 validation contracts
│   │   ├── services/          # Business logic: risk, predictions, alerts, twins
│   │   ├── simulation/        # Swarm kinematics, vitals generator, environment
│   │   └── ws/                # WebSocket connection manager & topic fan-out
│   ├── ml/                    # Feature engineering, PyTorch LSTM, registry
│   │   └── artifacts/         # Trained model weights (model.pt, model.joblib)
│   ├── seeds/                 # Idempotent database seeder (demo accounts & data)
│   └── tests/                 # Unit & integration test suites (Pytest)
├── frontend/                  # Next.js 15 web application
│   ├── src/app/               # App Router pages (18 operational routes)
│   ├── src/components/        # UI design system, Recharts, terrain canvas
│   ├── src/hooks/             # useLiveStream WebSocket hook, session hooks
│   ├── src/lib/               # API client, types, formatters, token store
│   └── e2e/                   # Playwright end-to-end specifications
├── infra/docker/              # Production & development Dockerfiles
├── docs/                      # Comprehensive technical architecture & ADRs
├── scripts/                   # Honesty scanner, claim auditor
├── docker-compose.yml         # Full local orchestration stack
└── .github/workflows/ci.yml   # Continuous integration pipeline
```

---

## 6. Local Setup & Installation

### Option A: Running with Docker Compose (Recommended)

**Prerequisites:** Docker Desktop (v24+) with Docker Compose.

```bash
# 1. Clone repository
git clone https://github.com/Vidhan360/a4s-plus.git
cd a4s-plus

# 2. Configure environment
cp .env.example .env
# Open .env and set A4S_JWT_SECRET (must be >= 32 characters)

# 3. Launch complete stack
docker compose up --build
```
- **Frontend:** [http://localhost:3000](http://localhost:3000)
- **API Documentation:** [http://localhost:8000/api/docs](http://localhost:8000/api/docs)
- **API Health:** [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health)

---

### Option B: Local Native Development (Without Docker)

**Prerequisites:** Python 3.13, Node.js 20+, PostgreSQL 16 (UTF-8 enabled).

```bash
# 1. Database Setup (UTF-8 is strictly required for JSONB)
createdb -E UTF8 -T template0 a4s
createdb -E UTF8 -T template0 a4s_test

# 2. Backend Setup
cd backend
python -m venv .venv
source .venv/bin/activate        # On Windows: .\.venv\Scripts\activate
pip install -r requirements-dev.txt

# Run migrations and seed initial data
alembic upgrade head
python -m seeds.seed --history 90

# Start backend server
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# 3. Frontend Setup (in a separate terminal)
cd frontend
cp .env.local.example .env.local
npm ci
npm run dev                      # Available at http://localhost:3000
```

> **Starting the Simulation:** After logging in, navigate to **Simulation**, select the `MIXED` scenario, and click **Start**. The dashboard, digital twins, and UAV maps will begin updating live in real-time.

---

## 7. Demo Credentials

Seed data creates standard accounts for verifying Role-Based Access Control:

| Role | Email | Password | Permissions & Views |
|---|---|---|---|
| **Admin** | `admin@a4s.local` | `Adm1n-A4Splus-2026!` | Full platform administration, RBAC, system config |
| **Commander** | `commander@a4s.local` | `Cmdr-A4Splus-2026!` | Command dashboard, simulation controls, UAV commands |
| **Medical Officer** | `medic@a4s.local` | `Medic-A4Splus-2026!` | Personnel health, digital twins, alerts, ML predictions |
| **Operator** | `operator@a4s.local` | `Oper-A4Splus-2026!` | Terrain analysis, A* route planning, security monitor |
| **Viewer** | `viewer@a4s.local` | `View-A4Splus-2026!` | Read-only access to operational dashboards |

---

## 8. Genuinely ₹0 / Month Cloud Deployment

A4S+ is designed to deploy on permanent free tiers with **zero recurring cost** and no credit card required:

| Component | Free Provider | Free Tier Limits | Architecture Notes |
|---|---|---|---|
| **Frontend** | **Vercel** / **Render** | 100 GB bandwidth, free SSL | Next.js standalone build |
| **Backend** | **Render (Web Service)** | 512 MB RAM, 750 free hrs/mo | Custom Dockerfile, native WebSockets. Sleeps after 15m inactivity |
| **Database** | **Neon.tech** | 0.5 GiB storage, 1 project | Serverless PostgreSQL 16. **Does not expire**; pauses compute when idle |
| **Redis** | **In-Memory Fallback** | ₹0 | Single-instance fallback built directly into `events.py` and `rate_limit.py` |

### Step-by-Step Free Cloud Deployment

#### 1. Database (Neon.tech — Free Forever)
1. Sign up at [neon.tech](https://neon.tech) (Free, no credit card required).
2. Create a project named `a4s-plus` (PostgreSQL 16).
3. Copy the pooled connection string (e.g., `postgresql://user:pass@ep-xyz-pooler.us-east-2.aws.neon.tech/neondb?sslmode=require`).
4. Replace `postgresql://` with `postgresql+asyncpg://` for `A4S_DATABASE_URL`.

#### 2. Backend (Render.com — Free Docker Web Service)
1. Sign up at [render.com](https://render.com).
2. Select **New Web Service** → Connect your GitHub repository (`Vidhan360/a4s-plus`).
3. Set **Runtime** to **Docker**, Dockerfile path to `infra/docker/backend.Dockerfile`.
4. Add Environment Variables:
   - `A4S_ENV`: `production`
   - `A4S_DEBUG`: `false`
   - `A4S_DATABASE_URL`: *your Neon connection string*
   - `A4S_JWT_SECRET`: *generate with `python -c "import secrets;print(secrets.token_urlsafe(64))"`*
   - `A4S_CORS_ORIGINS`: *your frontend domain (e.g., `https://a4s-frontend.vercel.app`)*
   - `A4S_SEED_ADMIN_PASSWORD`: `Adm1n-A4Splus-2026!`
   - `A4S_SEED_COMMANDER_PASSWORD`: `Cmdr-A4Splus-2026!`
   - `A4S_SEED_MEDICAL_PASSWORD`: `Medic-A4Splus-2026!`
   - `A4S_SEED_OPERATOR_PASSWORD`: `Oper-A4Splus-2026!`
   - `A4S_SEED_VIEWER_PASSWORD`: `View-A4Splus-2026!`
5. Deploy. Once live, run database migration via Render shell:
   ```bash
   alembic upgrade head && python -m seeds.seed --history 90
   ```

#### 3. Frontend (Vercel or Render)
1. Import repository on [Vercel](https://vercel.com).
2. Set root directory to `frontend`.
3. Add Environment Variable:
   - `NEXT_PUBLIC_API_BASE_URL`: *your live backend URL, e.g. `https://a4s-backend.onrender.com`*
4. Deploy.

---

## 9. API & Real-time WebSocket Protocol

### Key API Endpoints
- `GET /api/v1/health`: System health, database connectivity, ML model readiness, and event bus state.
- `POST /api/v1/auth/login`: Authenticate and receive short-lived access JWT + rotating refresh token.
- `GET /api/v1/dashboard`: Aggregated operational overview (roster risk, alerts, telemetry).
- `GET /api/v1/predictions/models`: Status and evaluation metrics of registered ML models.
- `POST /api/v1/routes/calculate`: Calculate A* safe vs. shortest path across risk terrain.
- `POST /api/v1/simulation/control`: Engine controls (`START`, `PAUSE`, `STOP`, `RESET`, speed multipliers).

### Real-Time WebSocket Channel
- **URL:** `wss://<backend-domain>/api/v1/ws?token=<access_token>&topics=vitals,alerts,drones,simulation`
- **Negotiation:** Server emits `connection.ready` with permitted topics, followed by a current `snapshot`.
- **Streaming:** Broadcasts live envelopes whenever simulation advances or alerts trigger.

---

## 10. Screenshots

<!-- SCREENSHOTS_PLACEHOLDER -->
| Command & Control Dashboard | Digital Twin & AI Prediction |
|:---:|:---:|
| ![Command Dashboard Placeholder](docs/screenshots/dashboard.png)<br>_Real-time vitals, roster risk distribution, and alert queue_ | ![Digital Twin Placeholder](docs/screenshots/digital-twin.png)<br>_Biomarker telemetry, 30-minute LSTM forecast, and feature attribution_ |

| Tactical Terrain & A* Safe Routing | UAV Swarm Relay & Electronic Warfare |
|:---:|:---:|
| ![Terrain & A* Route Placeholder](docs/screenshots/terrain-routes.png)<br>_Interactive elevation & hazard layers with A* optimal navigation_ | ![UAV Swarm Placeholder](docs/screenshots/uav-swarm.png)<br>_Multi-UAV patrol formations, battery status, and RF jamming simulation_ |

---

## 11. Known Limitations & Future Improvements

1. **Simulated Telemetry:** Every data stream is synthetically generated; no live medical sensors or avionics are connected.
2. **Clinical Applicability:** Models are trained on synthetic physiology and are not validated on clinical human trials.
3. **Single-Instance Deployment:** The default ₹0 architecture uses in-memory pub/sub. Scaling horizontally across multiple nodes requires attaching Redis.
4. **Token Persistence:** Frontend session tokens reside in `localStorage`; a future iteration should migrate refresh tokens to HttpOnly, SameSite cookies.
5. **Hardware Integration Roadmap:** Architectural seam (`DataSource` ABC in `app/datasources/base.py`) is fully prepared for future LoRa/BLE gateway integration without core redesign.

---

## 12. Verification & Test Suite Results

Every test in this repository has been strictly verified:

- **Backend Pytest Suite:** `175 unit tests passed` (`backend/tests/unit`), `145 integration tests passed` (`backend/tests/integration`).
- **Frontend Vitest Suite:** `46 component & unit tests passed` across 8 test suites.
- **Static Analysis:** Strict Mypy type-checking clean across 96 backend files; TypeScript check clean across 94 frontend files; Ruff linter clean.
- **Docker Compose:** Verified with multi-stage builds and local model artifact mounts.

---

## 13. License & Acknowledgements

Created by **Vidhan Mishra and Ishika Masih** ([@Vidhan360](https://github.com/Vidhan360)) ([@ishikamasih369-oss](https://github.com/ishikamasih369-oss)) as part of **Team The Third Eye** for the COMPOSIT 2026 student innovation challenge. Built for research and educational purposes.
