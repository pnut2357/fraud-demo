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

    def score(self, feats: Dict[str, float]) -> float:
        x = np.array([[float(feats.get(f, 0.0)) for f in self.features]])
        return float(self.pipe.predict_proba(x)[0, 1])
