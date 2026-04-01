# IPL Prediction Tool

This project builds an IPL live-match prediction system from Cricsheet ball-by-ball data.

It currently predicts:
- Final innings total
- Uncertainty-aware score range (quantile residuals + simulation)
- Batting-team win probability
- Win probability band from simulation
- Match phase (`Powerplay`, `Middle`, `Death`)
- Venue par score for the innings
- Runs vs par
- Target remaining in a chase
- Required-RR pressure (`required RR - current RR`)

The project includes:
- Data ingestion from Cricsheet IPL CSV2 files (2008 to March 30, 2026)
- Historical-only feature engineering for live match state
- CPU baseline training for score prediction
- GPU-first training for win prediction on RTX 3050
- Probability calibration tracking (raw vs calibrated)
- Slice-wise evaluation by phase / innings / wickets bucket
- CLI, Flask, and Streamlit frontends

---

## Latest April 2026 Updates

- Streamlit UI redesigned for layman-friendly use:
  - fewer mandatory inputs
  - smart defaults for optional match context
  - plain-language result cards (winner chance, score range, pressure)
- Added simulation-facing outputs in UI:
  - score distribution snapshot
  - collapse risk and big-finish chance
- Added external model benchmark check against Hugging Face model:
  - tested `pdp19/ipl_match_winner_predictor` on IPL live-state rows
  - local win model performed significantly better on all key metrics

---

## What We Updated And Why

### 1) Fixed venue-stat leakage
Before the update, venue averages were computed from the full dataset and then used for older matches too.

Why this was a problem:
- It leaked future information into training rows.
- It made backtests look better than a real live prediction setup.

What changed:
- `scripts/preprocess_ipl.py` now snapshots venue stats before each match and only then updates them after the match.

Reason:
- A live prediction model should only use information that would have been available at that time.

### 2) Moved shared prediction logic into one module
Before the update, path handling, aliases, parsing, and feature-building logic were duplicated across:
- `predict_cli.py`
- `web_app.py`
- `streamlit_app.py`

What changed:
- Shared logic now lives in `ipl_predictor/common.py`.

Reason:
- Prevents code drift.
- Keeps CLI, Flask, and Streamlit using the same features and model inputs.
- Makes future feature additions much safer.

### 3) Removed machine-specific paths
Before the update, scripts used absolute Windows paths tied to one laptop.

What changed:
- Paths are now resolved relative to the repo.

Reason:
- The project is portable now.
- You can move the folder, clone it elsewhere, or run it on another machine without rewriting paths.

### 4) Added repo hygiene
What changed:
- Added `.gitignore`
- Added `requirements.txt`
- Added `pyproject.toml`

Reason:
- Keeps `.venv`, generated models, and processed artifacts out of source control.
- Makes the environment reproducible.

### 5) Added stronger cricket features
The project now uses richer features such as:
- Wickets left
- Legal balls bowled
- Innings progress
- Over number and ball-in-over
- Match phase
- Target remaining
- Required RR minus current RR
- Current RR minus required RR
- Runs vs venue par
- Batting team vs bowling team historical matchup form
- Last-6 and last-12 legal-ball momentum features
- Phase indicator flags (`is_powerplay`, `is_middle`, `is_death`)

Reason:
- These features reflect real live-match pressure better than only runs, wickets, and overs.
- They usually help tabular models more than switching blindly to deep learning.

### 6) Added GPU-first model training
What changed:
- Added `scripts/train_gpu_best.py`
- Added `ipl_predictor/ensembles.py`

Reason:
- Your RTX 3050 should be used where it actually helps.
- In this project, GPU boosting is useful, but only for some targets.

---

## Best Model Choice Right Now

After running the updated pipeline on this repo:

### Score prediction
Best current choice:
- `HistGradientBoostingRegressor` on CPU

Reason:
- It beat the GPU boosters on held-out score regression in this project.
- Final-score prediction here is still best handled by the CPU baseline.

Latest baseline score metrics:
- `MAE: 18.47`
- `RMSE: 25.01`

### Win probability
Best current choice:
- `CatBoostClassifier` on GPU

Reason:
- It beat the CPU baseline on held-out win-probability prediction.
- This is the best place to use the RTX 3050 in the current repo.

Latest GPU win metrics:
- `Log loss: 0.547`
- `Brier: 0.186`
- `Accuracy: 0.701`

### Current default deployment setup
The app now uses the best model per task:
- `models/score_model.pkl` -> CPU baseline score model
- `models/win_model.pkl` -> GPU CatBoost win model

Reason:
- "Use GPU everywhere" is not the goal.
- "Use the best model for each target" is the goal.

---

## Why Not Deep Learning Right Now

Deep learning is not the best default choice for this project yet.

Reason:
- Your current data is mostly structured tabular match-state data.
- For this kind of problem, CatBoost/XGBoost/HistGradientBoosting usually beat generic neural networks.
- Deep learning becomes more useful only if you add richer sequence and player-level data.

Deep learning may become worth trying later if you add:
- Batter-by-batter recent form
- Bowler spell history
- Batter-vs-bowler matchup sequences
- Playing XI strength
- Venue + weather + dew context
- Ball sequence models instead of only snapshot features

---

## Project Structure

- `ipl_predictor/common.py`
  Centralized paths, aliases, support-table loading, feature building, and prediction helpers.

- `ipl_predictor/ensembles.py`
  Simple weighted ensemble wrappers for model comparison.

- `scripts/preprocess_ipl.py`
  Builds processed training rows and historical support tables.

- `scripts/train_models.py`
  Trains the CPU baseline models.

- `scripts/train_boosting_compare.py`
  Compares XGBoost and CatBoost against the updated feature set.

- `scripts/train_gpu_best.py`
  GPU-first training workflow for CatBoost/XGBoost and a held-out comparison report.

- `predict_cli.py`
  CLI prediction interface.

- `web_app.py`
  Flask app.

- `streamlit_app.py`
  Streamlit app.

---

## Data Pipeline

### 1) Raw data
Stored in:
- `data/ipl_csv2/`

Source:
- https://cricsheet.org/downloads/ipl_csv2.zip

Why this source:
- Standardized ball-by-ball structure
- Match metadata included
- Easy to update each season

### 2) Processed outputs
Generated by `scripts/preprocess_ipl.py`:
- `data/processed/ipl_features.csv`
- `data/processed/venue_stats.csv`
- `data/processed/team_form_latest.csv`
- `data/processed/team_venue_form_latest.csv`
- `data/processed/matchup_form_latest.csv`
- `data/processed/batter_form_latest.csv`
- `data/processed/bowler_form_latest.csv`
- `data/processed/batter_bowler_form_latest.csv`

Why these support tables exist:
- `venue_stats.csv`: historical venue scoring context
- `team_form_latest.csv`: recent team strength
- `team_venue_form_latest.csv`: team performance at specific grounds
- `matchup_form_latest.csv`: team-vs-team history

---

## Training Workflows

### CPU baseline
Run:
```powershell
& .\.venv\Scripts\python.exe scripts\train_models.py
```

What it does:
- Trains the baseline score model
- Trains the baseline win model
- Saves uncertainty profile from held-out residuals:
  - `models/score_uncertainty.json`
- Saves evaluation report:
  - `models/cpu_model_report.json`
- Saves backup baseline artifacts:
  - `models/score_model_hgb.pkl`
  - `models/win_model_hgb.pkl`

Why keep this:
- Strong, stable, and fast baseline for tabular data

### GPU-first training
Run:
```powershell
& .\.venv\Scripts\python.exe scripts\train_gpu_best.py
```

What it does:
- Trains CatBoost and XGBoost candidates
- Trains optional calibrated win variants using validation probabilities
- Evaluates them on held-out seasons (overall + by phase/innings/wickets bucket)
- Compares score candidates against CPU HGB baseline when available
- Writes a comparison report:
  - `models/gpu_model_report.json`
- Saves GPU artifacts:
  - `models/score_model_gpu_cat.pkl`
  - `models/score_model_gpu_xgb.pkl`
  - `models/score_model_gpu_ensemble.pkl`
  - `models/win_model_gpu_cat.pkl`
  - `models/win_model_gpu_xgb.pkl`
  - `models/win_model_gpu_ensemble.pkl`
  - `models/win_model_gpu_cat_calibrated.pkl`
  - `models/win_model_gpu_xgb_calibrated.pkl`
  - `models/win_model_gpu_ensemble_calibrated.pkl`

Why this exists:
- Lets the laptop GPU help where it actually improves real metrics
- Keeps experiments separate from the baseline flow

---

## Running The Apps

### Streamlit
Run:
```powershell
& .\.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

Why use it:
- Fastest way to test the model interactively
- Best for non-technical users because it has a simplified input flow

### Flask
Run:
```powershell
& .\.venv\Scripts\python.exe web_app.py
```

Open:
- `http://127.0.0.1:5000`

Why use it:
- Lightweight browser UI

### CLI
Run:
```powershell
& .\.venv\Scripts\python.exe predict_cli.py
```

Why use it:
- Fast manual testing without opening a browser

### Safety checks
Run:
```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_common.py -q
```

What it validates:
- venue-stat snapshot leakage behavior
- alias normalization
- feature-column consistency between inference and model schema
- model loading + prediction path smoke checks

---

## External Benchmark (Hugging Face vs Local)

Compared model:
- `pdp19/ipl_match_winner_predictor` (Transformers text-classification pipeline)

Evaluation setup:
- 600 sampled rows from held-out IPL live match-state data
- same rows used for both models

Results:
- Local `models/win_model.pkl`
  - Accuracy: `0.683`
  - Log loss: `0.574`
  - Brier score: `0.199`
- Hugging Face `pdp19/ipl_match_winner_predictor`
  - Accuracy: `0.513`
  - Log loss: `3.239`
  - Brier score: `0.466`

Conclusion:
- Local win model is clearly better for this repository's live IPL binary win-probability task.
- The Hugging Face model exposes multi-class labels (`LABEL_0` to `LABEL_9`), which are not directly aligned with this binary prediction target.

---

## Publish To GitHub

Current remote repository:
- `https://github.com/soulrahulrk/ipl-prediction`

To push future updates:

```powershell
git add .
git commit -m "Update project"
git push -u origin main
```

If prompted, use GitHub credentials/token with repo write access.

---

## Repository File Management

To keep the project clean, remove generated runtime folders regularly:

```powershell
Remove-Item -LiteralPath "__pycache__" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath ".pytest_cache" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath "catboost_info" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath "logs" -Recurse -Force -ErrorAction SilentlyContinue
```

Folders you should treat as generated/temporary:
- `__pycache__/`
- `.pytest_cache/`
- `catboost_info/`
- `logs/`

Persistent project folders:
- `data/ipl_csv2/` (raw source data)
- `data/processed/` (generated features/support tables)
- `models/` (active model artifacts)
- `scripts/` (pipeline and training commands)
- `ipl_predictor/` (shared core logic)

---

## Recommended Workflow

If you add new seasons or new raw data:

1. Rebuild features
```powershell
& .\.venv\Scripts\python.exe scripts\preprocess_ipl.py
```

2. Re-train the CPU baseline
```powershell
& .\.venv\Scripts\python.exe scripts\train_models.py
```

3. Re-run the GPU comparison
```powershell
& .\.venv\Scripts\python.exe scripts\train_gpu_best.py
```

4. Launch Streamlit
```powershell
& .\.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

---

## Best Next Upgrades

If you want the next real jump in quality, add:

1. Player-level features
Reason:
- Batter form, bowler form, and batter-vs-bowler history are more informative than only team-level signals.

2. Playing-XI strength
Reason:
- Today's actual lineup matters more than a season-average team label.

3. Match-condition features
Reason:
- Dew, day/night effect, and venue recency can influence chases and scoring.

4. Separate specialist models
Reason:
- First-innings score prediction and second-innings chase prediction are different problems and benefit from separate tuning.

5. Lineup-strength modeling from full playing XI
Reason:
- The current build includes player context but not a dedicated learned XI-strength feature.

6. Venue-time weather lag features
Reason:
- Current weather is integrated at inference; lagged historical weather by venue/date can further improve stability.

---

## Quick Start

```powershell
& .\.venv\Scripts\python.exe scripts\preprocess_ipl.py
& .\.venv\Scripts\python.exe scripts\train_models.py
& .\.venv\Scripts\python.exe scripts\train_gpu_best.py
& .\.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```
