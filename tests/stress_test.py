"""Stress test: does detection generalise, or was it tuned to one dataset?

Runs the full pipeline against scam variants designed to evade specific
signals - stealthy payout ratios, slow recruitment, jittered timing, and
operators who never leave one city. Prints a table showing which
configurations are still caught.

Run:  python3 tests/stress_test.py
"""

import os
import random
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pandas as pd  # noqa: E402

from generator.generator import (                       # noqa: E402
    UserPool, ScamScheme, generate_normal_transaction, CITIES, CITY_NAMES,
    jitter_coords)
from detection.features import build_txn_graph, build_feature_matrix  # noqa: E402
from detection.detector import score_accounts, evaluate  # noqa: E402


# --------------------------------------------------------------------------
# Scheme variants
# --------------------------------------------------------------------------

class StealthScheme(ScamScheme):
    """A Ponzi that actively tries to look normal.

    Three evasion levers, each aimed at one of our signals:
      payout_ratio      - a low rate looks more like cashback than a Ponzi
      recruits_per_day  - flat, slow growth instead of an accelerating curve
      timing_jitter_min - wide payout windows defeat the timing-regularity rule
      home_city         - staying put defeats the impossible-travel rule
    """

    def __init__(self, scheme_id, pool, payout_ratio, recruits_per_day,
                 timing_jitter_min, home_city=None, day_offset=0):
        super().__init__(scheme_id, pool, payout_ratio=payout_ratio,
                         day_offset=day_offset)
        self.recruits_per_day = recruits_per_day
        self.timing_jitter_min = timing_jitter_min
        self.home_city = home_city

    def _scattered_location(self):
        if self.home_city is None:
            return super()._scattered_location()
        lat, lon = CITIES[self.home_city]
        return (self.home_city, *jitter_coords(lat, lon))

    def onboard_new_members(self, day, base_time, count=None):
        return super().onboard_new_members(
            day, base_time, count=self.recruits_per_day)

    def daily_payouts(self, day, base_time):
        txs = super().daily_payouts(day, base_time)
        # Re-jitter payout timestamps to widen the schedule
        if self.timing_jitter_min > 5:
            for t in txs:
                ts = datetime.fromisoformat(t["timestamp"])
                extra = random.uniform(-self.timing_jitter_min,
                                       self.timing_jitter_min)
                t["timestamp"] = (ts + timedelta(minutes=extra)).isoformat()
        return txs


class LaunderedScheme(StealthScheme):
    """The hardest case: also hides its merchant-category footprint.

    Our generator tags every scheme transaction as crypto/investment/gaming,
    which hands the detector a signal no real operator would give away. A
    scheme that routes most traffic through ordinary categories removes that
    advantage, and is the fairest test of whether the remaining behavioural
    signals stand on their own.
    """

    NORMAL_CATS = ["p2p", "retail", "grocery", "utilities"]

    def _launder(self, txs):
        for t in txs:
            if random.random() < 0.85:
                t["category"] = random.choice(self.NORMAL_CATS)
        return txs

    def onboard_new_members(self, day, base_time, count=None):
        return self._launder(super().onboard_new_members(day, base_time, count))

    def daily_payouts(self, day, base_time):
        return self._launder(super().daily_payouts(day, base_time))


def generate_with_schemes(schemes, num_days=14, normal_txns_per_day=800,
                          pool=None, seed=42):
    random.seed(seed)
    pool = pool or UserPool(initial_size=300)
    base_time = datetime(2026, 8, 1)
    txns = []

    for day in range(num_days):
        day_time = base_time + timedelta(days=day)
        for _ in range(normal_txns_per_day):
            txns.append(generate_normal_transaction(pool, day_time, day=day))
        for s in schemes:
            if day >= s.day_offset:
                d = day - s.day_offset
                txns.extend(s.onboard_new_members(d, base_time))
                txns.extend(s.daily_payouts(d, base_time))

    txns.sort(key=lambda t: t["timestamp"])
    return txns


# --------------------------------------------------------------------------
# Configurations
# --------------------------------------------------------------------------

CONFIGS = [
    # name,                       ratio, recruits, jitter, single_city, rings, cls
    ("Baseline (5-10%, fast)",   None,  None,     5,          False,       3),
    ("Stealth 3% payout",        0.03,  None,     5,          False,       3),
    ("Stealth 2% payout",        0.02,  None,     5,          False,       3),
    ("Aggressive 15% payout",    0.15,  None,     5,          False,       3),
    ("Slow recruitment (2/day)", None,  2,        5,          False,       3),
    ("Slow recruit + 3% payout", 0.03,  2,        5,          False,       3),
    ("Jittered timing (±90min)", None,  None,     90,         False,       3),
    ("Single city (no geo)",     None,  None,     5,          True,        3),
    ("Full evasion stack",       0.03,  2,        90,         True,        3),
    ("Single ring only",         None,  None,     5,          False,       1),
    ("Six rings",                None,  None,     5,          False,       6),
    ("Evasion + cat. laundering", 0.03, 2,        90,         True,        3, "laundered"),
]


def build_schemes(cfg, pool):
    ratio, recruits, jitter, single_city, rings = cfg[1:6]
    cls = LaunderedScheme if (len(cfg) > 6 and cfg[6] == "laundered") else StealthScheme
    schemes = []
    for i in range(rings):
        city = CITY_NAMES[i % len(CITY_NAMES)] if single_city else None
        schemes.append(cls(
            scheme_id=f"S{i+1}",
            pool=pool,
            payout_ratio=ratio if ratio else random.uniform(0.05, 0.10),
            recruits_per_day=recruits,
            timing_jitter_min=jitter,
            home_city=city,
            day_offset=i,
        ))
    return schemes


def run_config(cfg):
    name = cfg[0]
    random.seed(42)
    pool = UserPool(initial_size=300)
    schemes = build_schemes(cfg, pool)

    txns = generate_with_schemes(schemes, pool=pool)
    df = pd.DataFrame(txns)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    for col in ("lat", "lon"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    G = build_txn_graph(df)
    fdf = build_feature_matrix(df, G)
    scored = score_accounts(fdf)

    operators = [s.scheme_account for s in schemes]
    present = [o for o in operators if o in scored.index]

    caught_high = sum(1 for o in present
                      if scored.at[o, "risk_score"] >= 0.7)
    caught_any = sum(1 for o in present
                     if scored.at[o, "risk_score"] >= 0.4)

    verdicts = {}
    if "verdict" in scored.columns:
        for o in present:
            v = scored.at[o, "verdict"]
            verdicts[v] = verdicts.get(v, 0) + 1

    m_high = evaluate(scored, threshold=0.7)
    m_review = evaluate(scored, threshold=0.4)

    mean_score = (sum(scored.at[o, "risk_score"] for o in present) / len(present)
                  if present else 0.0)

    return {
        "Config": name,
        "Ops": len(operators),
        "High risk": f"{caught_high}/{len(operators)}",
        "Flagged": f"{caught_any}/{len(operators)}",
        "Mean score": round(mean_score, 3),
        "YES": verdicts.get("YES", 0),
        "MAYBE": verdicts.get("MAYBE", 0),
        "NO": verdicts.get("NO", 0),
        "Precision@.7": f"{m_high.get('precision', 0):.0%}",
        "FPR@.4": f"{m_review.get('fpr', 0):.1%}",
    }


def main():
    print("Running stress test across scam variants...\n")
    rows = []
    for cfg in CONFIGS:
        print(f"  {cfg[0]:<28} ", end="", flush=True)
        try:
            r = run_config(cfg)
            rows.append(r)
            print(f"high-risk {r['High risk']}  flagged {r['Flagged']}")
        except Exception as e:
            print(f"FAILED: {type(e).__name__}: {e}")
            rows.append({"Config": cfg[0], "Ops": "-", "High risk": "ERROR",
                         "Flagged": "-", "Mean score": "-", "YES": "-",
                         "MAYBE": "-", "NO": "-", "Precision@.7": "-",
                         "FPR@.4": "-"})

    table = pd.DataFrame(rows)

    print("\n" + "=" * 108)
    print("STRESS TEST RESULTS")
    print("=" * 108)
    print(table.to_string(index=False))
    print("=" * 108)

    out = os.path.join(os.path.dirname(__file__), "stress_test_results.md")
    with open(out, "w") as f:
        f.write("# Stress test results\n\n")
        f.write("Detection run against scam variants designed to evade "
                "specific signals.\n\n")
        f.write(table.to_markdown(index=False))
        f.write("\n\n## How to read this\n\n")
        f.write("- **High risk** - operators scoring >= 0.7 (would trigger action)\n")
        f.write("- **Flagged** - operators scoring >= 0.4 (reaches the review queue)\n")
        f.write("- **Precision@.7** - of accounts at high risk, share truly fraudulent\n")
        f.write("- **FPR@.4** - share of clean accounts pulled into review\n")
    print(f"\nWritten to {out}")

    # Plain-language verdict
    full = next((r for r in rows if r["Config"] == "Evasion + cat. laundering"), None)
    if full and isinstance(full["High risk"], str) and "/" in full["High risk"]:
        caught, total = full["High risk"].split("/")
        if caught == total:
            print("\nFull evasion stack still caught at high risk.")
        elif int(caught) > 0:
            print(f"\nFull evasion stack: {caught}/{total} caught at high risk "
                  f"({full['Flagged']} reached review).")
        else:
            print(f"\nFull evasion stack evaded the high-risk tier "
                  f"({full['Flagged']} reached review). Worth stating openly.")


if __name__ == "__main__":
    main()
