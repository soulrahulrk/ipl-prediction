"""Train and evaluate pre-match models with strict hold-out splits.

Pre-match is a low-data setup, so this script intentionally uses regularized,
data-efficient learners with rolling season validation for hyperparameter
selection.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

try:
    from catboost import CatBoostClassifier

    CATBOOST_AVAILABLE = True
except Exception:
    CATBOOST_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

ROOT_DIR = Path(__file__).resolve().parents[1]
FEATURES_PATH = ROOT_DIR / "data" / "processed" / "ipl_features.csv"
MODELS_DIR = ROOT_DIR / "models"
WIN_MODEL_PATH = MODELS_DIR / "pre_match_win_model.pkl"
SCORE_MODEL_PATH = MODELS_DIR / "pre_match_score_model.pkl"
REPORT_PATH = MODELS_DIR / "pre_match_model_report.json"

CATEGORICAL_FEATURES = ["batting_team", "bowling_team", "venue"]
NUMERIC_FEATURES = [
    "batting_team_form",
    "bowling_team_form",
    "batting_team_venue_form",
    "bowling_team_venue_form",
    "batting_vs_bowling_form",
    "venue_avg_first_innings",
    "venue_avg_second_innings",
    "venue_bat_first_win_rate",
]
MODEL_FEATURES = CATEGORICAL_FEATURES + NUMERIC_FEATURES

SCORE_ALPHA_GRID = [0.1, 0.5, 1.0, 3.0, 10.0]
WIN_C_GRID = [0.25, 0.5, 1.0, 2.0, 4.0]
CATBOOST_WIN_PARAMS = {
    "iterations": 600,
    "depth": 5,
    "learning_rate": 0.04,
    "l2_leaf_reg": 8.0,
    "loss_function": "Logloss",
    "eval_metric": "Logloss",
    "verbose": 0,
    "random_seed": 42,
}


def season_to_year(season_value: object) -> int | None:
    if season_value is None:
        return None
    text = str(season_value).strip()
    if not text:
        return None
    first = text.split("/")[0]
    try:
        return int(first)
    except ValueError:
        return None


def split_train_valid_test(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, object]]:
    seasons = sorted(df["season_key"].dropna().unique())
    if len(seasons) < 3:
        raise ValueError("Need at least 3 seasons for strict train/valid/test pre-match evaluation.")

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


def rolling_season_splits(df: pd.DataFrame, min_train_seasons: int = 4) -> list[tuple[pd.DataFrame, pd.DataFrame]]:
    seasons = sorted(df["season_key"].dropna().unique())
    splits: list[tuple[pd.DataFrame, pd.DataFrame]] = []
    for idx in range(min_train_seasons, len(seasons)):
        train_seasons = seasons[:idx]
        valid_season = seasons[idx]
        tr = df[df["season_key"].isin(train_seasons)]
        va = df[df["season_key"] == valid_season]
        if not tr.empty and not va.empty:
            splits.append((tr, va))
    return splits


def make_preprocessor() -> ColumnTransformer:
    cat_pipe = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
        ]
    )
    num_pipe = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
        ]
    )
    return ColumnTransformer(
        transformers=[
            ("cat", cat_pipe, CATEGORICAL_FEATURES),
            ("num", num_pipe, NUMERIC_FEATURES),
        ]
    )


def make_score_pipeline(alpha: float) -> Pipeline:
    return Pipeline(
        steps=[
            ("preprocessor", make_preprocessor()),
            ("regressor", Ridge(alpha=float(alpha), random_state=42)),
        ]
    )


def make_win_pipeline(c_value: float) -> Pipeline:
    return Pipeline(
        steps=[
            ("preprocessor", make_preprocessor()),
            (
                "classifier",
                LogisticRegression(
                    C=float(c_value),
                    max_iter=2000,
                    class_weight="balanced",
                    solver="lbfgs",
                    random_state=42,
                ),
            ),
        ]
    )


def score_metrics(y_true: pd.Series, preds: np.ndarray) -> dict[str, float]:
    return {
        "mae": float(mean_absolute_error(y_true, preds)),
        "rmse": float(mean_squared_error(y_true, preds) ** 0.5),
        "r2": float(r2_score(y_true, preds)),
    }


def win_metrics(y_true: pd.Series, probs: np.ndarray) -> dict[str, float]:
    clipped = np.clip(probs, 1e-6, 1 - 1e-6)
    preds = (clipped >= 0.5).astype(int)
    return {
        "accuracy": float(accuracy_score(y_true, preds)),
        "log_loss": float(log_loss(y_true, clipped, labels=[0, 1])),
        "brier": float(brier_score_loss(y_true, clipped)),
    }


def build_pre_match_frame() -> pd.DataFrame:
    if not FEATURES_PATH.exists():
        raise FileNotFoundError(f"Cannot find data at {FEATURES_PATH}")

    columns = [
        "match_id",
        "season",
        "innings",
        "batting_team",
        "bowling_team",
        "venue",
        "total_runs",
        "winner",
        "batting_team_form",
        "bowling_team_form",
        "batting_team_venue_form",
        "bowling_team_venue_form",
        "batting_vs_bowling_form",
        "venue_avg_first_innings",
        "venue_avg_second_innings",
        "venue_bat_first_win_rate",
    ]
    df = pd.read_csv(FEATURES_PATH, usecols=columns, low_memory=False)
    df_1st = df[df["innings"] == 1].drop_duplicates(subset=["match_id"]).copy()
    df_1st = df_1st.dropna(subset=["season", "batting_team", "bowling_team", "winner", "total_runs", "venue"])
    df_1st["season_key"] = df_1st["season"].apply(season_to_year)
    df_1st = df_1st[df_1st["season_key"].notna()].copy()
    df_1st["season_key"] = df_1st["season_key"].astype(int)
    df_1st["win_target"] = (df_1st["winner"] == df_1st["batting_team"]).astype(int)
    return df_1st


def as_catboost_features(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame[MODEL_FEATURES].copy()
    out[CATEGORICAL_FEATURES] = out[CATEGORICAL_FEATURES].fillna("Unknown").astype(str)
    return out


def choose_score_alpha(selection_df: pd.DataFrame) -> tuple[float, list[dict[str, float]]]:
    splits = rolling_season_splits(selection_df)
    if not splits:
        return 1.0, []

    summary: list[dict[str, float]] = []
    best_alpha = 1.0
    best_mae = float("inf")
    for alpha in SCORE_ALPHA_GRID:
        fold_mae: list[float] = []
        for tr, va in splits:
            model = make_score_pipeline(alpha)
            model.fit(tr[MODEL_FEATURES], tr["total_runs"].astype(float))
            preds = model.predict(va[MODEL_FEATURES])
            fold_mae.append(float(mean_absolute_error(va["total_runs"].astype(float), preds)))
        mean_mae = float(np.mean(fold_mae))
        summary.append({"alpha": float(alpha), "cv_mae": mean_mae})
        if mean_mae < best_mae:
            best_mae = mean_mae
            best_alpha = float(alpha)

    return best_alpha, summary


def choose_win_c(selection_df: pd.DataFrame) -> tuple[float, list[dict[str, float]]]:
    splits = rolling_season_splits(selection_df)
    if not splits:
        return 1.0, []

    summary: list[dict[str, float]] = []
    best_c = 1.0
    best_logloss = float("inf")
    for c_value in WIN_C_GRID:
        fold_ll: list[float] = []
        for tr, va in splits:
            if tr["win_target"].nunique() < 2 or va["win_target"].nunique() < 2:
                continue
            model = make_win_pipeline(c_value)
            model.fit(tr[MODEL_FEATURES], tr["win_target"].astype(int))
            probs = model.predict_proba(va[MODEL_FEATURES])[:, 1]
            fold_ll.append(float(log_loss(va["win_target"].astype(int), np.clip(probs, 1e-6, 1 - 1e-6), labels=[0, 1])))
        if not fold_ll:
            continue
        mean_ll = float(np.mean(fold_ll))
        summary.append({"c": float(c_value), "cv_log_loss": mean_ll})
        if mean_ll < best_logloss:
            best_logloss = mean_ll
            best_c = float(c_value)

    return best_c, summary


def main() -> None:
    logging.info("Loading pre-match dataset...")
    df_1st = build_pre_match_frame()
    logging.info("Prepared %s pre-match rows.", len(df_1st))

    train_df, valid_df, test_df, split_summary = split_train_valid_test(df_1st)
    logging.info("Split summary: %s", split_summary)

    X_train = train_df[MODEL_FEATURES]
    X_valid = valid_df[MODEL_FEATURES]
    X_test = test_df[MODEL_FEATURES]

    y_win_train = train_df["win_target"].astype(int)
    y_win_valid = valid_df["win_target"].astype(int)
    y_win_test = test_df["win_target"].astype(int)

    y_score_train = train_df["total_runs"].astype(float)
    y_score_valid = valid_df["total_runs"].astype(float)
    y_score_test = test_df["total_runs"].astype(float)

    selection_df = pd.concat([train_df, valid_df], ignore_index=True)
    selected_alpha, score_cv = choose_score_alpha(selection_df)
    selected_c, win_cv = choose_win_c(selection_df)
    logging.info("Selected pre-match score alpha=%s and logistic win C=%s from rolling-season CV", selected_alpha, selected_c)

    logging.info("Training pre-match win classifier...")
    win_pipeline = make_win_pipeline(selected_c)
    win_pipeline.fit(X_train, y_win_train)

    win_train_probs = win_pipeline.predict_proba(X_train)[:, 1]
    win_valid_probs = win_pipeline.predict_proba(X_valid)[:, 1]
    win_test_probs = win_pipeline.predict_proba(X_test)[:, 1]

    selected_win_model = "logistic_regression"
    selected_win_model_details: dict[str, float | int | str | None] = {
        "win_c": float(selected_c),
        "catboost_best_iteration": None,
    }
    best_valid_logloss = float(win_metrics(y_win_valid, win_valid_probs)["log_loss"])

    if CATBOOST_AVAILABLE and y_win_train.nunique() >= 2 and y_win_valid.nunique() >= 2:
        logging.info("Training CatBoost pre-match win candidate...")
        X_train_cb = as_catboost_features(train_df)
        X_valid_cb = as_catboost_features(valid_df)
        X_test_cb = as_catboost_features(test_df)

        cb_candidate = CatBoostClassifier(**CATBOOST_WIN_PARAMS)
        cb_candidate.fit(
            X_train_cb,
            y_win_train,
            cat_features=CATEGORICAL_FEATURES,
            eval_set=(X_valid_cb, y_win_valid),
            use_best_model=True,
            early_stopping_rounds=40,
        )

        cb_train_probs = cb_candidate.predict_proba(X_train_cb)[:, 1]
        cb_valid_probs = cb_candidate.predict_proba(X_valid_cb)[:, 1]
        cb_test_probs = cb_candidate.predict_proba(X_test_cb)[:, 1]
        cb_valid_logloss = float(win_metrics(y_win_valid, cb_valid_probs)["log_loss"])

        if cb_valid_logloss < best_valid_logloss:
            selected_win_model = "catboost_classifier"
            best_valid_logloss = cb_valid_logloss
            selected_win_model_details = {
                "win_c": float(selected_c),
                "catboost_best_iteration": int(cb_candidate.get_best_iteration() or CATBOOST_WIN_PARAMS["iterations"]),
            }
            win_pipeline = cb_candidate
            win_train_probs = cb_train_probs
            win_valid_probs = cb_valid_probs
            win_test_probs = cb_test_probs

    logging.info("Training pre-match score regressor...")
    score_pipeline = make_score_pipeline(selected_alpha)
    score_pipeline.fit(X_train, y_score_train)

    score_train_preds = score_pipeline.predict(X_train)
    score_valid_preds = score_pipeline.predict(X_valid)
    score_test_preds = score_pipeline.predict(X_test)

    # Refit final artifacts on train+valid after strict hold-out evaluation.
    fit_df = pd.concat([train_df, valid_df], ignore_index=True)
    X_fit = fit_df[MODEL_FEATURES]
    y_fit_win = fit_df["win_target"].astype(int)
    y_fit_score = fit_df["total_runs"].astype(float)

    if selected_win_model == "catboost_classifier" and CATBOOST_AVAILABLE:
        X_fit_cb = as_catboost_features(fit_df)
        best_iteration = int(selected_win_model_details.get("catboost_best_iteration") or CATBOOST_WIN_PARAMS["iterations"])
        final_params = dict(CATBOOST_WIN_PARAMS)
        final_params["iterations"] = max(20, best_iteration)
        final_win_pipeline = CatBoostClassifier(**final_params)
        final_win_pipeline.fit(X_fit_cb, y_fit_win, cat_features=CATEGORICAL_FEATURES)
    else:
        final_win_pipeline = make_win_pipeline(selected_c)
        final_win_pipeline.fit(X_fit, y_fit_win)

    final_score_pipeline = make_score_pipeline(selected_alpha)
    final_score_pipeline.fit(X_fit, y_fit_score)

    report = {
        "task": "pre_match",
        "modeling_strategy": "low_data_regularized_ml_with_rolling_season_cv",
        "features": {
            "categorical": CATEGORICAL_FEATURES,
            "numeric": NUMERIC_FEATURES,
        },
        "split": split_summary,
        "selection": {
            "score_model": "ridge",
            "score_alpha": float(selected_alpha),
            "score_cv": score_cv,
            "win_model": selected_win_model,
            "win_c": float(selected_c),
            "win_model_details": selected_win_model_details,
            "win_cv": win_cv,
        },
        "win_metrics": {
            "train": win_metrics(y_win_train, win_train_probs),
            "valid": win_metrics(y_win_valid, win_valid_probs),
            "test": win_metrics(y_win_test, win_test_probs),
        },
        "score_metrics": {
            "train": score_metrics(y_score_train, score_train_preds),
            "valid": score_metrics(y_score_valid, score_valid_preds),
            "test": score_metrics(y_score_test, score_test_preds),
        },
        "artifacts": {
            "pre_match_win_model": str(WIN_MODEL_PATH.relative_to(ROOT_DIR)),
            "pre_match_score_model": str(SCORE_MODEL_PATH.relative_to(ROOT_DIR)),
            "report": str(REPORT_PATH.relative_to(ROOT_DIR)),
        },
    }

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(final_win_pipeline, WIN_MODEL_PATH)
    joblib.dump(final_score_pipeline, SCORE_MODEL_PATH)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    logging.info("Saved %s", WIN_MODEL_PATH.name)
    logging.info("Saved %s", SCORE_MODEL_PATH.name)
    logging.info("Saved %s", REPORT_PATH.name)
    logging.info("Hold-out win test metrics: %s", report["win_metrics"]["test"])
    logging.info("Hold-out score test metrics: %s", report["score_metrics"]["test"])


if __name__ == "__main__":
    main()
