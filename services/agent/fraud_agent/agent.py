import os, json, pika
from jsonschema import validate
from .config import Settings
from .storage import SqliteStore
from .llm_client import OllamaClient
from .schemas import AGENT_JSON_SCHEMA

class AgentService:
    def __init__(self, s: Settings):
        self.s = s
        self.store = SqliteStore(self.s.DB_PATH)
        self.client = OllamaClient(self.s.OLLAMA_URL, self.s.AGENT_MODEL)
        self.conn = pika.BlockingConnection(pika.ConnectionParameters(host=self.s.MQ_HOST))
        self.ch = self.conn.channel()
        for q in ["alerts.high_risk","analyst.recommendations"]:
            self.ch.queue_declare(queue=q, durable=True)

        self.system_prompt = open(os.path.join(os.path.dirname(__file__), "prompts/system_prompt.txt")).read()

    def policy_fallback(self, alert: dict) -> dict:
        tau, tau_high = 0.75, 0.9
        try:
            pol = json.load(open(self.s.POLICY_PATH))
            tau = float(pol.get("thresholds",{}).get("tau", tau))
            tau_high = float(pol.get("thresholds",{}).get("tau_high", tau_high))
        except Exception:
            pass
        s = float(alert.get("score",0.0)); reasons = alert.get("reasons",[])
        if s >= tau_high or len(reasons) >= 2: rec = "block"
        elif s >= tau or len(reasons) >= 1: rec = "step_up"
        else: rec = "allow"
        return {
            "decision_recommendation": rec,
            "rationale": f"score={s:.2f}; rules={reasons}; tau={tau:.2f} tau_high={tau_high:.2f}",
            "key_signals": [{"name":k,"value":v} for k,v in (alert.get("features") or {}).items()][:3],
            "actions": ["manual_review_queue"] if rec in ("step_up","block") else ["none"]
        }

    def publish_rec(self, txn_id: str, rec: dict):
        self.ch.basic_publish("", "analyst.recommendations", json.dumps({"txn_id": txn_id, "recommendation": rec}))

    def handle(self, ch, method, props, body):
        try:
            alert = json.loads(body)
        except Exception:
            self.ch.basic_ack(delivery_tag=method.delivery_tag); return

        self.store.upsert_alert(alert)
        hist = self.store.recent(alert.get("user_id"), alert.get("merchant"))

        rec_json = None
        try:
            txt = self.client.chat(self.system_prompt, {"alert": alert, "history": hist})
            candidate = json.loads(txt)
            validate(candidate, AGENT_JSON_SCHEMA)
            rec_json = candidate
        except Exception:
            if self.s.FALLBACK_ENABLE:
                rec_json = self.policy_fallback(alert)

        if rec_json is None:
            rec_json = {"decision_recommendation":"step_up","rationale":"no LLM/invalid JSON","key_signals":[],"actions":["manual_review_queue"]}

        self.publish_rec(alert.get("txn_id"), rec_json)
        self.store.save_recommendation(alert.get("txn_id"), rec_json)
        self.ch.basic_ack(delivery_tag=method.delivery_tag)

    def run(self):
        print("Agent: consuming alerts.high_risk...")
        self.ch.basic_qos(prefetch_count=50)
        self.ch.basic_consume("alerts.high_risk", lambda ch, method, props, body: self.handle(ch, method, props, body), auto_ack=False)
        self.ch.start_consuming()

if __name__ == "__main__":
    AgentService(Settings()).run()
