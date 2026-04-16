"""
online_learning.py
===================
Lightweight feedback & online-learning system.

How it works:
  1. User submits actual match result after prediction
  2. Row saved to data/processed/feedback_log.csv
  3. When enough rows accumulate (default: 20), the models are
     fine-tuned on the new data (warm-start for sklearn, partial
     training rounds for tree models)
  4. Accuracy drift tracked per session

This is NOT full reinforcement learning — it is supervised
online learning (incremental update with real labels).
For RL you would need an explicit reward signal and an
environment loop which requires streaming data.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

ROOT_DIR     = Path(__file__).resolve().parents[1]
PROC_DIR     = ROOT_DIR / "data" / "processed"
MODELS_DIR   = ROOT_DIR / "models"
FEEDBACK_PATH = PROC_DIR / "feedback_log.csv"
SCORE_PATH   = MODELS_DIR / "score_model.pkl"
WIN_PATH     = MODELS_DIR / "win_model.pkl"
DRIFT_PATH   = MODELS_DIR / "accuracy_drift.json"

RETRAIN_THRESHOLD = 20   # retrain after this many new feedback rows


def save_feedback(
    payload: dict[str, Any],
    actual_total: float | None,
    actual_winner: str | None,
) -> None:
    """Persist one feedback row."""
    row = {**payload,
           "actual_total": actual_total,
           "actual_winner": actual_winner,
           "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%S")}

    PROC_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame([row])
    if FEEDBACK_PATH.exists():
        df.to_csv(FEEDBACK_PATH, mode="a", header=False, index=False)
    else:
        df.to_csv(FEEDBACK_PATH, index=False)


def load_feedback() -> pd.DataFrame:
    if not FEEDBACK_PATH.exists():
        return pd.DataFrame()
    return pd.read_csv(FEEDBACK_PATH)


def pending_count() -> int:
    fb = load_feedback()
    if fb.empty or "fine_tuned" not in fb.columns:
        return len(fb)
    return int((fb["fine_tuned"] != True).sum())


def get_accuracy_drift() -> dict:
    if not DRIFT_PATH.exists():
        return {"history": [], "current_accuracy": None, "total_feedback": 0}
    return json.loads(DRIFT_PATH.read_text())


def fine_tune_models() -> dict[str, Any]:
    """
    Incrementally update score and win models with feedback data.
    Returns a summary dict.
    """
    fb = load_feedback()
    if fb.empty:
        return {"status": "no_feedback", "rows": 0}

    from ipl_predictor import (
        ACTIVE_IPL_TEAMS_2026, CATEGORICAL_FEATURES, NUMERIC_FEATURES, season_to_year
    )
    ALL = CATEGORICAL_FEATURES + NUMERIC_FEATURES

    # Filter rows that have enough info
    score_fb = fb[fb["actual_total"].notna()].copy()
    win_fb   = fb[fb["actual_winner"].notna()].copy()

    summary: dict[str, Any] = {
        "status": "ok",
        "score_rows": len(score_fb),
        "win_rows": len(win_fb),
        "fine_tuned_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    if len(score_fb) >= 5:
        try:
            model = joblib.load(SCORE_PATH)
            feat_cols = [c for c in ALL if c in score_fb.columns]
            X = score_fb[feat_cols].reindex(columns=ALL, fill_value=0)
            y = score_fb["actual_total"].astype(float)
            _warm_start_score(model, X, y)
            joblib.dump(model, SCORE_PATH)
            summary["score_update"] = "ok"
        except Exception as e:
            summary["score_update"] = f"failed: {e}"

    if len(win_fb) >= 5:
        try:
            model = joblib.load(WIN_PATH)
            win_fb["win_label"] = (win_fb["actual_winner"] == win_fb.get("batting_team", "")).astype(int)
            feat_cols = [c for c in ALL if c in win_fb.columns]
            X = win_fb[feat_cols].reindex(columns=ALL, fill_value=0)
            y = win_fb["win_label"].astype(int)
            _warm_start_win(model, X, y)
            joblib.dump(model, WIN_PATH)
            summary["win_update"] = "ok"
        except Exception as e:
            summary["win_update"] = f"failed: {e}"

    # Track accuracy drift
    drift = get_accuracy_drift()
    drift["total_feedback"] = len(fb)
    if len(win_fb) >= 5:
        try:
            model = joblib.load(WIN_PATH)
            win_fb["win_label"] = (win_fb["actual_winner"] == win_fb.get("batting_team", "")).astype(int)
            X = win_fb[[c for c in ALL if c in win_fb.columns]].reindex(columns=ALL, fill_value=0)
            y = win_fb["win_label"]
            probs = _try_predict_proba(model, X)
            if probs is not None:
                preds = (probs >= 0.5).astype(int)
                from sklearn.metrics import accuracy_score
                acc = float(accuracy_score(y, preds))
                drift["current_accuracy"] = round(acc, 4)
                drift["history"].append({
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "accuracy": round(acc, 4),
                    "n_feedback": len(win_fb),
                })
        except Exception:
            pass
    DRIFT_PATH.write_text(json.dumps(drift, indent=2))

    # Mark rows as fine-tuned
    fb["fine_tuned"] = True
    fb.to_csv(FEEDBACK_PATH, index=False)

    return summary


def _warm_start_score(model, X: pd.DataFrame, y: pd.Series) -> None:
    """Add new training data to score model via warm start or CatBoost continuation."""
    from sklearn.pipeline import Pipeline
    from sklearn.ensemble import HistGradientBoostingRegressor

    if isinstance(model, Pipeline):
        est = model.named_steps.get("m")
        if isinstance(est, HistGradientBoostingRegressor):
            est.warm_start = True
            est.max_iter += 20
            model.fit(X, y)
            est.warm_start = False
            return

    # CatBoost
    try:
        from catboost import CatBoostRegressor
        if isinstance(model, CatBoostRegressor):
            from ipl_predictor import CATEGORICAL_FEATURES
            X_cb = X.copy()
            X_cb[CATEGORICAL_FEATURES] = X_cb[CATEGORICAL_FEATURES].fillna("Unknown").astype(str)
            model.fit(X_cb, y, init_model=model)
            return
    except ImportError:
        pass

    # Dict model (XGBoost / RF)
    if isinstance(model, dict) and "model" in model and "pre" in model:
        try:
            X_enc = model["pre"].transform(X)
            import xgboost as xgb
            if isinstance(model["model"], xgb.XGBRegressor):
                model["model"].fit(X_enc, y, xgb_model=model["model"].get_booster())
                return
        except Exception:
            pass
        model["model"].fit(X_enc, y)


def _warm_start_win(model, X: pd.DataFrame, y: pd.Series) -> None:
    from sklearn.pipeline import Pipeline
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.calibration import CalibratedClassifierCV

    inner = model
    if isinstance(model, CalibratedClassifierCV):
        inner = model.base_estimator if hasattr(model, "base_estimator") else model.estimator

    if isinstance(inner, Pipeline):
        est = inner.named_steps.get("m")
        if isinstance(est, HistGradientBoostingClassifier):
            est.warm_start = True
            est.max_iter += 20
            inner.fit(X, y)
            est.warm_start = False
            return

    try:
        from catboost import CatBoostClassifier
        if isinstance(inner, CatBoostClassifier):
            from ipl_predictor import CATEGORICAL_FEATURES
            X_cb = X.copy()
            X_cb[CATEGORICAL_FEATURES] = X_cb[CATEGORICAL_FEATURES].fillna("Unknown").astype(str)
            inner.fit(X_cb, y, init_model=inner)
            return
    except ImportError:
        pass

    if isinstance(model, dict) and "model" in model and "pre" in model:
        X_enc = model["pre"].transform(X)
        model["model"].fit(X_enc, y)


def _try_predict_proba(model, X: pd.DataFrame) -> np.ndarray | None:
    try:
        if hasattr(model, "predict_proba"):
            return model.predict_proba(X)[:, 1]
        if isinstance(model, dict) and "model" in model:
            X_enc = model["pre"].transform(X)
            if hasattr(model["model"], "predict_proba"):
                return model["model"].predict_proba(X_enc)[:, 1]
    except Exception:
        pass
    return None
