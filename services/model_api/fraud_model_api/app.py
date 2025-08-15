from typing import Dict, List, Optional, Any
from fastapi import FastAPI, HTTPException
from .core.config import ModelConfig          # keep if you want to load artifact paths from here
from .core.model_service import ModelService  # required
from .core.schemas import ScoreIn, ScoreOut   # reuse request schema

# Extend your existing ScoreOut so we can include explanations + feature list
class ScoreOutV2(ScoreOut):
    explain: Optional[Dict[str, Any]] = None  # {"bias":..., "contribs": {...}, "top_factors":[...]}
    features: List[str]                       # model’s expected feature order

app = FastAPI(title="Fraud Model API", version="1.0.0")

_service: Optional[ModelService] = None
_startup_error: Optional[str] = None

@app.on_event("startup")
def _startup():
    global _service, _startup_error
    try:
        cfg = ModelConfig()  # expects .model_path and .model_cfg_path inside
        _service = ModelService(cfg.model_path, cfg.model_cfg_path)
        _startup_error = None
    except Exception as e:
        _service = None
        _startup_error = f"{type(e).__name__}: {e}"

@app.get("/health")
def health():
    if _service is None:
        return {
            "status": "error",
            "reason": _startup_error or "model not loaded",
            "expects": {"model": "./artifacts/model.pkl", "config": "./artifacts/model_config.json"},
        }
    return {"status": "ok", "features": _service.features}

@app.get("/features")
def features():
    if _service is None:
        raise HTTPException(status_code=503, detail="model not loaded")
    return {"features": _service.features}

@app.post("/score", response_model=ScoreOutV2)
def score(req: ScoreIn):
    if _service is None:
        raise HTTPException(status_code=503, detail="model not loaded")

    # Prefer explanation-capable scorer if present
    if hasattr(_service, "score_with_explain"):
        res = _service.score_with_explain(req.features)  # {"score": ..., "explain": {...}}
        return ScoreOutV2(score=res["score"], explain=res.get("explain"), features=_service.features)
    else:
        p = _service.score(req.features)
        return ScoreOutV2(score=p, explain=None, features=_service.features)

@app.get("/")
def root():
    return {"service": "fraud-model-api", "endpoints": ["/health", "/features", "/score"]}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("fraud_model_api.app:app", host="0.0.0.0", port=8001, reload=False)

# from __future__ import annotations
#
# import json
# from typing import Dict, List, Optional, Any
#
# from fastapi import FastAPI, HTTPException
# from pydantic import BaseModel, Field
# from .core.schemas import ScoreIn, ScoreOut
#
# # Try to import your existing config + service
# try:
#     # expected to define something like model_path, model_cfg_path
#     from .core.config import Settings as AppSettings
# except Exception:
#     # Some repos used "Config" instead of "Settings"
#     try:
#         from .core.config import Config as AppSettings  # type: ignore
#     except Exception:
#         AppSettings = None  # fallback to defaults below
#
# try:
#     from .core.model_service import ModelService
# except Exception as e:
#     raise RuntimeError(f"Cannot import ModelService: {e}")
#
# # --------- Pydantic I/O schemas ---------
# class ScoreRequest(BaseModel):
#     features: Dict[str, float] = Field(..., description="Feature map expected by the model")
#
# class ScoreResponse(BaseModel):
#     score: float
#     features: List[str]
#     explain: Optional[Dict[str, Any]] = None  # contains bias, contribs, top_factors
#
#
# # --------- App + global state ----------
# app = FastAPI(title="Fraud Model API", version="1.0.0")
#
# _service: Optional[ModelService] = None
# _startup_error: Optional[str] = None
#
#
# def _load_settings_paths():
#     """
#     Resolve artifact paths from your repo's config, with safe fallbacks.
#     """
#     if AppSettings is not None:
#         cfg = AppSettings()  # may read env or defaults from your config.py
#         # Try common attribute names:
#         model_path = getattr(cfg, "model_path", "./artifacts/model.pkl")
#         model_cfg_path = getattr(cfg, "model_cfg_path", "./artifacts/model_config.json")
#         return str(model_path), str(model_cfg_path)
#     # Fallback to conventional locations
#     return "./artifacts/model.pkl", "./artifacts/model_config.json"
#
#
# @app.on_event("startup")
# def _startup():
#     global _service, _startup_error
#     model_path, model_cfg_path = _load_settings_paths()
#     try:
#         _service = ModelService(model_path, model_cfg_path)
#         _startup_error = None
#     except Exception as e:
#         # Do not crash the container; report via /health
#         _service = None
#         _startup_error = f"{type(e).__name__}: {e}"
#
#
# @app.get("/health")
# def health():
#     """
#     Returns service readiness and, if not ready, the reason (e.g., missing artifacts).
#     """
#     if _service is None:
#         return {
#             "status": "error",
#             "reason": _startup_error or "model not loaded",
#             "expects": {"model": "./artifacts/model.pkl", "config": "./artifacts/model_config.json"},
#         }
#     return {"status": "ok", "features": _service.features}
#
#
# @app.get("/features")
# def features():
#     if _service is None:
#         raise HTTPException(status_code=503, detail="model not loaded")
#     return {"features": _service.features}
#
#
# @app.post("/score", response_model=ScoreResponse)
# def score(req: ScoreRequest):
#     """
#     Scores a feature dict. Returns probability and lightweight explanation.
#
#     Response.explain:
#       - bias: intercept term of the linear model (if available)
#       - contribs: per-feature logit contributions on standardized inputs
#       - top_factors: top |contribution| features (for quick display)
#     """
#     if _service is None:
#         raise HTTPException(status_code=503, detail="model not loaded")
#
#     # Prefer the explain-enabled scorer if available
#     try:
#         res = _service.score_with_explain(req.features)  # type: ignore[attr-defined]
#         return ScoreResponse(score=res["score"], explain=res.get("explain"), features=_service.features)
#     except AttributeError:
#         # Backward compatibility if your ModelService only implements score()
#         p = _service.score(req.features)
#         return ScoreResponse(score=p, explain=None, features=_service.features)
#
#
# # Optional: simple root to hint where to go
# @app.get("/")
# def root():
#     return {"service": "fraud-model-api", "endpoints": ["/health", "/features", "/score"]}
#
#
# # Running with `uvicorn fraud_model_api.app:app --host 0.0.0.0 --port 8001`
# # is recommended; keep this for ad-hoc local runs.
# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run("fraud_model_api.app:app", host="0.0.0.0", port=8001, reload=False)

####################

# from fastapi import FastAPI, HTTPException
# from .core.config import ModelConfig
# from .core.model_service import ModelService
# from .core.schemas import ScoreIn, ScoreOut


# cfg = ModelConfig()
# try:
#     service = ModelService(cfg.model_path, cfg.model_cfg_path)
# except Exception as e:
#     service = None  # run without artifacts; /score returns 0.0
#
# app = FastAPI(title="Fraud Model API", version="1.0")
#
# @app.get("/health")
# def health():
#     # return {"status":"ok", "features": service.features}
#     return {"status": "ok", "features": (service.features if service else [])}
#
# @app.post("/score", response_model=ScoreOut)
# def score(inp: ScoreIn):
#     # try:
#     #     return {"score": service.score(inp.features)}
#     # except Exception as e:
#     #     raise HTTPException(status_code=400, detail=f"Scoring failed: {e}")
#     if service is None: return {"score": 0.0}
#     res = service.score_with_explain(req)
#     try:
#         return {"score": service.score(inp.features)}
#     except Exception as e:
#         raise HTTPException(status_code=400, detail=f"Scoring failed: {e}")
