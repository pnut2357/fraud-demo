#!/usr/bin/env python3
import pika
import json
import sqlite3
import os
from datetime import datetime

# Database path
DB_PATH = "data/fraud.db"

def store_fraud_score(data):
    """Store a fraud score in the database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO fraud_scores 
            (txn_id, user_id, merchant, amount, score, features, reasons, label, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.get('txn_id'),
            data.get('user_id'),
            data.get('merchant'),
            data.get('amount'),
            data.get('score'),
            json.dumps(data.get('features', {})),
            json.dumps(data.get('reasons', [])),
            data.get('label'),
            datetime.now().isoformat()
        ))
        conn.commit()
        print(f"Stored score for transaction {data.get('txn_id')}: {data.get('score')}")
    except Exception as e:
        print(f"Error storing score: {e}")
    finally:
        conn.close()

def main():
    # Connect to RabbitMQ
    connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
    channel = connection.channel()
    
    # Declare the queue
    channel.queue_declare(queue='fraud.scores', durable=True)
    
    print("Starting to consume fraud.scores queue...")
    
    # Consume messages
    for method_frame, properties, body in channel.consume('fraud.scores', auto_ack=True):
        try:
            data = json.loads(body)
            store_fraud_score(data)
        except Exception as e:
            print(f"Error processing message: {e}")
        
        # Check if we've processed all messages
        if method_frame.delivery_tag % 1000 == 0:
            print(f"Processed {method_frame.delivery_tag} messages...")
    
    connection.close()

if __name__ == "__main__":
    main() 