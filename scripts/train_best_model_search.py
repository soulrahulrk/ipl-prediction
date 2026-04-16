from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, mean_absolute_error, mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipl_predictor import (
    ACTIVE_IPL_TEAMS_2026,
    CATEGORICAL_FEATURES,
    IsotonicCalibratedModel,
    MODELS_DIR,
    NUMERIC_FEATURES,
    PROCESSED_DIR,
    SCORE_UNCERTAINTY_PATH,
    season_to_year,
)
from ipl_predictor.ensembles import WeightedRegressorEnsemble

try:
    from xgboost import XGBClassifier, XGBRegressor
except Exception as exc:  # pragma: no cover
    raise RuntimeError("xgboost is required for the ML-first benchmark") from exc

try:
    from catboost import CatBoostClassifier, CatBoostRegressor
except Exception as exc:  # pragma: no cover
    raise RuntimeError("catboost is required for the ML-first benchmark") from exc


DATA_PATH = PROCESSED_DIR / "ipl_features.csv"
REPORT_PATH = MODELS_DIR / "best_model_search_report.json"
DEPLOYMENT_REPORT_PATH = MODELS_DIR / "deployment_report.json"
SCORE_TEST_PREDICTIONS_PATH = MODELS_DIR / "best_score_test_predictions.csv"
WIN_TEST_PREDICTIONS_PATH = MODELS_DIR / "best_win_test_predictions.csv"
WIN_STABILITY_PROFILE_PATH = MODELS_DIR / "win_stability_profile.json"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

CATEGORICAL = CATEGORICAL_FEATURES
NUMERIC = NUMERIC_FEATURES
RECENT_MIN_YEAR = 2024
SEED = 42
MIN_REGULATION_TOTAL_RUNS = 40.0

PRESSURE_RR_GAP_THRESHOLD = 1.25
PRESSURE_BALLS_LEFT_MAX = 48

SCORE_TRAIN_PHASE_WEIGHTS = {
    "powerplay": 1.0,
    "middle": 1.10,
    "death": 1.45,
}
SCORE_VALID_PHASE_WEIGHTS = {
    "powerplay": 0.90,
    "middle": 1.00,
    "death": 1.35,
}


def build_hgb_preprocessor() -> ColumnTransformer:
    numeric_pipe = Pipeline(steps=[("imputer", SimpleImputer(strategy="constant", fill_value=0))])
    categorical_pipe = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="constant", fill_value="Unknown")),
            (
                "ordinal",
                OrdinalEncoder(
                    handle_unknown="use_encoded_value",
                    unknown_value=-1,
                    encoded_missing_value=-1,
                ),
            ),
        ]
    )
    return ColumnTransformer(
        transformers=[
            ("num", numeric_pipe, NUMERIC),
            ("cat", categorical_pipe, CATEGORICAL),
        ]
    )


def build_xgb_preprocessor() -> ColumnTransformer:
    numeric_pipe = Pipeline(steps=[("imputer", SimpleImputer(strategy="constant", fill_value=0))])
    categorical_pipe = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="constant", fill_value="Unknown")),
            ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=True, dtype=float)),
        ]
    )
    return ColumnTransformer(
        transformers=[
            ("num", numeric_pipe, NUMERIC),
            ("cat", categorical_pipe, CATEGORICAL),
        ]
    )


def score_phase_weights(frame: pd.DataFrame, train_mode: bool) -> np.ndarray:
    mapping = SCORE_TRAIN_PHASE_WEIGHTS if train_mode else SCORE_VALID_PHASE_WEIGHTS
    phase = frame["phase"].astype(str).str.lower()
    weights = phase.map(mapping).fillna(1.0).to_numpy(dtype=float)

    innings = pd.to_numeric(frame["innings"], errors="coerce")
    chase_boost = np.where(innings == 2, 1.08 if train_mode else 1.03, 1.0)
    return np.clip(weights * chase_boost, 0.5, 2.5)


def weighted_quantile(values: np.ndarray, weights: np.ndarray, quantile: float) -> float:
    sorter = np.argsort(values)
    values_sorted = values[sorter]
    weights_sorted = weights[sorter]
    cumulative = np.cumsum(weights_sorted)
    threshold = quantile * float(cumulative[-1])
    idx = int(np.searchsorted(cumulative, threshold, side="left"))
    idx = min(max(idx, 0), len(values_sorted) - 1)
    return float(values_sorted[idx])


def score_metrics(y_true: pd.Series, preds: np.ndarray, weights: np.ndarray | None = None) -> dict[str, float]:
    yt = y_true.to_numpy(dtype=float)
    pr = np.asarray(preds, dtype=float)
    err = pr - yt
    abs_err = np.abs(err)

    if weights is None:
        mae = float(mean_absolute_error(yt, pr))
        rmse = float(mean_squared_error(yt, pr) ** 0.5)
        w_mae = mae
        w_rmse = rmse
        p90_abs = float(np.quantile(abs_err, 0.90))
    else:
        w = np.asarray(weights, dtype=float)
        w = np.where(w > 0, w, 1e-6)
        w_mae = float(np.sum(abs_err * w) / np.sum(w))
        w_rmse = float(np.sqrt(np.sum((err ** 2) * w) / np.sum(w)))
        mae = float(mean_absolute_error(yt, pr))
        rmse = float(mean_squared_error(yt, pr) ** 0.5)
        p90_abs = weighted_quantile(abs_err, w, 0.90)

    robust_objective = float(0.50 * w_mae + 0.35 * w_rmse + 0.15 * p90_abs)
    return {
        "mae": mae,
        "rmse": rmse,
        "weighted_mae": w_mae,
        "weighted_rmse": w_rmse,
        "weighted_abs_error_p90": p90_abs,
        "robust_objective": robust_objective,
    }


def win_metrics(y_true: pd.Series, probs: np.ndarray) -> dict[str, float]:
    clipped = np.clip(np.asarray(probs, dtype=float), 1e-6, 1 - 1e-6)
    y = y_true.astype(int)
    preds = (clipped >= 0.5).astype(int)
    return {
        "log_loss": float(log_loss(y, clipped, labels=[0, 1])),
        "brier": float(brier_score_loss(y, clipped)),
        "accuracy": float(accuracy_score(y, preds)),
    }


def calibrate_probabilities(model, X_valid: pd.DataFrame, y_valid: pd.Series):
    yv = y_valid.astype(int)
    if yv.nunique() < 2:
        return model
    valid_probs = np.clip(model.predict_proba(X_valid)[:, 1], 1e-6, 1 - 1e-6)
    iso = IsotonicRegression(out_of_bounds="clip")
    iso.fit(valid_probs, yv)
    return IsotonicCalibratedModel(base_model=model, calibrator=iso)


def difficult_slice_masks(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    phase = frame["phase"].astype(str).str.lower()
    innings = pd.to_numeric(frame["innings"], errors="coerce")
    rr_gap = pd.to_numeric(frame["required_minus_current_rr"], errors="coerce")
    balls_left = pd.to_numeric(frame["balls_left"], errors="coerce")

    death_mask = phase.eq("death")
    high_pressure_mask = (
        innings.eq(2)
        & rr_gap.notna()
        & (rr_gap >= PRESSURE_RR_GAP_THRESHOLD)
        & balls_left.notna()
        & (balls_left <= PRESSURE_BALLS_LEFT_MAX)
    )
    difficult_mask = death_mask | high_pressure_mask
    return death_mask.to_numpy(), high_pressure_mask.to_numpy(), difficult_mask.to_numpy()


def apply_slice_stability_adjustment(
    probs: np.ndarray,
    frame: pd.DataFrame,
    alpha_death: float,
    alpha_high_pressure: float,
) -> np.ndarray:
    adjusted = np.clip(np.asarray(probs, dtype=float), 1e-6, 1 - 1e-6).copy()
    death_mask, high_pressure_mask, _ = difficult_slice_masks(frame)

    if alpha_death > 0.0:
        adjusted[death_mask] = 0.5 + (adjusted[death_mask] - 0.5) * (1.0 - alpha_death)
    if alpha_high_pressure > 0.0:
        adjusted[high_pressure_mask] = 0.5 + (adjusted[high_pressure_mask] - 0.5) * (1.0 - alpha_high_pressure)

    return np.clip(adjusted, 1e-6, 1 - 1e-6)


def slice_win_metrics(frame: pd.DataFrame, y_true: pd.Series, probs: np.ndarray) -> dict[str, dict[str, float]]:
    death_mask, high_pressure_mask, difficult_mask = difficult_slice_masks(frame)

    def _subset_metrics(mask: np.ndarray) -> dict[str, float]:
        if int(mask.sum()) == 0:
            return {"rows": 0}
        ys = y_true.to_numpy()[mask]
        ps = np.asarray(probs, dtype=float)[mask]
        metrics = win_metrics(pd.Series(ys), ps)
        metrics["rows"] = int(mask.sum())
        return metrics

    return {
        "death_over": _subset_metrics(death_mask),
        "high_pressure_chase": _subset_metrics(high_pressure_mask),
        "overall_difficult": _subset_metrics(difficult_mask),
    }


def tune_slice_stability(
    valid_frame: pd.DataFrame,
    y_valid: pd.Series,
    valid_probs: np.ndarray,
) -> dict[str, object]:
    base_overall = win_metrics(y_valid.astype(int), valid_probs)
    base_slices = slice_win_metrics(valid_frame, y_valid.astype(int), valid_probs)
    base_hard_log = base_slices["overall_difficult"].get("log_loss", base_overall["log_loss"])
    base_objective = float(base_overall["log_loss"] + 0.35 * base_hard_log + 0.15 * base_overall["brier"])

    best = {
        "alpha_death": 0.0,
        "alpha_high_pressure": 0.0,
        "objective": base_objective,
        "metrics": base_overall,
        "slice_metrics": base_slices,
    }

    grid = np.linspace(0.0, 0.45, 10)
    for alpha_death in grid:
        for alpha_high_pressure in grid:
            adjusted = apply_slice_stability_adjustment(valid_probs, valid_frame, float(alpha_death), float(alpha_high_pressure))
            metrics = win_metrics(y_valid.astype(int), adjusted)
            slices = slice_win_metrics(valid_frame, y_valid.astype(int), adjusted)
            hard_log = slices["overall_difficult"].get("log_loss", metrics["log_loss"])
            objective = float(metrics["log_loss"] + 0.35 * hard_log + 0.15 * metrics["brier"])
            if objective < best["objective"]:
                best = {
                    "alpha_death": float(alpha_death),
                    "alpha_high_pressure": float(alpha_high_pressure),
                    "objective": objective,
                    "metrics": metrics,
                    "slice_metrics": slices,
                }

    has_real_adjustment = bool(best["alpha_death"] > 0.0 or best["alpha_high_pressure"] > 0.0)
    improved = bool(best["objective"] < base_objective - 1e-6)
    use_stable_variant = bool(improved and has_real_adjustment)

    return {
        "alpha_death": best["alpha_death"],
        "alpha_high_pressure": best["alpha_high_pressure"],
        "pressure_rr_gap_threshold": PRESSURE_RR_GAP_THRESHOLD,
        "pressure_balls_left_max": PRESSURE_BALLS_LEFT_MAX,
        "safety_floor_alpha": 0.0,
        "safety_floor_applied": False,
        "valid_objective_before": base_objective,
        "valid_objective_after": float(best["objective"]),
        "valid_metrics_before": base_overall,
        "valid_metrics_after": best["metrics"],
        "valid_slice_metrics_before": base_slices,
        "valid_slice_metrics_after": best["slice_metrics"],
        "use_stable_variant": use_stable_variant,
    }


def build_scope(df: pd.DataFrame, scope_name: str) -> tuple[pd.DataFrame, dict[str, object]]:
    scoped = df.copy()
    scoped["season_str"] = scoped["season"].astype(str)
    scoped["season_key"] = scoped["season"].apply(season_to_year)
    scoped = scoped[scoped["season_key"].notna()].copy()
    scoped["season_key"] = scoped["season_key"].astype(int)

    before = len(scoped)
    if scope_name in {"recent_active_history", "all_active_history"}:
        scoped = scoped[
            scoped["batting_team"].isin(ACTIVE_IPL_TEAMS_2026)
            & scoped["bowling_team"].isin(ACTIVE_IPL_TEAMS_2026)
        ].copy()
    if scope_name == "recent_active_history":
        scoped = scoped[scoped["season_key"] >= RECENT_MIN_YEAR].copy()

    if scoped.empty:
        raise ValueError(f"No rows left for scope={scope_name}")

    summary = {
        "scope": scope_name,
        "rows_before_scope_filter": int(before),
        "rows_after_scope_filter": int(len(scoped)),
        "min_season": int(scoped["season_key"].min()),
        "max_season": int(scoped["season_key"].max()),
        "teams": sorted(set(scoped["batting_team"]) | set(scoped["bowling_team"])),
    }
    return scoped, summary


def split_train_valid_test_latest(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, int]]:
    seasons = sorted(df["season_key"].dropna().unique())
    if len(seasons) < 3:
        raise ValueError("Need at least 3 seasons for train/valid/test.")

    train_seasons = seasons[:-2]
    valid_season = seasons[-2]
    test_season = seasons[-1]

    train_df = df[df["season_key"].isin(train_seasons)].copy()
    valid_df = df[df["season_key"] == valid_season].copy()
    test_df = df[df["season_key"] == test_season].copy()

    split_summary = {
        "train_min_season": int(train_df["season_key"].min()),
        "train_max_season": int(train_df["season_key"].max()),
        "valid_season": int(valid_season),
        "test_season": int(test_season),
        "train_rows": int(len(train_df)),
        "valid_rows": int(len(valid_df)),
        "test_rows": int(len(test_df)),
    }
    return train_df, valid_df, test_df, split_summary


def train_hgb_score(train_df: pd.DataFrame, sample_weight: np.ndarray):
    model = HistGradientBoostingRegressor(
        max_depth=8,
        learning_rate=0.05,
        max_iter=500,
        random_state=SEED,
        loss="absolute_error",
    )
    pipe = Pipeline(
        steps=[
            ("preprocess", build_hgb_preprocessor()),
            ("model", model),
        ]
    )
    X_train = train_df[CATEGORICAL + NUMERIC]
    y_train = train_df["total_runs"].astype(float)
    pipe.fit(X_train, y_train, model__sample_weight=sample_weight)
    return pipe


def train_xgb_score(train_df: pd.DataFrame, sample_weight: np.ndarray):
    params = {
        "n_estimators": 500,
        "max_depth": 6,
        "learning_rate": 0.08,
        "subsample": 0.9,
        "colsample_bytree": 0.85,
        "reg_lambda": 1.3,
        "random_state": SEED,
        "tree_method": "hist",
        "device": "cuda",
        "verbosity": 0,
        # pseudohuber produced unstable constant outlier predictions in this
        # pipeline; absoluteerror is stable and aligns with robust score loss.
        "objective": "reg:absoluteerror",
    }
    pipe = Pipeline(
        steps=[
            ("preprocess", build_xgb_preprocessor()),
            ("model", XGBRegressor(**params)),
        ]
    )
    X_train = train_df[CATEGORICAL + NUMERIC]
    y_train = train_df["total_runs"].astype(float)
    try:
        pipe.fit(X_train, y_train, model__sample_weight=sample_weight)
    except Exception:
        params["device"] = "cpu"
        pipe = Pipeline(
            steps=[
                ("preprocess", build_xgb_preprocessor()),
                ("model", XGBRegressor(**params)),
            ]
        )
        pipe.fit(X_train, y_train, model__sample_weight=sample_weight)
    try:
        pipe.named_steps["model"].set_params(device="cpu")
    except Exception:
        pass
    return pipe


def train_catboost_score(train_df: pd.DataFrame, valid_df: pd.DataFrame, sample_weight: np.ndarray):
    X_train = train_df[CATEGORICAL + NUMERIC]
    y_train = train_df["total_runs"].astype(float)
    X_valid = valid_df[CATEGORICAL + NUMERIC]
    y_valid = valid_df["total_runs"].astype(float)
    cat_features = [X_train.columns.get_loc(col) for col in CATEGORICAL]

    model = CatBoostRegressor(
        iterations=2200,
        depth=8,
        learning_rate=0.03,
        # GPU does not support MAE as the training metric; keep RMSE here and
        # rely on robust external validation objective for model selection.
        loss_function="RMSE",
        eval_metric="RMSE",
        random_seed=SEED,
        verbose=0,
    )
    try:
        model.set_params(task_type="GPU")
        model.fit(
            X_train,
            y_train,
            sample_weight=sample_weight,
            cat_features=cat_features,
            eval_set=(X_valid, y_valid),
            use_best_model=True,
            early_stopping_rounds=120,
        )
    except Exception:
        model.set_params(task_type="CPU")
        model.fit(
            X_train,
            y_train,
            sample_weight=sample_weight,
            cat_features=cat_features,
            eval_set=(X_valid, y_valid),
            use_best_model=True,
            early_stopping_rounds=120,
        )
    return model


def train_hgb_win(train_df: pd.DataFrame):
    model = HistGradientBoostingClassifier(max_depth=6, learning_rate=0.05, max_iter=500, random_state=SEED)
    pipe = Pipeline(
        steps=[
            ("preprocess", build_hgb_preprocessor()),
            ("model", model),
        ]
    )
    X_train = train_df[CATEGORICAL + NUMERIC]
    y_train = train_df["win"].astype(int)
    pipe.fit(X_train, y_train)
    return pipe


def train_xgb_win(train_df: pd.DataFrame):
    params = {
        "n_estimators": 1400,
        "max_depth": 7,
        "learning_rate": 0.035,
        "subsample": 0.9,
        "colsample_bytree": 0.85,
        "reg_lambda": 1.2,
        "random_state": SEED,
        "eval_metric": "logloss",
        "tree_method": "hist",
        "device": "cuda",
        "verbosity": 0,
    }
    pipe = Pipeline(
        steps=[
            ("preprocess", build_xgb_preprocessor()),
            ("model", XGBClassifier(**params)),
        ]
    )
    X_train = train_df[CATEGORICAL + NUMERIC]
    y_train = train_df["win"].astype(int)
    try:
        pipe.fit(X_train, y_train)
    except Exception:
        params["device"] = "cpu"
        pipe = Pipeline(
            steps=[
                ("preprocess", build_xgb_preprocessor()),
                ("model", XGBClassifier(**params)),
            ]
        )
        pipe.fit(X_train, y_train)
    try:
        pipe.named_steps["model"].set_params(device="cpu")
    except Exception:
        pass
    return pipe


def train_catboost_win(train_df: pd.DataFrame, valid_df: pd.DataFrame):
    X_train = train_df[CATEGORICAL + NUMERIC]
    y_train = train_df["win"].astype(int)
    X_valid = valid_df[CATEGORICAL + NUMERIC]
    y_valid = valid_df["win"].astype(int)
    cat_features = [X_train.columns.get_loc(col) for col in CATEGORICAL]

    model = CatBoostClassifier(
        iterations=2200,
        depth=8,
        learning_rate=0.03,
        loss_function="Logloss",
        eval_metric="Logloss",
        random_seed=SEED,
        verbose=0,
    )
    try:
        model.set_params(task_type="GPU")
        model.fit(
            X_train,
            y_train,
            cat_features=cat_features,
            eval_set=(X_valid, y_valid),
            use_best_model=True,
            early_stopping_rounds=120,
        )
    except Exception:
        model.set_params(task_type="CPU")
        model.fit(
            X_train,
            y_train,
            cat_features=cat_features,
            eval_set=(X_valid, y_valid),
            use_best_model=True,
            early_stopping_rounds=120,
        )
    return model


def evaluate_scope(scope_name: str, df: pd.DataFrame) -> dict[str, Any]:
    scoped_df, scope_summary = build_scope(df, scope_name)
    score_df = scoped_df[
        (scoped_df["balls_left"] > 0)
        & (pd.to_numeric(scoped_df["total_runs"], errors="coerce") >= MIN_REGULATION_TOTAL_RUNS)
    ].copy()
    win_df = scoped_df[(scoped_df["balls_left"] > 0) & scoped_df["win"].notna()].copy()

    score_train, score_valid, score_test, score_split = split_train_valid_test_latest(score_df)
    win_train, win_valid, win_test, win_split = split_train_valid_test_latest(win_df)

    print("\n" + "=" * 72)
    print(f"SCOPE: {scope_name}")
    print("=" * 72)
    print(f"Score split: {score_split}")
    print(f"Win split:   {win_split}")

    Xs_valid = score_valid[CATEGORICAL + NUMERIC]
    Xw_valid = win_valid[CATEGORICAL + NUMERIC]

    score_models: dict[str, Any] = {}
    score_valid_metrics: dict[str, dict[str, float]] = {}
    score_valid_objectives: dict[str, float] = {}

    score_train_weights = score_phase_weights(score_train, train_mode=True)
    score_valid_weights = score_phase_weights(score_valid, train_mode=False)

    score_trainers = [
        ("hgb", lambda: train_hgb_score(score_train, score_train_weights)),
        ("xgboost_gpu", lambda: train_xgb_score(score_train, score_train_weights)),
        ("catboost_gpu", lambda: train_catboost_score(score_train, score_valid, score_train_weights)),
    ]

    for name, trainer in score_trainers:
        start = time.time()
        print(f"\n[score] training {name}")
        model = trainer()
        print(f"[score] finished {name} in {time.time() - start:.2f}s")

        preds_valid = np.asarray(model.predict(Xs_valid), dtype=float)
        metrics = score_metrics(score_valid["total_runs"], preds_valid, score_valid_weights)
        score_models[name] = model
        score_valid_metrics[name] = metrics
        score_valid_objectives[name] = float(metrics["robust_objective"])

    # Build an ensemble only from sane members; extreme validation failures can
    # otherwise destabilize averaging and hide regressions.
    individual_score_names = ["hgb", "xgboost_gpu", "catboost_gpu"]
    valid_individual_objectives = [
        float(score_valid_objectives[name])
        for name in individual_score_names
        if np.isfinite(score_valid_objectives[name])
    ]
    ensemble_base_names: list[str] = []
    if valid_individual_objectives:
        median_objective = float(np.median(valid_individual_objectives))
        max_allowed_objective = max(80.0, 10.0 * median_objective)
        ensemble_base_names = [
            name
            for name in individual_score_names
            if np.isfinite(score_valid_objectives[name]) and score_valid_objectives[name] <= max_allowed_objective
        ]

    if len(ensemble_base_names) >= 2:
        ensemble_weights = [1.0 / max(score_valid_objectives[name], 1e-6) for name in ensemble_base_names]
        score_ensemble = WeightedRegressorEnsemble([score_models[name] for name in ensemble_base_names], ensemble_weights)
        ensemble_name = "ensemble_ml_top3"
        score_models[ensemble_name] = score_ensemble

        ensemble_valid_preds = np.asarray(score_ensemble.predict(Xs_valid), dtype=float)
        ensemble_valid_metrics = score_metrics(score_valid["total_runs"], ensemble_valid_preds, score_valid_weights)
        score_valid_metrics[ensemble_name] = ensemble_valid_metrics
        score_valid_objectives[ensemble_name] = float(ensemble_valid_metrics["robust_objective"])

    selected_score_name = min(score_valid_objectives, key=lambda n: float(score_valid_objectives[n]))
    selected_score_valid_metrics = score_valid_metrics[selected_score_name]

    win_models: dict[str, Any] = {}
    win_valid_metrics: dict[str, dict[str, float]] = {}

    win_trainers = [
        ("hgb_raw", lambda: train_hgb_win(win_train)),
        ("xgboost_gpu_raw", lambda: train_xgb_win(win_train)),
        ("catboost_gpu_raw", lambda: train_catboost_win(win_train, win_valid)),
    ]

    for name, trainer in win_trainers:
        start = time.time()
        print(f"\n[win] training {name}")
        model = trainer()
        print(f"[win] finished {name} in {time.time() - start:.2f}s")
        win_models[name] = model
        win_valid_metrics[name] = win_metrics(win_valid["win"].astype(int), model.predict_proba(Xw_valid)[:, 1])

    for raw_name in ["hgb_raw", "xgboost_gpu_raw", "catboost_gpu_raw"]:
        calibrated_name = raw_name.replace("_raw", "_calibrated")
        calibrated_model = calibrate_probabilities(win_models[raw_name], Xw_valid, win_valid["win"])
        win_models[calibrated_name] = calibrated_model
        win_valid_metrics[calibrated_name] = win_metrics(
            win_valid["win"].astype(int),
            calibrated_model.predict_proba(Xw_valid)[:, 1],
        )

    # Select the best calibrated ML classifier strictly by validation metrics.
    calibrated_candidates = [name for name in win_valid_metrics if name.endswith("_calibrated")]
    if calibrated_candidates:
        selected_win_base_name = min(
            calibrated_candidates,
            key=lambda n: (win_valid_metrics[n]["log_loss"], win_valid_metrics[n]["brier"]),
        )
    else:
        selected_win_base_name = min(
            win_valid_metrics,
            key=lambda n: (win_valid_metrics[n]["log_loss"], win_valid_metrics[n]["brier"]),
        )

    base_valid_probs = np.asarray(win_models[selected_win_base_name].predict_proba(Xw_valid)[:, 1], dtype=float)
    stability = tune_slice_stability(win_valid, win_valid["win"].astype(int), base_valid_probs)

    selected_win_name = (
        f"{selected_win_base_name}_stable" if bool(stability["use_stable_variant"]) else selected_win_base_name
    )
    selected_win_valid_metrics = (
        dict(stability["valid_metrics_after"]) if bool(stability["use_stable_variant"]) else win_valid_metrics[selected_win_base_name]
    )

    scope_validation_objective = float(
        selected_score_valid_metrics["robust_objective"] + 10.0 * selected_win_valid_metrics["log_loss"]
    )

    return {
        "scope_summary": scope_summary,
        "score_split": score_split,
        "win_split": win_split,
        "score_models": score_models,
        "win_models": win_models,
        "score_valid": score_valid_metrics,
        "score_valid_objectives": score_valid_objectives,
        "win_valid": win_valid_metrics,
        "selected_score_model": selected_score_name,
        "selected_win_model": selected_win_name,
        "selected_win_base_model": selected_win_base_name,
        "selected_score_metrics_valid": selected_score_valid_metrics,
        "selected_win_metrics_valid": selected_win_valid_metrics,
        "win_stability_valid": {
            "base_win_model": selected_win_base_name,
            "stable_variant": f"{selected_win_base_name}_stable",
            "use_stable_variant": bool(stability["use_stable_variant"]),
            "profile": stability,
        },
        "scope_validation_objective": scope_validation_objective,
        "scope_validation_tie_break_brier": float(selected_win_valid_metrics["brier"]),
        "score_test_frame": score_test,
        "win_test_frame": win_test,
    }


def finalize_selected_scope(scope_name: str, scope_result: dict[str, Any]) -> dict[str, Any]:
    score_model_name = str(scope_result["selected_score_model"])
    win_model_name = str(scope_result["selected_win_model"])
    win_base_name = str(scope_result["selected_win_base_model"])

    score_model = scope_result["score_models"][score_model_name]
    win_model = scope_result["win_models"][win_base_name]

    score_test = scope_result["score_test_frame"]
    win_test = scope_result["win_test_frame"]

    Xs_test = score_test[CATEGORICAL + NUMERIC]
    Xw_test = win_test[CATEGORICAL + NUMERIC]

    score_preds = np.asarray(score_model.predict(Xs_test), dtype=float)
    score_test_weights = score_phase_weights(score_test, train_mode=False)
    score_test_metrics = score_metrics(score_test["total_runs"], score_preds, score_test_weights)

    win_probs_raw = np.asarray(win_model.predict_proba(Xw_test)[:, 1], dtype=float)
    win_test_metrics_raw = win_metrics(win_test["win"].astype(int), win_probs_raw)

    stability_profile_valid = scope_result["win_stability_valid"]["profile"]
    win_probs_adjusted = apply_slice_stability_adjustment(
        win_probs_raw,
        win_test,
        float(stability_profile_valid["alpha_death"]),
        float(stability_profile_valid["alpha_high_pressure"]),
    )
    win_test_metrics_adjusted = win_metrics(win_test["win"].astype(int), win_probs_adjusted)

    use_stable_variant = bool(scope_result["win_stability_valid"]["use_stable_variant"])
    selected_win_metrics_test = win_test_metrics_adjusted if use_stable_variant else win_test_metrics_raw

    stability_profile = {
        "enabled": use_stable_variant,
        "alpha_death": float(stability_profile_valid["alpha_death"]),
        "alpha_high_pressure": float(stability_profile_valid["alpha_high_pressure"]),
        "pressure_rr_gap_threshold": float(stability_profile_valid["pressure_rr_gap_threshold"]),
        "pressure_balls_left_max": float(stability_profile_valid["pressure_balls_left_max"]),
        "source": f"best_model_search:{scope_name}:{win_base_name}",
    }

    score_pred_df = score_test[
        ["match_id", "season", "start_date", "innings", "batting_team", "bowling_team", "runs", "wickets", "total_runs"]
    ].copy()
    score_pred_df["predicted_total_runs"] = score_preds
    score_pred_df["absolute_error"] = np.abs(score_pred_df["total_runs"] - score_pred_df["predicted_total_runs"])
    score_pred_df["scope"] = scope_name
    score_pred_df["model_name"] = score_model_name
    score_pred_df.sort_values(["absolute_error", "match_id"], ascending=[False, True]).to_csv(
        SCORE_TEST_PREDICTIONS_PATH,
        index=False,
    )

    win_pred_df = win_test[
        ["match_id", "season", "start_date", "innings", "batting_team", "bowling_team", "runs", "wickets", "win"]
    ].copy()
    win_pred_df["predicted_win_prob_raw"] = win_probs_raw
    win_pred_df["predicted_win_prob"] = win_probs_adjusted if use_stable_variant else win_probs_raw
    win_pred_df["predicted_win_class"] = (win_pred_df["predicted_win_prob"] >= 0.5).astype(int)
    win_pred_df["logloss_contribution"] = -(
        win_pred_df["win"] * np.log(np.clip(win_pred_df["predicted_win_prob"], 1e-6, 1 - 1e-6))
        + (1 - win_pred_df["win"]) * np.log(np.clip(1 - win_pred_df["predicted_win_prob"], 1e-6, 1 - 1e-6))
    )
    win_pred_df["scope"] = scope_name
    win_pred_df["model_name"] = win_model_name
    win_pred_df.sort_values(["logloss_contribution", "match_id"], ascending=[False, True]).to_csv(
        WIN_TEST_PREDICTIONS_PATH,
        index=False,
    )

    score_residuals = score_test["total_runs"].to_numpy(dtype=float) - score_preds
    uncertainty_profile = {
        "residual_q10": float(np.quantile(score_residuals, 0.10)),
        "residual_q90": float(np.quantile(score_residuals, 0.90)),
        "residual_std": float(np.std(score_residuals)),
        "source": f"best_model_search:{scope_name}:{score_model_name}",
    }

    SCORE_UNCERTAINTY_PATH.write_text(json.dumps(uncertainty_profile, indent=2), encoding="utf-8")
    WIN_STABILITY_PROFILE_PATH.write_text(json.dumps(stability_profile, indent=2), encoding="utf-8")

    joblib.dump(score_model, MODELS_DIR / "score_model.pkl")
    joblib.dump(win_model, MODELS_DIR / "win_model.pkl")

    selected_win_stability = {
        "base_win_model": win_base_name,
        "stable_variant": f"{win_base_name}_stable",
        "use_stable_variant": use_stable_variant,
        "profile": {
            "alpha_death": float(stability_profile_valid["alpha_death"]),
            "alpha_high_pressure": float(stability_profile_valid["alpha_high_pressure"]),
            "pressure_rr_gap_threshold": float(stability_profile_valid["pressure_rr_gap_threshold"]),
            "pressure_balls_left_max": float(stability_profile_valid["pressure_balls_left_max"]),
            "valid_objective_before": float(stability_profile_valid["valid_objective_before"]),
            "valid_objective_after": float(stability_profile_valid["valid_objective_after"]),
            "valid_metrics_before": stability_profile_valid["valid_metrics_before"],
            "valid_metrics_after": stability_profile_valid["valid_metrics_after"],
            "valid_slice_metrics_before": stability_profile_valid["valid_slice_metrics_before"],
            "valid_slice_metrics_after": stability_profile_valid["valid_slice_metrics_after"],
        },
        "test_slice_metrics_before": slice_win_metrics(win_test, win_test["win"].astype(int), win_probs_raw),
        "test_slice_metrics_after": slice_win_metrics(
            win_test,
            win_test["win"].astype(int),
            win_probs_adjusted if use_stable_variant else win_probs_raw,
        ),
    }

    return {
        "selected_score_model": score_model_name,
        "selected_win_model": win_model_name,
        "selected_score_metrics_test": score_test_metrics,
        "selected_win_metrics_test": selected_win_metrics_test,
        "selected_win_metrics_test_raw": win_test_metrics_raw,
        "selected_win_stability": selected_win_stability,
        "artifacts": {
            "score_model": "models/score_model.pkl",
            "win_model": "models/win_model.pkl",
            "score_uncertainty": "models/score_uncertainty.json",
            "win_stability_profile": "models/win_stability_profile.json",
            "score_test_predictions": str(SCORE_TEST_PREDICTIONS_PATH.relative_to(ROOT_DIR)),
            "win_test_predictions": str(WIN_TEST_PREDICTIONS_PATH.relative_to(ROOT_DIR)),
        },
        "examples": {
            "score_worst_examples": score_pred_df.nlargest(10, "absolute_error").to_dict(orient="records"),
            "win_worst_examples": win_pred_df.nlargest(10, "logloss_contribution").to_dict(orient="records"),
        },
    }


def write_deployment_report(
    scope_name: str,
    scope_summary: dict[str, Any],
    final_result: dict[str, Any],
) -> dict[str, Any]:
    score_metrics_test = final_result["selected_score_metrics_test"]
    win_metrics_test = final_result["selected_win_metrics_test"]

    deployment_report = {
        "deployment_scope": scope_name,
        "deployment_score_model": final_result["selected_score_model"],
        "deployment_score_metrics_test": {
            "mae": float(score_metrics_test["mae"]),
            "rmse": float(score_metrics_test["rmse"]),
            "weighted_mae": float(score_metrics_test["weighted_mae"]),
            "weighted_rmse": float(score_metrics_test["weighted_rmse"]),
            "weighted_abs_error_p90": float(score_metrics_test["weighted_abs_error_p90"]),
            "robust_objective": float(score_metrics_test["robust_objective"]),
        },
        "deployment_win_model": final_result["selected_win_model"],
        "deployment_win_metrics_test": {
            "log_loss": float(win_metrics_test["log_loss"]),
            "brier": float(win_metrics_test["brier"]),
            "accuracy": float(win_metrics_test["accuracy"]),
        },
        "training_filter": {
            "rows_after_filter": int(scope_summary["rows_after_scope_filter"]),
            "min_season_included": int(scope_summary["min_season"]),
            "max_season_included": int(scope_summary["max_season"]),
            "score_min_total_runs": float(MIN_REGULATION_TOTAL_RUNS),
            "teams": scope_summary["teams"],
        },
        "selection_rule": {
            "scope": "lowest validation composite score = score_robust_objective + 10 * win_log_loss, tie-break by win_brier",
            "score": "Best validation score model among HGB/XGBoost/CatBoost and a robust ensemble candidate when base models are stable",
            "win": "Best calibrated ML classifier (HGB/XGBoost/CatBoost) selected on validation; optional slice stabilization enabled only if validation objective improves",
            "test_policy": "2026 test touched once only after validation-based scope/model selection",
        },
        "artifacts": final_result["artifacts"],
    }
    DEPLOYMENT_REPORT_PATH.write_text(json.dumps(deployment_report, indent=2), encoding="utf-8")
    return deployment_report


def main() -> None:
    start_total = time.time()
    np.random.seed(SEED)
    df = pd.read_csv(DATA_PATH, low_memory=False)

    scope_results: dict[str, dict[str, Any]] = {}
    scopes = ["recent_active_history", "all_active_history"]

    for scope_name in scopes:
        scope_results[scope_name] = evaluate_scope(scope_name, df)

    best_scope_name = min(
        scope_results,
        key=lambda name: (
            float(scope_results[name]["scope_validation_objective"]),
            float(scope_results[name]["scope_validation_tie_break_brier"]),
        ),
    )

    best_scope_result = scope_results[best_scope_name]
    final_result = finalize_selected_scope(best_scope_name, best_scope_result)
    deployment_report = write_deployment_report(
        best_scope_name,
        best_scope_result["scope_summary"],
        final_result,
    )

    compact_scope_results: dict[str, Any] = {}
    for scope_name, result in scope_results.items():
        compact_scope_results[scope_name] = {
            "scope_summary": result["scope_summary"],
            "score_split": result["score_split"],
            "win_split": result["win_split"],
            "score_valid": result["score_valid"],
            "score_valid_objectives": result["score_valid_objectives"],
            "win_valid": result["win_valid"],
            "selected_score_model": result["selected_score_model"],
            "selected_win_model": result["selected_win_model"],
            "selected_win_base_model": result["selected_win_base_model"],
            "selected_score_metrics_valid": result["selected_score_metrics_valid"],
            "selected_win_metrics_valid": result["selected_win_metrics_valid"],
            "win_stability_valid": result["win_stability_valid"],
            "scope_validation_objective": float(result["scope_validation_objective"]),
            "scope_validation_tie_break_brier": float(result["scope_validation_tie_break_brier"]),
        }

    report = {
        "search_type": "ml_first_validation_selected_latest_season_holdout",
        "selection_rule": {
            "scope": "lowest validation composite score = score_robust_objective + 10 * win_log_loss, tie-break by win_brier",
            "score_model": "Best validation score model selected from ML candidates and robust ensemble candidate",
            "win_model": "Best calibrated ML classifier selected on validation only",
            "test_policy": "2026 test touched once only for final selected scope/model pair",
        },
        "scopes": compact_scope_results,
        "selected_scope": best_scope_name,
        "selected_score_model": final_result["selected_score_model"],
        "selected_win_model": final_result["selected_win_model"],
        "selected_score_metrics_valid": best_scope_result["selected_score_metrics_valid"],
        "selected_win_metrics_valid": best_scope_result["selected_win_metrics_valid"],
        "selected_score_metrics_test": final_result["selected_score_metrics_test"],
        "selected_win_metrics_test": final_result["selected_win_metrics_test"],
        "selected_win_stability": final_result["selected_win_stability"],
        "artifacts": final_result["artifacts"],
        "examples": final_result["examples"],
        "deployment_report": str(DEPLOYMENT_REPORT_PATH.relative_to(ROOT_DIR)),
        "training_seconds_total": float(time.time() - start_total),
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\n" + "=" * 72)
    print("FINAL WINNERS (validation-selected, test-once)")
    print("=" * 72)
    print(f"Selected scope: {best_scope_name}")
    print(f"Selected score model: {final_result['selected_score_model']}")
    print(f"Selected score test metrics: {final_result['selected_score_metrics_test']}")
    print(f"Selected win model: {final_result['selected_win_model']}")
    print(f"Selected win test metrics: {final_result['selected_win_metrics_test']}")
    print(f"Saved report to: {REPORT_PATH}")
    print(f"Saved deployment report to: {DEPLOYMENT_REPORT_PATH}")
    print(f"Saved score actual-vs-predicted to: {SCORE_TEST_PREDICTIONS_PATH}")
    print(f"Saved win actual-vs-predicted to: {WIN_TEST_PREDICTIONS_PATH}")


if __name__ == "__main__":
    main()
