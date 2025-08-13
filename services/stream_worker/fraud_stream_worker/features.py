from collections import defaultdict, deque
import math

class FeatureComputer:
    """Online features with simple per-entity velocity state."""
    def __init__(self, maxlen: int = 10):
        self.user_history = defaultdict(lambda: deque(maxlen=maxlen))
        self.merchant_history = defaultdict(lambda: deque(maxlen=maxlen))

    @staticmethod
    def derive_step_from_ts(ts: str) -> int:
        try:
            base_prefix = "2025-08-01T"
            if isinstance(ts, str) and ts.startswith(base_prefix):
                hour = int(ts[11:13]); day = int(ts[8:10])
                return (day - 1) * 24 + hour
            return 0
        except Exception:
            return 0

    def compute(self, event: dict):
        step = event.get("ts_step") or self.derive_step_from_ts(event.get("ts"))
        amount = float(event.get("amount", 0.0))
        user_id = event.get("user_id", "u?")
        merchant = event.get("merchant", "m?")
        ip = event.get("ip", "192.168.0.1")

        u_hist = self.user_history[user_id]
        m_hist = self.merchant_history[merchant]
        user_prev10 = len(u_hist); merchant_prev10 = len(m_hist)
        u_hist.append(step); m_hist.append(step)

        return {
            "amount": amount,
            "log_amount": math.log1p(max(0.0, amount)),
            "hour_mod_24": float(step % 24),
            "user_txn_prev10": user_prev10,
            "merchant_txn_prev10": merchant_prev10,
            "ip_country_mismatch": 1.0 if str(ip).startswith("10.") else 0.0
        }
