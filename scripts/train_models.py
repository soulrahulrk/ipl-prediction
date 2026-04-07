import json
import os
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, mean_absolute_error, mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipl_predictor import (
    ACTIVE_IPL_TEAMS_2026,
    CATEGORICAL_FEATURES,
    MODELS_DIR,
    NUMERIC_FEATURES,
    PROCESSED_DIR,
    SCORE_UNCERTAINTY_PATH,
    season_to_year,
)


os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")

DATA_PATH = PROCESSED_DIR / "ipl_features.csv"
CPU_REPORT_PATH = MODELS_DIR / "cpu_model_report.json"
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
            ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False, dtype=float)),
        ]
    )

    return ColumnTransformer(
        transformers=[
            ("num", numeric_pipe, NUMERIC),
            ("cat", categorical_pipe, CATEGORICAL),
        ]
    )


def split_by_season(df: pd.DataFrame, season_col: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    seasons = sorted(df[season_col].dropna().unique())
    if len(seasons) <= 1:
        return df, df
    test_seasons = seasons[-2:] if len(seasons) > 2 else seasons[-1:]
    train_df = df[~df[season_col].isin(test_seasons)]
    test_df = df[df[season_col].isin(test_seasons)]
    return train_df, test_df


def split_by_season_three(
    df: pd.DataFrame, season_col: str
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    seasons = sorted(df[season_col].dropna().unique())
    if len(seasons) <= 1:
        return df, df, df
    if len(seasons) >= 4:
        test_seasons = seasons[-2:]
        calib_seasons = seasons[-3:-2]
        train_seasons = seasons[:-3]
    elif len(seasons) == 3:
        test_seasons = seasons[-1:]
        calib_seasons = seasons[-2:-1]
        train_seasons = seasons[:1]
    else:
        test_seasons = seasons[-1:]
        calib_seasons = seasons[-1:]
        train_seasons = seasons[:1]

    train_df = df[df[season_col].isin(train_seasons)]
    calib_df = df[df[season_col].isin(calib_seasons)]
    test_df = df[df[season_col].isin(test_seasons)]
    return train_df, calib_df, test_df


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


def _safe_log_loss(y_true: pd.Series, probs: np.ndarray) -> float:
    p = np.clip(probs, 1e-6, 1 - 1e-6)
    return float(log_loss(y_true, p, labels=[0, 1]))


def _score_metrics(y_true: pd.Series, y_pred: np.ndarray) -> dict[str, float]:
    return {
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "rmse": float(mean_squared_error(y_true, y_pred) ** 0.5),
    }


def _win_metrics(y_true: pd.Series, probs: np.ndarray) -> dict[str, float]:
    preds = (probs >= 0.5).astype(int)
    return {
        "log_loss": _safe_log_loss(y_true, probs),
        "brier": float(brier_score_loss(y_true, probs)),
        "accuracy": float(accuracy_score(y_true, preds)),
    }


def _regression_metrics_by_slice(
    frame: pd.DataFrame,
    preds: np.ndarray,
    group_col: str,
) -> dict[str, dict[str, float]]:
    eval_df = frame.copy()
    eval_df["_pred"] = preds
    out: dict[str, dict[str, float]] = {}
    for key, group in eval_df.groupby(group_col):
        if len(group) < 50:
            continue
        out[str(key)] = {
            "mae": float(mean_absolute_error(group["total_runs"], group["_pred"])),
            "rmse": float(mean_squared_error(group["total_runs"], group["_pred"]) ** 0.5),
            "rows": int(len(group)),
        }
    return out


def _classification_metrics_by_slice(
    frame: pd.DataFrame,
    probs: np.ndarray,
    group_col: str,
) -> dict[str, dict[str, float]]:
    eval_df = frame.copy()
    eval_df["_prob"] = probs
    out: dict[str, dict[str, float]] = {}
    for key, group in eval_df.groupby(group_col):
        if len(group) < 50:
            continue
        y = group["win"].astype(int)
        p = np.clip(group["_prob"].to_numpy(), 1e-6, 1 - 1e-6)
        out[str(key)] = {
            "log_loss": _safe_log_loss(y, p),
            "brier": float(brier_score_loss(y, p)),
            "accuracy": float(accuracy_score(y, (p >= 0.5).astype(int))),
            "rows": int(len(group)),
        }
    return out


def _wickets_bucket(series: pd.Series) -> pd.Series:
    return pd.cut(
        series,
        bins=[-0.1, 2.0, 5.0, 10.0],
        labels=["0-2", "3-5", "6-10"],
        include_lowest=True,
    ).astype(str)


def train_score_model(df: pd.DataFrame) -> dict:
    print("\n" + "=" * 60)
    print("TRAINING SCORE MODEL (HistGradientBoostingRegressor)")
    print("=" * 60)

    df = df[df["balls_left"] > 0].copy()
    df["season_str"] = df["season"].astype(str)
    if "season_key" not in df.columns:
        df["season_key"] = pd.to_numeric(df["season_str"].str.split("/").str[0], errors="coerce")

    train_df, test_df = split_by_season(df, "season_key")
    X_train = train_df[CATEGORICAL + NUMERIC]
    y_train = train_df["total_runs"]
    X_test = test_df[CATEGORICAL + NUMERIC]
    y_test = test_df["total_runs"]

    print(f"Training data: {len(train_df):,} rows")
    print(f"Test data: {len(test_df):,} rows")
    print(f"Features: {len(CATEGORICAL + NUMERIC)}")
    print("\nStarting model training (max 250 iterations)...")

    model = HistGradientBoostingRegressor(max_depth=8, learning_rate=0.08, max_iter=250, verbose=1)
    pipeline = Pipeline(
        steps=[
            ("preprocess", build_preprocessor()),
            ("model", model),
        ]
    )

    start_time = time.time()
    pipeline.fit(X_train, y_train)
    training_time = time.time() - start_time
    preds = pipeline.predict(X_test)

    overall = _score_metrics(y_test, preds)
    residuals = (y_test.to_numpy() - preds).astype(float)
    uncertainty_profile = {
        "residual_q10": float(np.quantile(residuals, 0.10)),
        "residual_q90": float(np.quantile(residuals, 0.90)),
        "residual_std": float(np.std(residuals)),
    }
    SCORE_UNCERTAINTY_PATH.write_text(json.dumps(uncertainty_profile, indent=2), encoding="utf-8")

    eval_df = test_df.copy()
    eval_df["wickets_bucket"] = _wickets_bucket(eval_df["wickets"])
    by_phase = _regression_metrics_by_slice(eval_df, preds, "phase")
    by_innings = _regression_metrics_by_slice(eval_df, preds, "innings")
    by_wickets = _regression_metrics_by_slice(eval_df, preds, "wickets_bucket")

    print(f"\n✓ Training completed in {training_time:.2f} seconds")
    print("\nScore Model Performance:")
    print(f"  MAE:  {overall['mae']:.2f} runs")
    print(f"  RMSE: {overall['rmse']:.2f} runs")

    joblib.dump(pipeline, MODELS_DIR / "score_model.pkl")
    joblib.dump(pipeline, MODELS_DIR / "score_model_hgb.pkl")
    print("\n✓ Model saved to models/score_model.pkl")
    print("✓ Uncertainty profile saved to models/score_uncertainty.json")

    return {
        "overall": overall,
        "by_phase": by_phase,
        "by_innings": by_innings,
        "by_wickets_bucket": by_wickets,
        "train_rows": len(train_df),
        "test_rows": len(test_df),
        "training_time": training_time,
        "uncertainty_profile": uncertainty_profile,
    }


def train_win_model(df: pd.DataFrame) -> dict:
    print("\n" + "=" * 60)
    print("TRAINING WIN PROBABILITY MODEL (HistGradientBoostingClassifier)")
    print("=" * 60)

    df = df[df["win"].notna()].copy()
    df = df[df["balls_left"] > 0].copy()
    df["season_str"] = df["season"].astype(str)
    if "season_key" not in df.columns:
        df["season_key"] = pd.to_numeric(df["season_str"].str.split("/").str[0], errors="coerce")

    train_df, calib_df, test_df = split_by_season_three(df, "season_key")
    fit_df = pd.concat([train_df, calib_df], ignore_index=True)
    X_fit = fit_df[CATEGORICAL + NUMERIC]
    y_fit = fit_df["win"].astype(int)
    X_test = test_df[CATEGORICAL + NUMERIC]
    y_test = test_df["win"].astype(int)

    print(f"Training data: {len(fit_df):,} rows")
    print(f"Test data: {len(test_df):,} rows")
    print(f"Features: {len(CATEGORICAL + NUMERIC)}")

    raw_model = HistGradientBoostingClassifier(max_depth=6, learning_rate=0.08, max_iter=250, verbose=1)
    raw_pipeline = Pipeline(
        steps=[
            ("preprocess", build_preprocessor()),
            ("model", raw_model),
        ]
    )

    start_time = time.time()
    raw_pipeline.fit(X_fit, y_fit)
    raw_probs = raw_pipeline.predict_proba(X_test)[:, 1]
    raw_metrics = _win_metrics(y_test, raw_probs)

    calibrated_model = HistGradientBoostingClassifier(max_depth=6, learning_rate=0.08, max_iter=250, verbose=1)
    calibrated_pipeline = Pipeline(
        steps=[
            ("preprocess", build_preprocessor()),
            ("model", calibrated_model),
        ]
    )
    calibrated = CalibratedClassifierCV(calibrated_pipeline, method="isotonic", cv=3)
    calibrated.fit(X_fit, y_fit)
    calibrated_probs = calibrated.predict_proba(X_test)[:, 1]
    calibrated_metrics = _win_metrics(y_test, calibrated_probs)
    training_time = time.time() - start_time

    use_calibrated = calibrated_metrics["log_loss"] <= raw_metrics["log_loss"]
    best_model = calibrated if use_calibrated else raw_pipeline
    best_probs = calibrated_probs if use_calibrated else raw_probs

    eval_df = test_df.copy()
    eval_df["wickets_bucket"] = _wickets_bucket(eval_df["wickets"])
    by_phase = _classification_metrics_by_slice(eval_df, best_probs, "phase")
    by_innings = _classification_metrics_by_slice(eval_df, best_probs, "innings")
    by_wickets = _classification_metrics_by_slice(eval_df, best_probs, "wickets_bucket")

    print(f"\n✓ Training completed in {training_time:.2f} seconds")
    print("\nWin Model Performance (raw):")
    print(f"  Accuracy: {raw_metrics['accuracy']:.1%}")
    print(f"  Log Loss: {raw_metrics['log_loss']:.4f}")
    print(f"  Brier Score: {raw_metrics['brier']:.4f}")
    print("\nWin Model Performance (calibrated):")
    print(f"  Accuracy: {calibrated_metrics['accuracy']:.1%}")
    print(f"  Log Loss: {calibrated_metrics['log_loss']:.4f}")
    print(f"  Brier Score: {calibrated_metrics['brier']:.4f}")

    joblib.dump(raw_pipeline, MODELS_DIR / "win_model_hgb_raw.pkl")
    joblib.dump(calibrated, MODELS_DIR / "win_model_hgb_calibrated.pkl")
    joblib.dump(best_model, MODELS_DIR / "win_model.pkl")
    joblib.dump(best_model, MODELS_DIR / "win_model_hgb.pkl")
    print("\n✓ Model saved to models/win_model.pkl")

    return {
        "selected_variant": "calibrated" if use_calibrated else "raw",
        "raw": raw_metrics,
        "calibrated": calibrated_metrics,
        "selected": calibrated_metrics if use_calibrated else raw_metrics,
        "by_phase": by_phase,
        "by_innings": by_innings,
        "by_wickets_bucket": by_wickets,
        "train_rows": len(train_df),
        "calib_rows": len(calib_df),
        "test_rows": len(test_df),
        "training_time": training_time,
    }


def main() -> None:
    print("\n" + "#" * 60)
    print("#" + " " * 58 + "#")
    print("#  IPL PREDICTION: CPU BASELINE MODEL TRAINING" + " " * 11 + "#")
    print("#" + " " * 58 + "#")
    print("#" * 60)

    start_total = time.time()
    df = pd.read_csv(DATA_PATH, low_memory=False)
    print(f"\nLoaded {len(df):,} training samples")

    df, filter_summary = filter_current_ipl_training_data(df)
    print("\nApplied training filters:")
    print(
        f"  Active teams only: {filter_summary['rows_before_filter']:,} -> {filter_summary['rows_after_filter']:,} rows"
    )
    print(
        f"  Seasons included: {filter_summary['min_season_included']} to {filter_summary['max_season_included']}"
    )
    print(f"  Teams: {', '.join(filter_summary['teams'])}")

    score_report = train_score_model(df)
    win_report = train_win_model(df)

    total_time = time.time() - start_total
    combined_report = {
        "score": score_report,
        "win": win_report,
        "training_filter": filter_summary,
        "total_training_seconds": total_time,
    }
    CPU_REPORT_PATH.write_text(json.dumps(combined_report, indent=2), encoding="utf-8")

    print("\n" + "=" * 60)
    print("FINAL SUMMARY")
    print("=" * 60)
    print(f"\nScore Model Training Time: {score_report.get('training_time', 0):.2f} seconds")
    print(f"Win Model Training Time:   {win_report.get('training_time', 0):.2f} seconds")
    print(f"\nTotal Training Time:       {total_time:.2f} seconds ({total_time/60:.2f} minutes)")
    print("✓ All models trained successfully!")
    print("✓ Evaluation report saved to models/cpu_model_report.json")
    print("=" * 60)


if __name__ == "__main__":
    main()
