import ast, yaml
from typing import Dict, List


ALLOWED = (ast.Expression, ast.BoolOp, ast.BinOp, ast.UnaryOp, ast.Compare,
           ast.Name, ast.Load, ast.Constant, ast.And, ast.Or,
           ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow,
           ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE)

def _safe_eval(expr: str, ctx: Dict[str, float]) -> bool:
    node = ast.parse(expr, mode='eval')
    for n in ast.walk(node):
        if not isinstance(n, ALLOWED) or isinstance(n, (ast.Attribute, ast.Call, ast.Subscript)):
            raise ValueError("Unsupported expression")
    return bool(eval(compile(node, "<expr>", "eval"), {"__builtins__": {}}, ctx))

class RulesEngine:
    def __init__(self, rules_path: str):
        with open(rules_path, "r") as f:
            self.rules = yaml.safe_load(f) or []

    def eval(self, feats: Dict[str, float]) -> List[str]:
        fired = []
        for r in self.rules:
            rid, cond = r.get("id"), r.get("if", "")
            try:
                if cond and _safe_eval(cond, feats):
                    fired.append(rid)
            except Exception:
                continue
        return fired
