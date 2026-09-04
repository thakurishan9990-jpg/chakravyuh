import pandas as pd
import numpy as np
import networkx as nx
import math
from collections import defaultdict


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


# Merchant category risk weights. Real PSPs derive this from MCC codes.
CATEGORY_RISK = {
    "grocery": 0.0, "fuel": 0.0, "utilities": 0.0, "restaurant": 0.0,
    "retail": 0.0, "p2p": 0.0,
    "gaming": 0.6, "crypto": 0.9, "investment": 0.8, "forex": 0.7,
}


def load_transactions(client):
    """Load all transactions from the mock gateway into a DataFrame."""
    txns = client.get("/transactions").json()
    df = pd.DataFrame(txns)
    if len(df) == 0:
        return df
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    for col, default in [("category", "p2p"), ("city", None),
                         ("lat", np.nan), ("lon", np.nan)]:
        if col not in df.columns:
            df[col] = default
    return df


def payout_ratio_features(df, low=0.04, high=0.12):
    """Core Ponzi signal.

    Counting "paid out 4-12% of something" alone is far too loose - with
    random amounts a busy normal account hits that band by coincidence.
    What actually identifies a Ponzi is that the SAME ratio repeats: every
    victim gets 7%, day after day.

    Returns per account:
      match_count      - payouts landing in the band at all
      ratio_consistency - share of those matches sitting on the single most
                          common ratio (rounded to 0.5%). Near 1.0 means one
                          fixed rate is being applied mechanically.
      dominant_ratio    - that most common ratio
    """
    deposits = df[df.type == "deposit"]
    payouts = df[df.type == "payout"]

    # For a scheme operator, deposits arrive TO them and payouts go FROM them.
    dep_by_receiver = deposits.groupby("receiver").amount.agg(list).to_dict()

    out = {}
    for acct, grp in payouts.groupby("sender"):
        prior_deps = dep_by_receiver.get(acct, [])
        if not prior_deps:
            continue

        matched_ratios = []
        for amt in grp.amount.values:
            for dep in prior_deps:
                if dep <= 0:
                    continue
                r = amt / dep
                if low <= r <= high:
                    matched_ratios.append(round(r * 200) / 200)  # 0.5% buckets
                    break

        if not matched_ratios:
            continue

        counts = defaultdict(int)
        for r in matched_ratios:
            counts[r] += 1
        dominant_ratio, dominant_count = max(counts.items(), key=lambda kv: kv[1])
        consistency = dominant_count / len(matched_ratios)

        out[acct] = (len(matched_ratios), consistency, dominant_ratio)

    return out


def payout_timing_std(df):
    """Std dev (seconds) of an account's payout times. Low = bot-like."""
    payouts = df[df.type == "payout"].copy()
    if len(payouts) == 0:
        return {}
    payouts["ts"] = payouts.timestamp.astype("int64") // 10**9
    return payouts.groupby("sender").ts.std().fillna(0).to_dict()


def active_day_span(df):
    first = df.groupby("sender").timestamp.min()
    last = df.groupby("sender").timestamp.max()
    return {a: (last[a] - first[a]).days for a in first.index}


def new_counterparties_per_day(df):
    """Rate of new transaction partners - pyramid recruitment signal."""
    growth = {}
    for acct, grp in df.groupby("sender"):
        span_days = max((grp.timestamp.max() - grp.timestamp.min()).days, 1)
        growth[acct] = grp.receiver.nunique() / span_days
    return growth


def geo_velocity_features(df):
    """Distance-based signals.

    max_jump_km       - largest distance between two consecutive transactions
    max_velocity_kmph - implied travel speed for that jump
    impossible_trips  - count of jumps needing > 900 km/h (faster than a
                        commercial flight, so physically implausible)
    distinct_cities   - how many different cities this account transacted from

    Note: real UPI payloads do not include GPS. PSPs derive approximate
    location from device/IP. This models that field.
    """
    out = {}
    df_geo = df.dropna(subset=["lat", "lon"]).sort_values("timestamp")

    for acct, grp in df_geo.groupby("sender"):
        if len(grp) < 2:
            out[acct] = (0.0, 0.0, 0, grp.city.nunique() if "city" in grp else 1)
            continue

        lats = grp.lat.values
        lons = grp.lon.values
        times = grp.timestamp.values

        max_jump = 0.0
        max_vel = 0.0
        impossible = 0

        for i in range(1, len(grp)):
            d = haversine_km(lats[i-1], lons[i-1], lats[i], lons[i])
            hours = (times[i] - times[i-1]) / np.timedelta64(1, "h")
            hours = max(float(hours), 1/60)  # floor at 1 minute
            vel = d / hours

            max_jump = max(max_jump, d)
            max_vel = max(max_vel, vel)
            if vel > 900:
                impossible += 1

        out[acct] = (max_jump, max_vel, impossible, grp.city.nunique())

    return out


def category_risk_features(df):
    """Exposure to high-risk merchant categories (crypto, investment, gaming)."""
    out = {}
    for acct, grp in df.groupby("sender"):
        risks = grp.category.map(lambda c: CATEGORY_RISK.get(c, 0.0))
        high_risk_txns = (risks > 0.5).sum()
        out[acct] = (
            float(risks.mean()),
            float(risks.max()),
            int(high_risk_txns),
            float(high_risk_txns / len(grp)) if len(grp) else 0.0,
        )
    return out


def money_velocity_features(df):
    """How fast money passes through an account.

    A real merchant accumulates funds and withdraws on its own schedule. A
    Ponzi operator or mule pays money straight back out, often within hours,
    and the amount out closely tracks the amount in.

    median_hold_hours - typical gap between receiving and next sending
    passthrough_ratio - total sent / total received (near 1.0 = pass-through)
    same_day_turnover - share of days where money came in AND went out
    """
    out = {}
    accts = set(df.sender.unique()) | set(df.receiver.unique())

    for acct in accts:
        inflow = df[df.receiver == acct].sort_values("timestamp")
        outflow = df[df.sender == acct].sort_values("timestamp")

        if len(inflow) == 0 or len(outflow) == 0:
            out[acct] = (999.0, 0.0, 0.0)
            continue

        # For each outgoing payment, how long since the most recent inflow?
        in_times = inflow.timestamp.values
        holds = []
        for t_out in outflow.timestamp.values:
            prior = in_times[in_times <= t_out]
            if len(prior):
                gap_h = (t_out - prior[-1]) / np.timedelta64(1, "h")
                holds.append(max(float(gap_h), 0.0))

        median_hold = float(np.median(holds)) if holds else 999.0

        total_in = float(inflow.amount.sum())
        total_out = float(outflow.amount.sum())
        passthrough = total_out / total_in if total_in > 0 else 0.0

        in_days = set(inflow.timestamp.dt.date)
        out_days = set(outflow.timestamp.dt.date)
        both = in_days & out_days
        turnover = len(both) / len(in_days | out_days) if (in_days | out_days) else 0.0

        out[acct] = (median_hold, passthrough, turnover)

    return out


def build_txn_graph(df):
    G = nx.DiGraph()
    for _, row in df.iterrows():
        if G.has_edge(row.sender, row.receiver):
            G[row.sender][row.receiver]["weight"] += row.amount
        else:
            G.add_edge(row.sender, row.receiver, weight=row.amount)
    return G


def calc_fan_in_out_ratio(G):
    return {n: G.in_degree(n) / (G.out_degree(n) + 1) for n in G.nodes}


def build_feature_matrix(df, G):
    """One row per account, with every fraud signal as a numeric column."""
    all_accts = sorted(set(df.sender.unique()) | set(df.receiver.unique()))

    ratio_feats = payout_ratio_features(df)
    geo = geo_velocity_features(df)
    cat = category_risk_features(df)
    vel = money_velocity_features(df)
    fan = calc_fan_in_out_ratio(G)
    span = active_day_span(df)

    def col(d, idx=None, default=0.0):
        if idx is None:
            return [float(d.get(a, default)) for a in all_accts]
        return [float(d.get(a, (default,)*4)[idx]) for a in all_accts]

    fdf = pd.DataFrame({
        "acct": all_accts,
        "payout_ratio_match_count": [float(ratio_feats.get(a, (0, 0, 0))[0]) for a in all_accts],
        "ratio_consistency": [float(ratio_feats.get(a, (0, 0, 0))[1]) for a in all_accts],
        "dominant_payout_ratio": [float(ratio_feats.get(a, (0, 0, 0))[2]) for a in all_accts],
        "payout_timing_std": col(payout_timing_std(df)),
        "new_counterparties_per_day": col(new_counterparties_per_day(df)),
        "fan_in_out_ratio": col(fan),
        "active_day_span": col(span),
        "max_jump_km": col(geo, 0),
        "max_velocity_kmph": col(geo, 1),
        "impossible_trips": col(geo, 2),
        "distinct_cities": col(geo, 3),
        "avg_category_risk": col(cat, 0),
        "max_category_risk": col(cat, 1),
        "high_risk_txn_count": col(cat, 2),
        "high_risk_txn_share": col(cat, 3),
        "median_hold_hours": [float(vel.get(a, (999.0, 0.0, 0.0))[0]) for a in all_accts],
        "passthrough_ratio": [float(vel.get(a, (999.0, 0.0, 0.0))[1]) for a in all_accts],
        "same_day_turnover": [float(vel.get(a, (999.0, 0.0, 0.0))[2]) for a in all_accts],
    }).set_index("acct")

    # Ground truth: only the SCHEME OPERATOR is fraudulent, not its victims.
    # In a scheme transaction the operator receives the deposit and sends the
    # payout; everyone else on those rows is a victim.
    #
    # scheme_id must be treated carefully. Depending on how a row was written
    # it can arrive as SQL NULL, the *string* "None", "nan", or an empty
    # string. Only NULL is caught by .notna(), so without this guard every
    # ordinary transaction looks like part of a scheme and the ground-truth
    # set explodes from a handful of operators to hundreds of accounts.
    NULL_SENTINELS = {"", "none", "nan", "null", "na", "<na>"}

    if "scheme_id" in df.columns:
        sid = df["scheme_id"]
        is_real_scheme = sid.notna() & ~sid.astype(str).str.strip().str.lower().isin(NULL_SENTINELS)
        scheme_rows = df[is_real_scheme]
    else:
        scheme_rows = df.iloc[0:0]
    operators = set()
    if len(scheme_rows):
        operators |= set(scheme_rows[scheme_rows.type == "deposit"].receiver.unique())
        operators |= set(scheme_rows[scheme_rows.type == "payout"].sender.unique())

    fdf["is_scam"] = [1 if a in operators else 0 for a in all_accts]

    return fdf
