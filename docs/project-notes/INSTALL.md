# Installation & Setup Guide

## Prerequisites

- **Python**: 3.11 or higher
- **pip**: Latest version
- **Virtual Environment**: Recommended (venv, conda, etc.)
- **GPU** (Optional): RTX 3050 or better for GPU-accelerated training

---

## Quick Start (5 Minutes)

### 1. Clone or Extract Project
```powershell
cd c:\Users\rahul\Documents\code\projects\ipl prediction
```

### 2. Create Virtual Environment
```powershell
python -m venv .venv
```

### 3. Activate Virtual Environment
```powershell
& .\.venv\Scripts\Activate.ps1
```

### 4. Install Dependencies
```powershell
pip install -r requirements.txt
```

Or using `pyproject.toml`:
```powershell
pip install -e .
```

### 5. Verify Installation
```powershell
python -c "import ipl_predictor; print('✓ IPL Predictor installed successfully')"
```

---

## Setting Up From Scratch

### Step 1: Environment Setup

```powershell
# Create virtual environment
python -m venv .venv

# Activate it
& .\.venv\Scripts\Activate.ps1

# Upgrade pip
python -m pip install --upgrade pip
```

### Step 2: Install Dependencies

```powershell
# Core packages
pip install pandas scikit-learn joblib

# Web frameworks
pip install Flask streamlit

# Boosting libraries
pip install xgboost catboost

# Testing (optional, for development)
pip install pytest pytest-cov
```

Or install all at once:
```powershell
pip install -r requirements.txt
```

### Step 3: Data Setup

Ensure raw data exists at `data/ipl_csv2/`:
```powershell
# Check if raw data exists
Get-ChildItem data/ipl_csv2/ -First 5

# If not, download from https://cricsheet.org/downloads/ipl_csv2.zip
# Extract to data/ipl_csv2/
```

### Step 4: Generate Processed Data

```powershell
python scripts/preprocess_ipl.py
```

This creates:
- `data/processed/ipl_features.csv`
- `data/processed/venue_stats.csv`
- `data/processed/team_form_latest.csv`
- `data/processed/team_venue_form_latest.csv`
- `data/processed/matchup_form_latest.csv`

### Step 5: Train Models

#### CPU Baseline
```powershell
python scripts/train_models.py
```

Outputs:
- `models/score_model.pkl`
- `models/win_model.pkl`

#### GPU Comparison (Optional)
```powershell
python scripts/train_gpu_best.py
```

Outputs:
- `models/gpu_model_report.json`
- Experimental GPU models in `models/archive/`

---

## Verify Installation

### Test 1: Import Package
```powershell
python -c "from ipl_predictor.common import predict_match; print('✓ Package imports OK')"
```

### Test 2: Check Paths
```powershell
python -c "from ipl_predictor.common import MODELS_DIR, DATA_DIR; print(f'Models: {MODELS_DIR}'); print(f'Data: {DATA_DIR}')"
```

### Test 3: Run Unit Tests
```powershell
python -m pytest tests/test_common.py -v
```

### Test 4: Test Prediction
```powershell
python predict_cli.py
```

Expected output: Interactive CLI prompt asking for match details.

---

## Running the Applications

### CLI (Quickest)
```powershell
python predict_cli.py
```

### Flask (Browser UI)
```powershell
python web_app.py
```
Then open: `http://127.0.0.1:5000`

### Streamlit (Interactive Dashboard)
```powershell
streamlit run streamlit_app.py
```

---

## Troubleshooting

### Issue: "Module not found: ipl_predictor"

**Solution 1**: Install in development mode
```powershell
pip install -e .
```

**Solution 2**: Ensure virtual environment is activated
```powershell
& .\.venv\Scripts\Activate.ps1
```

**Solution 3**: Add to PYTHONPATH
```powershell
$env:PYTHONPATH += ";$(Get-Location)"
```

---

### Issue: "FileNotFoundError: models/score_model.pkl not found"

**Solution**: Train the models first
```powershell
python scripts/preprocess_ipl.py
python scripts/train_models.py
```

Expected time: ~5-10 minutes

---

### Issue: "ModuleNotFoundError: No module named 'catboost'"

**Solution**: Install CatBoost
```powershell
pip install catboost
```

For GPU support:
```powershell
pip install catboost-gpu
```

---

### Issue: "ModuleNotFoundError: No module named 'xgboost'"

**Solution**: Install XGBoost
```powershell
pip install xgboost
```

---

### Issue: "Port 5000 already in use" (Flask)

**Solution**: Specify different port
```powershell
python -c "from web_app import app; app.run(port=5001)"
```

---

### Issue: "CUDA not detected" (GPU training)

**Check CUDA Installation**:
```powershell
python -c "import torch; print(torch.cuda.is_available())"
```

**Option 1**: Train on CPU only
```powershell
python scripts/train_models.py
```

**Option 2**: Install CUDA
- Download from https://developer.nvidia.com/cuda-downloads
- Reinstall GPU packages:
  ```powershell
  pip install --upgrade --force-reinstall catboost-gpu xgboost
  ```

---

## Development Setup

### For Testing
```powershell
pip install pytest pytest-cov pytest-xdist
python -m pytest tests/ -v
```

### For Code Quality
```powershell
pip install pylint mypy black isort
```

### For Documentation
```powershell
pip install sphinx sphinx-rtd-theme
```

---

## Project Dependencies

### Core
- **pandas** ≥2.2 - Data manipulation
- **scikit-learn** ≥1.6 - Baseline models (HistGradientBoosting)
- **joblib** ≥1.4 - Model serialization

### Boosting
- **xgboost** ≥2.1 - Gradient boosting
- **catboost** ≥1.2 - Categorical boosting (GPU support)

### Web Frameworks
- **Flask** ≥3.1 - Lightweight web app
- **streamlit** ≥1.44 - Interactive dashboard

### Optional (Development)
- **pytest** - Unit testing
- **black** - Code formatting
- **pylint** - Linting

---

## Performance Tips

### For Faster Training
1. Use GPU models instead of CPU:
   ```powershell
   python scripts/train_gpu_best.py
   ```

2. Use fewer CV folds (edit in `train_gpu_best.py`):
   ```python
   cv_folds = 3  # Default is 5
   ```

3. Use stratified sampling:
   ```python
   test_size = 0.15  # Reduce test set for faster training
   ```

### For Faster Predictions
1. Use CLI (no web overhead):
   ```powershell
   python predict_cli.py
   ```

2. Cache support tables:
   - Load once, reuse for multiple predictions
   - Already implemented in `common.py`

### For Faster Preprocessing
1. Parallel processing:
   ```python
   # In preprocess_ipl.py
   n_jobs = -1  # Use all CPU cores
   ```

---

## Docker Support (Optional)

If you need containerization:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000
CMD ["python", "web_app.py"]
```

Build and run:
```powershell
docker build -t ipl-predictor .
docker run -p 5000:5000 ipl-predictor
```

---

## Get Help

1. **API Usage**: See `docs/API.md`
2. **Architecture**: See `docs/ARCHITECTURE.md`
3. **Contributing**: See `docs/CONTRIBUTING.md`
4. **Examples**: Check `predict_cli.py`, `web_app.py`, `streamlit_app.py`
5. **README**: See `README.md` for detailed feature descriptions

---

## Next Steps After Installation

1. ✅ Run preprocessing: `python scripts/preprocess_ipl.py`
2. ✅ Train baseline: `python scripts/train_models.py`
3. ✅ Try predictions: `python predict_cli.py`
4. ✅ Launch Streamlit: `streamlit run streamlit_app.py`
5. ✅ Check documentation: Read `docs/API.md` and `docs/ARCHITECTURE.md`
6. ✅ Run tests: `python -m pytest tests/ -v`

---

**Installation Status**: ✅ Ready to use
