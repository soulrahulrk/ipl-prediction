# Contributing Guide

## Project Structure

```
ipl-prediction/
├── ipl_predictor/          # Main package
│   ├── __init__.py
│   ├── common.py          # Centralized logic (paths, aliases, features)
│   └── ensembles.py       # Model ensemble utilities
├── scripts/               # Training and preprocessing
│   ├── preprocess_ipl.py  # Data pipeline
│   ├── train_models.py    # CPU baseline
│   ├── train_gpu_best.py  # GPU comparison
│   └── train_boosting_compare.py
├── predict_cli.py         # CLI interface
├── web_app.py            # Flask app
├── streamlit_app.py      # Streamlit app
├── tests/                # Unit tests (to be added)
├── docs/                 # Documentation
├── data/
│   ├── ipl_csv2/        # Raw ball-by-ball data
│   └── processed/        # Generated feature tables
├── models/              # Trained models
│   ├── score_model.pkl
│   ├── win_model.pkl
│   └── archive/         # Old models
└── logs/                # Application logs
```

---

## Running Tests

```powershell
# Run all tests
python -m pytest tests/

# Run with coverage
python -m pytest tests/ --cov=ipl_predictor

# Run specific test
python -m pytest tests/test_common.py::test_predict_match
```

---

## Adding New Features

### 1. Update `ipl_predictor/common.py`

Add new feature column:

```python
def build_features(match_state: dict) -> pd.DataFrame:
    # ... existing features ...
    
    # NEW: Add player-level feature
    df['key_batters_remaining'] = calculate_key_batters(match_state)
    
    return df
```

### 2. Retrain Models

```powershell
python scripts/preprocess_ipl.py
python scripts/train_models.py
python scripts/train_gpu_best.py
```

### 3. Test All Interfaces

```powershell
# CLI
python predict_cli.py

# Flask
python web_app.py
# Visit http://localhost:5000

# Streamlit
streamlit run streamlit_app.py
```

### 4. Update Documentation

- Add feature to `docs/API.md`
- Update `docs/ARCHITECTURE.md` if logic changed

---

## Code Style

### Type Hints
All functions must have type hints:

```python
def predict_match(
    batting_team: str,
    bowling_team: str,
    venue: str,
    overs_bowled: float,
    runs: int,
    wickets_lost: int
) -> dict[str, Any]:
    """Predict match outcome from live state."""
    pass
```

### Docstrings
Use Google-style docstrings:

```python
def preprocess_match_data(raw_csv: Path) -> pd.DataFrame:
    """Preprocess raw Cricsheet CSV to feature table.
    
    Args:
        raw_csv: Path to raw ball-by-ball CSV
        
    Returns:
        DataFrame with features ready for model input
        
    Raises:
        FileNotFoundError: If raw_csv does not exist
    """
    pass
```

### Naming Conventions
- `PascalCase` for classes
- `snake_case` for functions and variables
- `CONSTANT_CASE` for module constants
- Prefix private functions with `_`

---

## Testing Strategy

### Unit Tests
Location: `tests/test_common.py`

Template:

```python
import pytest
from ipl_predictor.common import predict_match

def test_predict_match_valid_input():
    """Test prediction with valid match state."""
    result = predict_match(
        batting_team="Mumbai Indians",
        bowling_team="Chennai Super Kings",
        venue="Wankhede Stadium",
        overs_bowled=10.0,
        runs=75,
        wickets_lost=1
    )
    
    assert "predicted_score" in result
    assert 0 <= result["win_probability"] <= 1
    assert result["predicted_score"] > 0

def test_predict_match_invalid_team():
    """Test prediction with invalid team name."""
    with pytest.raises(ValueError):
        predict_match(
            batting_team="Invalid Team",
            bowling_team="Chennai Super Kings",
            venue="Wankhede Stadium",
            overs_bowled=10.0,
            runs=75,
            wickets_lost=1
        )

def test_predict_match_invalid_venue():
    """Test prediction with invalid venue."""
    with pytest.raises(ValueError):
        predict_match(
            batting_team="Mumbai Indians",
            bowling_team="Chennai Super Kings",
            venue="Invalid Venue",
            overs_bowled=10.0,
            runs=75,
            wickets_lost=1
        )
```

---

## Release Checklist

Before tagging a release:

- [ ] All tests pass: `pytest tests/`
- [ ] No unused imports: `pylint ipl_predictor/ scripts/`
- [ ] Type checking passes: `mypy ipl_predictor/`
- [ ] README updated with latest metrics
- [ ] Models trained and committed
- [ ] CHANGELOG.md updated
- [ ] Version bumped in `pyproject.toml`
- [ ] Git tag created: `git tag v0.X.Y`

---

## Common Issues

### Issue: "Module not found" when importing `ipl_predictor`

**Solution**: Install in development mode:
```powershell
pip install -e .
```

### Issue: Models not found during prediction

**Solution**: Run training first:
```powershell
python scripts/preprocess_ipl.py
python scripts/train_models.py
```

### Issue: Venue stats out of date

**Solution**: Rerun preprocessing:
```powershell
python scripts/preprocess_ipl.py
```

---

## Questions?

- Check `docs/ARCHITECTURE.md` for design decisions
- Check `docs/API.md` for function signatures
- Check README.md for end-to-end workflow
