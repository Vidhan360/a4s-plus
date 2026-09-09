# ADR 0005 — Store tokens in `localStorage` behind a single seam

**Status:** Accepted for prototype only

## Context

The frontend is a Next.js client app talking to a separate FastAPI origin. The
secure option is httpOnly, `Secure`, `SameSite` cookies, which requires
cookie-setting endpoints, CSRF protection, a shared parent domain or a proxy,
and TLS — none of which the prototype has.

## Decision

Store the access and refresh tokens in `localStorage`, confined to
`frontend/src/lib/token-store.ts`. No other file reads a token directly;
`api-client.ts` is the only consumer.

## Consequences

- **An XSS bug would expose a session.** This is stated in the README, in
  `docs/security.md` §11 and on the admin System page.
- Mitigations that are in place: 15-minute access tokens, single-use rotating
  refresh tokens with family revocation on reuse, strict CSP on the API, and
  frame-deny plus nosniff on the frontend.
- Migration cost is genuinely small: rewrite one file, add cookie-setting to
  `/auth/*`, add CSRF tokens. That containment was the reason for accepting the
  trade-off rather than the trade-off being harmless.
