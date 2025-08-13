from dataclasses import dataclass
import os


@dataclass
class ModelConfig:
    model_path: str = os.environ.get("MODEL_PATH", "/app/artifacts/model.pkl")
    model_cfg_path: str = os.environ.get("MODEL_CONFIG", "/app/artifacts/model_config.json")
