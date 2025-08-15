import os, json, argparse
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.metrics import (
    roc_auc_score, average_precision_score,
    precision_recall_fscore_support, confusion_matrix
)
import joblib

ART_DIR = Path("artifacts")
CFG_POLICY = Path("config/decision_policy.json")

FEATURES = ["amount","log_amount","hour_mod_24","user_txn_prev10","merchant_txn_prev10","ip_country_mismatch"]

def load_model(art_dir: Path):
    pipe = joblib.load(art_dir / "model.pkl")
    with open(art_dir / "model_config.json") as f:
        cfg = json.load(f)
    feats = cfg.get("features", FEATURES)
    return pipe, feats

def featurize(jsonl_path: Path) -> pd.DataFrame:
    df = pd.read_json(jsonl_path, lines=True)

    # Base
    df["amount"] = df["amount"].astype(float)
    df["log_amount"] = np.log1p(df["amount"].clip(lower=0))

    # Time features
    if "ts_step" in df.columns:
        df["ts_step"] = df["ts_step"].fillna(0).astype(int)
    else:
        df["ts_step"] = 0
    df["hour_mod_24"] = (df["ts_step"] % 24).astype(float)

    # Velocity proxies (approximate runtime)
    df = df.sort_values(["user_id","ts_step","txn_id"], kind="mergesort").reset_index(drop=True)
    df["user_txn_prev10"] = df.groupby("user_id").cumcount().clip(upper=10).astype(float)
    df = df.sort_values(["merchant","ts_step","txn_id"], kind="mergesort").reset_index(drop=True)
    df["merchant_txn_prev10"] = df.groupby("merchant").cumcount().clip(upper=10).astype(float)

    # IP heuristic used by demo rules
    df["ip_country_mismatch"] = df["ip"].astype(str).str.startswith("10.").astype(float)

    # Label from PaySim conversion
    if "label_is_fraud" not in df.columns:
        raise SystemExit("JSONL lacks label_is_fraud. Recreate with scripts/prepare_paysim.py.")
    df["label"] = df["label_is_fraud"].astype(int)

    return df

def split_indices(df: pd.DataFrame, art_dir: Path):
    """Use saved holdout indices if available; else make a deterministic split."""
    idx_path = art_dir / "holdout_idx.json"
    if idx_path.exists():
        with open(idx_path) as f:
            saved = json.load(f)
        test_idx = set(saved.get("test_idx", []))
        mask_test = df.index.isin(test_idx)
        return (~mask_test), mask_test

    # Deterministic split by hashing txn_id (stable across runs)
    # ~80/20 split
    h = pd.util.hash_pandas_object(df["txn_id"].astype(str), index=False) % 10
    mask_test = (h >= 8)  # 0-7 train (80%), 8-9 test (20%)
    return (~mask_test), mask_test

def metrics_at_threshold(y_true, y_score, thr):
    y_pred = (y_score >= thr).astype(int)
    p, r, f1, _ = precision_recall_fscore_support(y_true, y_pred, average="binary", zero_division=0)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred).ravel()
    spec = tn / (tn + fp) if (tn + fp) else 0.0
    return {
        "threshold": float(thr),
        "precision": float(p),
        "recall": float(r),
        "f1": float(f1),
        "specificity": float(spec),
        "tp": int(tp), "fp": int(fp), "tn": int(tn), "fn": int(fn)
    }

def threshold_for_alert_rate(y_score, alert_rate):
    """Choose threshold so that ~alert_rate of samples are flagged."""
    if not (0 < alert_rate < 1):
        raise ValueError("--alert-rate must be in (0,1)")
    # Higher score => more suspicious; pick (1 - alert_rate) quantile
    return float(np.quantile(y_score, 1.0 - alert_rate))

def maybe_load_policy_thresholds():
    if not CFG_POLICY.exists():
        return None
    try:
        with open(CFG_POLICY) as f:
            pol = json.load(f)
        tau = float(pol.get("thresholds", {}).get("tau", 0.75))
        tau_high = float(pol.get("thresholds", {}).get("tau_high", 0.9))
        return {"tau": tau, "tau_high": tau_high}
    except Exception:
        return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", default="data/transactions_sample.jsonl")
    ap.add_argument("--artifacts", default="artifacts")
    ap.add_argument("--threshold", type=float, default=0.5, help="Fixed threshold for metrics (default 0.5)")
    ap.add_argument("--alert-rate", type=float, default=None, help="Optional fraction (e.g., 0.03 for top 3%)")
    args = ap.parse_args()

    pipe, feat_order = load_model(Path(args.artifacts))
    df = featurize(Path(args.jsonl))

    train_mask, test_mask = split_indices(df, Path(args.artifacts))
    X_test = df.loc[test_mask, feat_order].astype(float).values
    y_test = df.loc[test_mask, "label"].values

    # Scores
    y_score = pipe.predict_proba(X_test)[:, 1]

    # Global metrics
    roc = roc_auc_score(y_test, y_score)
    prc = average_precision_score(y_test, y_score)

    report = {"n_test": int(test_mask.sum()), "positive_rate_test": float(y_test.mean()),
              "roc_auc": float(roc), "pr_auc": float(prc), "by_threshold": {}}

    # Fixed threshold
    report["by_threshold"][f"fixed@{args.threshold:.3f}"] = metrics_at_threshold(y_test, y_score, args.threshold)

    # Policy thresholds (if config present)
    pol = maybe_load_policy_thresholds()
    if pol:
        report["by_threshold"][f"policy@tau({pol['tau']:.2f})"] = metrics_at_threshold(y_test, y_score, pol["tau"])
        report["by_threshold"][f"policy@tau_high({pol['tau_high']:.2f})"] = metrics_at_threshold(y_test, y_score, pol["tau_high"])

    # Alert rate target
    if args.alert_rate is not None:
        thr = threshold_for_alert_rate(y_score, args.alert_rate)
        report["by_threshold"][f"alert_rate@{args.alert_rate:.3f}"] = metrics_at_threshold(y_test, y_score, thr)
        report["by_threshold"][f"alert_rate@{args.alert_rate:.3f}"]["chosen_threshold"] = thr

    # Also compute an F1-maximizing threshold (sweep 100 points)
    grid = np.linspace(0.0, 1.0, 101)
    f1s = [metrics_at_threshold(y_test, y_score, t)["f1"] for t in grid]
    t_star = float(grid[int(np.argmax(f1s))])
    report["by_threshold"]["f1_max"] = metrics_at_threshold(y_test, y_score, t_star)

    # Pretty print
    def fmt(m):
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.items()}

    print("=== Evaluation Summary ===")
    print(f"Test size: {report['n_test']}  |  Pos rate: {report['positive_rate_test']:.4f}")
    print(f"ROC-AUC: {report['roc_auc']:.4f}  |  PR-AUC: {report['pr_auc']:.4f}\n")
    for name, met in report["by_threshold"].items():
        m = fmt(met)
        print(f"[{name}]")
        print(f"  precision={m['precision']}, recall={m['recall']}, f1={m['f1']}, specificity={m['specificity']}")
        print(f"  tp={m['tp']} fp={m['fp']} tn={m['tn']} fn={m['fn']}")
        if "chosen_threshold" in m:
            print(f"  chosen_threshold={m['chosen_threshold']}")
        print()

    # Save a machine-readable copy
    out_path = ART_DIR / "eval_report.json"
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Wrote {out_path}")

if __name__ == "__main__":
    main()