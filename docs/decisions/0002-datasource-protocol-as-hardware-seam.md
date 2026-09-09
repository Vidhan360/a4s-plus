# ADR 0002 — One `DataSource` abstraction as the only hardware seam

**Status:** Accepted

## Context

The brief requires a software-only prototype whose architecture allows hardware
to be swapped in later without redesign. The obvious failure mode is scattering
"if simulated" branches through the codebase, after which adding hardware means
touching everything.

The second, worse failure mode is stubbing hardware adapters so they return
plausible values — at which point fabricated data can reach the UI wearing a
real provenance stamp.

## Decision

Define one abstract `DataSource` in `app/datasources/base.py` producing
`VitalSample` and `EnvironmentSample`. Make `VitalSample.source` a **mandatory**
field so provenance travels with the data into `vital_readings.source` and out
to the UI. Ship exactly one implementation, `SimulationDataSource`.

Declare the future adapters — `WearableDataSource`, `UAVDataSource`,
`EdgeDataSource` — and have their constructors **raise `NotImplementedError`**
with an integration note. Expose that list at
`GET /api/v1/simulation/data-source` and in the admin UI as "declared but not
implemented".

## Consequences

- The risk engine, alert engine, twin builder, prediction service, dashboard
  and WebSocket layer contain no reference to simulation at all.
- No code path can accidentally serve invented sensor data.
- The honesty claim is checkable by a reader in one file.
- Declaring classes that only raise looks odd to reviewers unfamiliar with the
  intent. Accepted; the docstrings explain it, and the alternative (silent
  stubs) is worse.
