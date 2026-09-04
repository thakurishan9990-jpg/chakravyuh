# Generator calibration

This documents every parameter in `generator/generator.py` that was set (or
deliberately *not* set) from published NPCI/RBI figures, what the source
number was, how it was turned into a code constant, and where each constant
lives. Anything not listed here that looks like a "real" number (city
coordinates, VPA suffixes, etc.) is scaffolding, not a calibrated figure.

Search was done in September 2026; NPCI/RBI figures below are the latest
publicly reported numbers as of that date and will drift over time — re-check
before relying on this for anything beyond a synthetic training/demo dataset.

## Sourced figures

| # | Published figure | Source | Used for |
|---|---|---|---|
| 1 | UPI average ticket size ≈ ₹1,293 (down from ₹1,600+ in early 2023) | [10+ Freshly Updated UPI Statistics for 2026 — Meetanshi](https://meetanshi.com/blog/upi-statistics/) | Normal-transaction amount distribution |
| 2 | March 2026: 22.64B transactions worth ₹29.53 lakh crore | [UPI records 22.64 billion transactions in March 2026 — ANI](https://www.aninews.in/news/business/upi-records-2264-billion-transactions-in-march-2026-says-department-of-financial-services20260402142807/) | Cross-check for #1 (see below) |
| 3 | May 2026: 23.2B transactions/month; 737.79M transactions/day | [UPI Hits new high in May 2026 — ANI](https://www.aninews.in/news/business/upi-hits-new-high-in-may-2026-with-232-billion-transactions-worth-rs-299-trillion-npci-data-shows20260602155337/) | Per-user daily transaction rate |
| 4 | UPI user base: 55.49 crore (≈554.9M) as of June 2026 | [UPI user base reaches 55.49 crore — ANI](https://www.aninews.in/news/business/upi-user-base-reaches-5549-crore-fy26-transactions-rise-to-24162-crore-worth-rs-314-lakh-crore20260720191431/) | Per-user daily transaction rate |
| 5 | P2M vs P2P split: 63% merchant / 37% peer | [IDP — NPCI UPI P2P and P2M dataset](https://indiadataportal.com/p/national-payments-corporation-of-india-npci/r/npci-upi_p2p_p2m_transactions-in-mn-aaa) | Category-selection weights for normal transactions |
| 6 | ₹805 crore lost across 10.64 lakh UPI fraud incidents, first 8 months of FY26 (Finance Ministry, Lok Sabha) | [1 in 5 UPI users faced fraud — Business Standard](https://www.business-standard.com/finance/news/upi-transaction-fraud-india-survey-one-in-five-users-hit-localcircles-125062601141_1.html) | Scam-scheme deposit amount range |
| 7 | FY24–25: 185.8B UPI transactions (+41.7% YoY), 83.4% of digital payment volume | [RBI Annual Report 2024-25 Highlights — Medianama](https://www.medianama.com/2025/06/223-rbi-annual-report-2024-25-central-bank-agenda/) | Context for #8 (fraud rarity), not directly coded |
| 8 | RBI FY24-25: 13,516 digital (card/internet) fraud cases, ₹520 crore, 66.8% of fraud cases by count but a minority of value | [RBI Annual Report 2024-25 Highlights — Medianama](https://www.medianama.com/2025/06/223-rbi-annual-report-2024-25-central-bank-agenda/) | Context only — this bucket is bank-wide "card/internet" fraud, not UPI-specific, so it wasn't used for a direct calibration, only as a sanity check that #6 is the right order of magnitude |

## Derived constants and where they live

### 1. Normal transaction amount distribution
`generator/generator.py` — `NORMAL_AMOUNT_BANDS` / `NORMAL_AMOUNT_WEIGHTS`, used in `generate_normal_transaction()`

- Target: mean amount ≈ ₹1,300 (source #1, independently cross-checked against source #2: ₹29.53 lakh crore ÷ 22.64B txns = ₹1,304.6 — both land in the same ~₹1,290–1,305 band, so ₹1,300 is used as the calibration target).
- The three amount bands (₹20–500, ₹500–5,000, ₹5,000–20,000) were kept from the original generator; only the selection *weights* were changed. Solved `0.62×260 + 0.37×2,750 + 0.01×12,500 = 1,293` (band midpoints), giving weights `[0.62, 0.37, 0.01]` — i.e. UPI is overwhelmingly small-ticket, with a thin tail of larger P2P transfers.
- **Caveat:** NPCI doesn't publish the band-level breakdown (only the aggregate mean), so the *shape* (three flat uniform bands) and the specific weight split that hits ₹1,300 is a calibration choice, not a directly-sourced distribution. Only the target mean is sourced.

### 2. Transactions per day
`generator/generator.py` — `generate_dataset()` default `normal_txns_per_day=400`, against the hardcoded `UserPool(initial_size=300)`

- Source #3 ÷ source #4: 737.79M transactions/day ÷ 554.9M users ≈ **1.33 transactions/user/day** nationally.
- Applied to this generator's 300-seed user pool: `300 × 1.33 ≈ 400`.
- **Caveat:** this generator runs at a toy scale (hundreds of users, not hundreds of millions), so matching *absolute* national daily volume is meaningless — what's calibrated is the *per-user* daily rate, which is what actually shapes account-level features like `active_day_span` and `new_counterparties_per_day` that the detector consumes.

### 3. P2M/P2P category mix
`generator/generator.py` — `P2M_P2P_WEIGHTS`, used in `generate_normal_transaction()`

- Source #5: 63% merchant (P2M), 37% peer (P2P).
- The five P2M-like categories (`grocery`, `fuel`, `utilities`, `restaurant`, `retail`) split the 63% evenly (12.6% each); `p2p` gets 37%.
- **Caveat:** NPCI's category is a binary P2M/P2P flag, not a 6-way merchant category breakdown — splitting the 63% evenly across five merchant categories is a simplifying assumption, since no public per-category (grocery vs. fuel vs. retail, etc.) split exists.

### 4. Scam-scheme deposit amount
`generator/generator.py` — `ScamScheme.onboard_new_members()`, `deposit_amount = round(random.uniform(3000, 13000), 2)`

- Source #6: ₹805 crore ÷ 10.64 lakh incidents ≈ **₹7,566 average loss per UPI fraud incident**.
- In this generator, a victim's net loss is `deposit_amount × (1 − payout_ratio)`. With `payout_ratio` sampled from `uniform(0.05, 0.10)` (midpoint 0.075), solving `mean_deposit × (1 − 0.075) ≈ 7,566` gives `mean_deposit ≈ 8,180`. The range `uniform(3000, 13000)` (mean 8,000) was chosen to land close to that.
- **Caveat:** the ₹805cr/10.64L figure is *all* reported UPI fraud (phishing, SIM-swap, QR scams, etc.), not Ponzi/HYIP schemes specifically — no public breakdown by fraud *type* exists, so this is used as a general "typical loss size" anchor, not a Ponzi-specific figure.

## Explicitly NOT calibrated (documented assumptions, not sourced)

These were left as-is or already were assumptions — flagging them so nobody mistakes them for sourced figures later:

- **Fraud prevalence in the dataset (roughly a quarter of rows scam-labeled at default settings — checked empirically after this calibration, since lowering `normal_txns_per_day` from 800→400 raised the scam share from ~16% while scam-scheme volume was left untouched).** Real-world UPI fraud incidence is roughly source #6's 10.64L incidents against ~176B transactions over the same 8 months (source #7-scale volume) ≈ **1 fraudulent transaction per ~165,000**, i.e. ~0.0006%. This generator runs orders of magnitude above that by design — it's a labeled dataset meant for supervised precision/recall evaluation (this repo's `detector.py` / `README.md` metrics), and real-world rarity would make a 13k-row toy dataset contain effectively zero positives. Not changed; documented instead.
- **`payout_ratio = uniform(0.05, 0.10)`** — the "pays back 5–10% of deposit" mechanic. No public RBI/NPCI data on typical Ponzi/HYIP payout percentages was found; this is a literature-informed guess about how these schemes look plausible to victims, left unsourced.
- **Onboarding growth curve** (`2 + day × 1.5` new victims/day per scheme) — models exponential-ish recruitment growth; no source, kept as-is.
- **5% chance a normal user transacts in a high-risk category** — kept as-is; no source for how often ordinary users touch gaming/crypto/investment categories on UPI.
- **Trip behavior** (`trip_prob=0.03`, 2–6 day trips) and the scam operator's "scattered location" behavior — both modeling choices to produce plausible/implausible travel patterns for the detector's geo features, not sourced from any travel or fraud dataset.
- **City list and coordinates, VPA suffix list, `SUSPICIOUS_HANDLES` keyword list (mock_api)** — structural/demo data, not statistical parameters.

## Files touched by this calibration

- `generator/generator.py` — amount bands/weights, P2M/P2P weights, scam deposit range, `normal_txns_per_day` default
- `mock_api/app.py` — `/simulate` endpoint's `normal_txns_per_day` default (800 → 400, matching the generator default)
- `dashboard/app.py` — UI defaults for the "Txns/day" inputs and the two hardcoded `simulate(14, 800, 3)` regenerate calls (800 → 400)
