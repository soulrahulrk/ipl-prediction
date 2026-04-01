from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class IsotonicCalibratedModel:
    base_model: object
    calibrator: object

    def predict_proba(self, X):
        raw = self.base_model.predict_proba(X)
        p1 = np.clip(self.calibrator.transform(raw[:, 1]), 0.0, 1.0)
        p0 = 1.0 - p1
        return np.column_stack([p0, p1])

    def predict(self, X):
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)
