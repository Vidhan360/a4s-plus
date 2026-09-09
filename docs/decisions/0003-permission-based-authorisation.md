# ADR 0003 — Permission-based authorisation, not role checks

**Status:** Accepted

## Context

Five roles are required: ADMIN, COMMANDER, MEDICAL_OFFICER, OPERATOR, VIEWER.
The naive implementation is `if user.role in (...)` at each endpoint, which
spreads policy across dozens of files and makes a sixth role a large diff.

## Decision

Endpoints declare **permissions** via a dependency, `require(Perm.X)`. Roles are
bundles of permissions, defined once in `app/core/permissions.py` and mirrored
into the `roles`/`permissions`/`role_permissions` tables for the admin UI and
audit. 36 permissions in total. The frontend renders from
`GET /auth/permissions` rather than from a hard-coded role assumption.

## Consequences

- Adding a role changes one dictionary and no routes.
- Denial happens in a dependency, before the handler and before any database
  access, and writes both an audit row (`result = DENIED`) and a
  `PERMISSION_VIOLATION` security event.
- The `403` body names the missing permission, so the UI can explain instead of
  just refusing.
- Two sources of truth (enum and tables) must stay in step. The seed derives the
  tables from the enum, and a test asserts they match.
- **The frontend mirror is a real risk.** During integration testing the UI was
  found to reference `alert:acknowledge` and `alert:resolve`, which never
  existed in the backend enum — so those buttons could never render. The
  constants file is now an exact mirror and is covered by tests. A generated
  constants file would be better and is not implemented.
