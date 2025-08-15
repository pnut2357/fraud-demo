import os, json, time, pika
from pika.exceptions import AMQPConnectionError, StreamLostError, ChannelClosedByBroker
from jsonschema import validate

from .config import Settings
from .storage import SqliteStore
from .llm_client import OllamaClient
from .schemas import AGENT_JSON_SCHEMA


def connect_with_retry(
    host: str,
    port: int = 5672,
    vhost: str = "/",
    retries: int = 10,
    delay: float = 2.0,
):
    """Open a BlockingConnection with backoff; declare required queues."""
    user = os.getenv("MQ_USER", "guest")
    password = os.getenv("MQ_PASS", "guest")
    vhost = (os.getenv("MQ_VHOST") or "/").strip() or "/"

    creds = pika.PlainCredentials(user, password)
    params = pika.ConnectionParameters(
        host=host,
        port=port,
        virtual_host=vhost,  # <- this is the key; defaults to "/"
        credentials=creds,
        heartbeat=30,
        blocked_connection_timeout=300,
    )

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            conn = pika.BlockingConnection(params)
            ch = conn.channel()
            for q in ["alerts.high_risk", "analyst.recommendations"]:
                ch.queue_declare(queue=q, durable=True)
            print(f"[Agent AMQP] connected host={host} vhost={vhost}", flush=True)
            return conn, ch
        except Exception as e:
            last_err = e
            print(f"[Agent AMQP] connect failed ({attempt}/{retries}): {e}", flush=True)
            time.sleep(delay)
    raise last_err

def _normalize_key_signals(obj: dict, alert: dict | None = None, max_items: int = 5) -> dict:
    """
    Ensure obj['key_signals'] is a list of {"name": str, "value": number}.
    - Coerces booleans to 1/0.
    - Drops non-numeric values (lists/strings/dicts) unless we can backfill:
        • If name matches a numeric feature in alert["features"] → use that number
        • If name matches a fired rule in alert["reasons"]       → use 1.0
    - Trims to max_items items.
    """
    ks = obj.get("key_signals")
    cleaned = []
    if isinstance(ks, list):
        feats = ((alert or {}).get("features")) or {}
        reasons = set(((alert or {}).get("reasons")) or [])
        for item in ks:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue

            val = item.get("value")

            # Coerce booleans
            if isinstance(val, bool):
                val = 1 if val else 0

            if isinstance(val, (int, float)):
                cleaned.append({"name": name, "value": float(val)})
            else:
                # Try to backfill from features or fired rules
                if name in feats and isinstance(feats[name], (int, float)):
                    cleaned.append({"name": name, "value": float(feats[name])})
                elif name in reasons:
                    cleaned.append({"name": name, "value": 1.0})
                else:
                    # Unknown/non-numeric signal – skip it
                    continue

            if len(cleaned) >= max_items:
                break

    obj["key_signals"] = cleaned
    return obj


class AgentService:
    def __init__(self, s: Settings):
        self.s = s
        self.store = SqliteStore(self.s.DB_PATH)
        self.client = OllamaClient(self.s.OLLAMA_URL, self.s.AGENT_MODEL)

        # AMQP connection (with retry) — supports MQ_HOST, MQ_PORT, MQ_VHOST, MQ_USER, MQ_PASS
        host = self.s.MQ_HOST
        port = int(os.getenv("MQ_PORT", "5672"))
        vhost = os.getenv("MQ_VHOST", "/")
        self.conn, self.ch = connect_with_retry(host, port, vhost=vhost)

        sp_path = os.path.join(os.path.dirname(__file__), "prompts", "system_prompt.txt")
        with open(sp_path, "r", encoding="utf-8") as f:
            self.system_prompt = f.read()

    def policy_fallback(self, alert: dict) -> dict:
        tau, tau_high = 0.75, 0.9
        try:
            with open(self.s.POLICY_PATH, "r", encoding="utf-8") as f:
                pol = json.load(f)
            tau = float(pol.get("thresholds", {}).get("tau", tau))
            tau_high = float(pol.get("thresholds", {}).get("tau_high", tau_high))
        except Exception:
            pass
        s = float(alert.get("score", 0.0))
        reasons = alert.get("reasons", [])
        if s >= tau_high or len(reasons) >= 2:
            rec = "block"
        elif s >= tau or len(reasons) >= 1:
            rec = "step_up"
        else:
            rec = "allow"
        return {
            "decision_recommendation": rec,
            "rationale": f"score={s:.2f}; rules={reasons}; tau={tau:.2f} tau_high={tau_high:.2f}",
            "key_signals": [{"name": k, "value": v} for k, v in (alert.get("features") or {}).items()][:3],
            "actions": ["manual_review_queue"] if rec in ("step_up", "block") else ["none"],
        }

    def publish_rec(self, txn_id: str, rec: dict):
        props = pika.BasicProperties(
            delivery_mode=2,  # make message persistent
            content_type="application/json",
        )
        self.ch.basic_publish(
            exchange="",
            routing_key="analyst.recommendations",
            body=json.dumps({"txn_id": txn_id, "recommendation": rec}),
            properties=props,
        )

    def handle(self, ch, method, props, body):
        try:
            alert = json.loads(body)
        except Exception:
            ch.basic_ack(delivery_tag=method.delivery_tag)
            return

        # 1) persist alert
        self.store.upsert_alert(alert)

        # 2) fetch brief history
        hist = self.store.recent(alert.get("user_id"), alert.get("merchant"))

        score = float(alert.get("score", 0.0) or 0.0)
        min_llm = float(os.getenv("MIN_SCORE_FOR_LLM", "0.001"))  # optional knob
        if score <= min_llm:
            rec_json = self.policy_fallback(alert)
            # make the reason explicit
            rec_json["rationale"] = f"[no-llm: score={score:.3f}<=min_llm={min_llm}] " + rec_json.get("rationale", "")
            self.publish_rec(alert.get("txn_id"), rec_json)
            self.store.save_recommendation(alert.get("txn_id"), rec_json)
            self.ch.basic_ack(delivery_tag=method.delivery_tag)
            return
        # 3) query LLM (strict JSON), else fallback policy
        rec_json = None
        try:
            txt = self.client.chat(self.system_prompt, {"alert": alert, "history": hist})
            candidate = json.loads(txt)
            candidate = _normalize_key_signals(candidate)
            validate(candidate, AGENT_JSON_SCHEMA)
            rec_json = candidate
        except Exception as e:
            print(f"[Agent] LLM/validation failed, using fallback: {e}", flush=True)
            if self.s.FALLBACK_ENABLE:
                rec_json = self.policy_fallback(alert)

        if rec_json is None:
            rec_json = {
                "decision_recommendation": "step_up",
                "rationale": "no LLM/invalid JSON",
                "key_signals": [],
                "actions": ["manual_review_queue"],
            }

        # 4) publish + persist recommendation
        self.publish_rec(alert.get("txn_id"), rec_json)
        self.store.save_recommendation(alert.get("txn_id"), rec_json)

        # 5) ack
        ch.basic_ack(delivery_tag=method.delivery_tag)

    def _setup_consumer(self):
        self.ch.basic_qos(prefetch_count=50)
        self.ch.basic_consume(
            queue="alerts.high_risk",
            on_message_callback=self.handle,
            auto_ack=False,
        )

    def run(self):
        print("Agent: consuming alerts.high_risk...", flush=True)
        self._setup_consumer()
        while True:
            try:
                self.ch.start_consuming()
            except (KeyboardInterrupt, SystemExit):
                try:
                    self.ch.stop_consuming()
                except Exception:
                    pass
                break
            except (AMQPConnectionError, StreamLostError, ChannelClosedByBroker) as e:
                # auto-reconnect path
                print(f"[Agent] AMQP lost: {e}. Reconnecting...", flush=True)
                time.sleep(2.0)
                host = self.s.MQ_HOST
                port = int(os.getenv("MQ_PORT", "5672"))
                vhost = os.getenv("MQ_VHOST", "/")
                self.conn, self.ch = connect_with_retry(host, port, vhost)
                self._setup_consumer()
            except Exception as e:
                # don't crash the process; log and continue
                print(f"[Agent] unexpected error: {e}", flush=True)
                time.sleep(1.0)


if __name__ == "__main__":
    AgentService(Settings()).run()

# import os, json, pika
# from jsonschema import validate
# from .config import Settings
# from .storage import SqliteStore
# from .llm_client import OllamaClient
# from .schemas import AGENT_JSON_SCHEMA
#
# class AgentService:
#     def __init__(self, s: Settings):
#         self.s = s
#         self.store = SqliteStore(self.s.DB_PATH)
#         self.client = OllamaClient(self.s.OLLAMA_URL, self.s.AGENT_MODEL)
#         self.conn = pika.BlockingConnection(pika.ConnectionParameters(host=self.s.MQ_HOST))
#         self.ch = self.conn.channel()
#         for q in ["alerts.high_risk","analyst.recommendations"]:
#             self.ch.queue_declare(queue=q, durable=True)
#
#         self.system_prompt = open(os.path.join(os.path.dirname(__file__), "prompts/system_prompt.txt")).read()
#
#     def policy_fallback(self, alert: dict) -> dict:
#         tau, tau_high = 0.75, 0.9
#         try:
#             pol = json.load(open(self.s.POLICY_PATH))
#             tau = float(pol.get("thresholds",{}).get("tau", tau))
#             tau_high = float(pol.get("thresholds",{}).get("tau_high", tau_high))
#         except Exception:
#             pass
#         s = float(alert.get("score",0.0)); reasons = alert.get("reasons",[])
#         if s >= tau_high or len(reasons) >= 2: rec = "block"
#         elif s >= tau or len(reasons) >= 1: rec = "step_up"
#         else: rec = "allow"
#         return {
#             "decision_recommendation": rec,
#             "rationale": f"score={s:.2f}; rules={reasons}; tau={tau:.2f} tau_high={tau_high:.2f}",
#             "key_signals": [{"name":k,"value":v} for k,v in (alert.get("features") or {}).items()][:3],
#             "actions": ["manual_review_queue"] if rec in ("step_up","block") else ["none"]
#         }
#
#     def publish_rec(self, txn_id: str, rec: dict):
#         self.ch.basic_publish("", "analyst.recommendations", json.dumps({"txn_id": txn_id, "recommendation": rec}))
#
#     def handle(self, ch, method, props, body):
#         try:
#             alert = json.loads(body)
#         except Exception:
#             self.ch.basic_ack(delivery_tag=method.delivery_tag); return
#
#         self.store.upsert_alert(alert)
#         hist = self.store.recent(alert.get("user_id"), alert.get("merchant"))
#
#         rec_json = None
#         try:
#             txt = self.client.chat(self.system_prompt, {"alert": alert, "history": hist})
#             candidate = json.loads(txt)
#             validate(candidate, AGENT_JSON_SCHEMA)
#             rec_json = candidate
#         except Exception:
#             if self.s.FALLBACK_ENABLE:
#                 rec_json = self.policy_fallback(alert)
#
#         if rec_json is None:
#             rec_json = {"decision_recommendation":"step_up","rationale":"no LLM/invalid JSON","key_signals":[],"actions":["manual_review_queue"]}
#
#         self.publish_rec(alert.get("txn_id"), rec_json)
#         self.store.save_recommendation(alert.get("txn_id"), rec_json)
#         self.ch.basic_ack(delivery_tag=method.delivery_tag)
#
#     def run(self):
#         print("Agent: consuming alerts.high_risk...")
#         self.ch.basic_qos(prefetch_count=50)
#         self.ch.basic_consume("alerts.high_risk", lambda ch, method, props, body: self.handle(ch, method, props, body), auto_ack=False)
#         self.ch.start_consuming()
#
# if __name__ == "__main__":
#     AgentService(Settings()).run()
