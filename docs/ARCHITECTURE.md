# Architecture

## End-to-End Pipeline

```text
Cricsheet CSV2
  -> preprocessing (feature and support-table build)
  -> model training workflows
  -> promoted deployment artifacts
  -> live inference via CLI / Flask / Streamlit
```

## Core Principles

### 1) Shared inference contract

All live entry points call the same core functions in ipl_predictor/common.py for:

- input validation
- alias normalization
- feature-frame construction
- support-table lookups
- score and win prediction formatting

This avoids frontend drift between CLI, Flask, and Streamlit.

### 2) Time-aware contextual features

Preprocessing computes historical support tables (venue stats, team form, matchup form, player form) used at inference time.

Main preprocessing file:

- scripts/preprocess_ipl.py

### 3) Multiple training workflows

CPU baseline workflow:

- scripts/train_models.py
- Focus: strong and fast baseline refresh
- Produces score_model_hgb and win_model_hgb variants plus baseline reports

GPU comparison workflow:

- scripts/train_gpu_best.py
- Focus: compare CatBoost/XGBoost/ensembles against CPU artifacts on recent active seasons
- Produces gpu_model_report and deployment_report

Best-model search workflow:

- scripts/train_best_model_search.py
- Focus: cross-scope search over classical ML and Torch entity-embedding models
- Scopes: recent_active_history and all_active_history
- Promotes the best scope and model pair into score_model.pkl and win_model.pkl

Pre-match workflow:

- scripts/train_pre_match.py
- Produces dedicated pre-match models for team-vs-team plus venue inference

## Deployment Artifacts

Primary live artifacts:

- models/score_model.pkl
- models/win_model.pkl
- models/score_uncertainty.json

Selection/provenance reports:

- models/deployment_report.json
- models/gpu_model_report.json
- models/best_model_search_report.json

## Frontends

CLI:

- predict_cli.py
- Live prediction only

Flask:

- web_app.py
- Live form, pre-match form, and POST /api/predict

Streamlit:

- streamlit_app.py
- Live prediction flow with interactive analysis widgets

## Supporting Modules

- ipl_predictor/calibration.py: isotonic probability wrapper
- ipl_predictor/ensembles.py: weighted regressor/classifier ensembles
- ipl_predictor/live_data.py: weather context and dew risk helpers
- ipl_predictor/torch_tabular.py: entity-embedding tabular DL models

## SaaS Layer (Current)

The project now includes a secure persistence layer around ML inference:

- Auth: invite-only signup, login/logout, admin role
- DB: SQLAlchemy models for users, matches, predictions, outcomes, model versions, audit logs
- Migrations: Alembic (`alembic/`)
- Validation: Marshmallow request schemas for prediction and outcome payloads
- Protection: route guards, CSRF for forms, and write/login rate limits
- Monitoring: DB-first monitoring read path with compatibility fallback to local files

### Request Lifecycle (API Predict)

1. User authenticates via session.
2. `/api/predict` validates payload schema and cricket constraints.
3. Inference runs through existing feature engineering/model path.
4. Prediction is persisted with user_id, match_id, input payload, output payload, and model version IDs.
5. Monitoring event IDs continue flowing in prediction payloads for drift/outcome linkage.

### Request Lifecycle (Outcome)

1. Admin submits outcome to `/api/monitoring/outcome`.
2. Payload is validated.
3. Outcome row is upserted against stored prediction.
4. Error metrics (score absolute error and win brier error) are computed and persisted.
5. Drift report is recalculated via monitoring subsystem.
