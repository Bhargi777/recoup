# recoup

AI-powered revenue recovery engine for Razorpay **Test Mode** (Buildathon Track 03: AI Revenue Recovery).

> Status: Phase 1 (Ledger). The architecture, ground rules, and money-action invariants
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
