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
