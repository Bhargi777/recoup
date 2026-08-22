# recoup

AI-powered revenue recovery engine for Razorpay **Test Mode** (Buildathon Track 03: AI Revenue Recovery).

> Status: Phase 3 (Data). The architecture, ground rules, and money-action invariants
> live in [CLAUDE.md](CLAUDE.md) — read that first.

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

## Synthetic data (Phase 3)

**This is synthetic data for demo/eval purposes — it is not real Razorpay traffic.**
`core/ingest/synthetic.py` generates 600 fabricated at-risk records so later phases
(diagnosis, policy, eval) have something to run against before live volume exists. Every
record carries `source: "synthetic"` as a real schema field, not just a doc claim, so
nothing downstream can present it as a live payment.

The 600 records split evenly across four cohorts (150 each):

- `one_time_checkout_failure` — a single hard card/UPI decline
- `checkout_abandonment` — customer never completed auth/collect (cancelled, timed out)
- `subscription_mandate_failure` — recurring card/eMandate or UPI Autopay debit failure
- `overdue_b2b_invoice` — a net-terms invoice past due, with no gateway attempt at all

`error_code`/`error_reason` values are drawn **only** from the verified catalog in
[`.claude/skills/razorpay-testmode/SKILL.md`](.claude/skills/razorpay-testmode/SKILL.md)
§5 (cards) and §6 (UPI) — nothing from its §7 banned/unverified list is ever used. Each
record also carries `true_root_cause`, a closed-taxonomy ground-truth label the generator
alone knows (it authored the scenario); the not-yet-built diagnosis path only ever sees
`error_code`/`error_reason`/free text, exactly like it would for a real payment —
`true_root_cause` exists purely so a future held-out evaluation can score itself honestly.

The split is deterministic: `get_settings().split_seed` (`42`) seeds the generator, and
exactly 200 of the 600 records are marked `held_out: true` as a pure function of that seed
— the same seed always produces the same held-out set.

```bash
recoup generate-synthetic-data          # generate + persist 600 records, one ledger
                                         # event per insert; no-ops if data already exists
recoup generate-synthetic-data --force  # wipe and regenerate instead of skipping
```
