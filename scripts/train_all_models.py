"""
train_all_models.py
====================
Comprehensive model trainer for IPL prediction.

Trains and compares:
  ML  : HistGradientBoosting, RandomForest, XGBoost, CatBoost
  DL  : PyTorch Entity-Embedding Network (if CUDA available, else CPU)

Splits:
  Train  : all seasons except last 2
  Valid  : season[-2]
  Test   : 2026 (current season hold-out)

Promotes best score + win models as production models.
Saves full comparison report to models/all_models_report.json

Usage:
  python scripts/train_all_models.py
  python scripts/train_all_models.py --skip-dl   # skip PyTorch training
  python scripts/train_all_models.py --quick      # small RF/HGB only (fast test)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import warnings
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    log_loss,
    mean_absolute_error,
    mean_squared_error,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder

warnings.filterwarnings("ignore")
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "4")

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

DATA_PATH   = PROCESSED_DIR / "ipl_features.csv"
REPORT_PATH = MODELS_DIR / "all_models_report.json"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

CAT_FEATS = CATEGORICAL_FEATURES
NUM_FEATS  = NUMERIC_FEATURES
ALL_FEATS  = CAT_FEATS + NUM_FEATS

# ── helpers ────────────────────────────────────────────────────────────────────
def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def season_int(s) -> int:
    return season_to_year(s) or 0


def load_and_prepare(min_year: int = 2007) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load ipl_features, filter active teams, split train/valid/test."""
    log("Loading ipl_features.csv ...")
    df = pd.read_csv(DATA_PATH, low_memory=False)

    # Backward compatibility: older feature snapshots may not include season_str.
    if "season_str" not in df.columns and "season" in df.columns:
        df["season_str"] = df["season"].astype(str)

    df["season_int"] = df["season"].apply(season_int)

    # Keep only active IPL teams
    mask = df["batting_team"].isin(ACTIVE_IPL_TEAMS_2026) & df["bowling_team"].isin(ACTIVE_IPL_TEAMS_2026)
    df = df[mask & (df["season_int"] >= min_year)].copy()
    log(f"After filter: {len(df):,} rows  |  seasons: {sorted(df['season_int'].unique())}")

    seasons = sorted(df["season_int"].unique())
    test_yr   = seasons[-1]          # 2026 hold-out
    valid_yr  = seasons[-2]          # 2025 validation
    train_yrs = seasons[:-2]         # 2007–2024

    train = df[df["season_int"].isin(train_yrs)].copy()
    valid = df[df["season_int"] == valid_yr].copy()
    test  = df[df["season_int"] == test_yr].copy()
    log(f"Train: {len(train):,}  Valid: {len(valid):,}  Test: {len(test):,}")
    return train, valid, test


def prep_score(df: pd.DataFrame):
    """Filter rows suitable for score prediction (ongoing innings)."""
    return df[(df["balls_left"] > 0) & df["total_runs"].notna()].copy()


def prep_win(df: pd.DataFrame):
    """Filter rows suitable for win prediction."""
    return df[(df["balls_left"] > 0) & df["win"].notna()].copy()


# ── preprocessors ─────────────────────────────────────────────────────────────
def make_hgb_preprocessor() -> ColumnTransformer:
    """HGB natively handles NaN; just ordinal-encode categoricals."""
    return ColumnTransformer(
        transformers=[
            ("num", SimpleImputer(strategy="constant", fill_value=0), NUM_FEATS),
            ("cat", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1), CAT_FEATS),
        ]
    )


def make_tree_preprocessor() -> ColumnTransformer:
    """For XGBoost / RF — OHE cats, fill numeric with 0."""
    from sklearn.preprocessing import OneHotEncoder
    return ColumnTransformer(
        transformers=[
            ("num", SimpleImputer(strategy="constant", fill_value=0), NUM_FEATS),
            ("cat", Pipeline([
                ("imp", SimpleImputer(strategy="constant", fill_value="Unknown")),
                ("ohe", OneHotEncoder(handle_unknown="ignore", sparse_output=False, dtype=np.float32)),
            ]), CAT_FEATS),
        ]
    )


# ── score models ──────────────────────────────────────────────────────────────
def train_score_models(train: pd.DataFrame, valid: pd.DataFrame, test: pd.DataFrame,
                       quick: bool = False) -> list[dict]:
    results = []

    tr = prep_score(train)
    va = prep_score(valid)
    te = prep_score(test)

    X_tr, y_tr = tr[ALL_FEATS], tr["total_runs"]
    X_va, y_va = va[ALL_FEATS], va["total_runs"]
    X_te, y_te = te[ALL_FEATS], te["total_runs"]

    tv_tr = pd.concat([tr, va])
    X_tv, y_tv = tv_tr[ALL_FEATS], tv_tr["total_runs"]

    log("  [Score] Training HistGradientBoostingRegressor ...")
    t0 = time.time()
    hgb_pre = make_hgb_preprocessor()
    hgb = Pipeline([
        ("pre", hgb_pre),
        ("m", HistGradientBoostingRegressor(max_iter=400, max_depth=8,
                                             learning_rate=0.07, l2_regularization=0.1,
                                             random_state=42, early_stopping=False)),
    ])
    hgb.fit(X_tr, y_tr)
    r = _score_metrics(hgb, X_te, y_te, "HGB", time.time() - t0)
    r["val_mae"] = round(float(mean_absolute_error(y_va, hgb.predict(X_va))), 3)
    results.append(r)
    joblib.dump(hgb, MODELS_DIR / "score_model_hgb2.pkl")

    if not quick:
        log("  [Score] Training XGBoost ...")
        import xgboost as xgb
        t0 = time.time()
        pre = make_tree_preprocessor()
        X_tr_enc = pre.fit_transform(X_tr)
        X_va_enc = pre.transform(X_va)
        X_te_enc = pre.transform(X_te)
        xg = xgb.XGBRegressor(
            n_estimators=600, max_depth=7, learning_rate=0.06,
            subsample=0.8, colsample_bytree=0.8, reg_lambda=1.5,
            device="cuda" if _has_gpu() else "cpu",
            tree_method="hist", early_stopping_rounds=30,
            eval_metric="rmse", random_state=42, n_jobs=-1,
        )
        xg.fit(X_tr_enc, y_tr, eval_set=[(X_va_enc, y_va)], verbose=False)
        # Refit on train+valid for final
        X_tv_enc = pre.transform(X_tv)
        xg_final = xgb.XGBRegressor(
            n_estimators=xg.best_iteration + 1, max_depth=7, learning_rate=0.06,
            subsample=0.8, colsample_bytree=0.8, reg_lambda=1.5,
            device="cuda" if _has_gpu() else "cpu",
            tree_method="hist", random_state=42, n_jobs=-1,
        )
        xg_final.fit(X_tv_enc, y_tv)
        r = _score_metrics_raw(xg_final, X_te_enc, y_te, "XGBoost", time.time() - t0)
        r["val_mae"] = round(float(mean_absolute_error(y_va, xg.predict(X_va_enc))), 3)
        results.append(r)
        pkg = {"pre": pre, "model": xg_final}
        joblib.dump(pkg, MODELS_DIR / "score_model_xgb2.pkl")

        log("  [Score] Training CatBoost ...")
        from catboost import CatBoostRegressor
        t0 = time.time()
        cat_idx = list(range(len(NUM_FEATS), len(NUM_FEATS) + len(CAT_FEATS)))
        X_tr_cb = X_tr.copy(); X_tr_cb[CAT_FEATS] = X_tr_cb[CAT_FEATS].fillna("Unknown").astype(str)
        X_va_cb = X_va.copy(); X_va_cb[CAT_FEATS] = X_va_cb[CAT_FEATS].fillna("Unknown").astype(str)
        X_te_cb = X_te.copy(); X_te_cb[CAT_FEATS] = X_te_cb[CAT_FEATS].fillna("Unknown").astype(str)
        X_tv_cb = X_tv.copy(); X_tv_cb[CAT_FEATS] = X_tv_cb[CAT_FEATS].fillna("Unknown").astype(str)

        cb = CatBoostRegressor(
            iterations=800, depth=8, learning_rate=0.07,
            l2_leaf_reg=2, cat_features=CAT_FEATS,
            task_type="GPU" if _has_gpu() else "CPU",
            eval_metric="RMSE", early_stopping_rounds=40,
            verbose=0, random_seed=42,
        )
        cb.fit(X_tr_cb, y_tr, eval_set=(X_va_cb, y_va))
        best_iters = cb.best_iteration_ or 800
        cb_final = CatBoostRegressor(
            iterations=best_iters, depth=8, learning_rate=0.07,
            l2_leaf_reg=2, cat_features=CAT_FEATS,
            task_type="GPU" if _has_gpu() else "CPU",
            verbose=0, random_seed=42,
        )
        cb_final.fit(X_tv_cb, y_tv)
        r = _score_metrics_raw(cb_final, X_te_cb, y_te, "CatBoost", time.time() - t0)
        r["val_mae"] = round(float(mean_absolute_error(y_va, cb.predict(X_va_cb))), 3)
        results.append(r)
        joblib.dump(cb_final, MODELS_DIR / "score_model_cat2.pkl")

        if not quick:
            log("  [Score] Training RandomForest (sampled, fast) ...")
            t0 = time.time()
            pre_rf = make_tree_preprocessor()
            # Use 20% of train for RF (too slow on full data)
            tr_rf = X_tr.sample(frac=0.25, random_state=42)
            y_rf  = y_tr.loc[tr_rf.index]
            X_tr_rf = pre_rf.fit_transform(tr_rf)
            X_te_rf = pre_rf.transform(X_te)
            rf = RandomForestRegressor(n_estimators=150, max_depth=12, n_jobs=-1,
                                       random_state=42, min_samples_leaf=4)
            rf.fit(X_tr_rf, y_rf)
            r = _score_metrics_raw(rf, X_te_rf, y_te, "RandomForest", time.time() - t0)
            r["val_mae"] = round(float(mean_absolute_error(y_va, rf.predict(pre_rf.transform(X_va)))), 3)
            results.append(r)
            pkg = {"pre": pre_rf, "model": rf}
            joblib.dump(pkg, MODELS_DIR / "score_model_rf2.pkl")

    return results


# ── win models ────────────────────────────────────────────────────────────────
def train_win_models(train: pd.DataFrame, valid: pd.DataFrame, test: pd.DataFrame,
                     quick: bool = False) -> list[dict]:
    results = []

    tr = prep_win(train)
    va = prep_win(valid)
    te = prep_win(test)

    X_tr, y_tr = tr[ALL_FEATS], tr["win"].astype(int)
    X_va, y_va = va[ALL_FEATS], va["win"].astype(int)
    X_te, y_te = te[ALL_FEATS], te["win"].astype(int)

    tv_tr = pd.concat([tr, va])
    X_tv, y_tv = tv_tr[ALL_FEATS], tv_tr["win"].astype(int)

    log("  [Win] Training HistGradientBoostingClassifier ...")
    t0 = time.time()
    hgb_base = Pipeline([
        ("pre", make_hgb_preprocessor()),
        ("m", HistGradientBoostingClassifier(max_iter=400, max_depth=6,
                                              learning_rate=0.07, l2_regularization=0.1,
                                              random_state=42)),
    ])
    # sklearn>=1.8 no longer supports cv="prefit" in CalibratedClassifierCV.
    # Fit calibrated model directly on train+valid with CV-based calibration.
    hgb_cal = CalibratedClassifierCV(hgb_base, method="isotonic", cv=5)
    hgb_cal.fit(X_tv, y_tv)
    r = _win_metrics(hgb_cal, X_te, y_te, "HGB", time.time() - t0)
    results.append(r)
    joblib.dump(hgb_cal, MODELS_DIR / "win_model_hgb2.pkl")

    if not quick:
        log("  [Win] Training XGBoost ...")
        import xgboost as xgb
        t0 = time.time()
        pre = make_tree_preprocessor()
        X_tr_enc = pre.fit_transform(X_tr)
        X_va_enc = pre.transform(X_va)
        X_te_enc = pre.transform(X_te)
        X_tv_enc = pre.transform(X_tv)
        xg = xgb.XGBClassifier(
            n_estimators=600, max_depth=6, learning_rate=0.06,
            subsample=0.8, colsample_bytree=0.8, reg_lambda=1.5,
            device="cuda" if _has_gpu() else "cpu",
            tree_method="hist", early_stopping_rounds=30,
            eval_metric="logloss", random_state=42, n_jobs=-1,
        )
        xg.fit(X_tr_enc, y_tr, eval_set=[(X_va_enc, y_va)], verbose=False)
        xg_final = xgb.XGBClassifier(
            n_estimators=xg.best_iteration + 1, max_depth=6, learning_rate=0.06,
            subsample=0.8, colsample_bytree=0.8, reg_lambda=1.5,
            device="cuda" if _has_gpu() else "cpu",
            tree_method="hist", random_state=42, n_jobs=-1,
        )
        xg_final.fit(X_tv_enc, y_tv)
        xg_cal = CalibratedClassifierCV(xg_final, method="isotonic", cv=5)
        xg_cal.fit(X_tv_enc, y_tv)
        r = _win_metrics_raw(xg_cal, X_te_enc, y_te, "XGBoost", time.time() - t0)
        results.append(r)
        pkg = {"pre": pre, "model": xg_cal}
        joblib.dump(pkg, MODELS_DIR / "win_model_xgb2.pkl")

        log("  [Win] Training CatBoost ...")
        from catboost import CatBoostClassifier
        t0 = time.time()
        X_tr_cb = X_tr.copy(); X_tr_cb[CAT_FEATS] = X_tr_cb[CAT_FEATS].fillna("Unknown").astype(str)
        X_va_cb = X_va.copy(); X_va_cb[CAT_FEATS] = X_va_cb[CAT_FEATS].fillna("Unknown").astype(str)
        X_te_cb = X_te.copy(); X_te_cb[CAT_FEATS] = X_te_cb[CAT_FEATS].fillna("Unknown").astype(str)
        X_tv_cb = X_tv.copy(); X_tv_cb[CAT_FEATS] = X_tv_cb[CAT_FEATS].fillna("Unknown").astype(str)

        cb = CatBoostClassifier(
            iterations=800, depth=7, learning_rate=0.07,
            l2_leaf_reg=2, cat_features=CAT_FEATS,
            task_type="GPU" if _has_gpu() else "CPU",
            eval_metric="Logloss", early_stopping_rounds=40,
            verbose=0, random_seed=42,
        )
        cb.fit(X_tr_cb, y_tr, eval_set=(X_va_cb, y_va))
        best_iters = cb.best_iteration_ or 800
        cb_final = CatBoostClassifier(
            iterations=best_iters, depth=7, learning_rate=0.07,
            l2_leaf_reg=2, cat_features=CAT_FEATS,
            task_type="GPU" if _has_gpu() else "CPU",
            verbose=0, random_seed=42,
        )
        cb_final.fit(X_tv_cb, y_tv)
        r = _win_metrics_raw(cb_final, X_te_cb, y_te, "CatBoost", time.time() - t0)
        results.append(r)
        joblib.dump(cb_final, MODELS_DIR / "win_model_cat2.pkl")

    return results


# ── deep learning ─────────────────────────────────────────────────────────────
def train_dl_models(train: pd.DataFrame, valid: pd.DataFrame, test: pd.DataFrame) -> list[dict]:
    """Train Entity-Embedding PyTorch model for score and win."""
    try:
        import torch
        from ipl_predictor.torch_tabular import TabularTensorPreprocessor, _EntityEmbeddingNet
    except ImportError as e:
        log(f"  [DL] Skipping — {e}")
        return []

    device = "cuda" if torch.cuda.is_available() else "cpu"
    log(f"  [DL] Device: {device}")
    results = []

    # ── Score DL ──────────────────────────────────────────────────────────────
    log("  [DL] Training Entity-Embedding Score model ...")
    t0 = time.time()
    tr_s = prep_score(train)
    va_s = prep_score(valid)
    te_s = prep_score(test)
    tv_s = pd.concat([tr_s, va_s])

    proc = TabularTensorPreprocessor.fit(tr_s, CAT_FEATS, NUM_FEATS)
    X_tr_c, X_tr_n = proc.transform(tr_s)
    X_va_c, X_va_n = proc.transform(va_s)
    X_te_c, X_te_n = proc.transform(te_s)
    X_tv_c, X_tv_n = proc.transform(tv_s)
    y_tr_s = tr_s["total_runs"].values.astype(np.float32)
    y_va_s = va_s["total_runs"].values.astype(np.float32)
    y_te_s = te_s["total_runs"].values.astype(np.float32)
    y_tv_s = tv_s["total_runs"].values.astype(np.float32)

    cardinalities = [len(v) + 1 for v in proc.category_maps.values()]
    net = _EntityEmbeddingNet(cardinalities, len(NUM_FEATS), task="regression").to(device)
    best_net, _ = _fit_dl(net, X_tr_c, X_tr_n, y_tr_s,
                           X_va_c, X_va_n, y_va_s, device,
                           task="regression", epochs=60)
    # refit on train+valid
    net2 = _EntityEmbeddingNet(cardinalities, len(NUM_FEATS), task="regression").to(device)
    net2, _ = _fit_dl(net2, X_tv_c, X_tv_n, y_tv_s,
                       X_va_c, X_va_n, y_va_s, device,
                       task="regression", epochs=60)
    preds = _dl_predict(net2, X_te_c, X_te_n, device, task="regression")
    mae  = float(mean_absolute_error(y_te_s, preds))
    rmse = float(mean_squared_error(y_te_s, preds) ** 0.5)
    r = {"model": "DL_EntityEmb", "task": "score",
         "test_mae": round(mae, 3), "test_rmse": round(rmse, 3),
         "train_secs": round(time.time() - t0, 1)}
    results.append(r)
    joblib.dump({"proc": proc, "net_state": net2.state_dict(),
                 "cardinalities": cardinalities, "n_numeric": len(NUM_FEATS)},
                MODELS_DIR / "score_model_dl2.pkl")
    log(f"  [DL Score] MAE={mae:.2f}  RMSE={rmse:.2f}")

    # ── Win DL ────────────────────────────────────────────────────────────────
    log("  [DL] Training Entity-Embedding Win model ...")
    t0 = time.time()
    tr_w = prep_win(train)
    va_w = prep_win(valid)
    te_w = prep_win(test)
    tv_w = pd.concat([tr_w, va_w])

    proc_w = TabularTensorPreprocessor.fit(tr_w, CAT_FEATS, NUM_FEATS)
    X_tr_c, X_tr_n = proc_w.transform(tr_w)
    X_va_c, X_va_n = proc_w.transform(va_w)
    X_te_c, X_te_n = proc_w.transform(te_w)
    X_tv_c, X_tv_n = proc_w.transform(tv_w)
    y_tr_w = tr_w["win"].values.astype(np.float32)
    y_va_w = va_w["win"].values.astype(np.float32)
    y_te_w = te_w["win"].values.astype(np.float32)
    y_tv_w = tv_w["win"].values.astype(np.float32)

    car_w = [len(v) + 1 for v in proc_w.category_maps.values()]
    net_w = _EntityEmbeddingNet(car_w, len(NUM_FEATS), task="classification").to(device)
    best_w, _ = _fit_dl(net_w, X_tr_c, X_tr_n, y_tr_w,
                         X_va_c, X_va_n, y_va_w, device,
                         task="classification", epochs=60)
    net_w2 = _EntityEmbeddingNet(car_w, len(NUM_FEATS), task="classification").to(device)
    net_w2, _ = _fit_dl(net_w2, X_tv_c, X_tv_n, y_tv_w,
                         X_va_c, X_va_n, y_va_w, device,
                         task="classification", epochs=60)
    probs = _dl_predict(net_w2, X_te_c, X_te_n, device, task="classification")
    preds_cls = (probs >= 0.5).astype(int)
    acc  = float(accuracy_score(y_te_w, preds_cls))
    ll   = float(log_loss(y_te_w, probs))
    brier = float(brier_score_loss(y_te_w, probs))
    r = {"model": "DL_EntityEmb", "task": "win",
         "test_accuracy": round(acc, 4), "test_log_loss": round(ll, 4),
         "test_brier": round(brier, 4), "train_secs": round(time.time() - t0, 1)}
    results.append(r)
    joblib.dump({"proc": proc_w, "net_state": net_w2.state_dict(),
                 "cardinalities": car_w, "n_numeric": len(NUM_FEATS)},
                MODELS_DIR / "win_model_dl2.pkl")
    log(f"  [DL Win] Acc={acc:.4f}  LogLoss={ll:.4f}")

    return results


def _fit_dl(net, X_tr_c, X_tr_n, y_tr,
             X_va_c, X_va_n, y_va, device,
             task: str, epochs: int = 60,
             batch_size: int = 2048, lr: float = 1e-3):
    import torch
    from torch.utils.data import DataLoader, TensorDataset

    is_cls = task == "classification"
    loss_fn = torch.nn.BCELoss() if is_cls else torch.nn.MSELoss()
    opt = torch.optim.Adam(net.parameters(), lr=lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)

    def to_tensors(Xc, Xn, y):
        return (torch.tensor(Xc, dtype=torch.long).to(device),
                torch.tensor(Xn, dtype=torch.float32).to(device),
                torch.tensor(y, dtype=torch.float32).to(device))

    tr_data = TensorDataset(*to_tensors(X_tr_c, X_tr_n, y_tr))
    loader  = DataLoader(tr_data, batch_size=batch_size, shuffle=True)
    Xvc, Xvn, yv = to_tensors(X_va_c, X_va_n, y_va)

    best_val, best_state, patience, no_improve = 1e9, None, 10, 0
    for ep in range(epochs):
        net.train()
        for batch_c, batch_n, batch_y in loader:
            opt.zero_grad()
            out = net(batch_c, batch_n).squeeze()
            loss = loss_fn(out, batch_y)
            loss.backward()
            opt.step()
        sched.step()
        net.eval()
        with torch.no_grad():
            val_out = net(Xvc, Xvn).squeeze().cpu().numpy()
        if is_cls:
            val_loss = float(log_loss(yv.cpu().numpy(), val_out))
        else:
            val_loss = float(mean_squared_error(yv.cpu().numpy(), val_out) ** 0.5)
        if val_loss < best_val:
            best_val = val_loss
            best_state = {k: v.clone() for k, v in net.state_dict().items()}
            no_improve = 0
        else:
            no_improve += 1
            if no_improve >= patience:
                break
    if best_state:
        net.load_state_dict(best_state)
    return net, best_val


def _dl_predict(net, X_c, X_n, device, task: str) -> np.ndarray:
    import torch
    net.eval()
    with torch.no_grad():
        Xc = torch.tensor(X_c, dtype=torch.long).to(device)
        Xn = torch.tensor(X_n, dtype=torch.float32).to(device)
        out = net(Xc, Xn).squeeze().cpu().numpy()
    return out


def _has_gpu() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


# ── metric helpers ─────────────────────────────────────────────────────────────
def _score_metrics(pipeline, X_te, y_te, name: str, elapsed: float) -> dict:
    preds = pipeline.predict(X_te)
    return {
        "model": name, "task": "score",
        "test_mae":  round(float(mean_absolute_error(y_te, preds)), 3),
        "test_rmse": round(float(mean_squared_error(y_te, preds) ** 0.5), 3),
        "train_secs": round(elapsed, 1),
    }

def _score_metrics_raw(model, X_te, y_te, name: str, elapsed: float) -> dict:
    preds = model.predict(X_te)
    return {
        "model": name, "task": "score",
        "test_mae":  round(float(mean_absolute_error(y_te, preds)), 3),
        "test_rmse": round(float(mean_squared_error(y_te, preds) ** 0.5), 3),
        "train_secs": round(elapsed, 1),
    }

def _win_metrics(pipeline, X_te, y_te, name: str, elapsed: float) -> dict:
    probs = pipeline.predict_proba(X_te)[:, 1]
    preds = (probs >= 0.5).astype(int)
    return {
        "model": name, "task": "win",
        "test_accuracy": round(float(accuracy_score(y_te, preds)), 4),
        "test_log_loss": round(float(log_loss(y_te, probs)), 4),
        "test_brier":    round(float(brier_score_loss(y_te, probs)), 4),
        "train_secs": round(elapsed, 1),
    }

def _win_metrics_raw(model, X_te, y_te, name: str, elapsed: float) -> dict:
    try:
        probs = model.predict_proba(X_te)[:, 1]
    except Exception:
        probs = np.clip(model.predict(X_te), 0.01, 0.99)
    preds = (probs >= 0.5).astype(int)
    return {
        "model": name, "task": "win",
        "test_accuracy": round(float(accuracy_score(y_te, preds)), 4),
        "test_log_loss": round(float(log_loss(y_te, probs)), 4),
        "test_brier":    round(float(brier_score_loss(y_te, probs)), 4),
        "train_secs": round(elapsed, 1),
    }


# ── select best & promote ──────────────────────────────────────────────────────
def promote_best(score_results: list[dict], win_results: list[dict]) -> dict:
    """Pick best models and copy to score_model.pkl / win_model.pkl."""
    model_file_map = {
        "HGB":         ("score_model_hgb2.pkl", "win_model_hgb2.pkl"),
        "XGBoost":     ("score_model_xgb2.pkl", "win_model_xgb2.pkl"),
        "CatBoost":    ("score_model_cat2.pkl", "win_model_cat2.pkl"),
        "RandomForest":("score_model_rf2.pkl",  None),
        "DL_EntityEmb":("score_model_dl2.pkl",  "win_model_dl2.pkl"),
    }

    best_score = min(score_results, key=lambda x: x["test_rmse"])
    best_win   = min(win_results,   key=lambda x: x["test_log_loss"])

    import shutil
    sf = model_file_map.get(best_score["model"], (None, None))[0]
    wf = model_file_map.get(best_win["model"],   (None, None))[1]

    promoted = {}
    if sf and (MODELS_DIR / sf).exists():
        shutil.copy(MODELS_DIR / sf, MODELS_DIR / "score_model.pkl")
        log(f"  Promoted score model: {best_score['model']}  (RMSE={best_score['test_rmse']})")
        promoted["score"] = best_score["model"]
    if wf and (MODELS_DIR / wf).exists():
        shutil.copy(MODELS_DIR / wf, MODELS_DIR / "win_model.pkl")
        log(f"  Promoted win model:   {best_win['model']}    (Acc={best_win['test_accuracy']})")
        promoted["win"] = best_win["model"]

    # Save uncertainty profile from best score model
    if sf and (MODELS_DIR / sf).exists():
        _save_uncertainty(MODELS_DIR / sf, best_score["model"])

    return promoted


def _save_uncertainty(model_path: Path, model_name: str) -> None:
    try:
        df = pd.read_csv(DATA_PATH, low_memory=False)
        df["season_int"] = df["season"].apply(season_int)
        mask = (df["batting_team"].isin(ACTIVE_IPL_TEAMS_2026) &
                df["bowling_team"].isin(ACTIVE_IPL_TEAMS_2026))
        seasons = sorted(df.loc[mask, "season_int"].unique())
        test_yr = seasons[-1]
        te = df[mask & (df["season_int"] == test_yr) & (df["balls_left"] > 0) & df["total_runs"].notna()]

        model = joblib.load(model_path)
        X_te = te[ALL_FEATS]
        if model_name == "DL_EntityEmb":
            return  # skip for DL
        if isinstance(model, dict):
            preds = model["model"].predict(model["pre"].transform(X_te))
        else:
            preds = model.predict(X_te)
        residuals = te["total_runs"].values - preds
        profile = {
            "residual_q10": round(float(np.percentile(residuals, 10)), 2),
            "residual_q90": round(float(np.percentile(residuals, 90)), 2),
            "residual_std": round(float(np.std(residuals)), 2),
            "source": model_name,
        }
        SCORE_UNCERTAINTY_PATH.write_text(json.dumps(profile, indent=2))
        log(f"  Uncertainty profile saved: Q10={profile['residual_q10']}, Q90={profile['residual_q90']}")
    except Exception as exc:
        log(f"  Warning: could not save uncertainty profile — {exc}")


# ── main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-dl",  action="store_true", help="Skip PyTorch DL training")
    parser.add_argument("--quick",    action="store_true", help="Only HGB models (fastest)")
    args = parser.parse_args()

    t_start = time.time()
    log("=" * 60)
    log("IPL All-Models Trainer")
    log("=" * 60)

    train, valid, test = load_and_prepare()

    log("\n--- Score Models ---")
    score_results = train_score_models(train, valid, test, quick=args.quick)

    log("\n--- Win Models ---")
    win_results = train_win_models(train, valid, test, quick=args.quick)

    if not args.skip_dl and not args.quick:
        log("\n--- Deep Learning Models ---")
        dl_results = train_dl_models(train, valid, test)
        score_results += [r for r in dl_results if r["task"] == "score"]
        win_results   += [r for r in dl_results if r["task"] == "win"]

    log("\n--- Selecting Best Models ---")
    promoted = promote_best(score_results, win_results)

    # Print comparison tables
    log("\n=== SCORE MODEL COMPARISON (test: 2026) ===")
    log(f"  {'Model':<18} {'MAE':>8} {'RMSE':>8} {'Val MAE':>10} {'Time(s)':>9}")
    log("  " + "-" * 58)
    for r in sorted(score_results, key=lambda x: x["test_rmse"]):
        flag = " ← BEST" if r["model"] == promoted.get("score") else ""
        log(f"  {r['model']:<18} {r['test_mae']:>8.3f} {r['test_rmse']:>8.3f} "
            f"{r.get('val_mae', '-'):>10} {r.get('train_secs', '-'):>9}{flag}")

    log("\n=== WIN MODEL COMPARISON (test: 2026) ===")
    log(f"  {'Model':<18} {'Accuracy':>10} {'LogLoss':>10} {'Brier':>8} {'Time(s)':>9}")
    log("  " + "-" * 60)
    for r in sorted(win_results, key=lambda x: -x["test_accuracy"]):
        flag = " ← BEST" if r["model"] == promoted.get("win") else ""
        log(f"  {r['model']:<18} {r['test_accuracy']:>10.4f} {r['test_log_loss']:>10.4f} "
            f"{r['test_brier']:>8.4f} {r.get('train_secs', '-'):>9}{flag}")

    # Save report
    report = {
        "trained_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "test_season": 2026,
        "promoted": promoted,
        "score_models": score_results,
        "win_models": win_results,
        "total_train_secs": round(time.time() - t_start, 1),
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    log(f"\nReport saved: {REPORT_PATH}")
    log(f"Total time: {report['total_train_secs']}s")
    log("Done!")


if __name__ == "__main__":
    main()
