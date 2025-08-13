from dataclasses import dataclass
import os

@dataclass
class RulesConfig:
    rules_path: str = os.environ.get("RULES_PATH", "/app/config/rules.yaml")
