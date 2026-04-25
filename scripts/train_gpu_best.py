from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, mean_absolute_error, mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

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
from ipl_predictor.ensembles import WeightedClassifierEnsemble, WeightedRegressorEnsemble

try:
    from xgboost import XGBClassifier, XGBRegressor
except Exception as exc:  # pragma: no cover
    raise RuntimeError("xgboost is required for this script") from exc

try:
    from catboost import CatBoostClassifier, CatBoostRegressor
except Exception as exc:  # pragma: no cover
    raise RuntimeError("catboost is required for this script") from exc


DATA_PATH = PROCESSED_DIR / "ipl_features.csv"
REPORT_PATH = MODELS_DIR / "gpu_model_report.json"
DEPLOYMENT_REPORT_PATH = MODELS_DIR / "deployment_report.json"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

CATEGORICAL = CATEGORICAL_FEATURES
NUMERIC = NUMERIC_FEATURES
MIN_ACTIVE_TRAIN_YEAR = 2024


def build_preprocessor() -> ColumnTransformer:
    numeric_pipe = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="constant", fill_value=0)),
        ]
    )
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


def split_train_valid_test(
    df: pd.DataFrame,
    season_col: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    seasons = sorted(df[season_col].dropna().unique())
    if len(seasons) < 3:
        raise ValueError("Need at least 3 seasons for the GPU best-model workflow.")

    if len(seasons) >= 5:
        train_seasons = seasons[:-3]
        valid_seasons = seasons[-3:-2]
        test_seasons = seasons[-2:]
    elif len(seasons) == 4:
        train_seasons = seasons[:-2]
        valid_seasons = seasons[-2:-1]
        test_seasons = seasons[-1:]
    else:
        train_seasons = seasons[:1]
        valid_seasons = seasons[1:2]
        test_seasons = seasons[2:]
    return (
        df[df[season_col].isin(train_seasons)].copy(),
        df[df[season_col].isin(valid_seasons)].copy(),
        df[df[season_col].isin(test_seasons)].copy(),
    )


def filter_current_ipl_training_data(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    scoped = df.copy()
    scoped["season_key"] = scoped["season"].apply(season_to_year)
    scoped = scoped[scoped["season_key"].notna()].copy()
    scoped["season_key"] = scoped["season_key"].astype(int)

    before_rows = len(scoped)
    scoped = scoped[
        scoped["batting_team"].isin(ACTIVE_IPL_TEAMS_2026)
        & scoped["bowling_team"].isin(ACTIVE_IPL_TEAMS_2026)
    ].copy()

    max_season = int(scoped["season_key"].max()) if not scoped.empty else MIN_ACTIVE_TRAIN_YEAR
    min_season = max(MIN_ACTIVE_TRAIN_YEAR, max_season - 2)
    scoped = scoped[scoped["season_key"] >= min_season].copy()

    if scoped.empty:
        raise ValueError("No rows left after active-team and season filters.")

    summary = {
        "rows_before_filter": before_rows,
        "rows_after_filter": len(scoped),
        "min_season_included": min_season,
        "max_season_included": int(scoped["season_key"].max()),
        "teams": sorted(
            set(scoped["batting_team"].dropna().astype(str))
            | set(scoped["bowling_team"].dropna().astype(str))
        ),
    }
    return scoped, summary


def score_metrics(y_true, preds) -> dict[str, float]:
    return {
        "mae": float(mean_absolute_error(y_true, preds)),
        "rmse": float(mean_squared_error(y_true, preds) ** 0.5),
    }


def win_metrics(y_true, probs) -> dict[str, float]:
    preds = (probs >= 0.5).astype(int)
    clipped = np.clip(probs, 1e-6, 1 - 1e-6)
    return {
        "log_loss": float(log_loss(y_true, clipped, labels=[0, 1])),
        "brier": float(brier_score_loss(y_true, clipped)),
        "accuracy": float(accuracy_score(y_true, preds)),
    }


def _wickets_bucket(series: pd.Series) -> pd.Series:
    return pd.cut(
        series,
        bins=[-0.1, 2.0, 5.0, 10.0],
        labels=["0-2", "3-5", "6-10"],
        include_lowest=True,
    ).astype(str)


def regression_metrics_by_slice(
    frame: pd.DataFrame,
    preds: np.ndarray,
    group_col: str,
) -> dict[str, dict[str, float]]:
    eval_df = frame.copy()
    eval_df["_pred"] = preds
    out: dict[str, dict[str, float]] = {}
    for key, g in eval_df.groupby(group_col):
        if len(g) < 50:
            continue
        out[str(key)] = {
            "mae": float(mean_absolute_error(g["total_runs"], g["_pred"])),
            "rmse": float(mean_squared_error(g["total_runs"], g["_pred"]) ** 0.5),
            "rows": int(len(g)),
        }
    return out


def classification_metrics_by_slice(
    frame: pd.DataFrame,
    probs: np.ndarray,
    group_col: str,
) -> dict[str, dict[str, float]]:
    eval_df = frame.copy()
    eval_df["_prob"] = probs
    out: dict[str, dict[str, float]] = {}
    for key, g in eval_df.groupby(group_col):
        if len(g) < 50:
            continue
        y = g["win"].astype(int)
        p = np.clip(g["_prob"].to_numpy(), 1e-6, 1 - 1e-6)
        out[str(key)] = {
            "log_loss": float(log_loss(y, p, labels=[0, 1])),
            "brier": float(brier_score_loss(y, p)),
            "accuracy": float(accuracy_score(y, (p >= 0.5).astype(int))),
            "rows": int(len(g)),
        }
    return out


def train_catboost_score(train_df: pd.DataFrame, valid_df: pd.DataFrame):
    print("  Training CatBoost Score model (3000 iterations)...")
    start_time = time.time()

    X_train = train_df[CATEGORICAL + NUMERIC]
    y_train = train_df["total_runs"]
    X_valid = valid_df[CATEGORICAL + NUMERIC]
    y_valid = valid_df["total_runs"]
    cat_features = [X_train.columns.get_loc(col) for col in CATEGORICAL]

    model = CatBoostRegressor(
        iterations=3000,
        depth=8,
        learning_rate=0.03,
        loss_function="RMSE",
        eval_metric="RMSE",
        random_seed=42,
        verbose=100,
    )
    try:
        model.set_params(task_type="GPU")
        model.fit(
            X_train,
            y_train,
            cat_features=cat_features,
            eval_set=(X_valid, y_valid),
            use_best_model=True,
            early_stopping_rounds=150,
        )
    except Exception:
        model.set_params(task_type="CPU")
        model.fit(
            X_train,
            y_train,
            cat_features=cat_features,
            eval_set=(X_valid, y_valid),
            use_best_model=True,
            early_stopping_rounds=150,
        )

    elapsed = time.time() - start_time
    print(f"    Completed in {elapsed:.2f}s")
    return model


def train_catboost_win(train_df: pd.DataFrame, valid_df: pd.DataFrame):
    print("  Training CatBoost Win model (2500 iterations)...")
    start_time = time.time()

    X_train = train_df[CATEGORICAL + NUMERIC]
    y_train = train_df["win"].astype(int)
    X_valid = valid_df[CATEGORICAL + NUMERIC]
    y_valid = valid_df["win"].astype(int)
    cat_features = [X_train.columns.get_loc(col) for col in CATEGORICAL]

    model = CatBoostClassifier(
        iterations=2500,
        depth=8,
        learning_rate=0.03,
        loss_function="Logloss",
        eval_metric="Logloss",
        random_seed=42,
        verbose=100,
    )
    try:
        model.set_params(task_type="GPU")
        model.fit(
            X_train,
            y_train,
            cat_features=cat_features,
            eval_set=(X_valid, y_valid),
            use_best_model=True,
            early_stopping_rounds=150,
        )
    except Exception:
        model.set_params(task_type="CPU")
        model.fit(
            X_train,
            y_train,
            cat_features=cat_features,
            eval_set=(X_valid, y_valid),
            use_best_model=True,
            early_stopping_rounds=150,
        )

    elapsed = time.time() - start_time
    print(f"    Completed in {elapsed:.2f}s")
    return model


def train_xgb_score(train_df: pd.DataFrame, valid_df: pd.DataFrame):
    print("  Training XGBoost Score model (2500 estimators)...")
    start_time = time.time()

    X_train = train_df[CATEGORICAL + NUMERIC]
    y_train = train_df["total_runs"]
    params = {
        "n_estimators": 2500,
        "max_depth": 7,
        "learning_rate": 0.03,
        "subsample": 0.9,
        "colsample_bytree": 0.85,
        "reg_lambda": 1.0,
        "random_state": 42,
        "tree_method": "hist",
        "device": "cuda",
        "verbosity": 1,
    }
    pipeline = Pipeline(
        steps=[
            ("preprocess", build_preprocessor()),
            ("model", XGBRegressor(**params)),
        ]
    )
    try:
        pipeline.fit(X_train, y_train)
    except Exception:
        print("    GPU not available, falling back to CPU...")
        params["device"] = "cpu"
        pipeline = Pipeline(
            steps=[
                ("preprocess", build_preprocessor()),
                ("model", XGBRegressor(**params)),
            ]
        )
        pipeline.fit(X_train, y_train)

    try:
        pipeline.named_steps["model"].set_params(device="cpu")
    except Exception:
        pass

    elapsed = time.time() - start_time
    print(f"    Completed in {elapsed:.2f}s")
    return pipeline


def train_xgb_win(train_df: pd.DataFrame, valid_df: pd.DataFrame):
    print("  Training XGBoost Win model (2000 estimators)...")
    start_time = time.time()

    X_train = train_df[CATEGORICAL + NUMERIC]
    y_train = train_df["win"].astype(int)
    params = {
        "n_estimators": 2000,
        "max_depth": 6,
        "learning_rate": 0.03,
        "subsample": 0.9,
        "colsample_bytree": 0.85,
        "reg_lambda": 1.0,
        "random_state": 42,
        "eval_metric": "logloss",
        "tree_method": "hist",
        "device": "cuda",
        "verbosity": 1,
    }
    pipeline = Pipeline(
        steps=[
            ("preprocess", build_preprocessor()),
            ("model", XGBClassifier(**params)),
        ]
    )
    try:
        pipeline.fit(X_train, y_train)
    except Exception:
        print("    GPU not available, falling back to CPU...")
        params["device"] = "cpu"
        pipeline = Pipeline(
            steps=[
                ("preprocess", build_preprocessor()),
                ("model", XGBClassifier(**params)),
            ]
        )
        pipeline.fit(X_train, y_train)

    try:
        pipeline.named_steps["model"].set_params(device="cpu")
    except Exception:
        pass

    elapsed = time.time() - start_time
    print(f"    Completed in {elapsed:.2f}s")
    return pipeline


def calibrate_binary_model(model, X_calib: pd.DataFrame, y_calib: pd.Series):
    raw_calib_probs = np.clip(model.predict_proba(X_calib)[:, 1], 1e-6, 1 - 1e-6)
    iso = IsotonicRegression(out_of_bounds="clip")
    iso.fit(raw_calib_probs, y_calib.astype(int))
    return IsotonicCalibratedModel(base_model=model, calibrator=iso)


def main() -> None:
    print("\n" + "#" * 60)
    print("#" + " " * 58 + "#")
    print("#  IPL PREDICTION: GPU MODEL COMPARISON TRAINING" + " " * 10 + "#")
    print("#" + " " * 58 + "#")
    print("#" * 60)

    start_total = time.time()

    df = pd.read_csv(DATA_PATH, low_memory=False)
    df, filter_summary = filter_current_ipl_training_data(df)
    df["season_str"] = df["season"].astype(str)

    score_df = df[df["balls_left"] > 0].copy()
    win_df = df[df["balls_left"] > 0].copy()
    win_df = win_df[win_df["win"].notna()].copy()

    print(f"\nLoaded {len(df):,} filtered samples")
    print(
        f"Applied training filters: {filter_summary['rows_before_filter']:,} -> {filter_summary['rows_after_filter']:,} rows"
    )
    print(
        f"Seasons included: {filter_summary['min_season_included']} to {filter_summary['max_season_included']}"
    )
    print(f"Teams: {', '.join(filter_summary['teams'])}")
    print(f"Score training: {len(score_df):,} samples")
    print(f"Win training: {len(win_df):,} samples")

    score_train, score_valid, score_test = split_train_valid_test(score_df, "season_key")
    win_train, win_valid, win_test = split_train_valid_test(win_df, "season_key")

    print("\n" + "=" * 60)
    print("TRAINING MODELS")
    print("=" * 60)
    print("\nScore Models:")
    score_cat = train_catboost_score(score_train, score_valid)
    score_xgb = train_xgb_score(score_train, score_valid)

    print("\nWin Probability Models:")
    win_cat = train_catboost_win(win_train, win_valid)
    win_xgb = train_xgb_win(win_train, win_valid)

    print("\n" + "=" * 60)
    print("EVALUATING MODELS")
    print("=" * 60)

    Xs_valid = score_valid[CATEGORICAL + NUMERIC]
    Xs_test = score_test[CATEGORICAL + NUMERIC]
    Xw_valid = win_valid[CATEGORICAL + NUMERIC]
    Xw_test = win_test[CATEGORICAL + NUMERIC]

    score_valid_metrics = {
        "catboost": score_metrics(score_valid["total_runs"], score_cat.predict(Xs_valid)),
        "xgboost": score_metrics(score_valid["total_runs"], score_xgb.predict(Xs_valid)),
    }
    win_valid_metrics = {
        "catboost_raw": win_metrics(win_valid["win"].astype(int), win_cat.predict_proba(Xw_valid)[:, 1]),
        "xgboost_raw": win_metrics(win_valid["win"].astype(int), win_xgb.predict_proba(Xw_valid)[:, 1]),
    }

    score_weights = [
        1.0 / max(score_valid_metrics["catboost"]["rmse"], 1e-6),
        1.0 / max(score_valid_metrics["xgboost"]["rmse"], 1e-6),
    ]
    win_weights = [
        1.0 / max(win_valid_metrics["catboost_raw"]["log_loss"], 1e-6),
        1.0 / max(win_valid_metrics["xgboost_raw"]["log_loss"], 1e-6),
    ]
    score_ensemble = WeightedRegressorEnsemble([score_cat, score_xgb], score_weights)
    win_ensemble = WeightedClassifierEnsemble([win_cat, win_xgb], win_weights)

    score_valid_metrics["ensemble"] = score_metrics(
        score_valid["total_runs"],
        score_ensemble.predict(Xs_valid),
    )
    win_valid_metrics["ensemble_raw"] = win_metrics(
        win_valid["win"].astype(int),
        win_ensemble.predict_proba(Xw_valid)[:, 1],
    )

    # Optional calibration on validation probabilities.
    win_cat_cal = calibrate_binary_model(win_cat, Xw_valid, win_valid["win"])
    win_xgb_cal = calibrate_binary_model(win_xgb, Xw_valid, win_valid["win"])
    win_ens_cal = calibrate_binary_model(win_ensemble, Xw_valid, win_valid["win"])

    win_valid_metrics["catboost_calibrated"] = win_metrics(
        win_valid["win"].astype(int),
        win_cat_cal.predict_proba(Xw_valid)[:, 1],
    )
    win_valid_metrics["xgboost_calibrated"] = win_metrics(
        win_valid["win"].astype(int),
        win_xgb_cal.predict_proba(Xw_valid)[:, 1],
    )
    win_valid_metrics["ensemble_calibrated"] = win_metrics(
        win_valid["win"].astype(int),
        win_ens_cal.predict_proba(Xw_valid)[:, 1],
    )

    score_test_metrics = {
        "catboost": score_metrics(score_test["total_runs"], score_cat.predict(Xs_test)),
        "xgboost": score_metrics(score_test["total_runs"], score_xgb.predict(Xs_test)),
        "ensemble": score_metrics(score_test["total_runs"], score_ensemble.predict(Xs_test)),
    }
    win_test_metrics = {
        "catboost_raw": win_metrics(win_test["win"].astype(int), win_cat.predict_proba(Xw_test)[:, 1]),
        "xgboost_raw": win_metrics(win_test["win"].astype(int), win_xgb.predict_proba(Xw_test)[:, 1]),
        "ensemble_raw": win_metrics(win_test["win"].astype(int), win_ensemble.predict_proba(Xw_test)[:, 1]),
        "catboost_calibrated": win_metrics(
            win_test["win"].astype(int), win_cat_cal.predict_proba(Xw_test)[:, 1]
        ),
        "xgboost_calibrated": win_metrics(
            win_test["win"].astype(int), win_xgb_cal.predict_proba(Xw_test)[:, 1]
        ),
        "ensemble_calibrated": win_metrics(
            win_test["win"].astype(int), win_ens_cal.predict_proba(Xw_test)[:, 1]
        ),
    }

    score_candidates = {
        "catboost": score_cat,
        "xgboost": score_xgb,
        "ensemble": score_ensemble,
    }

    # Keep score on CPU if it remains stronger than GPU candidates.
    cpu_score_path = MODELS_DIR / "score_model_hgb.pkl"
    if cpu_score_path.exists():
        cpu_score_model = joblib.load(cpu_score_path)
        score_candidates["cpu_hgb"] = cpu_score_model
        score_valid_metrics["cpu_hgb"] = score_metrics(
            score_valid["total_runs"], cpu_score_model.predict(Xs_valid)
        )
        score_test_metrics["cpu_hgb"] = score_metrics(
            score_test["total_runs"], cpu_score_model.predict(Xs_test)
        )

    win_candidates = {
        "catboost_raw": win_cat,
        "xgboost_raw": win_xgb,
        "ensemble_raw": win_ensemble,
        "catboost_calibrated": win_cat_cal,
        "xgboost_calibrated": win_xgb_cal,
        "ensemble_calibrated": win_ens_cal,
    }

    cpu_win_raw_path = MODELS_DIR / "win_model_hgb_raw.pkl"
    cpu_win_cal_path = MODELS_DIR / "win_model_hgb.pkl"
    if cpu_win_raw_path.exists():
        cpu_win_raw = joblib.load(cpu_win_raw_path)
        win_candidates["cpu_hgb_raw"] = cpu_win_raw
        win_valid_metrics["cpu_hgb_raw"] = win_metrics(
            win_valid["win"].astype(int), cpu_win_raw.predict_proba(Xw_valid)[:, 1]
        )
        win_test_metrics["cpu_hgb_raw"] = win_metrics(
            win_test["win"].astype(int), cpu_win_raw.predict_proba(Xw_test)[:, 1]
        )
    if cpu_win_cal_path.exists():
        cpu_win_cal = joblib.load(cpu_win_cal_path)
        win_candidates["cpu_hgb_calibrated"] = cpu_win_cal
        win_valid_metrics["cpu_hgb_calibrated"] = win_metrics(
            win_valid["win"].astype(int), cpu_win_cal.predict_proba(Xw_valid)[:, 1]
        )
        win_test_metrics["cpu_hgb_calibrated"] = win_metrics(
            win_test["win"].astype(int), cpu_win_cal.predict_proba(Xw_test)[:, 1]
        )

    best_score_name = min(score_test_metrics, key=lambda name: score_test_metrics[name]["rmse"])
    best_win_name = min(
        win_test_metrics,
        key=lambda name: (
            win_test_metrics[name]["log_loss"],
            win_test_metrics[name]["brier"],
        ),
    )

    # Persist artifacts.
    joblib.dump(score_cat, MODELS_DIR / "score_model_gpu_cat.pkl")
    joblib.dump(score_xgb, MODELS_DIR / "score_model_gpu_xgb.pkl")
    joblib.dump(score_ensemble, MODELS_DIR / "score_model_gpu_ensemble.pkl")

    joblib.dump(win_cat, MODELS_DIR / "win_model_gpu_cat.pkl")
    joblib.dump(win_xgb, MODELS_DIR / "win_model_gpu_xgb.pkl")
    joblib.dump(win_ensemble, MODELS_DIR / "win_model_gpu_ensemble.pkl")
    joblib.dump(win_cat_cal, MODELS_DIR / "win_model_gpu_cat_calibrated.pkl")
    joblib.dump(win_xgb_cal, MODELS_DIR / "win_model_gpu_xgb_calibrated.pkl")
    joblib.dump(win_ens_cal, MODELS_DIR / "win_model_gpu_ensemble_calibrated.pkl")

    joblib.dump(score_candidates[best_score_name], MODELS_DIR / "score_model.pkl")
    joblib.dump(win_candidates[best_win_name], MODELS_DIR / "win_model.pkl")

    # Write uncertainty profile from the selected score model on held-out test set.
    best_score_preds = score_candidates[best_score_name].predict(Xs_test)
    residuals = score_test["total_runs"].to_numpy() - best_score_preds
    uncertainty_profile = {
        "residual_q10": float(np.quantile(residuals, 0.10)),
        "residual_q90": float(np.quantile(residuals, 0.90)),
        "residual_std": float(np.std(residuals)),
        "source": f"gpu_workflow:{best_score_name}",
    }
    SCORE_UNCERTAINTY_PATH.write_text(json.dumps(uncertainty_profile, indent=2), encoding="utf-8")

    # Slice metrics for selected models.
    score_eval = score_test.copy()
    score_eval["wickets_bucket"] = _wickets_bucket(score_eval["wickets"])
    win_eval = win_test.copy()
    win_eval["wickets_bucket"] = _wickets_bucket(win_eval["wickets"])

    selected_score_preds = score_candidates[best_score_name].predict(Xs_test)
    selected_win_probs = win_candidates[best_win_name].predict_proba(Xw_test)[:, 1]

    score_slices = {
        "phase": regression_metrics_by_slice(score_eval, selected_score_preds, "phase"),
        "innings": regression_metrics_by_slice(score_eval, selected_score_preds, "innings"),
        "wickets_bucket": regression_metrics_by_slice(score_eval, selected_score_preds, "wickets_bucket"),
    }
    win_slices = {
        "phase": classification_metrics_by_slice(win_eval, selected_win_probs, "phase"),
        "innings": classification_metrics_by_slice(win_eval, selected_win_probs, "innings"),
        "wickets_bucket": classification_metrics_by_slice(win_eval, selected_win_probs, "wickets_bucket"),
    }

    print(f"\nBest Score Model: {best_score_name.upper()}")
    print(f"  Validation RMSE: {score_valid_metrics[best_score_name]['rmse']:.2f}")
    print(f"  Test RMSE: {score_test_metrics[best_score_name]['rmse']:.2f}")

    print(f"\nBest Win Model: {best_win_name.upper()}")
    print(f"  Validation Log Loss: {win_valid_metrics[best_win_name]['log_loss']:.4f}")
    print(f"  Test Log Loss: {win_test_metrics[best_win_name]['log_loss']:.4f}")

    report = {
        "training_filter": filter_summary,
        "score_valid": score_valid_metrics,
        "score_test": score_test_metrics,
        "win_valid": win_valid_metrics,
        "win_test": win_test_metrics,
        "best_score_model": best_score_name,
        "best_win_model": best_win_name,
        "deployment_selection_rule": {
            "score": "lowest held-out test RMSE",
            "win": "lowest held-out test log loss, tie-break by Brier score",
        },
        "score_weights": score_weights,
        "win_weights": win_weights,
        "score_slices_selected": score_slices,
        "win_slices_selected": win_slices,
        "uncertainty_profile": uncertainty_profile,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    deployment_report = {
        "deployment_score_model": best_score_name,
        "deployment_score_metrics_test": score_test_metrics[best_score_name],
        "deployment_win_model": best_win_name,
        "deployment_win_metrics_test": win_test_metrics[best_win_name],
        "training_filter": filter_summary,
        "selection_rule": report["deployment_selection_rule"],
        "artifacts": {
            "score_model": "models/score_model.pkl",
            "win_model": "models/win_model.pkl",
            "score_uncertainty": "models/score_uncertainty.json",
        },
    }
    DEPLOYMENT_REPORT_PATH.write_text(json.dumps(deployment_report, indent=2), encoding="utf-8")

    total_time = time.time() - start_total
    print("\n" + "=" * 60)
    print("FINAL SUMMARY")
    print("=" * 60)
    print(f"Total Training Time: {total_time:.2f} seconds ({total_time / 60:.2f} minutes)")
    print("Report saved to models/gpu_model_report.json")
    print("Deployment summary saved to models/deployment_report.json")


if __name__ == "__main__":
    np.random.seed(42)
    main()
