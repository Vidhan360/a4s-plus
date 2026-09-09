# A4S+ — Architecture

> A4S+ is a software prototype. Every reading it processes is simulated data,
> and its outputs are not clinically validated. This document describes how the
> code is organised, not a deployed system.

## 1. Goals that shaped the design

1. **Honesty is structural, not cosmetic.** Simulated data must be
   distinguishable from real data at every layer, so provenance travels with
   the payload rather than being added by the UI.
2. **Hardware must be addable without redesign.** All ingestion goes through
   one protocol (`app/datasources/base.py`).
3. **Every displayed number must be explainable.** The risk engine is
   deterministic and inspectable; the ML path emits contributions computed by a
   named method.
4. **Permissions decide the UI.** The frontend renders from the permission list
   the server returns, so a role change needs no frontend change.
5. **Determinism.** The same `(seed, scenario, tick count)` triple reproduces
   the same run, which is what makes the demo and the tests reliable.

## 2. Layers

```
┌─────────────────────────────────────────────────────────────────┐
│ frontend/  Next.js 15 App Router, TypeScript, Tailwind          │
│   src/app          18 routes, one route group `(app)` behind auth│
│   src/components   ui/ (shadcn-style) · domain/ · charts/ ·     │
│                    layout/                                      │
│   src/hooks        use-session (auth ctx) · use-live-stream (WS) │
│   src/lib          api-client · token-store · api-error ·       │
│                    query-keys · types · constants · format      │
└─────────────────────────────────────────────────────────────────┘
        │ REST /api/v1 · Bearer access token          │ WS /api/v1/ws
        ▼                                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ backend/app                                                     │
│  api/v1/*      routers: HTTP shape, validation, RBAC dependency │
│  api/deps.py   current_user, require(Perm...), pagination       │
│  services/*    18 services: business rules, no SQL, no HTTP     │
│  repositories/*  7 modules: every SQL statement in the codebase │
│  models/*      23 SQLAlchemy 2.0 mapped classes + enums         │
│  schemas/*     Pydantic v2 request/response contracts           │
│  simulation/*  environment · vitals · swarm · engine (the clock)│
│  datasources/* DataSource protocol  ← the hardware seam         │
│  algorithms/*  terrain_gen (procedural) · astar (+ Dijkstra)    │
│  ws/manager.py connection lifecycle, topic negotiation          │
│  core/*        config · security · permissions · database ·     │
│                events · errors · logging · middleware ·         │
│                rate_limit · defaults                            │
└─────────────────────────────────────────────────────────────────┘
        │                                             │
        ▼                                             ▼
   PostgreSQL 16 (23 tables, async via asyncpg)   Redis (rate limits,
                                                  event fan-out)
        ▲
        │
┌─────────────────────────────────────────────────────────────────┐
│ backend/ml   features · dataset · model · registry · evaluate · │
│              baseline · train        artifacts/<model>/<version>│
└─────────────────────────────────────────────────────────────────┘
```

**Dependency rule:** routers → services → repositories → models. Services never
import from `api/`; repositories never import from `services/`. No SQL exists
outside `repositories/` (and Alembic). This is what makes the service layer
unit-testable against a SQLite session in the fast tests.

## 3. Request lifecycle

`POST /api/v1/predictions/{personnel_id}/run` is representative:

1. **Middleware** (`core/middleware.py`) assigns a request id, starts a timer,
   and attaches security headers to the response.
2. **Rate limiting** (`core/rate_limit.py`, SlowAPI + Redis) applies the route
   limit; the default is `200/minute`, login `10/minute`.
3. **Auth dependency** decodes the JWT, loads the user, and rejects disabled or
   locked accounts.
4. **Permission dependency** `require(Perm.PREDICTION_RUN)` compares the
   route's requirement against the union of the user's role permissions and
   raises `403` with a machine-readable code on failure.
5. **Router** validates the path/body with Pydantic and calls the service.
6. **`PredictionService`** loads the latest window of readings through the
   repository, builds the feature matrix with `ml.features`, asks the active
   model in the registry for probabilities, computes contributions with the
   model's own explanation method, persists a `health_predictions` row, and
   publishes a `vitals`-topic event.
7. **Audit** middleware-level hook writes an append-only `audit_logs` row for
   state-changing verbs.
8. **Response** is serialised by the response model, so no ORM object can leak.
9. **Errors** are converted by `core/errors.py` into a single envelope:
   ```json
   { "error": { "code": "forbidden", "message": "…",
                "details": [{"field": "…", "message": "…", "type": "…"}],
                "request_id": "…" } }
   ```

## 4. Real-time pipeline

```
SimulationEngine tick (default 2 s wall clock, scaled by 1x/2x/5x/10x)
  → VitalsSimulator per person  → IngestionService
      → RiskEngine (present score)   → risk_assessments
      → AlertEngine (dedupe/cooldown/escalate) → health_alerts
      → TwinService (state vector)   → digital_twin_states
      → PredictionService (periodic) → health_predictions
  → SwarmSimulator                   → drones, drone_events
  → EventBus.publish(topic, event, payload)
      → Redis pub/sub (cross-worker) → WebSocketManager
          → each client filtered by negotiated topics AND permissions
```

The event bus is an abstract class (`core/events.py`) with an in-memory
implementation for tests and a Redis implementation for multi-worker runs, so
the WebSocket layer behaves identically in both.

**Topic → permission gate** (`ws/manager.py`): `vitals`→`vitals:read`,
`alerts`→`alert:read`, `drones`→`drone:read`, `security`→`security:read`,
`simulation`→`simulation:read`, `dashboard`→`dashboard:read`. A client asking
for a topic it cannot read simply does not receive it; a client with no
permitted topic is told so explicitly rather than left silently idle.
Unauthenticated sockets are closed with code **4401**. Heartbeats every 25 s.

## 5. The hardware seam

```python
# app/datasources/base.py
class DataSource(ABC):
    kind: DataSourceKind = DataSourceKind.SIMULATION   # provenance stamp

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def snapshot(self) -> list[VitalSample]: ...

    @abstractmethod
    def stream(self) -> AsyncIterator[list[VitalSample]]: ...
```

Everything downstream of ingestion — risk engine, prediction service, alert
engine, twin builder, dashboard, WebSockets — consumes `VitalSample` and
`EnvironmentSample` and knows nothing about where they came from. `VitalSample`
requires a `source`, so provenance is carried by the data rather than added by
the UI.

`GET /api/v1/simulation/data-source` reports the active source's `name`,
`kind`, `is_simulated` flag, capabilities and the declared-but-unimplemented
adapters. Those adapters — `WearableDataSource`, `UAVDataSource`,
`EdgeDataSource` — subclass `_UnimplementedHardwareSource`, whose constructor
raises `NotImplementedError` with its `_integration_note` and a pointer to the
roadmap. Raising rather than returning plausible values means no code path can
accidentally present invented sensor data as measured. See [`hardware-integration-roadmap.md`](hardware-integration-roadmap.md).

## 6. Frontend architecture

- **Route groups.** `(app)/*` sits behind a layout that requires a session and
  renders the app shell (sidebar, topbar, simulation controls, prototype
  banner). `/login` and error pages sit outside it.
- **Server state** is TanStack Query only; there is no client state library.
  Query keys are centralised in `lib/query-keys.ts` so invalidation after a
  mutation is a one-liner.
- **Live state** merges into the query cache. `use-live-stream` owns a single
  WebSocket for the whole app, reconnects with backoff, and exposes
  connection status to the topbar indicator.
- **One HTTP client.** `lib/api-client.ts` attaches the token, and on `401`
  performs a *single shared* refresh: concurrent failures await the same
  in-flight promise instead of stampeding `/auth/refresh`. Refresh-token reuse
  triggers `onSessionExpired`, which clears storage and redirects.
- **Errors are typed.** `ApiError` exposes `isUnauthorised`, `isForbidden`,
  `isNotFound` and `fieldErrors`, so RHF+Zod forms can attach server-side
  field errors, and `403` renders an RBAC explanation with no retry button.
- **Every panel handles four states.** `components/ui/states.tsx` provides
  `LoadingPanel`, `EmptyState`, `ErrorPanel` and a `QueryBoundary` wrapper, so
  loading and empty are designed rather than blank.
- **Permission-driven UI.** `useSession().can(perm)` hides actions the server
  would refuse. The permission constants in `lib/constants.ts` mirror the
  backend `Perm` enum exactly.

## 7. Configuration

`core/config.py` is a `pydantic-settings` model with the `A4S_` prefix and
fail-fast validation: a production environment with a development JWT secret
refuses to boot. `core/defaults.py` holds the seeded, editable system
configuration (risk weights, alert thresholds, cooldowns, route penalties) with
a description and default for each key, which is what powers the admin
configuration page and `POST /config/{key}/reset`.

## 8. Deployment shape

Two containers (API, frontend standalone Next server) plus PostgreSQL and
Redis, with a one-shot `migrate` service so a scaled API never races on
Alembic, and an optional `train` profile. **These container definitions have
never been executed** — the build environment had no Docker daemon. See README
§9.

## 9. Decisions

Recorded as ADRs in [`decisions/`](decisions): async SQLAlchemy, the data-source
protocol, permission-based rather than role-based authorisation, the choice to
keep the LSTM as the default despite gradient boosting scoring higher, the
`localStorage` token trade-off, and the append-only audit trigger.
