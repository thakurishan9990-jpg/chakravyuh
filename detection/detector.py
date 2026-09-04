import pandas as pd
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler


# Each rule: (column, comparison, threshold, weight, human-readable reason)
RULES = [
    ("ratio_consistency",        ">=", 0.55, 0.30, "Same fixed payout rate applied repeatedly - mechanical, not organic"),
    ("payout_ratio_match_count", ">=", 20,   0.15, "High volume of fixed-percentage payouts"),
    ("payout_timing_std",        "<",  100,  0.15, "Bot-like payout timing (near-zero variance)"),
    ("new_counterparties_per_day", ">", 2,   0.15, "Rapid new-counterparty recruitment"),
    ("impossible_trips",         ">=", 3,    0.20, "Repeated physically impossible location jumps"),
    ("distinct_cities",          ">",  6,    0.10, "Operating from an implausible number of cities"),
    ("high_risk_txn_share",      ">",  0.5,  0.15, "Majority of activity in crypto/investment/gaming"),
    ("median_hold_hours",        "<",  6,    0.10, "Funds move out within hours of arriving"),
    ("same_day_turnover",        ">",  0.8,  0.10, "Money in and out on the same day, almost every day"),
]

# Rules needing a range check rather than a single threshold
RANGE_RULES = [
    ("passthrough_ratio", 0.85, 1.15, 0.10,
     "Pass-through account: nearly everything received is sent straight back out"),
]


def apply_rules(fdf):
    """Rule layer. Returns per-account score plus the list of triggered reasons."""
    scores = pd.Series(0.0, index=fdf.index)
    reasons = {a: [] for a in fdf.index}

    for col, op, thresh, weight, reason in RULES:
        if col not in fdf.columns:
            continue
        if op == ">=":
            hit = fdf[col] >= thresh
        elif op == ">":
            hit = fdf[col] > thresh
        else:
            hit = fdf[col] < thresh

        # timing_std of exactly 0 means the account has <2 payouts, not a bot
        if col == "payout_timing_std":
            hit = hit & (fdf["payout_ratio_match_count"] > 5)

        # median_hold_hours defaults to 999 for accounts with no in+out flow,
        # so a low value only means something if the account actually cycles money
        if col == "median_hold_hours" and "passthrough_ratio" in fdf.columns:
            hit = hit & (fdf["passthrough_ratio"] > 0)

        scores += hit.astype(float) * weight
        for acct in fdf.index[hit]:
            reasons[acct].append(reason)

    for col, lo, hi, weight, reason in RANGE_RULES:
        if col not in fdf.columns:
            continue
        hit = (fdf[col] >= lo) & (fdf[col] <= hi)
        scores += hit.astype(float) * weight
        for acct in fdf.index[hit]:
            reasons[acct].append(reason)

    return scores.clip(0, 1), reasons


def apply_ml(fdf, contamination=0.15, random_state=42):
    """Isolation Forest anomaly layer. Returns a 0-1 score per account."""
    X = fdf.drop(columns=["is_scam"], errors="ignore")
    X = X.replace([np.inf, -np.inf], 0).fillna(0)

    X_scaled = StandardScaler().fit_transform(X)
    iso = IsolationForest(contamination=contamination, random_state=random_state)
    iso.fit(X_scaled)

    # decision_function: lower = more anomalous. Normalise to 0-1 where 1 = most anomalous.
    raw = iso.decision_function(X_scaled)
    lo, hi = raw.min(), raw.max()
    normalised = 1 - ((raw - lo) / (hi - lo)) if hi > lo else np.zeros_like(raw)

    return pd.Series(normalised, index=fdf.index)


def tier_for(score):
    if score >= 0.7:
        return "High risk"
    if score >= 0.4:
        return "Review"
    return "Safe"


def verdict_for(risk, rule_score, ml_score, n_reasons):
    """One-word answer: YES, MAYBE, or NO.

    A binary call is dishonest when the evidence is genuinely split, so the
    middle band is an explicit "look at this" rather than a forced guess.

    Bands are calibrated against the observed score distribution: the median
    account scores about 0.17 and the 95th percentile about 0.37, so 0.30 is
    roughly where an account stops looking ordinary. A low score means NO even
    if a rule fired, because the score already accounts for how weak that
    rule's weight was - a single low-weight rule is not evidence of fraud.

      YES   - high score AND at least three independent signals agree
      MAYBE - in the ambiguous middle, or the two layers contradict each other
      NO    - nothing meaningful pointing at this account
    """
    disagreement = abs(rule_score - ml_score)

    if risk >= 0.7 and n_reasons >= 3:
        return "YES"

    # Layers strongly contradicting each other is itself a reason for a human
    # to look, even when the blended score lands low.
    if disagreement > 0.45:
        return "MAYBE"

    if risk < 0.30:
        return "NO"

    if risk >= 0.7:
        # High score but thin corroboration - not confident enough for YES
        return "MAYBE"

    return "MAYBE"


def confidence_for(risk, rule_score, ml_score, n_reasons):
    """0-1 confidence in the verdict, independent of which verdict it is.

    High when the layers agree and evidence is thick or clearly absent; low
    near the decision boundary.
    """
    boundary_conf = min(abs(risk - 0.5) * 2, 1.0)
    agreement = 1.0 - min(abs(rule_score - ml_score), 1.0)

    if n_reasons == 0:
        corroboration = 0.8 if risk < 0.30 else 0.3
    else:
        corroboration = min(n_reasons / 4.0, 1.0)

    return round(0.5 * boundary_conf + 0.25 * agreement + 0.25 * corroboration, 3)


def score_accounts(fdf, rule_weight=0.6, ml_weight=0.4):
    """Full detection pipeline: rules + ML -> combined risk score and tier."""
    rule_scores, reasons = apply_rules(fdf)
    ml_scores = apply_ml(fdf)

    out = fdf.copy()
    out["rule_score"] = rule_scores
    out["ml_score"] = ml_scores

    blended = (rule_weight * rule_scores + ml_weight * ml_scores).clip(0, 1)

    # The ML layer refines ranking; it does not raise alerts on its own.
    # An account with no rule evidence is capped below the Review threshold,
    # so it appears on the watchlist for analysts but never auto-escalates.
    # This is how production fraud systems keep alert volume controllable:
    # an unsupervised model flagging its contamination rate every run would
    # bury a review team in false positives.
    no_rule_evidence = rule_scores <= 0
    blended[no_rule_evidence] = (ml_scores[no_rule_evidence] * 0.35).clip(0, 0.39)

    out["risk_score"] = blended
    out["risk_tier"] = out["risk_score"].apply(tier_for)
    out["n_reasons"] = [len(reasons[a]) for a in out.index]

    out["verdict"] = [
        verdict_for(out.at[a, "risk_score"], rule_scores[a], ml_scores[a],
                    out.at[a, "n_reasons"])
        for a in out.index
    ]
    out["confidence"] = [
        confidence_for(out.at[a, "risk_score"], rule_scores[a], ml_scores[a],
                       out.at[a, "n_reasons"])
        for a in out.index
    ]
    out["reasons"] = [reasons[a] for a in out.index]

    return out.sort_values("risk_score", ascending=False)


def evaluate(scored, threshold=0.4):
    """Precision / recall / FPR against the synthetic ground truth."""
    if "is_scam" not in scored.columns:
        return {}

    y_true = scored["is_scam"].astype(int)
    y_pred = (scored["risk_score"] >= threshold).astype(int)

    tp = int(((y_pred == 1) & (y_true == 1)).sum())
    fp = int(((y_pred == 1) & (y_true == 0)).sum())
    fn = int(((y_pred == 0) & (y_true == 1)).sum())
    tn = int(((y_pred == 0) & (y_true == 0)).sum())

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    return {
        "precision": precision, "recall": recall, "fpr": fpr, "f1": f1,
        "true_positives": tp, "false_positives": fp,
        "false_negatives": fn, "true_negatives": tn,
        "total_accounts": len(scored),
        "flagged": int((y_pred == 1).sum()),
    }


def run_detection(client):
    """Convenience wrapper: load -> features -> score -> evaluate."""
    from features import load_transactions, build_txn_graph, build_feature_matrix

    df = load_transactions(client)
    if len(df) == 0:
        return None, None, None

    G = build_txn_graph(df)
    fdf = build_feature_matrix(df, G)
    scored = score_accounts(fdf)
    metrics = evaluate(scored)
    return df, scored, metrics


if __name__ == "__main__":
    import sys, os
    sys.path.append(os.path.join(os.path.dirname(__file__), "..", "mock_api"))
    sys.path.append(os.path.dirname(__file__))

    from fastapi.testclient import TestClient
    from app import app

    client = TestClient(app)
    df, scored, metrics = run_detection(client)

    if df is None:
        print("No transactions in the database. Run POST /simulate first.")
        sys.exit(1)

    print(f"\nAnalysed {len(df)} transactions across {metrics['total_accounts']} accounts")
    print(f"Flagged: {metrics['flagged']}\n")

    for name, th in [("Review tier (>= 0.4)", 0.4), ("High-risk tier (>= 0.7)", 0.7)]:
        m = evaluate(scored, threshold=th)
        print(f"{name}  flagged={m['flagged']}")
        print(f"  Precision : {m['precision']:.1%}")
        print(f"  Recall    : {m['recall']:.1%}")
        print(f"  FPR       : {m['fpr']:.1%}")
        print(f"  F1        : {m['f1']:.1%}\n")

    print("\nTop 10 by risk score")
    cols = ["risk_score", "risk_tier", "payout_ratio_match_count",
            "impossible_trips", "high_risk_txn_share", "is_scam"]
    print(scored[cols].head(10).to_string())

    print("\nWhy the top account was flagged:")
    top = scored.index[0]
    for r in scored.loc[top, "reasons"]:
        print(f"  - {r}")
