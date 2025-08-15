import os, json, requests
from .config import Settings
from .messaging import RabbitClient
from .features import FeatureComputer


def load_policy_thresholds(policy_path: str, tau_default: float):
    """Read tau/tau_high from decision_policy.json if present; else fall back to env var or defaults."""
    tau = tau_default
    tau_high = float(os.getenv("ALERT_THRESHOLD_HIGH", tau + 0.15))  # sensible gap
    try:
        with open(policy_path, "r", encoding="utf-8") as f:
            pol = json.load(f)
        th = pol.get("thresholds", {})
        tau = float(th.get("tau", tau))
        tau_high = float(th.get("tau_high", tau_high))
    except Exception:
        # policy file optional
        pass
    return tau, tau_high

def baseline_decision(score: float, rules: list[str], tau: float, tau_high: float) -> str:
    """What the pipeline would do without the Agent."""
    if score >= tau_high or len(rules) >= 2:
        return "block"
    if score >= tau or len(rules) >= 1:
        return "step_up"
    return "allow"


class StreamWorker:
    """Consumes transactions, computes features, calls Model+Rules, emits scores and alerts."""
    def __init__(self, settings: Settings):
        self.s = settings
        self.mq = RabbitClient(self.s.MQ_HOST)
        self.mq.declare("transactions.raw","fraud.scores","alerts.high_risk")
        self.feats = FeatureComputer()
        # thresholds (tau / tau_high) from policy or env; defaults okay for demo
        policy_path = os.getenv("POLICY_PATH", "/app/config/decision_policy.json")
        self.tau, self.tau_high = load_policy_thresholds(policy_path, float(self.s.ALERT_THRESHOLD))

    def _model_score_and_explain(self, feats: dict):
        """
        Calls Model API /score. Returns (score, top_factors) where top_factors is a list of
        {feature, contribution}. Handles older model_api that lacks 'explain'.
        """
        try:
            resp = requests.post(f"{self.s.MODEL_API}/score", json={"features": feats}, timeout=3)
            data = resp.json()
            score = float(data.get("score", 0.0))
            top_factors = (data.get("explain") or {}).get("top_factors", [])
            if not isinstance(top_factors, list):
                top_factors = []
            return score, top_factors
        except Exception as e:
            print(f"[ERROR] Model API call failed: {type(e).__name__}: {e}", flush=True)
            return 0.0, []

    def _rules_fired(self, feats: dict):
        try:
            r = requests.post(f"{self.s.RULES_API}/eval", json={"features": feats}, timeout=2).json()
            fired = r.get("fired", [])
            return fired if isinstance(fired, list) else []
        except Exception:
            return []

    def handle(self, ch, method, body):
        try:
            tx = json.loads(body)
        except Exception:
            self.mq.ack(method.delivery_tag)
            return

        # Normalize IDs for PaySim-derived events
        user_id = tx.get("user_id") or tx.get("nameOrig")
        merchant = tx.get("merchant") or tx.get("nameDest")
        ts = tx.get("ts") or tx.get("timestamp")

        # Compute online features
        feats = self.feats.compute(tx)
        print(f"[DEBUG] Processing transaction {tx.get('txn_id')} with features: {feats}", flush=True)

        # Model + explain
        score, top_factors = self._model_score_and_explain(feats)
        print(f"[DEBUG] Model score: {score}", flush=True)

        # Rules
        fired = self._rules_fired(feats)

        # Ground-truth & balances (pass-through if present)
        label = tx.get("isFraud")
        flagged = tx.get("isFlaggedFraud")
        balances = {
            "oldbalanceOrg": tx.get("oldbalanceOrg"),
            "newbalanceOrig": tx.get("newbalanceOrig"),
            "oldbalanceDest": tx.get("oldbalanceDest"),
            "newbalanceDest": tx.get("newbalanceDest"),
        }

        # Baseline (pipeline-only) decision without Agent
        base_dec = baseline_decision(score, fired, self.tau, self.tau_high)

        # Telemetry topic (debug/metrics)
        self.mq.publish("fraud.scores", {
            "txn_id": tx.get("txn_id"),
            "user_id": user_id,
            "merchant": merchant,
            "amount": tx.get("amount"),
            "features": feats,
            "score": score,
            "reasons": fired,
            "label": label  # so offline consumers can compute PR curves, etc.
        })

        # Alert path (only for step_up/block baseline)
        if base_dec in ("step_up", "block"):
            alert = {
                "txn_id": tx.get("txn_id"),
                "ts": ts,
                "user_id": user_id,
                "merchant": merchant,
                "amount": tx.get("amount"),
                "features": feats,
                "score": score,
                "reasons": fired,
                "threshold": self.tau,
                "baseline_decision": base_dec,  # << baseline pipeline decision
                "model_top_factors": top_factors,  # << explanation from model_api
                "isFraud": label,  # << ground-truth
                "isFlaggedFraud": flagged,  # dataset’s own rule-based flag
                **balances,  # << balances for context/explainability
            }
            self.mq.publish("alerts.high_risk", alert)

        self.mq.ack(method.delivery_tag)

    def run(self):
        print(f"StreamWorker: consuming transactions.raw... (tau={self.tau:.2f}, tau_high={self.tau_high:.2f})")
        self.mq.consume("transactions.raw", self.handle)

if __name__ == "__main__":
    StreamWorker(Settings()).run()

    # def handle(self, ch, method, body):
    #     try:
    #         tx = json.loads(body)
    #     except Exception:
    #         self.mq.ack(method.delivery_tag); return
    #
    #     feats = self.feats.compute(tx)
    #
    #     # Model score
    #     try:
    #         score = float(requests.post(f"{self.s.MODEL_API}/score", json={"features":feats}, timeout=2).json()["score"])
    #     except Exception:
    #         score = 0.0
    #
    #     self.mq.publish("fraud.scores", {
    #         "txn_id": tx.get("txn_id"),
    #         "user_id": tx.get("user_id"),
    #         "merchant": tx.get("merchant"),
    #         "amount": tx.get("amount"),
    #         "features": feats,
    #         "score": score
    #     })
    #
    #     # Rules
    #     try:
    #         fired = requests.post(f"{self.s.RULES_API}/eval", json={"features":feats}, timeout=2).json().get("fired", [])
    #     except Exception:
    #         fired = []
    #
    #     # Alert
    #     if score >= self.s.ALERT_THRESHOLD or fired:
    #         self.mq.publish("alerts.high_risk", {
    #             "txn_id": tx.get("txn_id"),
    #             "user_id": tx.get("user_id"),
    #             "merchant": tx.get("merchant"),
    #             "amount": tx.get("amount"),
    #             "score": score,
    #             "reasons": fired,
    #             "threshold": self.s.ALERT_THRESHOLD,
    #             "ts": tx.get("ts"),
    #             "features": feats
    #         })
    #
    #     self.mq.ack(method.delivery_tag)

#     def run(self):
#         print("StreamWorker: consuming transactions.raw...")
#         self.mq.consume("transactions.raw", self.handle)
#
# if __name__ == "__main__":
#     StreamWorker(Settings()).run()
