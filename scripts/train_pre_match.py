"""
Train Pre-Match Deep Learning models for IPL.

This script creates lightweight neural networks using sklearn to predict:
1. Win probability (MLPClassifier)
2. Team 1 score (MLPRegressor)
"""

import logging
from pathlib import Path

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.neural_network import MLPClassifier, MLPRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

ROOT_DIR = Path(__file__).resolve().parents[1]
FEATURES_PATH = ROOT_DIR / "data" / "processed" / "ipl_features.csv"
MODELS_DIR = ROOT_DIR / "models"


def main():
    logging.info("Loading features data...")
    if not FEATURES_PATH.exists():
        logging.error(f"Cannot find data at {FEATURES_PATH}")
        return

    # Load data in chunks if large, but we only need a few columns for pre-match
    columns_to_load = [
        "match_id",
        "innings",
        "batting_team",
        "bowling_team",
        "venue",
        "total_runs",
        "winner",
    ]
    df = pd.read_csv(FEATURES_PATH, usecols=columns_to_load, low_memory=False)

    # We want a pre-match snapshot. 
    # Let's take only info from the 1st innings to define a matchup.
    # In pre-match, Team 1 = batting_team (assumed), Team 2 = bowling_team.
    df_1st = df[df["innings"] == 1].drop_duplicates(subset=["match_id"]).copy()

    # Drop unknowns
    df_1st = df_1st.dropna(subset=["batting_team", "bowling_team", "winner", "total_runs", "venue"])

    logging.info(f"Loaded {len(df_1st)} matches for training.")

    # Target 1: Win (1 if Team 1 (batting_team) wins, else 0)
    df_1st["win_target"] = (df_1st["winner"] == df_1st["batting_team"]).astype(int)

    # Output features / Dataset
    X = df_1st[["batting_team", "bowling_team", "venue"]]
    y_win = df_1st["win_target"]
    y_score = df_1st["total_runs"]

    # Build Pipeline with OneHotEncoder and MLP (Deep Learning)
    # We use DL layers (e.g. 64, 32)
    categorical_features = ["batting_team", "bowling_team", "venue"]

    preprocessor = ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), categorical_features)
        ]
    )

    logging.info("Training Pre-Match Win Probability Model (MLP Classifier)...")
    win_pipeline = Pipeline(
        steps=[
            ("preprocessor", preprocessor),
            # small neural network structure for tabular discrete vars
            ("classifier", MLPClassifier(hidden_layer_sizes=(128, 64), max_iter=500, early_stopping=True, random_state=42)),
        ]
    )
    win_pipeline.fit(X, y_win)
    win_acc = win_pipeline.score(X, y_win)
    logging.info(f"Win Model Accuracy on training data: {win_acc:.2%}")

    logging.info("Training Pre-Match Score Prediction Model (MLP Regressor)...")
    score_pipeline = Pipeline(
        steps=[
            ("preprocessor", preprocessor),
            # scaling target runs wouldn't hurt but MLPRegressor can handle it 
            # with standardizer on features (handled sparsely).
            ("regressor", MLPRegressor(hidden_layer_sizes=(128, 64), max_iter=500, early_stopping=True, random_state=42)),
        ]
    )
    score_pipeline.fit(X, y_score)
    score_r2 = score_pipeline.score(X, y_score)
    logging.info(f"Score Model R2 on training data: {score_r2:.4f}")

    # Save models
    MODELS_DIR.mkdir(exist_ok=True)
    win_path = MODELS_DIR / "pre_match_win_model.pkl"
    score_path = MODELS_DIR / "pre_match_score_model.pkl"

    joblib.dump(win_pipeline, win_path)
    joblib.dump(score_pipeline, score_path)

    logging.info(f"Saved Win model to {win_path.name}")
    logging.info(f"Saved Score model to {score_path.name}")


if __name__ == "__main__":
    main()
