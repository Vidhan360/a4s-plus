# A4S+ — API reference

Base URL `/api/v1`. **89 REST operations across 15 tags, plus one WebSocket.**
Interactive spec: `GET /api/docs` (Swagger UI), `GET /api/redoc`,
`GET /api/openapi.json`.

> Every response describing a person, aircraft, position or terrain feature
> carries simulated data. Payloads that originate from telemetry include a
> provenance field (`source`, `data_provenance`, `is_simulated`,
> `is_synthetic`) precisely so a consumer can never mistake it for a
> measurement.

## 1. Conventions

**Versioning.** The version lives in the path. `GET /api/v1/meta` reports the
service version, API version, build environment and the honesty declaration
(`prototype_status`, `data_provenance`, `validation_status`).

**Authentication.** `Authorization: Bearer <access_token>`. Access tokens last
15 minutes; refresh tokens last 7 days and rotate on every use.

**Pagination.** List endpoints take `limit` (1–200, default 50) and `offset`,
and return:

```json
{ "items": [ … ], "meta": { "total": 137, "limit": 50, "offset": 0 } }
```

Bare arrays are returned only where the collection is bounded by design:
`/terrain/maps`, `/config`, `/drones`, `/drones/events`, `/drones/missions`,
`/simulation/runs`, `/simulation/scenarios`, `/predictions/models`.

**Errors.** One envelope for every failure:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed.",
    "details": [{ "field": "body.spo2", "message": "…", "type": "less_than_equal" }],
    "request_id": "01J…"
  }
}
```

| Status | When |
|---|---|
| 400 | malformed request the schema cannot express |
| 401 | missing, expired or reused token (`code: unauthorised`, `token_reuse`) |
| 403 | authenticated but the permission is absent (`code: forbidden`, message names the permission) |
| 404 | unknown id |
| 409 | uniqueness conflict (duplicate call sign, email, map name) |
| 422 | Pydantic validation failure, **or** a valid request in an invalid state — e.g. a UAV command while the simulation is stopped |
| 429 | rate limit exceeded, with `Retry-After` |
| 500 | unexpected; `request_id` correlates with the structured log |

**Rate limits.** `POST /auth/login` 10/min · `POST /auth/refresh` 30/min ·
`POST /auth/change-password` 5/min · everything else 200/min, per client IP.

**Timestamps.** ISO-8601, UTC, timezone-aware.

## 2. Authorisation model

Routes require *permissions*, never roles. A role is a bundle of permissions,
so adding a role changes no route code. `GET /auth/permissions` returns the
caller's effective set, which is exactly what the frontend renders from.

The 36 permissions: `personnel:read|write|delete`, `vitals:read|ingest`,
`health:read`, `prediction:read|run`, `twin:read`,
`alert:read|ack|config`, `terrain:read|write`, `route:read|plan`,
`drone:read|command`, `security:read|write|simulate`, `crypto:demo`,
`audit:read`, `dashboard:read`, `analytics:read`,
`simulation:read|control`, `user:read|write`, `config:read|write`.

## 3. Endpoints

### 3.1 Auth (`/auth`) — 6

| Method | Path | Permission | Notes |
|---|---|---|---|
| POST | `/auth/login` | public | `{email, password}` → `{tokens:{access_token, refresh_token, token_type, expires_in}, user}`. Counts failures; locks the account for 15 min after 5. |
| POST | `/auth/refresh` | public | `{refresh_token}` → new pair. Rotation: the old token is revoked and points at its successor. Presenting a revoked token revokes the **whole family** and returns `401 token_reuse`. |
| POST | `/auth/logout` | authenticated | Revokes the presented refresh token family. |
| GET | `/auth/me` | authenticated | Profile, roles, permissions, status. |
| GET | `/auth/permissions` | authenticated | Flat permission list. |
| POST | `/auth/change-password` | authenticated | `{current_password, new_password}` (min 12 chars); revokes all other sessions. |

### 3.2 System (`/meta`, `/health`) — 2

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/meta` | public | Version, environment, `prototype_status`, `data_provenance`, `validation_status`, capability declaration. |
| GET | `/health` | public | Liveness plus per-dependency checks for PostgreSQL, Redis, the ML registry and the simulation engine. |

### 3.3 Personnel (`/personnel`) — 8

| Method | Path | Permission |
|---|---|---|
| GET | `/personnel` (`limit`,`offset`,`search`,`status`) | `personnel:read` |
| POST | `/personnel` → **201** | `personnel:write` |
| GET | `/personnel/{id}` | `personnel:read` |
| PATCH | `/personnel/{id}` | `personnel:write` |
| DELETE | `/personnel/{id}` | `personnel:delete` |
| GET | `/personnel/summary/roster` | `personnel:read` |
| GET | `/personnel/{id}/vitals` | `vitals:read` |
| GET | `/personnel/{id}/risk` | `health:read` |
| GET | `/personnel/{id}/twin` | `twin:read` |

`GET /personnel/{id}` returns the person, their latest reading, latest risk
assessment, `open_alerts` and a `twin` envelope. The twin envelope is
**identical** in shape to `GET /personnel/{id}/twin`
(`{personnel_id, call_sign, risk_score, risk_category, open_alert_count,
is_stale, updated_at, state}`) — a shared helper builds both, and a regression
test asserts the two surfaces agree.

### 3.4 Vitals (`/vitals`) — 2

| Method | Path | Permission | Notes |
|---|---|---|---|
| POST | `/vitals/ingest` → **201** | `vitals:ingest` | Manual ingestion. Runs the full pipeline: risk scoring → alert evaluation → twin update → event publication. Stored with `source: MANUAL`. |
| GET | `/vitals` | `vitals:read` | Recent readings across the roster (the dashboard live feed's initial page). |

### 3.5 Predictions (`/predictions`) — 7

| Method | Path | Permission | Notes |
|---|---|---|---|
| POST | `/predictions/{personnel_id}/run` | `prediction:run` | Runs the active model over the last 24 readings. Returns probability, category, per-class probabilities, `explanation` (method, top contributions, prose `narrative`), `inference_ms`. With fewer than 24 readings it says so instead of guessing. |
| GET | `/predictions/{personnel_id}/history` | `prediction:read` | Paged prediction history. |
| GET | `/predictions/{personnel_id}/compare` | `prediction:read` | **GET.** `results` is an **array** of one object per model: `{model_name, model_version, available, explanation_method, data_provenance, risk_probability, predicted_category, class_probabilities, inference_ms, horizon_minutes, top_contributions[], narrative, metrics}`. Unavailable models appear with `available: false` and a reason. |
| GET | `/predictions/explain/{prediction_id}` | `prediction:read` | Re-serves the stored explanation for an earlier prediction. |
| GET | `/predictions/models` | `prediction:read` | Registry: every trained version, its metrics, which is active. |
| GET | `/predictions/methods` | `prediction:read` | The explanation method each model actually uses, and its limitations. |
| POST | `/predictions/reload` | `config:write` | Re-reads `ml/artifacts/` so a retrained model goes live without a restart. |

`explanation.narrative` is a **single prose string**, not a list.

### 3.6 Alerts (`/alerts`) — 6

| Method | Path | Permission |
|---|---|---|
| GET | `/alerts` (`status`,`severity`,`personnel_id`,`limit`,`offset`) | `alert:read` |
| GET | `/alerts/summary` | `alert:read` |
| GET | `/alerts/rules` | `alert:read` |
| GET | `/alerts/{id}` | `alert:read` |
| POST | `/alerts/{id}/acknowledge` | `alert:ack` |
| POST | `/alerts/{id}/resolve` (`{resolution_note}`) | `alert:ack` |

### 3.7 Dashboard & analytics — 4

| Method | Path | Permission |
|---|---|---|
| GET | `/dashboard` | `dashboard:read` |
| GET | `/dashboard/twins` | `twin:read` |
| GET | `/analytics` (`window_hours`) | `analytics:read` |
| GET | `/analytics/model-comparison` | `analytics:read` |

`/analytics/model-comparison` serves the **measured** contents of
`ml/artifacts/last_comparison.json`. If no training run exists it returns an
empty result rather than illustrative numbers.

### 3.8 Terrain (`/terrain`) — 7

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/terrain/maps` | `terrain:read` | Bare list; each map declares `is_synthetic: true` and its generator seed. |
| POST | `/terrain/maps` → **201** | `terrain:write` | Generate a new procedural map from a seed. |
| POST | `/terrain/maps/{id}/default` | `terrain:write` | |
| DELETE | `/terrain/maps/{id}` | `terrain:write` | |
| GET | `/terrain/grid` (`map_id`,`layer`,`downsample`) | `terrain:read` | Layer matrix for the canvas. |
| GET | `/terrain/cell` (`map_id`,`x`,`y`) | `terrain:read` | Single-cell inspection. |
| GET | `/terrain/legend` | `terrain:read` | Layer definitions and colour scales. |

### 3.9 Routes (`/routes`) — 5

| Method | Path | Permission |
|---|---|---|
| POST | `/routes/plan` → **201** | `route:plan` |
| GET | `/routes` | `route:read` |
| GET | `/routes/{id}` | `route:read` |
| DELETE | `/routes/{id}` | `route:plan` |
| GET | `/routes/verify-optimality` | `route:read` |

`POST /routes/plan` body: `{map_id?, name?, start_x, start_y, goal_x, goal_y,
enabled_layers[], compare_shortest?, persist?, notes?}`. `enabled_layers` is a
subset of `avalanche, crevasse, weather, difficulty`; an unknown layer is a
**422** naming the valid ones. Start and goal must differ. There is **no**
`avoid_hazards` field — layer selection is how hazards are weighted. Both
profiles (`SAFEST` and `SHORTEST`) are solved when `compare_shortest` is true.

The response contains both profiles' results plus `comparison.delta`
(`distance_delta_m`, `distance_delta_pct`, `risk_delta`, `peak_risk_delta`,
`minutes_delta`). `path` is an array of `{x, y}` **objects**.
`avoided_hazards` is `{mean:{layer:number}, peak:{layer:number}, layers:[…]}`.

`GET /routes/verify-optimality` is a **GET with query parameters**
(`start_x`, `start_y`, `goal_x`, `goal_y`, `map_id`). It re-solves the same
grid with Dijkstra and reports whether A\*'s cost matched, plus the node
expansion counts for both — a real check, not an assertion.

### 3.10 UAV swarm (`/drones`) — 7

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/drones` | `drone:read` | Swarm status; every drone reports `is_simulated: true`. |
| GET | `/drones/{id}` | `drone:read` | |
| GET | `/drones/events` | `drone:read` | |
| GET | `/drones/missions` | `drone:read` | |
| POST | `/drones/{id}/command` `{action}` | `drone:command` | |
| POST | `/drones/formation` `{formation}` | `drone:command` | |
| POST | `/drones/inject/jamming` `{drone_id, duration_seconds}` | `security:simulate` | |
| POST | `/drones/inject/spoofing` `{drone_id, duration_seconds}` | `security:simulate` | |

All four write operations return **422** while the simulation engine is not
running. That is deliberate: there is no aircraft to command, and returning
success would be a lie.

### 3.11 Simulation (`/simulation`) — 11

| Method | Path | Permission |
|---|---|---|
| GET | `/simulation/status` | `simulation:read` |
| GET | `/simulation/snapshot` | `simulation:read` |
| GET | `/simulation/scenarios` | `simulation:read` |
| GET | `/simulation/runs` | `simulation:read` |
| GET | `/simulation/data-source` | `simulation:read` |
| POST | `/simulation/start` `{scenario, seed, speed, tick_seconds, sim_seconds_per_tick, reset_first}` | `simulation:control` |
| POST | `/simulation/pause` | `simulation:control` |
| POST | `/simulation/resume` | `simulation:control` |
| POST | `/simulation/stop` | `simulation:control` |
| POST | `/simulation/reset` | `simulation:control` |
| POST | `/simulation/speed` `{speed ∈ 1,2,5,10}` | `simulation:control` |
| POST | `/simulation/scenario` `{scenario, personnel_id?}` | `simulation:control` |

`GET /simulation/data-source` is the honesty endpoint: it returns the active
source's provenance, capabilities, and the adapters that are **declared but not
implemented**.

### 3.12 Security (`/security`) — 7

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/security/events` (`severity`,`origin`,`status`,`event_type`) | `security:read` | Enum-validated; an invalid filter is **422**, not silently ignored. |
| GET | `/security/posture` | `security:read` | |
| GET | `/security/settings` | `security:read` | `{access_token_minutes, refresh_token_days, max_failed_logins, lockout_minutes, min_password_length, password_hash, environment, controls[]}` |
| GET | `/security/catalogue` | `security:read` | Threats modelled and controls implemented, each flagged implemented / demonstrated / not implemented. |
| POST | `/security/inject` `{kind, drone_id?, payload?}` | `security:simulate` | Stored with `origin: INJECTED`. |
| POST | `/security/events/{id}/acknowledge` | `security:write` | |
| POST | `/security/crypto-demo` | `crypto:demo` | AES-256-GCM over supplied text; per-request ephemeral key; returns ciphertext, nonce, tag and a tamper-detection result. A demonstration, not the system's transport or storage encryption. |

### 3.13 Audit (`/audit`) — 2

| Method | Path | Permission |
|---|---|---|
| GET | `/audit` (`action`,`resource_type`,`actor`,`result`,`from`,`to`) | `audit:read` |
| GET | `/audit/facets` | `audit:read` |

The paged response adds an `immutability` block describing the append-only
database trigger. The per-entry metadata field is named **`meta`**.

### 3.14 Users & roles (`/users`) — 7

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/users` (`limit`,`offset`,`search`,`status`,`role`) | `user:read` | |
| POST | `/users` → **201** | `user:write` | `{email, full_name, password (min 12), roles[]}` |
| GET | `/users/roles` | `user:read` | `{roles:[{code,name,description,permissions[]}], permissions:[{code,description}], note}` — powers the permission matrix |
| GET | `/users/{id}` | `user:read` | |
| PATCH | `/users/{id}` | `user:write` | `{full_name?, status?, roles?}`, `status ∈ ACTIVE|DISABLED|LOCKED` |
| POST | `/users/{id}/password` | `user:write` | `{new_password}`; revokes that user's sessions |
| POST | `/users/{id}/unlock` | `user:write` | Clears lockout and the failure counter |

### 3.15 Configuration (`/config`) — 5

| Method | Path | Permission |
|---|---|---|
| GET | `/config` | `config:read` |
| GET | `/config/defaults` | `config:read` |
| GET | `/config/{key}` | `config:read` |
| PUT | `/config/{key}` `{value}` | `config:write` |
| POST | `/config/{key}/reset` | `config:write` |

`ConfigOut` = `{key, value, default_value, description, version, is_editable,
is_customised, updated_at}`. Every write bumps `version` and writes an audit
row, so a changed risk weight is traceable to a person and a time.

## 4. WebSocket

```
GET /api/v1/ws?token=<access_token>&topics=vitals,alerts,dashboard
```

Topics and their required permission: `vitals`→`vitals:read`,
`alerts`→`alert:read`, `drones`→`drone:read`, `security`→`security:read`,
`simulation`→`simulation:read`, `dashboard`→`dashboard:read`. Omitting
`topics` requests all of them; only the permitted subset is granted.

**Handshake**

```json
{"type":"connection.ready","topics":["vitals","alerts"],"permissions":[…]}
```

Then one message per event:

```json
{"topic":"alerts","event":"alert.created","payload":{…},"ts":"2026-…Z"}
```

**Client messages** `{"action":"subscribe","topics":[…]}` and
`{"action":"snapshot"}`. **Server heartbeat** every 25 s.
**Close codes:** `4401` unauthenticated or invalid token; `1008` policy
violation. A client whose role permits no topic is told so explicitly rather
than left connected and silent.

## 5. Trying it out

```bash
TOKEN=$(curl -s localhost:8000/api/v1/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"commander@a4s.local","password":"Cmdr-A4Splus-2026!"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["tokens"]["access_token"])')

curl -s localhost:8000/api/v1/simulation/data-source -H "authorization: Bearer $TOKEN" | jq
curl -s -X POST localhost:8000/api/v1/simulation/start -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' -d '{"scenario":"MIXED","seed":20260909,"speed":5}' | jq
curl -s localhost:8000/api/v1/dashboard -H "authorization: Bearer $TOKEN" | jq '.risk_distribution'
```
