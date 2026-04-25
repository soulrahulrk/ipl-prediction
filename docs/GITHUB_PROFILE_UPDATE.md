# GitHub Profile Update Snippet

Use this section in your GitHub profile README.

## Featured Project: IPL Prediction (Live + Pre-Match)

I built an IPL prediction system using Cricsheet ball-by-ball data with:

- Live innings total prediction
- Live batting-side win probability
- Uncertainty bands and simulation-based risk signals
- Pre-match winner and projected first-innings range
- Flask app + JSON API + Streamlit dashboard + CLI

### Live links

- Streamlit app: https://<your-streamlit-url>
- Flask API/Web app: https://<your-render-url>

### Current deployment snapshot

- Scope: all_active_history
- Score model: torch_entity_gpu
- Win model: catboost_gpu_calibrated
- Score MAE / RMSE: 15.36 / 19.81
- Win Log Loss / Brier / Accuracy: 0.4922 / 0.1681 / 0.6712

### Tech stack

Python, pandas, scikit-learn, XGBoost, CatBoost, PyTorch, Flask, Streamlit, Gunicorn

### Repo

- Project: https://github.com/soulrahulrk/ipl-prediction
