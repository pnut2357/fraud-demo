import sqlite3, json

class SqliteStore:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.ensure()

    def ensure(self):
        cur = self.conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS alerts(
            txn_id TEXT PRIMARY KEY, ts TEXT, user_id TEXT, merchant TEXT,
            amount REAL, score REAL, reasons TEXT, threshold REAL
        )""")
        cur.execute("""CREATE TABLE IF NOT EXISTS recommendations(
            txn_id TEXT PRIMARY KEY, recommendation TEXT, created_at TEXT
        )""")
        self.conn.commit()

    def upsert_alert(self, a: dict):
        cur = self.conn.cursor()
        cur.execute("""INSERT OR REPLACE INTO alerts(txn_id, ts, user_id, merchant, amount, score, reasons, threshold)
                       VALUES(?,?,?,?,?,?,?,?)""", (
            a.get("txn_id"), a.get("ts"), a.get("user_id"), a.get("merchant"),
            float(a.get("amount",0.0)), float(a.get("score",0.0)),
            json.dumps(a.get("reasons",[])), float(a.get("threshold",0.0))
        ))
        self.conn.commit()

    def recent(self, user_id=None, merchant=None, limit=5):
        cur = self.conn.cursor()
        out = {"user_recent": [], "merchant_recent": []}
        if user_id:
            cur.execute("SELECT txn_id, score, reasons, ts FROM alerts WHERE user_id=? ORDER BY ts DESC LIMIT ?", (user_id, limit))
            out["user_recent"] = [{"txn_id":r[0],"score":r[1],"reasons":json.loads(r[2] or "[]"),"ts":r[3]} for r in cur.fetchall()]
        if merchant:
            cur.execute("SELECT txn_id, score, reasons, ts FROM alerts WHERE merchant=? ORDER BY ts DESC LIMIT ?", (merchant, limit))
            out["merchant_recent"] = [{"txn_id":r[0],"score":r[1],"reasons":json.loads(r[2] or "[]"),"ts":r[3]} for r in cur.fetchall()]
        return out

    def save_recommendation(self, txn_id: str, rec: dict):
        cur = self.conn.cursor()
        cur.execute("INSERT OR REPLACE INTO recommendations(txn_id, recommendation, created_at) VALUES(?,?,datetime('now'))",
                    (txn_id, json.dumps(rec)))
        self.conn.commit()
