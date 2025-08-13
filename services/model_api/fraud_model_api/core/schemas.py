from pydantic import BaseModel
from typing import Dict


class ScoreIn(BaseModel):
    features: Dict[str, float]

class ScoreOut(BaseModel):
    score: float
