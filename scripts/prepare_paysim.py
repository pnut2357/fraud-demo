#!/usr/bin/env python3
"""
Convert PaySim.csv into event-stream JSONL following events_schema.json (transactions.raw).
- Stable IDs derived from nameOrig for card_id/device_id
- ts derived from PaySim "step" (hour index) with base date 2025-08-01
- Adds ts_step for online features (worker uses it if present)
- Includes label columns (isFraud/isFlaggedFraud) as extras (ignored by runtime, useful for analysis)
"""
import argparse, os, json, uuid, hashlib, random, pandas as pd
from datetime import datetime, timedelta

def stable_suffix(s: str, n: int = 6) -> str:
    return hashlib.sha1(str(s).encode()).hexdigest()[-n:]

def synth_device(user_id: str) -> str:
    return f"dev_{stable_suffix(user_id, 8)}"

def synth_card(user_id: str) -> str:
    return f"card_{stable_suffix(user_id, 10)}"

def synth_ip(prob_private_10: float = 0.15) -> str:
    # ~15% 10.x.x.x -> triggers ip_country_mismatch=1 in rules demo
    if random.random() < prob_private_10:
        from random import randint
        return f"10.{randint(0,255)}.{randint(0,255)}.{randint(1,254)}"
    else:
        from random import randint
        return f"192.168.{randint(0,255)}.{randint(1,254)}"

def step_to_ts(step: int) -> str:
    base_dt = datetime(2025, 8, 1, 0, 0, 0)
    ts = base_dt + timedelta(hours=int(step))
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")

def convert(csv_path: str, out_jsonl: str, max_rows: int = 20000, seed: int = 7, chunksize: int = 100_000):
    random.seed(seed)
    written = 0
    with open(out_jsonl, "w") as w:
        for chunk in pd.read_csv(csv_path, chunksize=chunksize):
            for _, r in chunk.iterrows():
                try:
                    event = {
                        "txn_id": str(uuid.uuid4()),
                        "user_id": str(r.get("nameOrig")),
                        "card_id": synth_card(r.get("nameOrig")),
                        "amount": float(r.get("amount", 0.0)),
                        "merchant": str(r.get("nameDest")),   # dest treated as merchant/beneficiary
                        "device_id": synth_device(r.get("nameOrig")),
                        "ip": synth_ip(),
                        "ts_step": int(r.get("step", 0)),
                        "ts": step_to_ts(int(r.get("step", 0))),
                        # extra columns for analysis (ignored by runtime)
                        "txn_type": str(r.get("type")),
                        "label_is_fraud": int(r.get("isFraud", 0)),
                        "label_is_flagged": int(r.get("isFlaggedFraud", 0))
                    }
                except Exception:
                    continue
                w.write(json.dumps(event) + "\n")
                written += 1
                if written >= max_rows:
                    return written
    return written

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/raw/PaySim.csv")
    ap.add_argument("--out", default="data/transactions_sample.jsonl")
    ap.add_argument("--max-rows", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--chunksize", type=int, default=100000)
    args = ap.parse_args()
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    n = convert(args.csv, args.out, max_rows=args.max_rows, seed=args.seed, chunksize=args.chunksize)
    print(f"Wrote {n} events → {args.out}")

if __name__ == "__main__":
    main()
