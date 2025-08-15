import json, os
from typing import List, Dict
import numpy as np
import joblib


class ModelService:
    """Loads a scikit-learn Pipeline and scores feature dicts."""
    def __init__(self, model_path: str, model_cfg_path: str):
        if not (os.path.exists(model_path) and os.path.exists(model_cfg_path)):
            raise RuntimeError("Model artifacts not found. Place model.pkl and model_config.json in ./artifacts")
        self.pipe = joblib.load(model_path)
        with open(model_cfg_path, "r") as f:
            cfg = json.load(f)
        self.features: List[str] = cfg.get("features", [])
        # Pull out scaler + clf for explanations
        self.scaler = self.pipe.named_steps.get("scaler")
        self.clf = self.pipe.named_steps.get("clf")
        if self.scaler is None or self.clf is None:
            raise RuntimeError("Expect Pipeline(scaler, clf) for explainability.")

    def _vec(self, feats: dict) -> np.ndarray:
        return np.array([float(feats[k]) for k in self.features], dtype=float).reshape(1, -1)

    # def score(self, feats: Dict[str, float]) -> float:
    #     x = np.array([[float(feats.get(f, 0.0)) for f in self.features]])
    #     return float(self.pipe.predict_proba(x)[0, 1])
    def score(self, feats: dict) -> float:
        X = self._vec(feats)
        p = self.pipe.predict_proba(X)[0, 1]
        return float(p)

    def score_with_explain(self, feats: dict) -> dict:
        X = self._vec(feats)
        # contributions on standardized features
        x_scaled = (X - self.scaler.mean_) / self.scaler.scale_
        contrib = (self.clf.coef_[0] * x_scaled[0])
        bias = float(self.clf.intercept_[0])
        # top absolute contributors
        pairs = list(zip(self.features, contrib.tolist()))
        top = sorted(pairs, key=lambda t: abs(t[1]), reverse=True)[:3]
        p = float(self.pipe.predict_proba(X)[0, 1])
        return {
            "score": p,
            "explain": {
                "bias": bias,
                "contribs": {k: float(v) for k, v in pairs},
                "top_factors": [{"feature": k, "contribution": float(v)} for k, v in top],
            },
        }
