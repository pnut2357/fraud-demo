from fastapi import FastAPI, HTTPException
from .core.config import ModelConfig
from .core.model_service import ModelService
from .core.schemas import ScoreIn, ScoreOut


cfg = ModelConfig()
service = ModelService(cfg.model_path, cfg.model_cfg_path)

app = FastAPI(title="Fraud Model API", version="1.0")

@app.get("/health")
def health():
    return {"status":"ok", "features": service.features}

@app.post("/score", response_model=ScoreOut)
def score(inp: ScoreIn):
    try:
        return {"score": service.score(inp.features)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Scoring failed: {e}")
