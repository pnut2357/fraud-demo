import os, json, joblib, numpy as np, pandas as pd
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, average_precision_score
from sklearn.model_selection import train_test_split

IN_JSONL = "data/transactions_sample.jsonl"
ART_DIR  = "artifacts"
FEATURES = ["amount","log_amount","hour_mod_24","user_txn_prev10","merchant_txn_prev10","ip_country_mismatch"]

def load_and_featurize(path: str) -> pd.DataFrame:
    df = pd.read_json(path, lines=True)
    # Basic online-like features (align with services/stream_worker/fraud_stream_worker/features.py)
    df["amount"] = df["amount"].astype(float)
    df["log_amount"] = np.log1p(df["amount"].clip(lower=0))
    # ts_step added by prepare_paysim.py; fall back to 0 if missing
    df["ts_step"] = df.get("ts_step", 0).fillna(0).astype(int)
    df["hour_mod_24"] = (df["ts_step"] % 24).astype(float)
    # velocity proxies (approximate the worker’s “previous count capped at 10”)
    df = df.sort_values(["user_id","ts_step","txn_id"]).reset_index(drop=True)
    df["user_txn_prev10"] = df.groupby("user_id").cumcount().clip(upper=10).astype(float)
    df = df.sort_values(["merchant","ts_step","txn_id"]).reset_index(drop=True)
    df["merchant_txn_prev10"] = df.groupby("merchant").cumcount().clip(upper=10).astype(float)
    # ip heuristic
    df["ip_country_mismatch"] = df["ip"].astype(str).str.startswith("10.").astype(float)
    # label (from PaySim)
    y = df.get("label_is_fraud")
    if y is None:
        raise RuntimeError("transactions_sample.jsonl lacks label_is_fraud; regenerate with scripts/prepare_paysim.py")
    df["label"] = y.astype(int)
    return df

def main():
    os.makedirs(ART_DIR, exist_ok=True)
    df = load_and_featurize(IN_JSONL)
    X = df[FEATURES].astype(float).values
    y = df["label"].values

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(max_iter=500, class_weight="balanced"))
    ])
    pipe.fit(X_train, y_train)

    # quick metrics
    proba = pipe.predict_proba(X_test)[:,1]
    auc = roc_auc_score(y_test, proba)
    ap  = average_precision_score(y_test, proba)
    print(f"AUC={auc:.3f}  AP={ap:.3f}  (class balance: {y.mean():.4f})")

    joblib.dump(pipe, os.path.join(ART_DIR, "model.pkl"))
    with open(os.path.join(ART_DIR, "model_config.json"), "w") as f:
        json.dump({"features": FEATURES}, f, indent=2)
    print("Wrote artifacts/model.pkl and artifacts/model_config.json")

if __name__ == "__main__":
    main()