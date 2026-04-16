# Project Organization Guide

Last updated: 2026-04-15

This document is the single source of truth for:

- folder responsibilities
- script ownership
- training, validation/calibration, and test data splits

## 1) Current Folder Organization

| Path | Purpose | Notes |
| --- | --- | --- |
| data/ipl_csv2 | Raw Cricsheet IPL CSV2 files | Source-of-truth raw data (match + info files) |
| data/processed | Engineered features and support tables | Main training table is data/processed/ipl_features.csv |
| ipl_predictor | Shared package for inference/training helpers | Used by CLI, Flask, Streamlit, and scripts |
| scripts | Data prep, training, and reporting workflows | One script = one workflow entry point |
| scripts/archive | Archived legacy training scripts | Not part of active training flow |
| models | Trained artifacts and evaluation reports | Deployment artifacts and model reports |
| docs | Technical and project documentation | Architecture, API, summaries, report assets |
| notebooks | EDA and analysis notebooks | Exploration only, not production entry points |
| notebooks/archive | Archived experimental notebooks | Kept for historical reference |
| tests | Unit and API tests | Validates inference contract and app behavior |
| templates + static | Flask frontend files | HTML templates and CSS |

## 2) Canonical Data Flow

1. Raw data: data/ipl_csv2
2. Feature engineering: scripts/preprocess_ipl.py -> data/processed/ipl_features.csv + support tables
3. Training workflows: scripts/train_*.py
4. Promotion outputs: models/score_model.pkl + models/win_model.pkl + models/score_uncertainty.json
5. Serving: predict_cli.py, web_app.py, streamlit_app.py

## 3) Training/Test Data Organization (By Script)

### Shared base table

- Main training table: data/processed/ipl_features.csv
- All live-model training scripts are season-aware and split by season (not random row split)

### Split matrix

| Script | Scope before split | Split logic | Typical current season split |
| --- | --- | --- | --- |
| scripts/train_models.py | Active IPL teams, recent seasons window (max(MIN_ACTIVE_TRAIN_YEAR, max_season - 2)) | Score: train vs test by latest seasons. Win: train + calibration + test | Score: train=2024, test=2025-2026. Win: train=2024, calib=2025, test=2026 |
| scripts/train_gpu_best.py | Active IPL teams, recent seasons window | Train/valid/test by latest seasons | train=2024, valid=2025, test=2026 |
| scripts/train_best_model_search.py | Two scopes: recent_active_history and all_active_history | Train/valid/test where valid is second-latest season and test is latest | recent: 2024/2025/2026; all-history: 2007-2024/2025/2026 |
| scripts/train_all_models.py | Active IPL teams, long history (default min year 2007) | Train=all except last 2, valid=second latest, test=latest | train=2007-2024, valid=2025, test=2026 |
| scripts/train_pre_match.py | First-innings, one row per match snapshot | Strict season-based train/valid/test split | train=all except last 2, valid=second latest, test=latest |
| scripts/retrain_and_register.py | Pipeline orchestration | update -> preprocess -> train_best_model_search -> train_pre_match -> registry write | Single-command retraining + version registration |

## 4) Artifact Ownership

| Artifact | Produced by |
| --- | --- |
| models/score_model.pkl | Deployment promotion workflow (currently best-model search result) |
| models/win_model.pkl | Deployment promotion workflow (currently best-model search result) |
| models/score_uncertainty.json | Score training workflows |
| models/cpu_model_report.json | scripts/train_models.py |
| models/gpu_model_report.json | scripts/train_gpu_best.py |
| models/best_model_search_report.json | scripts/train_best_model_search.py |
| models/deployment_report.json | scripts/train_gpu_best.py and/or scripts/train_best_model_search.py (current final deployment source) |
| models/all_models_report.json | scripts/train_all_models.py |
| models/pre_match_model_report.json | scripts/train_pre_match.py |
| models/win_stability_profile.json | scripts/train_best_model_search.py |
| models/production_drift_report.json | ipl_predictor/monitoring.py via prediction logging |
| models/model_registry.json | scripts/retrain_and_register.py |

## 5) Where To Put New Files

- New training or data scripts -> scripts
- Shared reusable code -> ipl_predictor
- Permanent docs -> docs
- Temporary analysis notes -> docs/project-notes
- Experimental notebooks -> notebooks
- Production model artifacts/reports -> models
- Archived scripts/notebooks -> scripts/archive and notebooks/archive

## 6) Notes On Legacy/Compatibility Files

- ipl_colab.csv is a legacy dataset used for earlier EDA and compatibility checks.
- Keep it in place unless all references are explicitly migrated.
