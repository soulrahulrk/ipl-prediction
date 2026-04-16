from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import torch
from sklearn.isotonic import IsotonicRegression
from torch import nn
from torch.utils.data import DataLoader, TensorDataset


def _embedding_dim(cardinality: int) -> int:
    return int(min(48, max(4, round(1.6 * (cardinality**0.56)))))


@dataclass
class TabularTensorPreprocessor:
    categorical_cols: list[str]
    numeric_cols: list[str]
    category_maps: dict[str, dict[str, int]]
    numeric_means: dict[str, float]
    numeric_stds: dict[str, float]

    @classmethod
    def fit(
        cls,
        frame: pd.DataFrame,
        categorical_cols: list[str],
        numeric_cols: list[str],
    ) -> "TabularTensorPreprocessor":
        category_maps: dict[str, dict[str, int]] = {}
        for col in categorical_cols:
            values = frame[col].fillna("Unknown").astype(str).tolist()
            uniques = sorted(set(values))
            category_maps[col] = {value: i + 1 for i, value in enumerate(uniques)}

        numeric_frame = frame[numeric_cols].apply(pd.to_numeric, errors="coerce")
        numeric_means = numeric_frame.mean().fillna(0.0).to_dict()
        numeric_stds = numeric_frame.std().replace(0.0, 1.0).fillna(1.0).to_dict()
        return cls(
            categorical_cols=categorical_cols,
            numeric_cols=numeric_cols,
            category_maps=category_maps,
            numeric_means={k: float(v) for k, v in numeric_means.items()},
            numeric_stds={k: float(v) for k, v in numeric_stds.items()},
        )

    def transform(self, frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        cats: list[np.ndarray] = []
        for col in self.categorical_cols:
            mapping = self.category_maps[col]
            values = frame[col].fillna("Unknown").astype(str).tolist()
            encoded = np.fromiter((mapping.get(value, 0) for value in values), dtype=np.int64, count=len(values))
            cats.append(encoded)
        cat_array = np.column_stack(cats) if cats else np.zeros((len(frame), 0), dtype=np.int64)

        num_df = frame[self.numeric_cols].apply(pd.to_numeric, errors="coerce").copy()
        for col in self.numeric_cols:
            mean = self.numeric_means[col]
            std = self.numeric_stds[col] if self.numeric_stds[col] != 0 else 1.0
            num_df[col] = (num_df[col].fillna(mean) - mean) / std
        num_array = num_df.to_numpy(dtype=np.float32, copy=True)
        return cat_array, num_array

    def cardinalities(self) -> list[int]:
        return [len(self.category_maps[col]) + 1 for col in self.categorical_cols]


class _EntityEmbeddingNet(nn.Module):
    def __init__(
        self,
        cat_cardinalities: list[int],
        num_numeric: int,
        out_dim: int,
        hidden_dims: tuple[int, ...] = (256, 128, 64),
        dropout: float = 0.15,
    ) -> None:
        super().__init__()
        self.embeddings = nn.ModuleList(
            [nn.Embedding(cardinality, _embedding_dim(cardinality)) for cardinality in cat_cardinalities]
        )
        embed_dim = sum(_embedding_dim(cardinality) for cardinality in cat_cardinalities)
        in_dim = embed_dim + num_numeric

        layers: list[nn.Module] = []
        last = in_dim
        for hidden in hidden_dims:
            layers.append(nn.Linear(last, hidden))
            layers.append(nn.ReLU())
            layers.append(nn.BatchNorm1d(hidden))
            layers.append(nn.Dropout(dropout))
            last = hidden
        layers.append(nn.Linear(last, out_dim))
        self.mlp = nn.Sequential(*layers)

    def forward(self, cats: torch.Tensor, nums: torch.Tensor) -> torch.Tensor:
        parts: list[torch.Tensor] = []
        if self.embeddings:
            for i, emb in enumerate(self.embeddings):
                parts.append(emb(cats[:, i]))
            cat_repr = torch.cat(parts, dim=1)
            x = torch.cat([cat_repr, nums], dim=1)
        else:
            x = nums
        return self.mlp(x)


class TorchEntityRegressor:
    def __init__(
        self,
        categorical_cols: list[str],
        numeric_cols: list[str],
        hidden_dims: tuple[int, ...] = (256, 128, 64),
        dropout: float = 0.15,
        lr: float = 1e-3,
        weight_decay: float = 1e-5,
        batch_size: int = 2048,
        max_epochs: int = 30,
        patience: int = 5,
        seed: int = 42,
    ) -> None:
        self.categorical_cols = categorical_cols
        self.numeric_cols = numeric_cols
        self.hidden_dims = hidden_dims
        self.dropout = dropout
        self.lr = lr
        self.weight_decay = weight_decay
        self.batch_size = batch_size
        self.max_epochs = max_epochs
        self.patience = patience
        self.seed = seed

        self.preprocessor_: TabularTensorPreprocessor | None = None
        self.state_dict_: dict[str, torch.Tensor] | None = None
        self.training_history_: list[dict[str, float]] = []

    def _build_model(self) -> _EntityEmbeddingNet:
        assert self.preprocessor_ is not None
        return _EntityEmbeddingNet(
            cat_cardinalities=self.preprocessor_.cardinalities(),
            num_numeric=len(self.numeric_cols),
            out_dim=1,
            hidden_dims=self.hidden_dims,
            dropout=self.dropout,
        )

    def fit(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_valid: pd.DataFrame,
        y_valid: pd.Series,
        device: str = "cuda",
    ) -> "TorchEntityRegressor":
        torch.manual_seed(self.seed)
        np.random.seed(self.seed)

        self.preprocessor_ = TabularTensorPreprocessor.fit(X_train, self.categorical_cols, self.numeric_cols)
        train_cat, train_num = self.preprocessor_.transform(X_train)
        valid_cat, valid_num = self.preprocessor_.transform(X_valid)

        train_ds = TensorDataset(
            torch.from_numpy(train_cat),
            torch.from_numpy(train_num),
            torch.from_numpy(y_train.to_numpy(dtype=np.float32)),
        )
        train_loader = DataLoader(train_ds, batch_size=self.batch_size, shuffle=True, drop_last=False)

        model = self._build_model().to(device)
        optimizer = torch.optim.AdamW(model.parameters(), lr=self.lr, weight_decay=self.weight_decay)
        loss_fn = nn.SmoothL1Loss()

        valid_cats = torch.from_numpy(valid_cat).to(device)
        valid_nums = torch.from_numpy(valid_num).to(device)
        valid_y = torch.from_numpy(y_valid.to_numpy(dtype=np.float32)).to(device)

        best_rmse = float("inf")
        best_state: dict[str, torch.Tensor] | None = None
        epochs_without_improve = 0

        for epoch in range(1, self.max_epochs + 1):
            model.train()
            losses: list[float] = []
            for cats_batch, nums_batch, y_batch in train_loader:
                cats_batch = cats_batch.to(device)
                nums_batch = nums_batch.to(device)
                y_batch = y_batch.to(device)

                optimizer.zero_grad(set_to_none=True)
                preds = model(cats_batch, nums_batch).squeeze(1)
                loss = loss_fn(preds, y_batch)
                loss.backward()
                optimizer.step()
                losses.append(float(loss.item()))

            model.eval()
            with torch.no_grad():
                valid_preds = model(valid_cats, valid_nums).squeeze(1)
                valid_rmse = torch.sqrt(torch.mean((valid_preds - valid_y) ** 2)).item()

            self.training_history_.append(
                {
                    "epoch": float(epoch),
                    "train_loss": float(np.mean(losses) if losses else 0.0),
                    "valid_rmse": float(valid_rmse),
                }
            )

            if valid_rmse < best_rmse:
                best_rmse = valid_rmse
                best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
                epochs_without_improve = 0
            else:
                epochs_without_improve += 1
                if epochs_without_improve >= self.patience:
                    break

        self.state_dict_ = best_state
        return self

    def _predict_tensor(self, X: pd.DataFrame, batch_size: int = 4096) -> np.ndarray:
        assert self.preprocessor_ is not None and self.state_dict_ is not None
        cat_array, num_array = self.preprocessor_.transform(X)
        cats = torch.from_numpy(cat_array)
        nums = torch.from_numpy(num_array)
        ds = TensorDataset(cats, nums)
        loader = DataLoader(ds, batch_size=batch_size, shuffle=False, drop_last=False)

        model = self._build_model()
        model.load_state_dict(self.state_dict_)
        model.eval()

        preds: list[np.ndarray] = []
        with torch.no_grad():
            for cat_batch, num_batch in loader:
                out = model(cat_batch, num_batch).squeeze(1).cpu().numpy()
                preds.append(out)
        return np.concatenate(preds, axis=0)

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self._predict_tensor(X)


class TorchEntityClassifier:
    def __init__(
        self,
        categorical_cols: list[str],
        numeric_cols: list[str],
        hidden_dims: tuple[int, ...] = (256, 128, 64),
        dropout: float = 0.15,
        lr: float = 1e-3,
        weight_decay: float = 1e-5,
        batch_size: int = 2048,
        max_epochs: int = 30,
        patience: int = 5,
        seed: int = 42,
    ) -> None:
        self.categorical_cols = categorical_cols
        self.numeric_cols = numeric_cols
        self.hidden_dims = hidden_dims
        self.dropout = dropout
        self.lr = lr
        self.weight_decay = weight_decay
        self.batch_size = batch_size
        self.max_epochs = max_epochs
        self.patience = patience
        self.seed = seed

        self.preprocessor_: TabularTensorPreprocessor | None = None
        self.state_dict_: dict[str, torch.Tensor] | None = None
        self.training_history_: list[dict[str, float]] = []
        self.calibrator_: IsotonicRegression | None = None

    def _build_model(self) -> _EntityEmbeddingNet:
        assert self.preprocessor_ is not None
        return _EntityEmbeddingNet(
            cat_cardinalities=self.preprocessor_.cardinalities(),
            num_numeric=len(self.numeric_cols),
            out_dim=1,
            hidden_dims=self.hidden_dims,
            dropout=self.dropout,
        )

    def fit(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_valid: pd.DataFrame,
        y_valid: pd.Series,
        device: str = "cuda",
    ) -> "TorchEntityClassifier":
        torch.manual_seed(self.seed)
        np.random.seed(self.seed)

        self.preprocessor_ = TabularTensorPreprocessor.fit(X_train, self.categorical_cols, self.numeric_cols)
        train_cat, train_num = self.preprocessor_.transform(X_train)
        valid_cat, valid_num = self.preprocessor_.transform(X_valid)

        train_ds = TensorDataset(
            torch.from_numpy(train_cat),
            torch.from_numpy(train_num),
            torch.from_numpy(y_train.to_numpy(dtype=np.float32)),
        )
        train_loader = DataLoader(train_ds, batch_size=self.batch_size, shuffle=True, drop_last=False)

        model = self._build_model().to(device)
        optimizer = torch.optim.AdamW(model.parameters(), lr=self.lr, weight_decay=self.weight_decay)
        pos_rate = float(y_train.mean()) if len(y_train) else 0.5
        pos_weight = torch.tensor([(1 - pos_rate) / max(pos_rate, 1e-6)], device=device, dtype=torch.float32)
        loss_fn = nn.BCEWithLogitsLoss(pos_weight=pos_weight)

        valid_cats = torch.from_numpy(valid_cat).to(device)
        valid_nums = torch.from_numpy(valid_num).to(device)
        valid_y = torch.from_numpy(y_valid.to_numpy(dtype=np.float32)).to(device)

        best_logloss = float("inf")
        best_state: dict[str, torch.Tensor] | None = None
        epochs_without_improve = 0

        for epoch in range(1, self.max_epochs + 1):
            model.train()
            losses: list[float] = []
            for cats_batch, nums_batch, y_batch in train_loader:
                cats_batch = cats_batch.to(device)
                nums_batch = nums_batch.to(device)
                y_batch = y_batch.to(device)

                optimizer.zero_grad(set_to_none=True)
                logits = model(cats_batch, nums_batch).squeeze(1)
                loss = loss_fn(logits, y_batch)
                loss.backward()
                optimizer.step()
                losses.append(float(loss.item()))

            model.eval()
            with torch.no_grad():
                valid_logits = model(valid_cats, valid_nums).squeeze(1)
                valid_probs = torch.sigmoid(valid_logits).clamp(1e-6, 1 - 1e-6)
                valid_logloss = (
                    -(valid_y * torch.log(valid_probs) + (1 - valid_y) * torch.log(1 - valid_probs)).mean().item()
                )

            self.training_history_.append(
                {
                    "epoch": float(epoch),
                    "train_loss": float(np.mean(losses) if losses else 0.0),
                    "valid_logloss": float(valid_logloss),
                }
            )

            if valid_logloss < best_logloss:
                best_logloss = valid_logloss
                best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
                epochs_without_improve = 0
            else:
                epochs_without_improve += 1
                if epochs_without_improve >= self.patience:
                    break

        self.state_dict_ = best_state
        return self

    def _predict_proba_raw(self, X: pd.DataFrame, batch_size: int = 4096) -> np.ndarray:
        assert self.preprocessor_ is not None and self.state_dict_ is not None
        cat_array, num_array = self.preprocessor_.transform(X)
        cats = torch.from_numpy(cat_array)
        nums = torch.from_numpy(num_array)
        ds = TensorDataset(cats, nums)
        loader = DataLoader(ds, batch_size=batch_size, shuffle=False, drop_last=False)

        model = self._build_model()
        model.load_state_dict(self.state_dict_)
        model.eval()

        probs: list[np.ndarray] = []
        with torch.no_grad():
            for cat_batch, num_batch in loader:
                out = torch.sigmoid(model(cat_batch, num_batch).squeeze(1)).cpu().numpy()
                probs.append(out)
        return np.concatenate(probs, axis=0)

    def set_calibrator(self, calibrator: IsotonicRegression | None) -> "TorchEntityClassifier":
        self.calibrator_ = calibrator
        return self

    def calibrated_copy(self, calibrator: IsotonicRegression) -> "TorchEntityClassifier":
        cloned = deepcopy(self)
        cloned.calibrator_ = calibrator
        return cloned

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        p1 = np.clip(self._predict_proba_raw(X), 1e-6, 1 - 1e-6)
        if self.calibrator_ is not None:
            p1 = np.clip(self.calibrator_.transform(p1), 1e-6, 1 - 1e-6)
        p0 = 1.0 - p1
        return np.column_stack([p0, p1])

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)
