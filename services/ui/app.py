import os, json, sqlite3, pandas as pd, streamlit as st

DB_PATH = os.environ.get("DB_PATH", "/data/fraud.db")
PAGE_SIZE = int(os.environ.get("PAGE_SIZE", "200"))
st.set_page_config(page_title="Fraud Alerts & Agent Recs", layout="wide")

@st.cache_data(ttl=5)
def load_df(sql, params=()):
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql_query(sql, conn, params=params)

st.title("🔎 Real-time Fraud Alerts (Agentic)")

col1, col2, col3 = st.columns(3)
total = load_df("SELECT COUNT(*) AS c FROM alerts")["c"].iloc[0] if os.path.exists(DB_PATH) else 0
avg = load_df("SELECT AVG(score) AS s FROM alerts")["s"].iloc[0] if os.path.exists(DB_PATH) else 0
col1.metric("Alerts (all time)", total)
col2.metric("Avg Score", f"{(avg or 0):.3f}")
col3.metric("Recent Alerts", len(load_df("SELECT txn_id FROM alerts ORDER BY ts DESC LIMIT 50")) if os.path.exists(DB_PATH) else 0)

with st.sidebar:
    st.header("Filters")
    ms = st.slider("Min score", 0.0, 1.0, 0.0, 0.01)
    uq = st.text_input("User contains","")
    mq = st.text_input("Merchant contains","")
    refresh = st.button("🔄 Refresh")

where, params = ["1=1"], []
if ms>0: where.append("score >= ?"); params.append(ms)
if uq.strip(): where.append("user_id LIKE ?"); params.append(f"%{uq}%")
if mq.strip(): where.append("merchant LIKE ?"); params.append(f"%{mq}%")
sql = f"""SELECT txn_id,ts,user_id,merchant,amount,score,reasons
FROM alerts WHERE {' AND '.join(where)} ORDER BY ts DESC LIMIT {PAGE_SIZE}"""
alerts = load_df(sql, tuple(params)) if os.path.exists(DB_PATH) else pd.DataFrame()

left, right = st.columns([2,1])
with left:
    st.subheader("Latest Alerts")
    st.dataframe(alerts, use_container_width=True, height=500)

with right:
    st.subheader("Alert detail")
    txn = st.selectbox("txn_id", alerts["txn_id"].tolist() if not alerts.empty else [])
    if txn:
        rec = load_df("SELECT recommendation FROM recommendations WHERE txn_id=?", (txn,))
        alert = load_df("SELECT * FROM alerts WHERE txn_id=?", (txn,))
        if not alert.empty:
            st.json({
                "txn_id": alert["txn_id"].iloc[0],
                "ts": alert["ts"].iloc[0],
                "user_id": alert["user_id"].iloc[0],
                "merchant": alert["merchant"].iloc[0],
                "amount": float(alert["amount"].iloc[0] or 0),
                "score": float(alert["score"].iloc[0] or 0),
                "reasons": json.loads(alert["reasons"].iloc[0] or "[]")
            })
        st.write("Agent recommendation:")
        if not rec.empty:
            try:
                st.json(json.loads(rec["recommendation"].iloc[0]))
            except Exception:
                st.code(rec["recommendation"].iloc[0])
        else:
            st.info("No recommendation yet.")

if refresh:
    st.cache_data.clear()
    st.experimental_rerun()
