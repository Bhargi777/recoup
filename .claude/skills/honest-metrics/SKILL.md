---
name: honest-metrics
description: Guidelines for rigorous, statistically sound, and un-cherry-picked evaluation of revenue recovery and ML models.
---

# Honest Metrics Skill

## 1. Zero Fabrication Policy
- Never report unmeasured numbers or synthetic benchmarks as real live results.
- Every metric in `REPORT.md`, CLI output, or UI must be computed from experimental data or ledger events.
- All synthetic datasets carry `source: "synthetic"` in the record schema and an explicit `[SYNTHETIC]` badge in the dashboard.

## 2. Held-Out Evaluation Protocol
- **Deterministic Split**: Train/validation/test split uses a fixed seed committed to the repo (`SPLIT_SEED = 42`).
- **Holdout Integrity**: The test partition (200 records) is sealed during prompt tuning and classifier iteration; no peeking, no re-splitting until metrics look good.
- **Reporting Metrics**:
  - Macro Precision / Recall / F1 across all diagnosis categories.
  - Confusion matrix: full true-vs-predicted root-cause breakdown.
  - Abstain rate: share routed to the human exception queue for low confidence.
  - Coverage: proportion resolved deterministically vs. LLM vs. abstained.

## 3. Uplift & Wilson Confidence Intervals

Recovery uplift compares Treatment (85%) against the deterministic holdout Control (15%).

Use plain code (no hand-typed LaTeX); reference `core/experiment/stats.py` as the single source of truth:

```python
p_hat = k / n                                   # observed recovery rate
z = 1.96                                        # 95% confidence
denom = 1 + z**2 / n
center = (p_hat + z**2 / (2 * n)) / denom
spread = z * math.sqrt(p_hat * (1 - p_hat) / n + z**2 / (4 * n**2)) / denom
wilson_ci = (center - spread, center + spread)  # 95% Wilson interval

uplift = p_treatment - p_control                # report with CI on the difference
net_incremental_inr = recovered_treatment_inr - p_control * n_treatment * avg_value_inr
```

Rules:
- Always publish n per arm alongside any rate.
- Never compare arms with different exposure windows without saying so.
- If control conversions are zero, say the CI is wide rather than quoting a raw multiple.

## 4. Cost-Benefit & Unit Economics
- **False-Positive Cost (INR)**: incentives given to customers who would have paid anyway, estimated against the control baseline rate.
- **Cost Per Rupee Recovered (CPRR)** = total intervention cost (incentives + messaging fees) / net incremental revenue recovered (INR).
- Report both treatment and control costs; never net out guardrail-blocked actions as "savings" they did not produce.

## 5. Anti-Cherry-Picking Rules
- Banned: showcasing only successful recoveries; omitting failed attempts and exceptions.
- Required: complete exception list categorized by root cause with the reason automation halted.
- Banned: switching metrics mid-report; if you change a definition, show both old and new values.
- Sample-size honesty: uplift claims on tiny cohorts must be labeled "directional only".
