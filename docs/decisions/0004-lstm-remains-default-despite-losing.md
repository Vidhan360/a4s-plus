# ADR 0004 — Keep the LSTM as the default although gradient boosting scored higher

**Status:** Accepted, with reservations

## Context

Measured on the held-out, subject-disjoint synthetic test split:

| Model | Accuracy | Macro F1 | Elevated F1 | ROC AUC | Brier |
|---|---|---|---|---|---|
| Rule baseline | 0.7474 | 0.7024 | 0.8122 | — | — |
| LSTM | 0.8913 | 0.8770 | 0.9357 | 0.9913 | 0.0370 |
| Gradient boosting | **0.9142** | **0.9024** | **0.9448** | **0.9925** | **0.0363** |

Gradient boosting wins on every headline metric, trains in 17 seconds, and
needs no GPU. The brief also explicitly required a real, trained PyTorch LSTM.

## Decision

Train, evaluate and serve all three. Report the measured numbers including the
loss. Keep `lstm` as the default active model, configurable with
`A4S_ML_ACTIVE_MODEL`, and make the comparison visible in the UI.

## Rationale

1. The gradient booster's advantage comes from the simulator being smooth,
   low-dimensional and short-memory, which is precisely what real sensor data
   is not.
2. Occlusion attributions over a sequence give per-timestep explanation, which
   is what the "WHY THIS RISK?" panel needs to say *when* a trend turned.
3. Both are served and comparable, so the decision is visible and reversible
   with one environment variable.

## Consequences

- The default model is not the most accurate model, and the UI says so.
- **If this were a product decision rather than a prototype, the honest answer
  would be to ship the gradient booster** and keep the LSTM in research until
  real sensor data justifies it. That sentence is in `docs/ml.md` too.
- Re-evaluate as soon as any real data exists.
