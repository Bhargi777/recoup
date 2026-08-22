---
name: money-action-gate
description: Mandatory pre-flight checklist and validation gate for any code path that moves, promises, discounts, or waives revenue.
---

# Money-Action Gate Skill & Checklist

Every code path that initiates a refund, issues a discount coupon, schedules a mandate debit, creates an incentive payment link, or waives overdue fees MUST strictly pass through the **Deterministic Policy Gate**.

## 1. Pre-Flight Gate Checklist

| # | Check Item | Validation Rule | Gate Failure Action |
| :- | :--- | :--- | :--- |
| 1 | **Idempotency Verification** | Unique `idempotency_key` present; entity state is not already processed. | Return cached execution result / Reject duplicate |
| 2 | **Global Budget Meter** | Total cumulative incentive spend + proposed discount $\le$ `MAX_GLOBAL_BUDGET_INR`. | Block discount; fallback to zero-cost reminder |
| 3 | **Cohort Incentive Ceiling** | Incentive does not exceed cohort cap (e.g., max 10% or ₹500 for Checkout, 0% for Invoices). | Cap incentive to ceiling or reject |
| 4 | **Customer Attempt Limits** | Total recovery attempts for this invoice/payment $\le$ `MAX_RETRY_ATTEMPTS` (NPCI limit: max 4). | Stop dunning; escalate to Human Queue |
| 5 | **Cooldown Interval** | Time since last communication $\ge$ cohort cooldown threshold (e.g. 6 hours). | Postpone action to next eligible window |
| 6 | **Quiet Hours (DND)** | Current target local time is between 09:00 and 21:00 IST. | Delay message dispatch to 09:01 IST next morning |
| 7 | **RBI E-Mandate Compliance** | Recurring mandate debits must have pre-debit notification sent $\ge$ 24 hours prior. | Reject immediate debit; schedule 24hr pre-notice |
| 8 | **NPCI Peak-Hour Restriction** | UPI AutoPay executions prohibited between 10:00–13:00 and 17:00–21:30 IST. | Defer mandate trigger to compliant off-peak window |
| 9 | **Kill Switch** | Emergency Kill Switch is `INACTIVE` across system and tenant. | Immediately halt execution; log emergency block |
| 10 | **Pre-Action Ledger Event** | Hash-chained event `MONEY_ACTION_INTENT` emitted to audit ledger. | Abort transaction if ledger write fails |

## 2. AI Authority Prohibition
- **No LLM may directly authorize money actions.**
- LLM outputs (e.g., extracted sentiment, proposed message text, suggested root cause) are treated as **untrusted inputs**.
- Policy engine constraints are **hard-coded, deterministic Python/YAML rules** that cannot be overridden by prompt engineering or LLM reasoning.

## 3. Reversibility & Refusal Contract
- Every executor must define a `rollback()` or `compensate()` handler.
- If gateway communication fails mid-flight, state is set to `ACTION_AMBIGUOUS_RECHECK`, and an automated verification job polls status before retrying.
