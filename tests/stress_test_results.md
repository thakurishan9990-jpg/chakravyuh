# Stress test results

Detection run against scam variants designed to evade specific signals.

| Config                    |   Ops | High risk   | Flagged   |   Mean score |   YES |   MAYBE |   NO | Precision@.7   | FPR@.4   |
|:--------------------------|------:|:------------|:----------|-------------:|------:|--------:|-----:|:---------------|:---------|
| Baseline (5-10%, fast)    |     3 | 3/3         | 3/3       |        0.916 |     3 |       0 |    0 | 100%           | 1.5%     |
| Stealth 3% payout         |     3 | 3/3         | 3/3       |        0.917 |     3 |       0 |    0 | 100%           | 1.5%     |
| Stealth 2% payout         |     3 | 3/3         | 3/3       |        0.923 |     3 |       0 |    0 | 100%           | 1.2%     |
| Aggressive 15% payout     |     3 | 3/3         | 3/3       |        0.916 |     3 |       0 |    0 | 100%           | 2.4%     |
| Slow recruitment (2/day)  |     3 | 3/3         | 3/3       |        0.904 |     3 |       0 |    0 | 100%           | 2.7%     |
| Slow recruit + 3% payout  |     3 | 3/3         | 3/3       |        0.9   |     3 |       0 |    0 | 100%           | 3.2%     |
| Jittered timing (±90min)  |     3 | 3/3         | 3/3       |        0.917 |     3 |       0 |    0 | 100%           | 1.1%     |
| Single city (no geo)      |     3 | 3/3         | 3/3       |        0.885 |     3 |       0 |    0 | 100%           | 2.4%     |
| Full evasion stack        |     3 | 2/3         | 3/3       |        0.707 |     2 |       1 |    0 | 100%           | 5.8%     |
| Single ring only          |     1 | 1/1         | 1/1       |        0.91  |     1 |       0 |    0 | 100%           | 4.8%     |
| Six rings                 |     6 | 6/6         | 6/6       |        0.956 |     6 |       0 |    0 | 100%           | 1.2%     |
| Evasion + cat. laundering |     3 | 0/3         | 3/3       |        0.605 |     0 |       3 |    0 | 0%             | 6.4%     |

## How to read this

- **High risk** - operators scoring >= 0.7 (would trigger action)
- **Flagged** - operators scoring >= 0.4 (reaches the review queue)
- **Precision@.7** - of accounts at high risk, share truly fraudulent
- **FPR@.4** - share of clean accounts pulled into review
