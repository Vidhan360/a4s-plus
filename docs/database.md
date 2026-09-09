# A4S+ — Database

PostgreSQL 16, accessed asynchronously through SQLAlchemy 2.0 (`asyncpg`) with
Alembic migrations. **23 tables.**

> Every row this schema ever holds in the prototype is simulated data. Columns
> such as `vital_readings.source`, `drones.is_simulated` and
> `terrain_maps.is_synthetic` exist so that provenance is recorded in the data
> itself and cannot be lost between the engine and the UI.

## 1. Requirements

- **The database must be UTF-8.** Ten tables store `JSONB`; a `SQL_ASCII`
  cluster accepts byte sequences that later fail to decode. Create with
  `createdb -E UTF8 -T template0 a4s`.
- Postgres-specific features in use: `JSONB`, partial/composite indexes, and a
  `BEFORE UPDATE OR DELETE` trigger on `audit_logs`.
- The test suite also runs against SQLite for the fast unit tier, which is why
  UUID primary keys are stored as `CHAR(36)` and timestamps as timezone-aware
  `DATETIME` rather than using Postgres-only column types.

## 2. Conventions

| Convention | Detail |
|---|---|
| Primary keys | `CHAR(36)` UUID4 for domain entities; `BIGINT` identity for high-volume append tables (`vital_readings`, `audit_logs`, `drone_events`) |
| Timestamps | `created_at` / `updated_at`, UTC, timezone-aware, server-independent defaults set in Python |
| Soft state | Status columns are string enums (`PersonnelStatus`, `AlertStatus`, …) validated by Pydantic at the edge |
| JSON | `JSONB` for evidence and structured detail (`factors`, `contributions`, `triggering_data`, `state`, `payload`, `meta`) |
| Naming | `ix_<table>_<columns>` for indexes; composite indexes are ordered for the query that needs them |

## 3. Table groups

### 3.1 Identity and authorisation (6)

| Table | Purpose |
|---|---|
| `users` | email (unique), Argon2id `password_hash`, `status`, `failed_login_count`, `locked_until`, `last_login_at`, `password_changed_at` |
| `roles` | `code` (ADMIN / COMMANDER / MEDICAL_OFFICER / OPERATOR / VIEWER), name, description |
| `permissions` | 36 permission codes with descriptions, seeded from the `Perm` enum |
| `user_roles` | many-to-many `users` ↔ `roles` |
| `role_permissions` | many-to-many `roles` ↔ `permissions` |
| `refresh_tokens` | SHA-256 `token_hash`, `family_id`, `expires_at`, `revoked_at`, `rotated_to_id`, `ip`, `user_agent` — the family + rotation pointer is what makes reuse detection possible |

Roles and permissions are persisted **and** mirrored in
`app/core/permissions.py`. The table is the record of truth for the admin UI
and audit; the enum is the record of truth for route protection, so a typo in a
route decorator is a static error rather than a silent grant.

### 3.2 Personnel and health (6)

| Table | Purpose |
|---|---|
| `personnel` | `call_sign` (unique), name, age, unit, rank, status, per-person baselines (`baseline_heart_rate`, `baseline_spo2`), `sim_scenario` |
| `vital_readings` | append-only telemetry: HR, SpO₂, body temp, respiratory rate, BP systolic/diastolic, altitude, fatigue, activity level, env temp, wind, lat/lon, grid x/y, **`source`** (`SIMULATION` / `MANUAL`), `scenario`, `simulation_run_id` |
| `risk_assessments` | rule-engine output: `risk_score`, `category`, `engine`, `factors` (JSONB per-factor evidence), `config_version` so a score can be re-explained under the weights that produced it |
| `health_predictions` | ML output: `model_name`, `model_version`, `horizon_minutes`, `risk_probability`, `predicted_category`, `contributions`, **`explanation_method`**, **`data_provenance`**, `sequence_length`, `inference_ms`, `trajectory` |
| `health_alerts` | `alert_type`, `severity`, title, `reason`, `recommended_action`, `triggering_data`, `status`, **`dedup_key`**, `occurrence_count`, `escalated_from`, acknowledge/resolve actor + timestamps, `resolution_note`, `last_triggered_at` |
| `digital_twin_states` | one row per person (PK = `personnel_id`): pointers to the latest reading/risk/prediction, denormalised `risk_score`, `risk_category`, `open_alert_count`, full `state` JSONB, `is_stale` |

`digital_twin_states` is a deliberate denormalisation: the dashboard needs the
current state of the whole roster on every tick, and a single indexed row per
person keeps that a sequential scan of tens of rows rather than a windowed
aggregate over hundreds of thousands of readings.

### 3.3 Terrain and routing (4)

| Table | Purpose |
|---|---|
| `terrain_maps` | name, dimensions, `cell_size_m`, origin lat/lon, elevation range, **`seed`**, `generator_version`, `is_default`, **`is_synthetic`** |
| `terrain_cells` | composite PK `(map_id, x, y)`: `elevation_m`, `terrain_type`, `difficulty`, `avalanche_risk`, `crevasse_risk`, `weather_risk`, `blocked` |
| `routes` | a saved start→goal request on a map, with `name`, `notes`, `created_by_id` |
| `route_calculations` | one A\* run: `profile` (`SAFEST`/`SHORTEST`), `cost_config`, `path` JSONB, `found`, `distance_m`, `ascent_m`, `descent_m`, `estimated_minutes`, `total_cost`, `risk_score`, `max_cell_risk`, `avoided_hazards`, `nodes_expanded`, `compute_ms`, `explanation` |

Storing `cost_config` and `nodes_expanded` alongside the path is what lets the
UI explain *why* a route was chosen and lets `GET /routes/verify-optimality`
re-check the result against Dijkstra afterwards.

### 3.4 UAV swarm (3)

| Table | Purpose |
|---|---|
| `drones` | `call_sign`, model, `status`, `comms_status`, battery, altitude, heading, speed, `signal_strength`, true `grid_x/grid_y` + lat/lon, `waypoint_index`, **`under_jamming`**, **`under_spoofing`**, **`reported_grid_x/y`**, `autonomous_mode`, `mission_id`, `last_telemetry_at`, **`is_simulated`** |
| `drone_missions` | name (unique), `mission_type`, `formation`, `waypoints` JSONB, `status`, optional `map_id` |
| `drone_events` | append-only: `event_type`, `severity`, message, `payload` |

The split between true position (`grid_x/grid_y`) and *reported* position
(`reported_grid_x/y`) is the entire spoofing model: a spoofed drone keeps flying
its real path while reporting a false one, and the UI can show the divergence.

### 3.5 System, security and audit (4)

| Table | Purpose |
|---|---|
| `simulation_runs` | `scenario_profile`, **`seed`**, `speed`, `status`, `tick_count`, `sim_clock_seconds`, `config`, `started_by_id`, timestamps — the reproducibility record for a run |
| `security_events` | `event_type`, `severity`, **`origin`** (`SYSTEM` / `INJECTED`), `source`, title, description, `status`, `response_action`, `actor_user_id`, `subject_email`, `drone_id`, `ip`, `user_agent`, `request_id`, `payload`, `handled_by_id`, `handled_at` |
| `system_configurations` | PK `key`, `value` JSONB, description, `version` (bumped on every write), `is_editable`, `updated_by_id` |
| `audit_logs` | `actor_user_id` + `actor_email` (denormalised so the trail survives user deletion), `action`, `resource_type`, `resource_id`, `result`, `ip`, `user_agent`, `request_id`, `meta` JSONB |

`security_events.origin` distinguishes an event the system genuinely detected
from one an operator injected on the Security page — without it, a demo
injection would be indistinguishable from a real detection.

## 4. Append-only audit log

Application code only ever inserts into `audit_logs`. That is enforced in the
database, not just by convention — migration `45d83b6b3424` installs:

```sql
CREATE OR REPLACE FUNCTION a4s_audit_logs_append_only()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'audit_logs is append-only: % is not permitted', TG_OP
        USING HINT = 'Audit history is immutable by design.';
END
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_logs_append_only
BEFORE UPDATE OR DELETE ON audit_logs
FOR EACH ROW EXECUTE FUNCTION a4s_audit_logs_append_only();
```

The same migration additionally attempts to `REVOKE UPDATE, DELETE, TRUNCATE`
on the table from the application role, guarded by the `a4s.app_role` database
setting. That defence only applies when migrations run as a different role than
the application and when the application is not the table owner — PostgreSQL
always lets an owner act on its own table — so the statement is best-effort and
raises a `NOTICE` when it is skipped. The trigger is the guarantee that holds
regardless of ownership.

`GET /api/v1/audit` returns an `immutability` block describing this guarantee,
and an integration test asserts that an `UPDATE` and a `DELETE` both raise.

**Honest limit:** the trigger stops the application role from rewriting history.
A superuser can drop the trigger. Cryptographic chaining or an append-only
external store would be needed for a stronger guarantee, and is not implemented.

## 5. Indexing strategy

Indexes exist for measured access patterns, not on principle:

- `ix_vital_readings_personnel_recorded (personnel_id, recorded_at)` — the LSTM
  window query, which fetches the last 24 readings for one person.
- `ix_vital_readings_recorded_at_desc (recorded_at)` — the dashboard live feed.
- `ix_health_alerts_status_severity_created` — the alert queue's default sort.
- `ix_health_alerts_dedup_status (dedup_key, status)` — the deduplication lookup
  the alert engine performs on every tick.
- `ix_health_predictions_personnel_created` — prediction history and trend.
- `ix_risk_assessments_personnel_created` — risk trend chart.
- `ix_terrain_cells_map_blocked (map_id, blocked)` — A\* grid load.
- `ix_security_events_severity_created` / `_origin_created` — triage filters.
- `ix_audit_logs_actor_created` / `_resource` — audit facets.
- `ix_drones_status_callsign`, `ix_personnel_status_call_sign`,
  `ix_users_status_email` — the roster/table listings, which sort by name
  within a status filter.

## 6. Migrations

| Revision | Contents |
|---|---|
| `45d83b6b3424_initial_schema` | All 23 tables, enum-backed check constraints, every index above, and the audit immutability trigger |
| `2b6d9bf2b390_add_total_cost_to_route_calculations` | Adds `route_calculations.total_cost`, needed by the optimality verifier |

```bash
alembic upgrade head        # apply
alembic downgrade -1        # step back
alembic revision --autogenerate -m "…"
```

Both revisions have working `downgrade()` implementations, including dropping
the trigger and function.

## 7. Seeding

`python -m seeds.seed --history 90` is idempotent and creates:

- 5 roles, 36 permissions, the role↔permission matrix;
- 5 demo users (passwords required from `A4S_SEED_*`, so seeding cannot invent
  a credential);
- a roster of personnel with individual baselines;
- a default 64×64 terrain map with all hazard layers;
- a UAV flight of simulated relay drones and a patrol mission;
- the editable system configuration from `core/defaults.py`;
- optionally `--history N` minutes of back-dated readings, risk assessments and
  twin state. **90 is recommended**: the LSTM needs 24 one-minute steps before
  it will emit a prediction instead of an honest "insufficient history".

Every seeded reading has `source = 'SIMULATION'`, and the command finishes by
printing a reminder that nothing in the database was measured from a person, an
aircraft or a terrain survey.
