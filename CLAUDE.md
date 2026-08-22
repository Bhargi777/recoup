# CLAUDE.md — Project Constitution for recoup

`recoup` is an AI-powered revenue recovery engine built for the Razorpay Buildathon (Track 03: AI Revenue Recovery).

---

## 1. Non-Negotiable Ground Rules

1. **Sole Authorship**: The user is the sole author. Never emit `Co-Authored-By` trailers or tool attributions in commits, PR descriptions, or source files. Only use the configured git user identity (`Bhargava Sri Sai <bhargavasrisai7@gmail.com>`).
2. **Commit Discipline**: Commit after every logically complete slice that passes tests. Target 8+ atomic Conventional Commits (`feat:`, `fix:`, `test:`, `refactor:`, `docs:`, `chore:`) per phase. Never squash commits. Never batch an entire phase into a single commit.
3. **Branching & PR Flow**: Each phase lives on its own branch (e.g. `feat/00-foundations`, `feat/01-domain-ledger`) created off `develop`. At phase completion, generate a clean PR body (summary of changes, test coverage, remaining caveats), perform self-review, and merge into `develop`. `develop` merges into `main` exclusively at integration checkpoints.
4. **Zero Fabrication & Honest Data**: If a metric is not measured, never print or report it. If an endpoint is not called, never claim it was. All synthetic data must be explicitly marked with `source: "synthetic"` at the schema, storage, and UI layers.
5. **Test Mode Enforcement**: Razorpay API keys must originate from the environment and are never committed. The application must hard-fail at startup if `RAZORPAY_KEY_ID` does not start with `rzp_test_`.

---

## 2. Architecture & Directory Structure

```
recoup/
├── core/
│   ├── ingest/       # Razorpay API client, webhook receiver, synthetic data generator
│   ├── diagnose/     # Deterministic error-code mapper + LLM fallback with explicit ABSTAIN
│   ├── policy/       # Versioned YAML playbooks, guardrails, quiet hours, budget meter, kill switch
│   ├── act/          # Action executors (payment links, retry scheduling, dunning drafts, escalations)
│   ├── ledger/       # Hash-chained append-only event log, verification, and state replay
│   ├── experiment/   # Deterministic holdout assignment (15% control), uplift calculation + Wilson CI
│   ├── eval/         # Batch runner, held-out evaluation suite, metrics report generator
│   └── config.py     # Environment settings & test-mode validation
├── recoup/
│   └── cli.py        # Typer CLI (`recoup verify-chain`, `recoup run-batch`, `recoup chaos`, etc.)
├── dashboard/        # React + Vite + Tailwind operator console
├── tests/            # Pytest test suite (unit, integration, red-team, chaos)
├── .claude/
│   ├── skills/       # Mandatory skills & checklists
│   └── agents/       # Specialized subagent definitions
└── CLAUDE.md         # Project constitution (this file)
```

---

## 3. Money-Action Invariants

Any code path that moves, promises, discounts, waives, or schedules money MUST satisfy four core invariants:

1. **Idempotent**: Every mutating operation carries a deterministic idempotency key (`idempotency_key = sha256(event_id + action_type + attempt_num)`). Re-running an action must produce the exact same outcome without duplicate execution or double billing.
2. **Gated**: Every action must pass the Policy Gate:
   - Within global and cohort budget caps.
   - Outside quiet hours (DND 21:00–09:00 local time).
   - Under max attempt thresholds per customer/cohort.
   - Compliant with RBI e-mandate pre-debit rules (24hr notice) and NPCI AutoPay constraints (max 4 total attempts, non-peak window: 10:00–13:00 & 17:00–21:30 prohibited).
   - Kill switch is `INACTIVE`.
3. **Logged**: The decision, policy evaluation, and execution must emit an immutable hash-chained event to the audit ledger BEFORE external execution begins and AFTER completion.
4. **Reversible or Refusable**: If an action fails, encounters a 5xx gateway error, or is disputed, it can be cancelled, refunded, or routed to the human exception queue without state corruption.

---

## 4. AI Authority & Judgment Boundary

- **LLMs are NEVER the sole authority for money actions.**
- Root-cause diagnosis uses a **deterministic error-code mapper first** (~80% coverage).
- LLMs are utilized **only as a secondary classifier** for ambiguous/free-text failure reasons.
- The LLM classifier must support an explicit **`ABSTAIN`** path when prediction confidence is below the set threshold ($< 0.80$).
- All `ABSTAIN` outcomes route directly to the human exception queue.
- Policy rules, guardrails, budget limits, cooldowns, and retry intervals are strictly **deterministic and auditable**.

---

## 5. Definition of Done for a Slice

A slice is considered complete and eligible for commit only when:
1. **Tests are Green**: Unit and integration tests for the slice pass completely (`pytest` exits with 0).
2. **Ledger Event Emitted**: Any state mutation or decision emits a verified audit event.
3. **No Guardrail Bypassed**: Red-team assertions pass (zero unmetered actions, zero double charges).
4. **Atomic Commit**: Committed with Conventional Commit syntax and zero author trailers.
