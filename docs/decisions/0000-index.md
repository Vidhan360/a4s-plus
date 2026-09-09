# Architecture decision records

Short records of the decisions that would otherwise be invisible in the code,
including the ones that turned out to be arguable.

| # | Decision | Status |
|---|---|---|
| [0001](0001-async-sqlalchemy-and-postgres.md) | Async SQLAlchemy 2.0 on PostgreSQL, with SQLite for fast tests | Accepted |
| [0002](0002-datasource-protocol-as-hardware-seam.md) | One `DataSource` abstraction as the only hardware seam | Accepted |
| [0003](0003-permission-based-authorisation.md) | Permission-based authorisation, not role checks | Accepted |
| [0004](0004-lstm-remains-default-despite-losing.md) | Keep the LSTM as the default model although gradient boosting scored higher | Accepted, with reservations |
| [0005](0005-localstorage-token-storage.md) | Store tokens in `localStorage` behind a single seam | Accepted for prototype only |
| [0006](0006-append-only-audit-log.md) | Enforce audit-log immutability with a database trigger | Accepted |
| [0007](0007-no-shap-named-explanation-methods.md) | Name the explanation method actually used; do not ship SHAP | Accepted |
| [0008](0008-refuse-to-predict-without-enough-history.md) | Refuse to predict on short history instead of padding | Accepted |
| [0009](0009-simulation-engine-owns-the-clock.md) | A single in-process simulation engine owns the clock | Accepted, limits scaling |
| [0010](0010-honesty-scan-in-ci.md) | Enforce the honesty disclaimers with a build check | Accepted |
