import json, requests
from .config import Settings
from .messaging import RabbitClient
from .features import FeatureComputer

class StreamWorker:
    """Consumes transactions, computes features, calls Model+Rules, emits scores and alerts."""
    def __init__(self, settings: Settings):
        self.s = settings
        self.mq = RabbitClient(self.s.MQ_HOST)
        self.mq.declare("transactions.raw","fraud.scores","alerts.high_risk")
        self.feats = FeatureComputer()

    def handle(self, ch, method, body):
        try:
            tx = json.loads(body)
        except Exception:
            self.mq.ack(method.delivery_tag); return

        feats = self.feats.compute(tx)

        # Model score
        try:
            score = float(requests.post(f"{self.s.MODEL_API}/score", json={"features":feats}, timeout=2).json()["score"])
        except Exception:
            score = 0.0

        self.mq.publish("fraud.scores", {
            "txn_id": tx.get("txn_id"),
            "user_id": tx.get("user_id"),
            "merchant": tx.get("merchant"),
            "amount": tx.get("amount"),
            "features": feats,
            "score": score
        })

        # Rules
        try:
            fired = requests.post(f"{self.s.RULES_API}/eval", json={"features":feats}, timeout=2).json().get("fired", [])
        except Exception:
            fired = []

        # Alert
        if score >= self.s.ALERT_THRESHOLD or fired:
            self.mq.publish("alerts.high_risk", {
                "txn_id": tx.get("txn_id"),
                "user_id": tx.get("user_id"),
                "merchant": tx.get("merchant"),
                "amount": tx.get("amount"),
                "score": score,
                "reasons": fired,
                "threshold": self.s.ALERT_THRESHOLD,
                "ts": tx.get("ts"),
                "features": feats
            })

        self.mq.ack(method.delivery_tag)

    def run(self):
        print("StreamWorker: consuming transactions.raw...")
        self.mq.consume("transactions.raw", self.handle)

if __name__ == "__main__":
    StreamWorker(Settings()).run()
