"""
model_zoo.py — Advanced model architectures for IPL prediction.

Contains
--------
TabTransformer              : PyTorch multi-head attention tabular model
TorchTabTransformerRegressor : sklearn-compatible wrapper (score prediction)
TorchTabTransformerClassifier: sklearn-compatible wrapper (win prediction)
StackingEnsemble            : two-level stacking with Ridge / Logistic meta-learner
PhaseModelBundle            : train separate models for powerplay/middle/death phases
"""
from __future__ import annotations

import time
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from copy import deepcopy
from typing import Dict, List, Optional, Tuple

from torch.utils.data import DataLoader, TensorDataset
from sklearn.linear_model import Ridge, LogisticRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, log_loss, brier_score_loss, accuracy_score
from sklearn.model_selection import KFold


# ── TabTransformer ────────────────────────────────────────────────────────────

class _CatEmbeddingBlock(nn.Module):
    """Embed all categorical features then apply a Transformer encoder."""

    def __init__(
        self,
        cardinalities: List[int],
        embed_dim: int = 32,
        n_heads: int = 4,
        n_layers: int = 3,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        self.embed_dim = embed_dim
        self.embeddings = nn.ModuleList(
            [nn.Embedding(card, embed_dim, padding_idx=0) for card in cardinalities]
        )
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=embed_dim,
            nhead=n_heads,
            dim_feedforward=embed_dim * 4,
            dropout=dropout,
            batch_first=True,
            norm_first=True,
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)

    def forward(self, x_cat: torch.Tensor) -> torch.Tensor:
        # x_cat: (B, n_cat)
        embeds = [emb(x_cat[:, i]) for i, emb in enumerate(self.embeddings)]
        x = torch.stack(embeds, dim=1)          # (B, n_cat, embed_dim)
        x = self.transformer(x)                  # (B, n_cat, embed_dim)
        return x.reshape(x.size(0), -1)          # (B, n_cat * embed_dim)


class TabTransformer(nn.Module):
    """
    TabTransformer for IPL tabular data.

    Categorical features → per-feature embeddings → Transformer encoder.
    Numeric features     → LayerNorm → linear projection.
    Combined             → deep MLP → task head.
    """

    def __init__(
        self,
        cardinalities: List[int],
        n_numeric: int,
        task: str = "regression",
        embed_dim: int = 32,
        n_heads: int = 4,
        n_layers: int = 3,
        hidden_dims: Tuple[int, ...] = (512, 256, 128),
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        assert task in ("regression", "classification")
        self.task = task

        self.cat_block = _CatEmbeddingBlock(cardinalities, embed_dim, n_heads, n_layers, dropout)
        cat_out_dim = len(cardinalities) * embed_dim

        # Numeric branch
        self.num_norm = nn.LayerNorm(n_numeric)
        num_proj_dim = max(64, n_numeric * 2)
        self.num_proj = nn.Sequential(
            nn.Linear(n_numeric, num_proj_dim),
            nn.GELU(),
        )

        in_dim = cat_out_dim + num_proj_dim
        layers: List[nn.Module] = []
        prev = in_dim
        for h in hidden_dims:
            layers += [nn.Linear(prev, h), nn.GELU(), nn.Dropout(dropout)]
            prev = h
        layers.append(nn.Linear(prev, 1))
        self.mlp = nn.Sequential(*layers)

        self._init_weights()

    def _init_weights(self) -> None:
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.xavier_uniform_(m.weight)
                if m.bias is not None:
                    nn.init.zeros_(m.bias)

    def forward(self, x_cat: torch.Tensor, x_num: torch.Tensor) -> torch.Tensor:
        cat_out = self.cat_block(x_cat)
        num_out = self.num_proj(self.num_norm(x_num))
        combined = torch.cat([cat_out, num_out], dim=1)
        out = self.mlp(combined).squeeze(-1)
        if self.task == "classification":
            out = torch.sigmoid(out)
        return out


# ── preprocessor (matches TabularTensorPreprocessor in torch_tabular.py) ─────

class _TensorPreprocessor:
    def __init__(self, cat_cols: List[str], num_cols: List[str]) -> None:
        self.cat_cols = cat_cols
        self.num_cols = num_cols
        self.cat_maps_: Dict[str, Dict[str, int]] = {}
        self.num_mean_: Dict[str, float] = {}
        self.num_std_:  Dict[str, float] = {}

    def fit(self, df: pd.DataFrame) -> "_TensorPreprocessor":
        for col in self.cat_cols:
            vals = df[col].fillna("Unknown").astype(str).tolist()
            uniq = sorted(set(vals))
            self.cat_maps_[col] = {v: i + 1 for i, v in enumerate(uniq)}
        num_df = df[self.num_cols].apply(pd.to_numeric, errors="coerce")
        self.num_mean_ = num_df.mean().fillna(0.0).to_dict()
        self.num_std_  = num_df.std().replace(0.0, 1.0).fillna(1.0).to_dict()
        return self

    def transform(self, df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        cats = []
        for col in self.cat_cols:
            m = self.cat_maps_[col]
            enc = np.fromiter(
                (m.get(v, 0) for v in df[col].fillna("Unknown").astype(str)),
                dtype=np.int64,
                count=len(df),
            )
            cats.append(enc)
        cat_arr = np.column_stack(cats) if cats else np.zeros((len(df), 0), dtype=np.int64)

        num_df = df[self.num_cols].apply(pd.to_numeric, errors="coerce").copy()
        for col in self.num_cols:
            num_df[col] = (num_df[col].fillna(self.num_mean_[col]) - self.num_mean_[col]) / self.num_std_[col]
        num_arr = num_df.to_numpy(dtype=np.float32, copy=True)
        return cat_arr, num_arr

    def cardinalities(self) -> List[int]:
        return [len(self.cat_maps_[c]) + 1 for c in self.cat_cols]


# ── sklearn-compatible wrappers ───────────────────────────────────────────────

def _fit_transformer(
    model: TabTransformer,
    proc: _TensorPreprocessor,
    X_tr: pd.DataFrame, y_tr: pd.Series,
    X_va: pd.DataFrame, y_va: pd.Series,
    device: str,
    task: str,
    batch_size: int = 4096,
    epochs: int = 80,
    lr: float = 8e-4,
    patience: int = 10,
) -> Tuple[TabTransformer, List[float]]:
    """Core training loop for TabTransformer."""
    is_cls = task == "classification"

    Xc_tr, Xn_tr = proc.transform(X_tr)
    Xc_va, Xn_va = proc.transform(X_va)

    y_tr_arr = y_tr.to_numpy(dtype=np.float32)
    y_va_arr = y_va.to_numpy(dtype=np.float32)

    ds = TensorDataset(
        torch.from_numpy(Xc_tr),
        torch.from_numpy(Xn_tr),
        torch.from_numpy(y_tr_arr),
    )
    loader = DataLoader(ds, batch_size=batch_size, shuffle=True, drop_last=False)

    Xc_v = torch.from_numpy(Xc_va).to(device)
    Xn_v = torch.from_numpy(Xn_va).to(device)
    y_v  = torch.from_numpy(y_va_arr).to(device)

    if is_cls:
        pos_rate = float(y_tr_arr.mean().clip(0.01, 0.99))
        loss_fn: nn.Module = nn.BCELoss()
    else:
        loss_fn = nn.HuberLoss(delta=15.0)

    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(
        opt, max_lr=lr * 5, epochs=epochs, steps_per_epoch=len(loader)
    )

    best_val, best_state, no_imp = float("inf"), None, 0
    val_history: List[float] = []

    for _ in range(epochs):
        model.train()
        for bc, bn, by in loader:
            bc, bn, by = bc.to(device), bn.to(device), by.to(device)
            opt.zero_grad(set_to_none=True)
            out = model(bc, bn)
            loss = loss_fn(out, by)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()

        model.eval()
        with torch.no_grad():
            out_v = model(Xc_v, Xn_v).cpu().numpy()
        if is_cls:
            val_metric = float(log_loss(y_va_arr, np.clip(out_v, 1e-7, 1 - 1e-7)))
        else:
            val_metric = float(np.sqrt(mean_squared_error(y_va_arr, out_v)))
        val_history.append(val_metric)

        if val_metric < best_val:
            best_val = val_metric
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            no_imp = 0
        else:
            no_imp += 1
            if no_imp >= patience:
                break

    if best_state:
        model.load_state_dict(best_state)
    return model, val_history


class TorchTabTransformerRegressor:
    """sklearn-compatible TabTransformer for score regression."""

    def __init__(
        self,
        cat_cols: List[str],
        num_cols: List[str],
        embed_dim: int = 32,
        n_heads: int = 4,
        n_layers: int = 3,
        hidden_dims: Tuple[int, ...] = (512, 256, 128),
        dropout: float = 0.1,
        batch_size: int = 4096,
        epochs: int = 80,
        lr: float = 8e-4,
        patience: int = 10,
        seed: int = 42,
    ) -> None:
        self.cat_cols = cat_cols
        self.num_cols = num_cols
        self.embed_dim = embed_dim
        self.n_heads = n_heads
        self.n_layers = n_layers
        self.hidden_dims = hidden_dims
        self.dropout = dropout
        self.batch_size = batch_size
        self.epochs = epochs
        self.lr = lr
        self.patience = patience
        self.seed = seed

        self.proc_: Optional[_TensorPreprocessor] = None
        self.model_: Optional[TabTransformer] = None

    def fit(
        self,
        X_tr: pd.DataFrame,
        y_tr: pd.Series,
        X_va: pd.DataFrame,
        y_va: pd.Series,
        device: str = "cuda",
    ) -> "TorchTabTransformerRegressor":
        torch.manual_seed(self.seed)
        np.random.seed(self.seed)

        self.proc_ = _TensorPreprocessor(self.cat_cols, self.num_cols).fit(X_tr)
        self.model_ = TabTransformer(
            cardinalities=self.proc_.cardinalities(),
            n_numeric=len(self.num_cols),
            task="regression",
            embed_dim=self.embed_dim,
            n_heads=self.n_heads,
            n_layers=self.n_layers,
            hidden_dims=self.hidden_dims,
            dropout=self.dropout,
        ).to(device)
        self.model_, self.val_history_ = _fit_transformer(
            self.model_, self.proc_,
            X_tr, y_tr, X_va, y_va,
            device=device, task="regression",
            batch_size=self.batch_size, epochs=self.epochs,
            lr=self.lr, patience=self.patience,
        )
        return self

    def predict(self, X: pd.DataFrame, device: str = "cpu") -> np.ndarray:
        assert self.proc_ and self.model_
        Xc, Xn = self.proc_.transform(X)
        self.model_.eval()
        with torch.no_grad():
            out = self.model_(
                torch.from_numpy(Xc).to(device),
                torch.from_numpy(Xn).to(device),
            ).cpu().numpy()
        return out


class TorchTabTransformerClassifier:
    """sklearn-compatible TabTransformer for win classification."""

    def __init__(
        self,
        cat_cols: List[str],
        num_cols: List[str],
        embed_dim: int = 32,
        n_heads: int = 4,
        n_layers: int = 3,
        hidden_dims: Tuple[int, ...] = (512, 256, 128),
        dropout: float = 0.1,
        batch_size: int = 4096,
        epochs: int = 80,
        lr: float = 8e-4,
        patience: int = 10,
        seed: int = 42,
    ) -> None:
        self.cat_cols = cat_cols
        self.num_cols = num_cols
        self.embed_dim = embed_dim
        self.n_heads = n_heads
        self.n_layers = n_layers
        self.hidden_dims = hidden_dims
        self.dropout = dropout
        self.batch_size = batch_size
        self.epochs = epochs
        self.lr = lr
        self.patience = patience
        self.seed = seed

        self.proc_: Optional[_TensorPreprocessor] = None
        self.model_: Optional[TabTransformer] = None

    def fit(
        self,
        X_tr: pd.DataFrame,
        y_tr: pd.Series,
        X_va: pd.DataFrame,
        y_va: pd.Series,
        device: str = "cuda",
    ) -> "TorchTabTransformerClassifier":
        torch.manual_seed(self.seed)
        np.random.seed(self.seed)

        self.proc_ = _TensorPreprocessor(self.cat_cols, self.num_cols).fit(X_tr)
        self.model_ = TabTransformer(
            cardinalities=self.proc_.cardinalities(),
            n_numeric=len(self.num_cols),
            task="classification",
            embed_dim=self.embed_dim,
            n_heads=self.n_heads,
            n_layers=self.n_layers,
            hidden_dims=self.hidden_dims,
            dropout=self.dropout,
        ).to(device)
        self.model_, self.val_history_ = _fit_transformer(
            self.model_, self.proc_,
            X_tr, y_tr, X_va, y_va,
            device=device, task="classification",
            batch_size=self.batch_size, epochs=self.epochs,
            lr=self.lr, patience=self.patience,
        )
        return self

    def predict_proba(self, X: pd.DataFrame, device: str = "cpu") -> np.ndarray:
        assert self.proc_ and self.model_
        Xc, Xn = self.proc_.transform(X)
        self.model_.eval()
        with torch.no_grad():
            p1 = self.model_(
                torch.from_numpy(Xc).to(device),
                torch.from_numpy(Xn).to(device),
            ).cpu().numpy()
        p1 = np.clip(p1, 1e-7, 1 - 1e-7)
        return np.column_stack([1 - p1, p1])

    def predict(self, X: pd.DataFrame, device: str = "cpu") -> np.ndarray:
        return (self.predict_proba(X, device)[:, 1] >= 0.5).astype(int)


# ── stacking ensemble ─────────────────────────────────────────────────────────

class StackingRegressor:
    """
    Two-level stacking for score prediction.

    Level 1: list of base regressors.
    Level 2: Ridge regression meta-learner trained on out-of-fold predictions.
    """

    def __init__(
        self,
        base_models: List,
        base_names: List[str],
        n_folds: int = 5,
        meta_alpha: float = 1.0,
    ) -> None:
        self.base_models = base_models
        self.base_names = base_names
        self.n_folds = n_folds
        self.meta = Ridge(alpha=meta_alpha)
        self.fitted_bases_: List = []

    def fit(
        self,
        X_tv: pd.DataFrame,
        y_tv: pd.Series,
        X_te: pd.DataFrame,
        y_te: pd.Series,
    ) -> "StackingRegressor":
        """
        Train base models with k-fold OOF, then train meta-learner.
        Also fits base models on full train+valid for final predictions.
        """
        n = len(X_tv)
        oof = np.zeros((n, len(self.base_models)))
        test_preds = np.zeros((len(X_te), len(self.base_models)))

        kf = KFold(n_splits=self.n_folds, shuffle=True, random_state=42)
        for mi, (model, name) in enumerate(zip(self.base_models, self.base_names)):
            fold_test_preds = []
            for fold_i, (tr_idx, va_idx) in enumerate(kf.split(X_tv)):
                m = deepcopy(model)
                Xf_tr = X_tv.iloc[tr_idx]
                yf_tr = y_tv.iloc[tr_idx]
                Xf_va = X_tv.iloc[va_idx]

                # Handle dict-wrapped models (XGBoost, RF)
                if isinstance(m, dict):
                    m["model"].fit(m["pre"].fit_transform(Xf_tr), yf_tr)
                    oof[va_idx, mi] = m["model"].predict(m["pre"].transform(Xf_va))
                    fold_test_preds.append(m["model"].predict(m["pre"].transform(X_te)))
                else:
                    m.fit(Xf_tr, yf_tr)
                    oof[va_idx, mi] = m.predict(Xf_va)
                    fold_test_preds.append(m.predict(X_te))

            test_preds[:, mi] = np.mean(fold_test_preds, axis=0)
            mae = mean_absolute_error(y_tv, oof[:, mi])
            print(f"    [Stacking OOF] {name:<20} MAE={mae:.3f}")

        # Train meta-learner
        self.meta.fit(oof, y_tv)
        self.oof_ = oof
        self.test_preds_l1_ = test_preds

        # Refit all base models on full data
        self.fitted_bases_ = []
        for model, name in zip(self.base_models, self.base_names):
            m = deepcopy(model)
            if isinstance(m, dict):
                m["model"].fit(m["pre"].fit_transform(X_tv), y_tv)
            else:
                m.fit(X_tv, y_tv)
            self.fitted_bases_.append(m)

        # Evaluate meta on test
        meta_preds = self.meta.predict(test_preds)
        mae_te  = mean_absolute_error(y_te, meta_preds)
        rmse_te = float(np.sqrt(mean_squared_error(y_te, meta_preds)))
        print(f"\n    [Stacking Meta] Test MAE={mae_te:.3f}  RMSE={rmse_te:.3f}")
        self.test_score_ = {"mae": mae_te, "rmse": rmse_te}
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        base_preds = np.column_stack([
            (m["model"].predict(m["pre"].transform(X)) if isinstance(m, dict) else m.predict(X))
            for m in self.fitted_bases_
        ])
        return self.meta.predict(base_preds)


class StackingClassifier:
    """
    Two-level stacking for win probability prediction.

    Level 1: list of base classifiers.
    Level 2: Logistic regression meta-learner.
    """

    def __init__(
        self,
        base_models: List,
        base_names: List[str],
        n_folds: int = 5,
        meta_C: float = 1.0,
    ) -> None:
        self.base_models = base_models
        self.base_names = base_names
        self.n_folds = n_folds
        self.meta = LogisticRegression(C=meta_C, max_iter=1000, random_state=42)
        self.fitted_bases_: List = []

    def _get_proba(self, m, X: pd.DataFrame) -> np.ndarray:
        if isinstance(m, dict):
            return m["model"].predict_proba(m["pre"].transform(X))[:, 1]
        return m.predict_proba(X)[:, 1]

    def fit(
        self,
        X_tv: pd.DataFrame,
        y_tv: pd.Series,
        X_te: pd.DataFrame,
        y_te: pd.Series,
    ) -> "StackingClassifier":
        n = len(X_tv)
        oof = np.zeros((n, len(self.base_models)))
        test_preds = np.zeros((len(X_te), len(self.base_models)))

        kf = KFold(n_splits=self.n_folds, shuffle=True, random_state=42)
        for mi, (model, name) in enumerate(zip(self.base_models, self.base_names)):
            fold_test_preds = []
            for tr_idx, va_idx in kf.split(X_tv):
                m = deepcopy(model)
                Xf_tr = X_tv.iloc[tr_idx]
                yf_tr = y_tv.iloc[tr_idx]
                Xf_va = X_tv.iloc[va_idx]

                if isinstance(m, dict):
                    m["model"].fit(m["pre"].fit_transform(Xf_tr), yf_tr)
                    try:
                        oof[va_idx, mi] = m["model"].predict_proba(m["pre"].transform(Xf_va))[:, 1]
                        fold_test_preds.append(m["model"].predict_proba(m["pre"].transform(X_te))[:, 1])
                    except Exception:
                        oof[va_idx, mi] = m["model"].predict(m["pre"].transform(Xf_va))
                        fold_test_preds.append(m["model"].predict(m["pre"].transform(X_te)))
                else:
                    m.fit(Xf_tr, yf_tr)
                    oof[va_idx, mi] = self._get_proba(m, Xf_va)
                    fold_test_preds.append(self._get_proba(m, X_te))

            test_preds[:, mi] = np.mean(fold_test_preds, axis=0)
            ll = log_loss(y_tv, np.clip(oof[:, mi], 1e-7, 1 - 1e-7))
            print(f"    [Stacking OOF] {name:<20} LogLoss={ll:.4f}")

        self.meta.fit(oof, y_tv)
        self.oof_ = oof
        self.test_preds_l1_ = test_preds

        self.fitted_bases_ = []
        for model in self.base_models:
            m = deepcopy(model)
            if isinstance(m, dict):
                m["model"].fit(m["pre"].fit_transform(X_tv), y_tv)
            else:
                m.fit(X_tv, y_tv)
            self.fitted_bases_.append(m)

        meta_probs = self.meta.predict_proba(test_preds)[:, 1]
        acc  = accuracy_score(y_te, (meta_probs >= 0.5).astype(int))
        ll   = log_loss(y_te, np.clip(meta_probs, 1e-7, 1 - 1e-7))
        brier = brier_score_loss(y_te, meta_probs)
        print(f"\n    [Stacking Meta] Test Acc={acc:.4f}  LogLoss={ll:.4f}  Brier={brier:.4f}")
        self.test_score_ = {"accuracy": acc, "log_loss": ll, "brier": brier}
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        base_preds = np.column_stack([self._get_proba(m, X) for m in self.fitted_bases_])
        p1 = self.meta.predict_proba(base_preds)[:, 1]
        return np.column_stack([1 - p1, p1])

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)


# ── phase-specific model bundle ───────────────────────────────────────────────

class PhaseModelBundle:
    """
    Train separate score and win models per game phase.
    Phases: powerplay (0-6 overs), middle (7-15), death (16-20).
    """

    PHASES = ["powerplay", "middle", "death"]

    def __init__(self, base_model_fn) -> None:
        """base_model_fn(): callable returning a fresh untrained model."""
        self.base_model_fn = base_model_fn
        self.models_: Dict[str, object] = {}

    def fit(
        self,
        X_tr: pd.DataFrame,
        y_tr: pd.Series,
        X_va: pd.DataFrame,
        y_va: pd.Series,
        phase_col: str = "phase",
    ) -> "PhaseModelBundle":
        for phase in self.PHASES:
            tr_mask = X_tr[phase_col] == phase
            va_mask = X_va[phase_col] == phase

            if tr_mask.sum() < 500:
                print(f"  [Phase:{phase}] Too few samples ({tr_mask.sum()}), skipping.")
                continue

            m = self.base_model_fn()
            Xp_tr = X_tr[tr_mask].drop(columns=[phase_col], errors="ignore")
            Xp_va = X_va[va_mask].drop(columns=[phase_col], errors="ignore")
            m.fit(Xp_tr, y_tr[tr_mask])
            preds = m.predict(Xp_va)
            mae = mean_absolute_error(y_va[va_mask], preds)
            print(f"  [Phase:{phase}] samples={tr_mask.sum():,}  val_MAE={mae:.3f}")
            self.models_[phase] = m
        return self

    def predict(self, X: pd.DataFrame, phase_col: str = "phase") -> np.ndarray:
        preds = np.full(len(X), np.nan)
        for phase, m in self.models_.items():
            mask = X[phase_col] == phase
            if mask.any():
                Xp = X[mask].drop(columns=[phase_col], errors="ignore")
                preds[mask.values] = m.predict(Xp)
        # Fallback: fill NaN with global mean (shouldn't happen normally)
        nan_mask = np.isnan(preds)
        if nan_mask.any():
            preds[nan_mask] = np.nanmean(preds)
        return preds
