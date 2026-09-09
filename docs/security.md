# A4S+ — Security

> **Framing.** A4S+ is a software prototype. This document states what is
> actually implemented, what is demonstrated, and what is missing. The phrase
> "military-grade" is not used to describe anything here, because it is a
> marketing phrase rather than a specification. `scripts/honesty-scan.sh` fails
> the build if that phrase or a clinical-validation claim ever appears
> unqualified.

## 1. Three concerns, deliberately kept apart

A common way to mislead is to blur these together. In this codebase they are
three separate modules and are described separately everywhere:

| Concern | Where | Status |
|---|---|---|
| **Application authentication** | `app/core/security.py` — Argon2id + JWT | Implemented |
| **Transport security** | TLS, terminated by the deployment's reverse proxy | Out of scope; not configured in the compose stack |
| **Demonstration encryption** | `app/services/crypto_service.py` — AES-256-GCM for the Security Monitor UI | Demonstration only |

The crypto demonstration is **not** what protects data in this application, and
the UI says so on the panel itself.

## 2. Threat model (prototype scope)

In scope:

1. Credential attacks — guessing, stuffing, brute force.
2. Session attacks — token theft, replay of a refresh token.
3. Authorisation bypass — a low-privilege user reaching a privileged operation.
4. Input abuse — malformed or hostile payloads, injection.
5. Repudiation — a privileged action later denied or quietly erased.
6. Simulated operational attacks — RF jamming and navigation spoofing against
   the simulated UAV relay, as a resilience exercise.

Explicitly out of scope: network-level attack, host compromise, supply-chain
attack, insider with database superuser rights, physical access, and anything
requiring real radio hardware.

## 3. Authentication

**Password hashing.** Argon2id via `argon2-cffi`, `time_cost=3`,
`memory_cost=65536` (64 MiB), `parallelism=4`, `hash_len=32`, `salt_len=16`.
Argon2id was chosen over bcrypt for GPU-resistance; the parameters are the
`argon2-cffi` recommended profile. Password policy: minimum 12 characters,
enforced by Pydantic at the schema boundary so it cannot be bypassed by a
different code path.

**Access tokens.** HS256 JWTs, 15-minute lifetime, carrying subject, roles and
permission claims. Verified on every request; issuer, type and expiry are all
checked, not just the signature.

**Refresh tokens.** Opaque random values, **stored only as SHA-256 hashes**, in
a `refresh_tokens` row carrying a `family_id`, `expires_at`, `revoked_at` and
`rotated_to_id`. 7-day lifetime. Every refresh:

1. hashes the presented token and looks it up;
2. if it is already revoked → **the entire token family is revoked**, a
   `TOKEN_REUSE_DETECTED` security event is written, and the caller gets
   `401 token_reuse`;
3. otherwise it is revoked, a successor is issued, and `rotated_to_id` links
   them.

That rotation-with-family-revocation is what turns a stolen refresh token from
"indefinite access" into "one use, then both sessions die loudly".

**Account lockout.** `failed_login_count` increments on each failure; after 5
(`A4S_MAX_FAILED_LOGINS`) the account locks for 15 minutes
(`A4S_LOCKOUT_MINUTES`), an `ACCOUNT_LOCKOUT` security event is recorded, and
the login response says the account is locked. An admin can clear it with
`POST /users/{id}/unlock`. Successful login resets the counter.

**Password change** revokes every other session for that user.

## 4. Authorisation — permissions, not roles

Routes require **permissions**. Roles are bundles of permissions. This matters
in practice: adding a sixth role requires no route changes and no frontend
changes, because the UI renders from `GET /auth/permissions`.

```python
@router.post("/{personnel_id}/run")
async def run_prediction(
    actor: Annotated[Any, require(Perm.PREDICTION_RUN)],
    ...
```

36 permissions, 5 roles:

| Role | Scope |
|---|---|
| `ADMIN` | Every permission, including `user:write` and `config:write` |
| `COMMANDER` | All reads, plus `simulation:control`, `route:plan`, `drone:command`, `alert:ack`, `prediction:run` |
| `MEDICAL_OFFICER` | Personnel, vitals, health, twin, prediction, alert acknowledge |
| `OPERATOR` | Terrain, routes, UAV command, `security:simulate` |
| `VIEWER` | Read-only |

Enforcement facts worth stating:

- The check happens in a FastAPI dependency, **before the handler runs**, so a
  denied request never touches business logic or the database.
- A denial writes a `PERMISSION_VIOLATION` security event and an audit row with
  `result = DENIED`.
- The `403` body names the missing permission, so the UI can explain rather
  than just refuse.
- WebSocket topics are gated by the same permissions, so a `VIEWER` cannot
  subscribe to a stream they cannot fetch over REST.
- The frontend's permission constants mirror the backend `Perm` enum exactly.
  A mismatch here was a real bug found during integration testing: the UI
  referenced `alert:acknowledge` and `alert:resolve`, which never existed, so
  the acknowledge and resolve buttons could never render. The permission list
  is now a single mirrored source and is covered by tests.

## 5. Input validation

Every request body, query parameter and path parameter is a Pydantic v2 model
with bounds — `spo2` 50–100, `heart_rate` 20–250, grid coordinates 0–4096,
`limit` 1–200, enum-typed filters. Invalid enum filter values return **422**
rather than being silently ignored, which is the difference between a filter
that works and one that quietly returns everything.

Database access is exclusively through SQLAlchemy 2.0 parameterised
constructs inside `app/repositories/`, and no endpoint accepts a raw
identifier, column name or ordering expression.

Responses are serialised through explicit response models, so an ORM object
cannot leak internal fields. (This was also a real bug found in testing:
`GET /personnel/{id}` returned raw `HealthAlert` ORM objects inside
`open_alerts` and 500'd. It is now `AlertOut.model_validate(...)` per row, with
a regression test.)

## 6. Rate limiting

SlowAPI with a Redis backend, per client IP:

| Route | Limit |
|---|---|
| `POST /auth/login` | 10/minute |
| `POST /auth/refresh` | 30/minute |
| `POST /auth/change-password` | 5/minute |
| everything else | 200/minute |

Exceeding a limit returns **429** with `Retry-After`. Redis rather than
in-process counters so the limit survives multiple workers.

## 7. Audit trail

Every state-changing request writes an `audit_logs` row: actor id **and**
denormalised actor email (so the trail survives user deletion), action,
resource type and id, result (`SUCCESS` / `DENIED` / `ERROR`), IP, user agent,
correlating `request_id`, and a `meta` JSONB payload.

**Append-only, enforced in the database** by a `BEFORE UPDATE OR DELETE`
trigger that raises. The application has no update or delete path for the
table, and the migration additionally attempts to revoke `UPDATE, DELETE,
TRUNCATE` from the application role. `GET /api/v1/audit` returns an
`immutability` block describing the guarantee, and an integration test asserts
that both an `UPDATE` and a `DELETE` raise.

**Honest limit:** a database superuser can drop the trigger. Cryptographic
hash-chaining or shipping to an external append-only store would be needed for
a stronger guarantee. Neither is implemented.

## 8. Security monitoring

`security_events` records both genuine detections and injected demonstrations,
distinguished by **`origin`** (`SYSTEM` vs `INJECTED`) — without that column a
demo injection would be indistinguishable from a real detection.

Automatically recorded by the application: `FAILED_LOGIN`,
`ACCOUNT_LOCKOUT`, `PERMISSION_VIOLATION`, `INVALID_TOKEN`,
`TOKEN_REUSE_DETECTED`. Each carries a `response_action` describing what the
system actually did, e.g. *"Request denied with HTTP 403 before reaching any
handler. No data was returned."*

Injectable for demonstration (`POST /security/inject`, requires
`security:simulate`): `jamming`, `spoofing`, `intrusion`, `suspicious_api`.
Every injected description states in its own text that it is a software
simulation and that no radio, receiver or credential was involved.

`GET /security/catalogue` returns the control list with an explicit status per
control — `IMPLEMENTED`, `DEMONSTRATION_ONLY`, `OUT_OF_SCOPE` or
`NOT_IMPLEMENTED` — and the UI renders those statuses verbatim.

## 9. Authenticated Encryption Demonstration

`POST /security/crypto-demo` (requires `crypto:demo`) runs **AES-256-GCM** from
the `cryptography` library (OpenSSL-backed; no primitive is hand-rolled) over
text the user supplies:

- 256-bit key derived per request with HKDF-SHA256 and **never persisted**;
- 96-bit random nonce per operation;
- returns ciphertext, nonce and authentication tag, then decrypts to prove the
  round trip;
- **then flips a bit and shows the decryption failing** with `InvalidTag` —
  which is the actually interesting part, because it demonstrates integrity,
  not just confidentiality.

What it is not, stated on the panel: not the transport or storage encryption of
this prototype (application data is stored **unencrypted at rest** in
PostgreSQL), not a key-management system, and not "military-grade" anything.

## 10. HTTP hardening

**API responses** (`app/core/middleware.py`): `X-Content-Type-Options: nosniff`,
`X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`,
`Cross-Origin-Opener-Policy: same-origin`,
`Permissions-Policy: geolocation=(), microphone=(), camera=()`, and
`Content-Security-Policy: default-src 'none'; frame-ancestors 'none'; base-uri
'none'` — safe to be that strict because the API serves only JSON. HSTS
(`max-age=31536000; includeSubDomains`) is added when the environment is
production.

**Frontend responses** (`next.config.mjs`): frame-deny, nosniff, referrer
policy, permissions policy, and `poweredByHeader: false`.

**CORS** is restricted to `A4S_CORS_ORIGINS`; there is no wildcard, and
credentials are not sent cross-origin.

**Configuration safety:** `core/config.py` refuses to boot in a production
environment with a development JWT secret, and seeding fails loudly if the
`A4S_SEED_*` passwords are unset rather than inventing a default credential.

## 11. Known weaknesses (the list we are not burying)

1. **Tokens in `localStorage`.** An XSS bug would expose a session. The
   trade-off was taken for prototype simplicity, and it is confined to a single
   seam: `frontend/src/lib/token-store.ts`. Moving to httpOnly, `Secure`,
   `SameSite` cookies with CSRF protection means rewriting that one file plus
   adding a cookie-setting path in `/auth/*`. Nothing else in the frontend
   reads a token directly.
2. **No data-at-rest encryption.** Vitals, personnel records and audit rows are
   stored in plaintext columns.
3. **No secret management.** Secrets come from environment variables; there is
   no KMS, vault or rotation.
4. **No MFA.** Password plus token only.
5. **No TLS in the stack.** HTTPS is assumed to be terminated upstream and is
   not configured in the compose files.
6. **Audit immutability is trigger-based**, not cryptographic (§7).
7. **Rate limiting is per-IP**, so it is defeated by a distributed source and
   can over-block a shared NAT.
8. **JWTs are not revocable before expiry.** Logout revokes the refresh family,
   but an already-issued access token remains valid for up to 15 minutes. A
   deny-list in Redis would fix this and is not implemented.
9. **Dependency scanning is CI-only** (`npm audit`, currently 0
   vulnerabilities); there is no runtime SCA or SBOM.
10. **No penetration test.** Nothing here has been externally reviewed.

## 12. What is tested

The backend suite covers: Argon2id hashing and verification, JWT issuance and
tampering, refresh rotation, refresh **reuse revoking the family**, lockout
after the configured threshold and unlock, permission enforcement on
representative endpoints for all five roles, `403` bodies naming the
permission, WebSocket rejection with close code **4401**, rate-limit `429`
behaviour, audit rows written for denials, the append-only trigger rejecting
`UPDATE` and `DELETE`, and the AES-256-GCM round trip **plus** the
tamper-detection failure path.

The Playwright suite additionally verifies RBAC from the user's side: signing in
as each of the five roles and asserting that forbidden navigation and actions
are genuinely absent, not merely hidden.
