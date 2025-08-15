import os, time, pika, json

class RabbitClient:
    def __init__(self, host: str, port: int = 5672, vhost: str = "/",
                 user: str | None = None, password: str | None = None,
                 retries: int = 30, delay: float = 2.0):
        user = user or os.getenv("MQ_USER", "guest")
        password = password or os.getenv("MQ_PASS", "guest")
        # Fix vhost handling - remove trailing slash for default vhost
        vhost_path = "" if vhost == "/" else f"/{vhost}"
        url = f"amqp://{user}:{password}@{host}:{port}{vhost_path}"
        params = pika.URLParameters(url)
        params.heartbeat = 30
        params.blocked_connection_timeout = 300

        last_err = None
        for attempt in range(1, retries + 1):
            try:
                self.conn = pika.BlockingConnection(params)
                self.ch = self.conn.channel()
                # declare queues we rely on (idempotent)
                for q in ["transactions.raw", "fraud.scores", "alerts.high_risk"]:
                    self.ch.queue_declare(queue=q, durable=True)
                return
            except Exception as e:
                last_err = e
                print(f"[RabbitClient] connect failed (attempt {attempt}/{retries}): {e}", flush=True)
                time.sleep(delay)
        raise last_err

    def declare(self, *queues):
        for q in queues:
            self.ch.queue_declare(queue=q, durable=True)

    def consume(self, queue: str, callback):
        self.ch.basic_qos(prefetch_count=100)
        self.ch.basic_consume(queue, lambda ch, method, props, body: callback(ch, method, body), auto_ack=False)
        self.ch.start_consuming()

    def publish(self, queue: str, obj: dict):
        self.ch.basic_publish("", queue, json.dumps(obj))

    def ack(self, delivery_tag):
        self.ch.basic_ack(delivery_tag=delivery_tag)
