# recoup

AI-powered revenue recovery engine for Razorpay **Test Mode** (Buildathon Track 03: AI Revenue Recovery).

> Status: Phase 0 (Foundations). The architecture, ground rules, and money-action invariants
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
