import pika, json

class RabbitClient:
    def __init__(self, host: str):
        self.conn = pika.BlockingConnection(pika.ConnectionParameters(host=host))
        self.ch = self.conn.channel()

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
