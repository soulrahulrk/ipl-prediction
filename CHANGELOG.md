# Change Log

## [0.1.0] - March 30, 2026

### Added
- Core IPL prediction system for score and win probability
- Centralized feature engineering in `ipl_predictor/common.py`
- CPU baseline training on HistGradientBoosting
- GPU-accelerated training on CatBoost/XGBoost with RTX 3050
- Three prediction interfaces: CLI, Flask, Streamlit
- Time-correct feature preprocessing to prevent information leakage
- Historical support tables: venue stats, team form, team-venue form, matchups
- API documentation in `docs/API.md`
- Architecture documentation in `docs/ARCHITECTURE.md`
- Project hygiene: `.gitignore`, `requirements.txt`, `pyproject.toml`

### Score Prediction
- HistGradientBoostingRegressor baseline
- MAE: 18.47 runs on held-out test
- RMSE: 25.01 runs on held-out test

### Win Probability Prediction
- CatBoostClassifier on GPU
- Accuracy: 70.1% on held-out test
- Log Loss: 0.547
- Brier Score: 0.186

### Fixed Issues
- **Venue stat leakage**: Snapshots now taken before each match to prevent future information leakage
- **Code duplication**: Common logic centralized to prevent drift between CLI/Flask/Streamlit
- **Machine-specific paths**: All paths now relative and portable
- **Missing dependencies**: Full list in `requirements.txt` and `pyproject.toml`

### Known Limitations
- No player-level features (would improve predictions significantly)
- No playing-XI data (current lineup vs season average)
- No match condition features (dew, day/night, weather)
- Single model per task (could benefit from per-phase or per-venue specialists)
- No uncertainty quantification (point predictions only)

---

## Next Planned Improvements

1. **Player-Level Features**
   - Batter recent form (last 5 innings)
   - Bowler recent form (last 5 spells)
   - Batter-vs-bowler historical matchups

2. **Match Condition Features**
   - Dew indicator
   - Day/night effect
   - Venue surface recency

3. **Specialist Models**
   - First innings score model (different dynamics than chases)
   - Phase-specific models (Powerplay/Middle/Death)
   - Venue-specialist models for high-variance grounds

4. **Uncertainty Quantification**
   - Prediction intervals instead of point estimates
   - Model confidence scores
   - Calibration analysis

5. **Feature Monitoring**
   - Track feature drift over seasons
   - Alert when team forms change significantly
   - Model performance tracking by phase/phase

---

## Version History

| Version | Date | Key Changes |
|---------|------|------------|
| 0.1.0 | Mar 30, 2026 | Initial implementation with CPU/GPU training |
