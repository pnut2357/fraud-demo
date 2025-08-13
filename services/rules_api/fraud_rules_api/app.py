from fastapi import FastAPI
from .core.config import RulesConfig
from .core.rules_engine import RulesEngine
from .core.schemas import EvalIn, EvalOut


cfg = RulesConfig()
engine = RulesEngine(cfg.rules_path)

app = FastAPI(title="Fraud Rules API", version="1.0")

@app.get("/health")
def health():
    return {"status":"ok", "rules_count": len(engine.rules)}

@app.post("/eval", response_model=EvalOut)
def eval_rules(inp: EvalIn):
    fired = engine.eval({k: float(v) for k, v in inp.features.items()})
    return {"fired": fired}
