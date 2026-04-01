# 🚀 Quick Start Dashboard

## ⚡ 5-Minute Setup

```powershell
# 1. Activate environment
& .\.venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r requirements.txt

# 3. Verify installation
python -c "from ipl_predictor.common import predict_match; print('✓ Ready')"

# 4. Try a prediction
python predict_cli.py
```

---

## 📱 Three Ways to Use

### **CLI** (Fastest - 30 seconds)
```powershell
python predict_cli.py
```
→ Best for: Fast testing, batch predictions

### **Web App** (Easy - 2 minutes)
```powershell
python web_app.py
# Open http://127.0.0.1:5000
```
→ Best for: Browser interface, sharing with team

### **Dashboard** (Interactive - 1 minute)
```powershell
streamlit run streamlit_app.py
```
→ Best for: Real-time exploration, visualizations

---

## 📚 Documentation Map

| Question | Answer |
|----------|--------|
| **How do I set up?** | →  [`INSTALL.md`](INSTALL.md) |
| **How do I use the API?** | → [`docs/API.md`](docs/API.md) |
| **How does it work?** | → [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| **Want to contribute?** | → [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) |
| **What changed?** | → [`CHANGELOG.md`](CHANGELOG.md) |
| **Project status?** | → [`PROJECT_REVIEW.md`](PROJECT_REVIEW.md) |
| **Organization?** | → [`PROJECT_ORGANIZATION.md`](PROJECT_ORGANIZATION.md) |

---

## 🎯 Current Models

### Score Prediction 🎯
- **Algorithm**: HistGradientBoostingRegressor
- **Accuracy**: MAE 18.47 runs
- **Device**: CPU (fast)
- **File**: `models/score_model.pkl`

### Win Probability 🏆
- **Algorithm**: CatBoostClassifier  
- **Accuracy**: 70.1% accuracy
- **Device**: GPU (accurate)
- **File**: `models/win_model.pkl`

---

## 🧪 Testing & Quality

```powershell
# Run all tests
python -m pytest tests/ -v

# Run with coverage
python -m pytest tests/ --cov=ipl_predictor

# Check specific test
python -m pytest tests/test_common.py::test_predict_with_valid_input -v
```

---

## 🔄 Training Workflow

```powershell
# 1. Preprocess data
python scripts/preprocess_ipl.py

# 2. Train CPU baseline
python scripts/train_models.py

# 3. Train GPU comparison
python scripts/train_gpu_best.py

# 4. Check results
cat models/gpu_model_report.json
```

---

## 📊 Project Health

| Component | Status | Details |
|-----------|--------|---------|
| Code Quality | ✅ | 8/10 - Well organized |
| Documentation | ✅ | 10/10 - Comprehensive |
| Testing | ✅ | 7/10 - Good foundation |
| Deployment | ✅ | 10/10 - Three interfaces |
| Models | ✅ | Production-ready |
| Organization | ✅ | Industry-standard |

**Overall**: 🟢 **9.0/10** - PRODUCTION READY

---

## 🛠️ Common Tasks

### Add a New Feature
1. Update `ipl_predictor/common.py`
2. Retrain: `python scripts/train_models.py`
3. Test: `python predict_cli.py`
4. Update docs if needed

### Fix a Bug
1. Add test case in `tests/`
2. Fix code in `ipl_predictor/` or `scripts/`
3. Run tests: `pytest tests/`
4. Push changes

### Deploy to Production
1. Ensure tests pass
2. Update `CHANGELOG.md`
3. Retrain models (if needed)
4. Commit with git tag: `git tag v0.X.Y`

---

## 📦 Project Structure

```
ipl-prediction/
├── 📄 README.md              ← Start here
├── 📄 INSTALL.md             ← Setup guide
├── 📄 PROJECT_REVIEW.md      ← Quality report
├── 📄 PROJECT_ORGANIZATION.md ← Structure
├── 📄 CHANGELOG.md            ← Version history
│
├── 📁 ipl_predictor/          ← Core package
│   ├── common.py             ← Main logic
│   └── ensembles.py          ← Model ensemble
│
├── 📁 scripts/               ← Training pipelines
│   ├── preprocess_ipl.py
│   ├── train_models.py
│   └── train_gpu_best.py
│
├── 📁 tests/                 ← Unit tests
│   ├── test_common.py
│   └── conftest.py
│
├── 📁 docs/                  ← Documentation
│   ├── API.md
│   ├── ARCHITECTURE.md
│   └── CONTRIBUTING.md
│
├── 📁 models/                ← Trained models
│   ├── score_model.pkl       ← Production
│   ├── win_model.pkl         ← Production
│   └── archive/              ← Old experiments
│
├── 📁 data/                  ← Data files
│   ├── ipl_csv2/             ← Raw data
│   └── processed/            ← Features
│
├── .venv/                    ← Virtual environment
├── .gitignore                ← Git ignore rules
├── requirements.txt          ← Python dependencies
└── pyproject.toml            ← Project metadata
```

---

## 🚦 Before You Start

- [ ] Virtual environment activated? (`& .\.venv\Scripts\Activate.ps1`)
- [ ] Dependencies installed? (`pip install -r requirements.txt`)
- [ ] Raw data exists? (`data/ipl_csv2/`)
- [ ] Models trained? (`python scripts/train_models.py`)
- [ ] Tests pass? (`python -m pytest tests/ -v`)

---

## 🆘 Quick Troubleshooting

| Problem | Solution |
|---------|----------|
| **ImportError: ipl_predictor** | Run: `pip install -e .` |
| **FileNotFoundError: models** | Run: `python scripts/train_models.py` |
| **Port 5000 in use** | Use: `python -c "from web_app import app; app.run(port=5001)"` |
| **CUDA not found** | Install CUDA or let it run on CPU |
| **Tests fail** | Check: `python -m pytest tests/ -v` |

---

## 📞 Key Commands Reference

```powershell
# Setup
python -m venv .venv
& .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Preprocess
python scripts/preprocess_ipl.py

# Train
python scripts/train_models.py
python scripts/train_gpu_best.py

# Predict
python predict_cli.py                          # CLI
python web_app.py                              # Flask (http://127.0.0.1:5000)
streamlit run streamlit_app.py                 # Streamlit

# Test
python -m pytest tests/ -v
python -m pytest tests/ --cov=ipl_predictor

# Install dev
pip install -e .
```

---

## 🎓 Learning Path

1. **New to project?** → Read `README.md` (5 min)
2. **Setting up?** → Read `INSTALL.md` (10 min)
3. **Understanding design?** → Read `docs/ARCHITECTURE.md` (10 min)
4. **Using the API?** → Read `docs/API.md` (10 min)
5. **Want to contribute?** → Read `docs/CONTRIBUTING.md` (10 min)
6. **Try it out** → `python predict_cli.py` (2 min)
7. **Run tests** → `pytest tests/ -v` (1 min)

**Total**: ~50 minutes to full understanding

---

## ✨ What's New

- ✅ **API Documentation** - Complete function reference
- ✅ **Architecture Guide** - Design decisions explained
- ✅ **Test Framework** - 30+ test cases
- ✅ **Contributing Guide** - Development workflow
- ✅ **Installation Guide** - Step-by-step setup
- ✅ **Project Review** - Quality assessment
- ✅ **Better Organization** - Professional structure
- ✅ **Improved .gitignore** - Smart model exclusions

---

## 🏆 Project Status: PRODUCTION READY ✅

**Rating**: 9.0/10 ⭐⭐⭐⭐☆

All systems operational. Ready for deployment.

---

*Last Updated: March 31, 2026*
*Next Review: When new features added or quarterly*
