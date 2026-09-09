# ADR 0009 — A single in-process simulation engine owns the clock

**Status:** Accepted, limits scaling

## Context

The simulation must advance every person and drone on a shared tick, remain
pausable and speed-adjustable, and be exactly reproducible from a seed.
Alternatives were an external scheduler (Celery beat, cron) or a database-driven
tick.

## Decision

One asyncio task inside the API process owns the clock. Run state is persisted
on `simulation_runs` (`seed`, `speed`, `tick_count`, `sim_clock_seconds`) on
every tick. Events are published through an abstract `EventBus` with an
in-memory implementation for tests and a Redis implementation for multi-worker
WebSocket fan-out.

## Consequences

- Simple, fast, and genuinely deterministic: each person's RNG is seeded from
  `(run_seed, personnel_index)`, so adding a person does not perturb anyone
  else's trajectory.
- **The API cannot be scaled horizontally as-is** — two workers would run two
  clocks. Real scaling needs leader election or a dedicated engine process.
  This is listed as a limitation in the README rather than hidden.
- Restarting the API stops the simulation. Acceptable for a prototype; the run
  record retains the seed so the run can be replayed.
- Redis is required for correct fan-out across workers, so the WebSocket layer
  behaves identically in tests and in a multi-worker deployment.
