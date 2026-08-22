# recoup

AI-powered revenue recovery engine for Razorpay **Test Mode** (Buildathon Track 03: AI Revenue Recovery).

> Status: Phase 2 (Razorpay integration). The architecture, ground rules, and money-action
> invariants live in [CLAUDE.md](CLAUDE.md) — read that first.

## Quickstart

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env            # fill in rzp_test_ credentials
recoup --help
pytest
```

## Hard guarantees

- Test Mode only: the process refuses to boot unless `RAZORPAY_KEY_ID` starts with `rzp_test_`.
- No fabricated metrics anywhere; synthetic data is labelled `source: "synthetic"` end to end.
- Every money-moving action must be idempotent, policy-gated, ledger-logged, and reversible.

## Audit ledger (Phase 1)

`core/ledger` is a hash-chained, append-only event log (spec:
[`.claude/skills/audit-ledger/SKILL.md`](.claude/skills/audit-ledger/SKILL.md)). Every event chains
to the current HEAD's `current_hash` via SHA-256 over a canonicalized payload; nothing later in the
project may write to the database without emitting one of these events first.

```bash
recoup verify-chain   # recomputes every hash and link; exits 1 with the exact
                       # broken sequence_num if anything was tampered with
```

## Razorpay integration (Phase 2)

`core/ingest` is the Test Mode HTTP client, webhook receiver, and reliability layer:

- `RazorpayClient` — `create_order`, `create_payment_link`, `fetch_payment`,
  `fetch_subscription`. Mutating calls are idempotency-gated against the ledger before
  any HTTP request is made (`.claude/skills/razorpay-testmode/SKILL.md` §3); every call,
  mutating or read-only, emits a ledger event.
- Retries: 429 honors `Retry-After`; 5xx/network errors retry with full-jitter exponential
  backoff behind a circuit breaker (CLOSED → OPEN → HALF_OPEN).
- `POST /webhooks/razorpay` (`recoup serve`) — verifies `X-Razorpay-Signature`
  (HMAC-SHA256 over the raw body) and dedupes on `x-razorpay-event-id`; a duplicate
  delivery is a ledger no-op and can never re-trigger a downstream action. Covers
  `payment.failed`, `payment_link.paid`, `subscription.charged`, `subscription.halted`.

**Honest status — live proof not yet done.** Everything above is unit-tested against
`httpx.MockTransport` (no network call made) — see `tests/test_ingest_*.py`. CLAUDE.md's
Phase 2 exit bar additionally requires creating a real Test Mode payment link and paying
it against `api.razorpay.com/v1` with real `rzp_test_` credentials. This environment does
not have Razorpay test-mode credentials, so that live proof has not been run and this PR
does not claim it has. Running it (and recording the `payment_id` as evidence per the
razorpay-testmode skill) is tracked as follow-up work once credentials are available.
