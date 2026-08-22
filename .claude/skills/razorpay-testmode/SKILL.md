---
name: razorpay-testmode
description: Integration guide and VERIFIED error catalog for Razorpay Test Mode API, Webhooks, Idempotency, and Failure Handling.
---

# Razorpay Test Mode Skill & Reference

> **Catalog provenance**: The error catalog below was transcribed from Razorpay's official
> documentation on **2026-08-22**:
> - Cards: https://razorpay.com/docs/errors/payments/cards/
> - UPI: https://razorpay.com/docs/errors/payments/upi/
> - Error anatomy: https://razorpay.com/docs/errors/
> - Subscriptions retry model: https://razorpay.com/docs/payments/subscriptions/payment-retries/
>
> Do not add a code to the catalog unless it appears in official docs or has been observed
> live in Test Mode (record the `payment_id` as evidence). Codes we could not verify are
> listed in §7 and MUST NOT be used by the synthetic data generator or mapper.

## 1. Authentication & Security Guardrails

- **Credential Storage**: API credentials load strictly from environment variables (`RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`).
- **Test Mode Enforcement**: `RAZORPAY_KEY_ID` MUST begin with `rzp_test_`. The app hard-fails at boot otherwise (`core/config.py`).
- **Base URL**: `https://api.razorpay.com/v1` (Basic auth: key id as username, secret as password).

## 2. Error Response Anatomy

Every failed API call returns HTTP != 200 with:

```json
{
  "error": {
    "code": "BAD_REQUEST_ERROR",
    "description": "Authentication failed due to incorrect otp",
    "field": null,
    "source": "customer",
    "step": "payment_authentication",
    "reason": "invalid_otp",
    "metadata": { "payment_id": "...", "order_id": "..." }
  }
}
```

- `error.code`: top-level class — `BAD_REQUEST_ERROR`, `GATEWAY_ERROR` (per the official *List of Errors* taxonomy).
- `error.source`: who must act — for cards: `customer | business | internal | gateway | issuer_bank`.
- `error.step`: failure stage; values vary by payment method (e.g., `payment_authentication`).
- `error.reason`: machine-handleable reason — **the primary join key for our deterministic mapper**.
- On the Payment entity itself the same fields appear as `error_code`, `error_description`,
  `error_source`, `error_step`, `error_reason`.

## 3. Idempotency & Safe Retries

- All mutating POST/PUT calls carry a deterministic idempotency key stored in the ledger BEFORE dispatch.
- Key rule: `idempotency_key = sha256(f"{action_type}:{entity_id}:{attempt_num}")`.
- Check the ledger first; if the same key already succeeded, return the recorded result — never re-dispatch.

## 4. Webhook Signature Verification

Razorpay signs webhook payloads with HMAC-SHA256 using `RAZORPAY_WEBHOOK_SECRET`.

- Verify against the **raw request body bytes**, never re-serialized JSON.
- Header: `X-Razorpay-Signature`. Comparison: `hmac.compare_digest(computed_hex, header_value)`.
- Deduplicate on event id: persist processed events in the ledger; duplicates get HTTP 200 + no-op
  (a duplicate webhook must never trigger a second payment link or charge).
- Events central to recoup: `payment.failed`, `subscription.pending`, `subscription.halted`
  (retry-model doc), plus payment-link paid events for checkout recovery.

## 5. Verified Failure Catalog — Cards

| `error.reason` | Doc summary | recoup strategy |
| :--- | :--- | :--- |
| `card_expired` | Customer's card is expired | Card-update link + alternate method prompt |
| `incorrect_cvv` | Incorrect CVV entered | Retry prompt; suggest saved-card/CVV-less flow |
| `card_not_enrolled` | Card not activated/enabled for online transactions | Guide customer to enable online usage via bank app |
| `card_disabled_for_online_payments` | Card not enabled for online use | Same as above |
| `debit_instrument_inactive` | Card not activated for online transactions | Same as above |
| `debit_instrument_blocked` | Card blocked by customer or bank | Ask customer to unblock; offer alternate instrument |
| `insufficient_funds` | Account lacks funds | Timed retry (post-salary window); payment link |
| `transaction_limit_exceeded` | Daily card limit exhausted | Retry next day or alternate instrument |
| `authentication_failed` | Wrong OTP / browser closed during auth | Re-authentication link |
| `invalid_otp` | OTP incorrect (docs example; customer/payment_authentication) | Re-authentication link |
| `payment_cancelled` | Customer cancelled / pressed back (also used for bank downtime variants) | Abandonment-recovery playbook |
| `payment_timed_out` | Exceeded processing time limit (~10 min) | Fresh link promptly |
| `payment_risk_check_failed` | Bank declined citing fraud | Route to human exception queue |
| `card_declined` | Issuer declined, reason withheld | Alternate instrument |
| `payment_failed` | Generic issuer decline | Alternate instrument |
| `bank_technical_error` | Customer's bank downtime | Delayed auto-retry after downtime clears |
| `gateway_technical_error` | Razorpay partner-bank downtime | Backoff retry; do NOT count against customer |

## 6. Verified Failure Catalog — UPI

| `error.reason` | Doc summary | recoup strategy |
| :--- | :--- | :--- |
| `insufficient_funds` | Insufficient balance in bank account | Timed retry / alternate account |
| `payment_declined` | Funds could not be debited | Single polite retry, then human queue |
| `payment_cancelled` | Customer cancelled / pressed back | Abandonment playbook |
| `payment_timed_out` | Exceeded time limit (~10 min) | Fresh collect request promptly |
| `payment_collect_request_expired` | Collect request expired (~10 min) | Fresh collect request promptly |
| `invalid_vpa` | Customer not a valid UPI app user | Onboarding-fix nudge |
| `vpa_resolution_failed` | Transaction failed on customer's UPI ID | Support ticket / human queue |
| `credit_failed` | Registered-account mismatch or partner-bank downtime | Disambiguate via free-text before acting |
| `bank_technical_error` | UPI provider downtime | Delayed auto-retry |
| `gateway_technical_error` | Partner-bank technical issues/downtime | Backoff retry |

## 7. Unverified / Excluded Codes — DO NOT USE

These appeared in earlier drafts but could NOT be found in official docs on 2026-08-22.
They are banned from the synthetic generator, deterministic mapper, and any policy rule
until observed live in Test Mode with evidence:

- ~~`expired_card`~~ → real code is `card_expired`
- ~~`mandate_inactive`~~ → mandate revocation is described in prose ("customer cancelled
  the mandate"), no reason code found; treat mandate-cancelled cases as free-text → LLM path
- ~~`amount_limit_exceeded`~~ → closest verified concept: debits above the mandate's
  `max_amount` fail (UPI Autopay doc); no such reason code published
- ~~`bank_account_invalid`~~ → closest verified UPI codes: `credit_failed`, `invalid_vpa`
- ~~`network_failure`~~ → no such reason code published

## 8. Subscription Retry Semantics (drives our policy)

Verified from the Payment Retries doc:

- **Cards**: T+3 cycle — auto-charge at T=0 fails → subscription `pending` → automatic
  retries once daily on T+1, T+2, T+3 → all fail ⇒ subscription `halted`.
- **eMandate**: next attempt happens only after confirmation/rejection of the last one
  (>24h gaps possible); bank holidays shift charge day back (T-1, or T-3 if both are holidays).
- While `pending`/`halted`: invoices keep generating but are NOT auto-charged; merchant may
  manually charge an invoice while it is in `issued` state.
- Policy implication: our agent NEVER re-attempts a hard decline inside Razorpay's own T+3
  window; it acts on `halted`/failed-final states with links and card-change nudges instead.

## 9. Rate Limits & 5xx Handling

- HTTP 429: honor `Retry-After` when present; else exponential backoff with full jitter:
  `backoff = min(cap, base * 2^attempt) + uniform(0, 1)`.
- 5xx / network errors: circuit breaker — OPEN after N consecutive failures in the sliding
  window; half-open probes before closing. In-flight actions go to queued-retry state, never lost.
- A failed dispatch is always recoverable: idempotency key makes re-dispatch safe.
