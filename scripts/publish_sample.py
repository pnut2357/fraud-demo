#!/usr/bin/env python3
import argparse, json, pika

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, help="transactions_sample.jsonl")
    ap.add_argument("--amqp", default="amqp://guest:guest@localhost:5672/")
    args = ap.parse_args()

    conn = pika.BlockingConnection(pika.URLParameters(args.amqp))
    ch = conn.channel()
    ch.queue_declare(queue="transactions.raw", durable=True)

    count = 0
    with open(args.file) as f:
        for line in f:
            line=line.strip()
            if not line: continue
            ch.basic_publish("", "transactions.raw", line)
            count += 1
    print(f"Published {count} messages")

if __name__ == "__main__":
    main()
