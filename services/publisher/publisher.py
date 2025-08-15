import os, json, time, pika


AMQP_URL = os.environ.get("AMQP_URL", "amqp://guest:guest@rabbitmq:5672/")
QUEUE    = os.environ.get("QUEUE", "transactions.raw")
FILE     = os.environ.get("FILE_PATH", "/data/transactions_sample.jsonl")
RATE     = float(os.environ.get("RATE", "0"))  # messages/sec; 0 = as fast as possible


def main():
    conn = pika.BlockingConnection(pika.URLParameters(AMQP_URL))
    ch = conn.channel()
    ch.queue_declare(queue=QUEUE, durable=True)

    delay = 1.0 / RATE if RATE > 0 else 0
    sent = 0
    with open(FILE) as f:
        for line in f:
            line = line.strip()
            if not line: continue
            ch.basic_publish(exchange="", routing_key=QUEUE, body=line)
            sent += 1
            if delay: time.sleep(delay)
    print(f"Published {sent} messages to {QUEUE}")
    conn.close()

if __name__ == "__main__":
    main()