# ADR 0007 — Name the explanation method actually used; do not ship SHAP

**Status:** Accepted

## Context

"Explainable AI" demos routinely show SHAP plots without running SHAP, or
present hand-written feature importances as model output. The brief explicitly
forbids fake SHAP values.

## Decision

Each model reports the method it genuinely uses, and the method name is part of
the API response and the stored prediction row:

| Model | Method | Computation |
|---|---|---|
| Rule baseline | `TRANSPARENT_WEIGHTS` | the engine's own weights and threshold distances — exact |
| LSTM | `OCCLUSION_SENSITIVITY` | 16 extra forward passes, each with one channel replaced by its training mean, measuring the change in the elevated-risk logit |
| Gradient boosting | `IMPURITY_IMPORTANCE` | split-impurity importance aggregated from 80 flattened features back to 16 channels; permutation importance also stored at training time |

`GET /predictions/methods` returns each method's **limitations**, and the UI
displays them. Do not add SHAP unless it is actually run.

## Consequences

- Explanations are weaker than SHAP: occlusion is a single-feature ablation and
  blind to interactions; impurity importance is global rather than local to a
  prediction. Both limitations are shown to the user.
- Explanation costs 16 extra forward passes. Acceptable at prototype scale.
- The `narrative` string is template-generated **from the computed numbers** —
  prose about real values, never a substitute for them.
