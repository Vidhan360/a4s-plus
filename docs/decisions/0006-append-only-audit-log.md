# ADR 0006 — Enforce audit-log immutability with a database trigger

**Status:** Accepted

## Context

An audit trail that the application can rewrite is not an audit trail. A
convention ("we never update this table") is not enforcement.

## Decision

Write no update or delete path for `audit_logs` in the application, and install
a `BEFORE UPDATE OR DELETE` trigger in migration `45d83b6b3424` that raises.
Additionally attempt to `REVOKE UPDATE, DELETE, TRUNCATE` from the application
role, guarded by the `a4s.app_role` database setting. Expose an `immutability`
block on `GET /api/v1/audit` describing the guarantee, and test that both an
`UPDATE` and a `DELETE` raise.

## Consequences

- The guarantee holds even if application code is later changed carelessly.
- The privilege revocation is **best-effort**: PostgreSQL always lets a table
  owner act on its own table, so it only applies when migrations run as a
  different role. The trigger is the part that always holds. This is documented
  rather than glossed.
- **A superuser can drop the trigger.** Cryptographic hash-chaining or an
  external append-only store would be needed for a stronger guarantee. Not
  implemented.
- Corrections must be made by appending a compensating entry, never by editing.
