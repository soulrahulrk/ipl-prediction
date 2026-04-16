from __future__ import annotations

from pathlib import Path
import sys

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, mean_absolute_error, mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipl_predictor import CATEGORICAL_FEATURES, MODELS_DIR, NUMERIC_FEATURES, PROCESSED_DIR

try:
    from xgboost import XGBClassifier, XGBRegressor
except Exception as exc:  # pragma: no cover
    raise RuntimeError("xgboost is required for this script") from exc

try:
    from catboost import CatBoostClassifier, CatBoostRegressor

    CATBOOST_AVAILABLE = True
except Exception:
    CATBOOST_AVAILABLE = False


DATA_PATH = PROCESSED_DIR / "ipl_features.csv"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

CATEGORICAL = CATEGORICAL_FEATURES
NUMERIC = NUMERIC_FEATURES


def split_by_season(df: pd.DataFrame, season_col: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    seasons = sorted(df[season_col].dropna().unique())
    if len(seasons) <= 1:
        return df, df
    test_seasons = seasons[-2:] if len(seasons) > 2 else seasons[-1:]
    train_df = df[~df[season_col].isin(test_seasons)]
    test_df = df[df[season_col].isin(test_seasons)]
    return train_df, test_df


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


def get_xgb_params(task: str) -> dict:
    params = {
        "n_estimators": 500,
        "max_depth": 6,
        "learning_rate": 0.05,
        "subsample": 0.9,
        "colsample_bytree": 0.8,
        "reg_lambda": 1.0,
        "tree_method": "gpu_hist",
        "predictor": "gpu_predictor",
        "random_state": 42,
    }
    if task == "clf":
        params["eval_metric"] = "logloss"
    return params


def train_xgboost_score(df: pd.DataFrame) -> dict:
    df = df[df["balls_left"] > 0].copy()
    df["season_str"] = df["season"].astype(str)
    df["season_key"] = pd.to_numeric(df["season_str"].str.split("/").str[0], errors="coerce")

    train_df, test_df = split_by_season(df, "season_key")
    X_train = train_df[CATEGORICAL + NUMERIC]
    y_train = train_df["total_runs"]
    X_test = test_df[CATEGORICAL + NUMERIC]
    y_test = test_df["total_runs"]

    params = get_xgb_params("reg")
    model = XGBRegressor(**params)
    pipeline = Pipeline(
        steps=[
            ("preprocess", build_preprocessor()),
            ("model", model),
        ]
    )

    try:
        pipeline.fit(X_train, y_train)
    except Exception:
        model = XGBRegressor(**{**params, "tree_method": "hist", "predictor": "auto"})
        pipeline = Pipeline(
            steps=[
                ("preprocess", build_preprocessor()),
                ("model", model),
            ]
        )
        pipeline.fit(X_train, y_train)

    preds = pipeline.predict(X_test)
    mae = mean_absolute_error(y_test, preds)
    rmse = mean_squared_error(y_test, preds) ** 0.5

    joblib.dump(pipeline, MODELS_DIR / "score_model_xgb.pkl")

    return {
        "mae": mae,
        "rmse": rmse,
        "train_rows": len(train_df),
        "test_rows": len(test_df),
    }


def train_xgboost_win(df: pd.DataFrame) -> dict:
    df = df[df["win"].notna()].copy()
    df = df[df["balls_left"] > 0].copy()
    df["season_str"] = df["season"].astype(str)
    df["season_key"] = pd.to_numeric(df["season_str"].str.split("/").str[0], errors="coerce")

    train_df, test_df = split_by_season(df, "season_key")
    X_train = train_df[CATEGORICAL + NUMERIC]
    y_train = train_df["win"].astype(int)
    X_test = test_df[CATEGORICAL + NUMERIC]
    y_test = test_df["win"].astype(int)

    params = get_xgb_params("clf")
    model = XGBClassifier(**params)
    pipeline = Pipeline(
        steps=[
            ("preprocess", build_preprocessor()),
            ("model", model),
        ]
    )

    try:
        pipeline.fit(X_train, y_train)
    except Exception:
        model = XGBClassifier(**{**params, "tree_method": "hist", "predictor": "auto"})
        pipeline = Pipeline(
            steps=[
                ("preprocess", build_preprocessor()),
                ("model", model),
            ]
        )
        pipeline.fit(X_train, y_train)

    calibrated = CalibratedClassifierCV(pipeline, method="isotonic", cv=3)
    calibrated.fit(X_train, y_train)

    probs = calibrated.predict_proba(X_test)[:, 1]
    preds = (probs >= 0.5).astype(int)

    ll = log_loss(y_test, probs)
    brier = brier_score_loss(y_test, probs)
    acc = accuracy_score(y_test, preds)

    joblib.dump(calibrated, MODELS_DIR / "win_model_xgb.pkl")

    return {
        "log_loss": ll,
        "brier": brier,
        "accuracy": acc,
        "train_rows": len(train_df),
        "test_rows": len(test_df),
    }


def train_catboost_score(df: pd.DataFrame) -> dict:
    df = df[df["balls_left"] > 0].copy()
    df["season_str"] = df["season"].astype(str)
    df["season_key"] = pd.to_numeric(df["season_str"].str.split("/").str[0], errors="coerce")

    train_df, test_df = split_by_season(df, "season_key")
    X_train = train_df[CATEGORICAL + NUMERIC]
    y_train = train_df["total_runs"]
    X_test = test_df[CATEGORICAL + NUMERIC]
    y_test = test_df["total_runs"]

    cat_features = [X_train.columns.get_loc(col) for col in CATEGORICAL]

    model = CatBoostRegressor(
        iterations=800,
        depth=8,
        learning_rate=0.05,
        loss_function="RMSE",
        verbose=False,
    )

    try:
        model.set_params(task_type="GPU")
        model.fit(X_train, y_train, cat_features=cat_features)
    except Exception:
        model.set_params(task_type="CPU")
        model.fit(X_train, y_train, cat_features=cat_features)

    preds = model.predict(X_test)
    mae = mean_absolute_error(y_test, preds)
    rmse = mean_squared_error(y_test, preds) ** 0.5

    joblib.dump(model, MODELS_DIR / "score_model_cat.pkl")

    return {
        "mae": mae,
        "rmse": rmse,
        "train_rows": len(train_df),
        "test_rows": len(test_df),
    }


def train_catboost_win(df: pd.DataFrame) -> dict:
    df = df[df["win"].notna()].copy()
    df = df[df["balls_left"] > 0].copy()
    df["season_str"] = df["season"].astype(str)
    df["season_key"] = pd.to_numeric(df["season_str"].str.split("/").str[0], errors="coerce")

    train_df, test_df = split_by_season(df, "season_key")
    X_train = train_df[CATEGORICAL + NUMERIC]
    y_train = train_df["win"].astype(int)
    X_test = test_df[CATEGORICAL + NUMERIC]
    y_test = test_df["win"].astype(int)

    cat_features = [X_train.columns.get_loc(col) for col in CATEGORICAL]

    model = CatBoostClassifier(
        iterations=800,
        depth=8,
        learning_rate=0.05,
        loss_function="Logloss",
        verbose=False,
    )

    try:
        model.set_params(task_type="GPU")
        model.fit(X_train, y_train, cat_features=cat_features)
    except Exception:
        model.set_params(task_type="CPU")
        model.fit(X_train, y_train, cat_features=cat_features)

    probs = model.predict_proba(X_test)[:, 1]
    preds = (probs >= 0.5).astype(int)

    ll = log_loss(y_test, probs)
    brier = brier_score_loss(y_test, probs)
    acc = accuracy_score(y_test, preds)

    joblib.dump(model, MODELS_DIR / "win_model_cat.pkl")

    return {
        "log_loss": ll,
        "brier": brier,
        "accuracy": acc,
        "train_rows": len(train_df),
        "test_rows": len(test_df),
    }


def main() -> None:
    df = pd.read_csv(DATA_PATH, low_memory=False)

    print("XGBOOST SCORE")
    xgb_score = train_xgboost_score(df)
    for key, value in xgb_score.items():
        print(f"{key}: {value}")

    print("\nXGBOOST WIN")
    xgb_win = train_xgboost_win(df)
    for key, value in xgb_win.items():
        print(f"{key}: {value}")

    if CATBOOST_AVAILABLE:
        print("\nCATBOOST SCORE")
        cat_score = train_catboost_score(df)
        for key, value in cat_score.items():
            print(f"{key}: {value}")

        print("\nCATBOOST WIN")
        cat_win = train_catboost_win(df)
        for key, value in cat_win.items():
            print(f"{key}: {value}")
    else:
        print("\nCatBoost not installed; skipping CatBoost training.")


if __name__ == "__main__":
    np.random.seed(42)
    main()
