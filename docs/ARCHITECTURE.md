# Architecture & Design Decisions

## High-Level Architecture

```
Raw Data (Cricsheet)
    ↓
Preprocessing (time-correct feature engineering)
    ↓
Feature Store (CSVs with historical snapshots)
    ↓
Model Training (CPU baseline + GPU comparison)
    ↓
Prediction Endpoints (CLI/Flask/Streamlit)
```

---

## Key Design Decisions

### 1. Why Time-Correct Preprocessing?

**Problem**: Using future information in training destroys model validity.

**Solution**: 
- For each match, snapshot all venue/team statistics BEFORE the match
- Only update statistics AFTER the match concludes
- Use these snapshots as features during training

**File**: `scripts/preprocess_ipl.py`

---

### 2. Why Centralize Logic in `common.py`?

**Problem**: 
- Path handling duplicated across `predict_cli.py`, `web_app.py`, `streamlit_app.py`
- Feature building logic drifts between apps
- Model loading logic repeated

**Solution**:
- All paths, aliases, loading, and feature engineering centralized
- Apps import from `ipl_predictor.common`
- Single source of truth for feature contracts

**Benefit**: If you change a feature, all apps update automatically.

---

### 3. Why Separate CPU and GPU Training?

**Problem**: Not all tasks benefit from GPU.

**Solution**:
- CPU baseline (`train_models.py`) → fast, stable reference
- GPU experiments (`train_gpu_best.py`) → compare XGBoost/CatBoost
- Choose best per task, not best per device

**Result**:
- Score: CPU wins (HistGradientBoosting)
- Win probability: GPU wins (CatBoost)

---

### 4. Why Ensemble Strategies?

**Problem**: Single models have blind spots.

**Solution**: `ipl_predictor/ensembles.py` provides:
- Weighted voting
- Stacking wrappers
- Easy model comparison

**File**: `ipl_predictor/ensembles.py`

---

## Feature Engineering Pipeline

### Static Features (computed once)
- Venue par score
- Team/venue/matchup historical form

### Live Match Features (computed per prediction)
- Over number and ball-in-over
- Match phase (Powerplay/Middle/Death)
- Runs vs par
- Required RR pressure
- Innings progress

---

## Model Training Workflow

1. **Preprocess**
   ```powershell
   python scripts/preprocess_ipl.py
   ```
   Creates `data/processed/` CSV files

2. **Baseline Training**
   ```powershell
   python scripts/train_models.py
   ```
   Trains HistGradientBoosting on CPU
   Output: `models/score_model.pkl`, `models/win_model.pkl`

3. **GPU Comparison**
   ```powershell
   python scripts/train_gpu_best.py
   ```
   Trains GPU models, writes report: `models/gpu_model_report.json`
   Allows model selection based on metrics

4. **Model Selection**
   - Copy best GPU model to `models/score_model.pkl` if it wins
   - Copy best GPU model to `models/win_model.pkl` if it wins
   - Or keep CPU baseline if it's better

---

## Data Flow (Example)

```
Raw: "Mumbai Indians vs Chennai Super Kings at Wankhede"
     Overs: 12.3, Runs: 87, Wickets: 2

↓ (Load from common.py)

Features:
  - batting_team_home: 1 (MI typically bats at home)
  - batting_team_form: 158.4 (recent avg)
  - bowling_team_form: 145.2 (CSK concedes this much on avg)
  - venue_par: 157.8
  - over: 12
  - ball_in_over: 3
  - innings_progress: 0.55 (87/157.8)
  - run_rate: 6.7
  - required_rr: 7.4
  - rr_pressure: 0.7
  - match_phase: "Middle"

↓ (Score Model)

Prediction: 158 runs (±25)

↓ (Win Model)

Win Probability: 62%
```

---

## Error Handling

### Missing Team Alias
- Raises `ValueError` with available teams
- Check `ipl_predictor/common.py` TEAM_ALIASES

### Missing Venue Alias
- Raises `ValueError` with available venues
- Check `ipl_predictor/common.py` VENUE_ALIASES

### Missing Models
- Training scripts must be run first
- Run: `python scripts/train_models.py`

### Missing Processed Data
- Preprocessing must be run first
- Run: `python scripts/preprocess_ipl.py`

---

## Code Quality Practices

1. **Avoid Duplicated Logic** → Use `common.py`
2. **Time-Correct Features** → Snapshot, then update
3. **Modular Models** → Train/compare separately
4. **Relative Paths** → Portable across machines
5. **Type Hints** → Explicit contracts
