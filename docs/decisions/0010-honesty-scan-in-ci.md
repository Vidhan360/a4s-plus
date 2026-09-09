# ADR 0010 — Enforce the honesty disclaimers with a build check

**Status:** Accepted

## Context

The disclaimers ("SOFTWARE PROTOTYPE", "SIMULATED DATA", "NOT CLINICALLY
VALIDATED") and the prohibitions (no "military-grade", no clinical claims) are
the most important properties of this project and the easiest to lose. A
reviewer under time pressure deletes a banner; a future contributor writes
"military-grade encryption" in a marketing paragraph. Documentation alone does
not prevent either.

## Decision

Add `scripts/honesty-scan.sh` plus `scripts/claim_scan.py` and run them as a
`make verify` step and a CI job. They fail the build on:

1. unfinished-work markers (`TODO`, `FIXME`, `XXX`, `HACK`) in shipped source;
2. test-double vocabulary (`mock`, `fake`, `dummy`, `lorem`) outside test files;
3. **unqualified** overclaiming language — `military-grade`, `clinically
   validated`, `medical-grade`, `FDA-approved`, `unhackable`, `100% accurate`,
   `production-ready`;
4. the disappearance of a required disclaimer from `README.md` or
   `frontend/src/lib/constants.ts`.

Check 3 needs care, because the codebase mentions those phrases **in order to
disclaim them**. `claim_scan.py` therefore inspects a two-line window around
each hit for negating language, and carries a short written allowlist for lines
that name a capability precisely to display it as withheld.

## Consequences

- The disclaimers cannot silently regress.
- The check is heuristic: a sufficiently creative overclaim will pass, and a
  legitimate new disclaimer phrasing may need a window or allowlist tweak. The
  allowlist entries each carry a reason so review stays possible.
- Current status: **passing**, with zero `TODO`/`FIXME` in shipped source.
