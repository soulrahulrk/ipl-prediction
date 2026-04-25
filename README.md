# IPL Prediction

IPL live-state and pre-match prediction system built from Cricsheet IPL ball-by-ball data.

It provides:

- Live innings total projection
- Live batting-side win probability
- Uncertainty bands and simulation-based risk indicators
- Pre-match winner and first-innings range projection
- Flask web app + JSON API
- Streamlit analysis dashboard
- CLI live prediction flow

## Quick Navigation

- docs/PROJECT_ORGANIZATION.md: organized folder map + training/test split rules
- docs/FINAL_PROJECT_SUMMARY.md: simple final summary of what was built, why, and what to improve next
- docs/DATA_SUMMARY.md: detailed dataset and feature reference
- docs/ARCHITECTURE.md: system and workflow architecture
- docs/API.md: live and pre-match API contracts

## Training/Test Data Guide

- For a single source of truth on training, validation, calibration, and test splits across all training scripts, see docs/PROJECT_ORGANIZATION.md.

## Current Deployment Snapshot

Based on `models/deployment_report.json` in this workspace:

- Deployment scope: `all_active_history`
- Promoted score model: `torch_entity_gpu`
- Promoted win model: `catboost_gpu_calibrated`

Held-out metrics in that report:

- Score MAE: `15.36`
- Score RMSE: `19.81`
- Win log loss: `0.4922`
- Win Brier: `0.1681`
- Win accuracy: `0.6712`

## Main Files

- `ipl_predictor/common.py`: shared feature engineering, validation, inference, pre-match helpers
- `ipl_predictor/live_data.py`: weather fetch and dew-risk estimation
- `ipl_predictor/calibration.py`: isotonic calibration wrapper
- `ipl_predictor/ensembles.py`: weighted regressor/classifier ensembles
- `ipl_predictor/torch_tabular.py`: deep tabular entity-embedding models
- `ipl_predictor/online_learning.py`: feedback logging and optional fine-tuning hooks
- `scripts/preprocess_ipl.py`: converts raw Cricsheet data into model-ready tables
- `scripts/update_external_data.py`: downloads latest IPL CSV2 zip + weather snapshot
- `scripts/train_models.py`: CPU baseline training and reports
- `scripts/train_gpu_best.py`: GPU CatBoost/XGBoost comparison and promotion
- `scripts/train_best_model_search.py`: broader GPU ML + DL search over scopes
- `scripts/train_all_models.py`: model-family benchmark used by Streamlit model comparison tab
- `scripts/train_pre_match.py`: dedicated pre-match model training
- `scripts/retrain_and_register.py`: end-to-end retrain orchestration + artifact/version registry entry
- `web_app.py`: Flask app (live + pre-match form + `/api/predict`)
- `streamlit_app.py`: interactive dashboard with model comparison and feedback panel
- `predict_cli.py`: terminal live prediction client

## Workspace Management (Clean Layout)

Keep these as the main top-level runnable files:

- `web_app.py`
- `streamlit_app.py`
- `predict_cli.py`

Keep generated outputs grouped in dedicated folders:

- `docs/reports/`: generated DOCX project reports
- `docs/report_assets/`: generated report figures/images
- `data/processed/`: generated feature/support tables
- `models/`: active deployment artifacts and evaluation reports
- `models/archive/`: archived/older artifacts and optional training logs

Quick PowerShell cleanup for temporary clutter:

```powershell
Get-ChildItem -Path . -Directory -Filter __pycache__ -Recurse -Force |
  Where-Object { $_.FullName -notlike "*\.venv\*" } |
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Get-ChildItem -Path . -Directory -Filter .pytest_cache -Recurse -Force |
  Where-Object { $_.FullName -notlike "*\.venv\*" } |
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Remove-Item "docs\~$*.docx" -Force -ErrorAction SilentlyContinue
```

## Data Layout

Raw source:

- `data/ipl_csv2/`
- Cricsheet source zip: <https://cricsheet.org/downloads/ipl_csv2.zip>

Generated processed tables (core):

- `data/processed/ipl_features.csv`
- `data/processed/venue_stats.csv`
- `data/processed/team_form_latest.csv`
- `data/processed/team_venue_form_latest.csv`
- `data/processed/matchup_form_latest.csv`
- `data/processed/batter_form_latest.csv`
- `data/processed/bowler_form_latest.csv`
- `data/processed/batter_bowler_form_latest.csv`
- `data/processed/active_teams_2026.csv`
- `data/processed/team_player_pool_2026.csv`
- `data/processed/live_weather_snapshot.json`

## Setup

### 1) Create and activate venv (PowerShell)

```powershell
python -m venv .venv
& .\.venv\Scripts\Activate.ps1
```

### 2) Install dependencies

```powershell
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Optional DL dependency for Torch-based workflows:

- Install PyTorch for your CPU/CUDA target before running DL search workflows.

## Typical Workflow

### A) Refresh external data

```powershell
& .\.venv\Scripts\python.exe scripts\update_external_data.py
```

This downloads latest IPL CSV2 files and writes weather snapshot data.

### B) Rebuild processed features

```powershell
& .\.venv\Scripts\python.exe scripts\preprocess_ipl.py
```

### C) Train or refresh models (pick one)

CPU baseline:

```powershell
& .\.venv\Scripts\python.exe scripts\train_models.py
```

GPU CatBoost/XGBoost comparison and deployment report:

```powershell
& .\.venv\Scripts\python.exe scripts\train_gpu_best.py
```

Broader best-model search across scopes and model families (includes Torch models):

```powershell
& .\.venv\Scripts\python.exe scripts\train_best_model_search.py
```

Comprehensive model benchmark used by Streamlit model tab (`*_2.pkl` artifacts + report):

```powershell
& .\.venv\Scripts\python.exe scripts\train_all_models.py
```

Pre-match model training:

```powershell
& .\.venv\Scripts\python.exe scripts\train_pre_match.py
```

### D) Automated retrain + registry

```powershell
& .\.venv\Scripts\python.exe scripts\retrain_and_register.py
```

Useful flags:

- `--skip-update`: skip external data refresh
- `--skip-pre-match`: skip pre-match retraining in that run

### E) Generate project reports

```powershell
& .\.venv\Scripts\python.exe scripts\generate_project_report.py
& .\.venv\Scripts\python.exe scripts\generate_project_report_refined.py
```

Report outputs:

- `docs/reports/IPL_Prediction_Project_Report.docx`
- `docs/reports/IPL_Prediction_Project_Report_Refined.docx`

## Produced Artifacts

Primary live deployment artifacts:

- `models/score_model.pkl`
- `models/win_model.pkl`
- `models/score_uncertainty.json`

Pre-match artifacts:

- `models/pre_match_score_model.pkl`
- `models/pre_match_win_model.pkl`
- `models/pre_match_model_report.json`

Reports:

- `models/cpu_model_report.json`
- `models/gpu_model_report.json`
- `models/deployment_report.json`
- `models/best_model_search_report.json`
- `models/best_score_test_predictions.csv`
- `models/best_win_test_predictions.csv`
- `models/win_stability_profile.json`
- `models/production_drift_report.json`
- `models/model_registry.json`

Streamlit benchmark report (when using `train_all_models.py`):

- `models/all_models_report.json`

Generated project reports:

- `docs/reports/IPL_Prediction_Project_Report.docx`
- `docs/reports/IPL_Prediction_Project_Report_Refined.docx`

## Run Interfaces

Flask app (live + pre-match + API):

```powershell
& .\.venv\Scripts\python.exe web_app.py
```

Open: <http://127.0.0.1:5000>

Streamlit dashboard:

```powershell
& .\.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

CLI live prediction:

```powershell
& .\.venv\Scripts\python.exe predict_cli.py
```

## Publish On GitHub + Make It Live

### 1) Push to GitHub

If this is your first push for this project:

```powershell
git init
git add .
git commit -m "Initial commit: IPL prediction system"
git branch -M main
git remote add origin https://github.com/<your-username>/ipl-prediction.git
git push -u origin main
```

For later updates:

```powershell
git add .
git commit -m "Update: <short description>"
git push
```

### 2) Deploy Streamlit Dashboard (fastest)

Use Streamlit Community Cloud:

1. Make the repository public on GitHub.
2. Go to <https://share.streamlit.io> and sign in with GitHub.
3. Select repository and branch.
4. Set app file path to `streamlit_app.py`.
5. Click Deploy.

Before deploying, make sure model artifacts are committed to `models/`:

- `models/pre_match_score_model.pkl`
- `models/pre_match_win_model.pkl`
- `models/score_model.pkl`
- `models/win_model.pkl`

### 3) Deploy Flask API/Web App (Render)

Use Render (<https://render.com>):

1. New Web Service -> connect your GitHub repository.
2. Environment: Python.
3. Build Command:

```bash
pip install -r requirements.txt
```

4. Start Command:

```bash
gunicorn web_app:app
```

`web_app.py` is configured to use host `0.0.0.0` and Render's `PORT`.

### 4) Recommended retrain pipeline before deployment

Use Cricsheet pipeline end-to-end before making a release:

```powershell
& .\.venv\Scripts\python.exe scripts\update_external_data.py
& .\.venv\Scripts\python.exe scripts\preprocess_ipl.py
& .\.venv\Scripts\python.exe scripts\train_pre_match.py
& .\.venv\Scripts\python.exe scripts\train_all_models.py --quick
```

### 5) Version compatibility note

Saved sklearn pipelines in this repo are currently aligned to `scikit-learn 1.7.x`.
If deploying on a new platform, ensure the environment installs the pinned range from `requirements.txt`.

## API

Endpoint:

- `POST /api/predict`
- `GET /api/monitoring`

Minimal JSON payload:

```json
{
  "season": "2026",
  "venue": "Wankhede Stadium",
  "batting_team": "Mumbai Indians",
  "bowling_team": "Chennai Super Kings",
  "innings": 1,
  "runs": 92,
  "wickets": 2,
  "overs": "10.2"
}
```

Example success response (fields truncated):

```json
{
  "ok": true,
  "prediction": {
    "predicted_total": "171.2",
    "win_prob": "0.738",
    "win_prob_pct": "73.8%",
    "projected_range": "155-186"
  }
}
```

## Tests

```powershell
& .\.venv\Scripts\python.exe -m pytest -q
```

Notes:

- Tests that depend on model artifacts are skipped automatically when artifacts are missing.
- Regression guard tests in `tests/test_regression_metrics.py` fail when key deployment metrics degrade.

## Implementation Notes

- `predict_match_state` in `ipl_predictor/common.py` is the shared live inference path.
- `score_uncertainty.json` is used for projected range and simulation spread.
- Cricsheet `*_info.csv` rows can have variable field counts; parser logic in preprocessing uses `csv.reader` accordingly.
- Keep `scikit-learn` in `1.7.x` range for compatibility with saved sklearn pipelines.
