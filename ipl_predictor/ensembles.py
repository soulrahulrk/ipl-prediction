from __future__ import annotations

import numpy as np


class WeightedRegressorEnsemble:
    def __init__(self, models: list, weights: list[float]):
        if len(models) != len(weights):
            raise ValueError("models and weights must have the same length")
        self.models = models
        self.weights = np.array(weights, dtype=float) / np.sum(weights)

    def predict(self, X):
        predictions = np.column_stack([model.predict(X) for model in self.models])
        return predictions @ self.weights


class WeightedClassifierEnsemble:
    def __init__(self, models: list, weights: list[float]):
        if len(models) != len(weights):
            raise ValueError("models and weights must have the same length")
        self.models = models
        self.weights = np.array(weights, dtype=float) / np.sum(weights)

    def predict_proba(self, X):
        probabilities = np.stack([model.predict_proba(X) for model in self.models], axis=0)
        return np.tensordot(self.weights, probabilities, axes=(0, 0))

    def predict(self, X):
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)
