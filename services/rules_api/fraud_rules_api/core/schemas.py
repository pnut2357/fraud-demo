from pydantic import BaseModel
from typing import Dict, List


class EvalIn(BaseModel):
    features: Dict[str, float]

class EvalOut(BaseModel):
    fired: List[str]
