# ADR 0008 — Refuse to predict on short history instead of padding

**Status:** Accepted

## Context

The LSTM needs 24 timesteps. A newly added person, or one whose device has just
come online, has fewer. The convenient options are zero-padding, edge-padding or
repeating the first reading — all of which produce a confident-looking number
from data that does not exist.

## Decision

Return an explicit insufficient-history response naming how many readings exist
and how many are needed. No padding, no extrapolation, no fallback guess.

## Consequences

- A fresh demo shows "insufficient history" until enough ticks have elapsed,
  which is why `seeds.seed --history 90` exists and why the demo guide
  recommends it.
- The behaviour is exactly what a real deployment with sensor dropouts needs,
  so this is a feature rather than a limitation.
- Callers must handle the case; the frontend has a designed state for it rather
  than an empty chart.
