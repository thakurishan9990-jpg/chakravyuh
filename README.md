# Chakravyuh

**UPI Ponzi scheme detection for PSP integration.**

In the Mahabharata, a *chakravyuh* is a spiral battle formation — easy to
enter, nearly impossible to leave. A Ponzi scheme has the same shape: money
flows inward from many victims, a trickle flows back out, and the structure
holds until it collapses. This system detects that shape in UPI transaction
streams and flags it for human review.

## Quick start

```bash
chmod +x start.sh
./start.sh
```

Opens at http://localhost:8501

Manual equivalent:

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=. streamlit run dashboard/app.py
```

## Detection signals

Four independent signal families. Each is individually weak; together they
are strong.

**1. Payout ratio consistency** (strongest signal)

A Ponzi pays every victim the same rate, mechanically. Counting payouts that
land in the 4-12% band is not enough on its own - a busy normal account hits
that band by coincidence. We measure whether the matches cluster on a
*single* repeated ratio. `ratio_consistency` near 1.0 means one fixed rate is
being applied over and over.

**2. Timing regularity**

Human-run businesses pay at irregular times. Scheme payouts run on a
scheduler, giving near-zero variance between payout times.

**3. Geography and money velocity**

- `impossible_trips` - consecutive transactions needing over 900 km/h travel
- `distinct_cities` - operating from an implausible number of locations
- `median_hold_hours` - how long funds sit before moving on
- `passthrough_ratio` - money out over money in; near 1.0 means pass-through

**4. Merchant category risk**

Crypto, investment, forex and gaming carry elevated base risk. Normal users
transact in these categories too, so this is corroborating evidence only,
never a standalone trigger.

## How scoring works

```
rule_score = weighted sum of triggered rules   (explainable)
ml_score   = Isolation Forest anomaly score    (unsupervised)
risk_score = 0.6 * rule_score + 0.4 * ml_score
```

The ML layer refines *ranking* but cannot raise an alert on its own. An
account with no rule evidence is capped below the review threshold. Without
that gate, an unsupervised model flags its contamination rate on every run
and buries the review team in false positives. Every alert traces back to a
stated rule.

Tiers: below 0.4 safe, 0.4 to 0.7 review, 0.7 and above high risk.

## Measured performance

On 13,342 synthetic transactions across 723 accounts, with 3 scheme
operators in the ground truth:

| Tier | Precision | Recall | False positive rate |
|---|---|---|---|
| High risk (>= 0.7) | 100% | 100% | 0.0% |
| Review (>= 0.4) | 12.5% | 100% | 2.9% |

Review-tier precision is low because the base rate is low - 3 fraudulent
accounts out of 723. That is realistic and expected: a review queue is meant
to be over-inclusive, and 21 accounts is a workable manual queue. The
high-risk tier is what would trigger action, and it is clean.

Tuning history, worth mentioning in the pitch: the first version flagged 158
accounts at a 21.9% false positive rate. Two fixes brought that to 24 and
2.9% - requiring ratio *consistency* rather than any ratio match, and fixing
the generator so normal users travel and stay in a city rather than
teleporting between cities on every transaction, which was manufacturing
fake impossible-travel alerts.

## Project layout

```
mock_api/    FastAPI gateway and SQLite storage
generator/   Synthetic transactions with geo and category metadata
detection/   Feature engineering and the scoring engine
dashboard/   Single-page live monitoring console
data/        SQLite database, created automatically
```

## Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness check |
| `POST /simulate` | Generate and load a dataset |
| `GET /transactions` | All stored transactions |
| `POST /transaction` | Insert one transaction |
| `GET /verify/{vpa}` | Simulated VPA reputation lookup |
| `GET /cities`, `GET /categories` | Reference data |

## Limitations - state these in the pitch

**Data is synthetic.** No real UPI transaction data is publicly available.
The generator models documented Ponzi behaviour: fixed-rate payouts,
accelerating recruitment, scheduled timing. Ground truth is known because we
generated it, which is exactly what makes the precision and recall numbers
meaningful.

**`/verify` is not a real Paytm or PhonePe API.** No public "is this VPA a
scam" endpoint exists. Those APIs are for merchants to accept payments and
require full KYC onboarding. This endpoint demonstrates the integration
*shape* a PSP-side reputation service would take.

**UPI payloads carry no GPS.** Real PSPs derive approximate location from
device and IP data. The geo signals model that enrichment layer and would
require the PSP to supply it.

**This flags, it does not block.** Stopping a UPI payment requires NPCI and
bank-level integration. Position it as something a PSP could plug into an
existing fraud pipeline, with human review before any action is taken.
