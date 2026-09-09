# ADR 0001 — Async SQLAlchemy 2.0 on PostgreSQL, SQLite for fast tests

**Status:** Accepted

## Context

The simulation engine writes for every person on every tick, and the WebSocket
fan-out reads concurrently. Blocking database calls inside FastAPI's event loop
would stall the whole stream. Separately, the test suite needs to be fast
enough to run constantly.

## Decision

Use SQLAlchemy 2.0's async ORM with `asyncpg` against PostgreSQL 16. Use
`JSONB` freely for structured evidence. Keep the unit tier of the test suite
runnable against `aiosqlite` by avoiding Postgres-only column types in the
mapped classes: UUIDs are `CHAR(36)`, timestamps are timezone-aware
`DateTime`.

## Consequences

- No blocking I/O in request or tick paths.
- Integration tests still need real PostgreSQL, because the audit trigger and
  `JSONB` behaviour cannot be exercised on SQLite. The suite therefore has two
  tiers, and CI provisions Postgres.
- **The database must be UTF-8.** A `SQL_ASCII` cluster accepts bytes that
  later fail to decode out of `JSONB`. This bit us during development and is
  now documented in the README and enforced in the compose init script.
- `CHAR(36)` UUIDs cost storage and index size versus a native `uuid` column.
  Accepted for test portability.
