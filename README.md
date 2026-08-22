# recoup

AI-powered revenue recovery engine for Razorpay **Test Mode** (Buildathon Track 03: AI Revenue Recovery).

> Status: Phase 5 (Policy Engine). The architecture, ground rules, and money-action invariants
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

## Diagnosis (Phase 4)

`core/diagnose` turns a failed payment/invoice into a root-cause label. Per CLAUDE.md
§4 ("AI Authority & Judgment Boundary"), this is a **deterministic-mapper-first**
design — an LLM is a secondary path only, and it never has sole authority.

**1. Deterministic mapper (`core/diagnose/mapper.py`)** — a pure lookup table sourced
directly from [`.claude/skills/razorpay-testmode/SKILL.md`](.claude/skills/razorpay-testmode/SKILL.md)
§5 (cards) and §6 (UPI). It imports `ROOT_CAUSE_MAP` from `core/ingest/synthetic.py`
rather than redefining it, so the mapper and Phase 3's ground truth can never drift
into two parallel taxonomies. The `overdue_b2b_invoice` cohort has no gateway error by
design, so it resolves through its own deterministic cohort rule
(`cohort == "overdue_b2b_invoice"` → `invoice_overdue`), never by falling through to
ABSTAIN.

**Why deterministic-first, not "always ask the LLM":** every `error.reason` Razorpay
returns is already a known, finite, documented string (SKILL.md §2/§5/§6). Running an
LLM call per failed payment to re-derive a fact that's already a structured field would
mean: paying inference cost and adding P95 latency on every single diagnosis; a
non-zero hallucination/inconsistency rate on a decision a plain dictionary lookup
answers exactly and deterministically; and a diagnosis that isn't reproducible run to
run, which breaks the audit trail this project's ledger exists to provide. A lookup
table is instant, free, deterministic, and trivially testable against the verified
catalog — so the LLM is reserved for the one case a lookup table structurally cannot
handle: free-text reasons that were never reduced to a `error.reason` code at all.

**2. LLM fallback with ABSTAIN (`core/diagnose/llm_classifier.py`)** — only invoked
when the deterministic mapper finds no match and the record carries free text worth
classifying. `classify()` calls the Anthropic API and returns a `predicted_root_cause`
+ `confidence`; a plain Python comparison (not the model) then enforces
`confidence < 0.80 → abstained=True` (`CONFIDENCE_THRESHOLD` in that module). ABSTAIN is
a first-class, ledgered outcome — it represents routing to the (not-yet-built) human
exception queue, never a silent failure.

**Honest status — no live LLM call in this environment.** There is no
`ANTHROPIC_API_KEY` available here. `classify()` raises `LLMUnavailableError` rather
than fabricating a confident label when the key is unset — `core/diagnose/diagnose.py`
catches that and routes the record to ABSTAIN. The confidence-gate logic and the
unavailable-key path are both unit-tested with an injected fake `classify_fn`
(`tests/test_diagnose_llm_classifier.py`, `tests/test_diagnose_orchestrator.py`); no
test in this repo makes a real network call to Anthropic.

**3. Orchestrator (`core/diagnose/diagnose.py`)** — `diagnose(session, record)` tries
the deterministic mapper first, falls back to the LLM path only if there's no
deterministic match *and* the record has free text, and otherwise ABSTAINs. Every
outcome (`DIAGNOSIS_COMPLETED` or `DIAGNOSIS_ABSTAINED`) emits exactly one ledger event
carrying the predicted root cause, method (`deterministic`/`llm`/`abstain`), and
confidence — no diagnosis happens silently.

**4. Held-out evaluation (`core/eval/diagnosis_eval.py`, `recoup eval-diagnosis`)** —
loads the 200 `held_out: true` records the Phase 3 generator sealed under
`split_seed = 42`, runs `diagnose()` on each record's `error_code`/`error_reason`/
`cohort` (never `true_root_cause` — that's the label being predicted), and scores
against `true_root_cause`. Reports macro precision/recall/F1, a full confusion matrix,
abstain rate, and coverage by method, per
[`.claude/skills/honest-metrics/SKILL.md`](.claude/skills/honest-metrics/SKILL.md) §2.

```bash
recoup eval-diagnosis   # self-contained: generates the synthetic dataset first if the
                         # database is empty, then runs the real held-out evaluation
```

**Actual measured results** (real run against the 200 held-out records, captured
2026-08-22 — not estimated):

```
held-out records evaluated: 200
  macro precision : 1.0000
  macro recall    : 1.0000
  macro f1        : 1.0000
  abstain rate    : 0.0000
  coverage:
    abstain       : 0
    deterministic : 200
    llm           : 0
```

This is not a cherry-picked number: it is the direct, expected consequence of how
Phase 3's generator was built — every `error_reason` it emits is drawn from the same
verified catalog the mapper covers, and the one cohort with no gateway error
(`overdue_b2b_invoice`) has its own deterministic rule. The LLM fallback and ABSTAIN
paths are real, tested code (`tests/test_diagnose_orchestrator.py`,
`tests/test_diagnose_llm_classifier.py`) — they are simply not exercised by this
particular dataset, because no held-out record is ambiguous enough to need them. That
is documented here rather than forced by inventing a fake ambiguous case just to make
the coverage report show a non-zero LLM number.

## Policy engine (Phase 5)

`core/policy` is the **deterministic decision core**: the only place in this codebase
allowed to decide whether a money action may proceed. Per CLAUDE.md §4, no LLM is called
anywhere in this module or anything it imports — every rule here is plain Python/YAML.

**1. Playbooks (`core/policy/playbooks/*.yaml`)** — one YAML file per root-cause label in
the closed taxonomy (`core.ingest.synthetic.ROOT_CAUSE_MAP` + `invoice_overdue`, 16
labels total). Each playbook declares `trigger_conditions.cohorts`, an ordered
`intervention_ladder` (`reminder_message` → `payment_link` → `incentive_offer` →
`escalate_to_human`, each with a `T+<offset>` timing), a hard `incentive_ceiling`
(`overdue_b2b_invoice`'s is a real enforced `0`, never a comment), `max_attempts`, and
`stopping_rules`. `core/policy/schema.py` validates every playbook against a Pydantic
model at load time — an unknown cohort, unknown step, malformed offset, or
out-of-range ceiling fails loudly (`PlaybookLoadError`), never silently no-ops.
`core/policy/loader.py`'s `validate_taxonomy_completeness` asserts a 1:1 mapping between
playbooks and taxonomy labels in both directions.

**2. The 10 guardrail checks (`core/policy/guardrails.py`)** — every check from
[`.claude/skills/money-action-gate/SKILL.md`](.claude/skills/money-action-gate/SKILL.md)
§1 is its own independently testable function: idempotency verification, global budget
meter, cohort incentive ceiling, customer/NPCI attempt limits, cooldown interval, quiet
hours (DND), RBI e-mandate pre-debit notice, NPCI peak-hour restriction, kill switch, and
ledger-writability (the pre-action-event readiness check).

**3. Replay-based kill switch and budget meter** — per the audit-ledger state-replay
contract, neither is a separate mutable table. The kill switch's state is whichever of
`KILL_SWITCH_ACTIVATED` / `KILL_SWITCH_DEACTIVATED` has the highest `sequence_num`
(`core/policy/kill_switch.py`); the budget meter's current spend is `sum()` over
`INCENTIVE_COMMITTED` event payloads, globally or filtered by cohort
(`core/policy/budget.py`). `recoup kill-switch on|off|status` proves this in practice —
the same way `recoup verify-chain` proves the hash chain:

```bash
recoup kill-switch status              # replays the ledger, reports INACTIVE/ACTIVE
recoup kill-switch on --reason "..."   # appends KILL_SWITCH_ACTIVATED, then reports state
recoup kill-switch off --reason "..."  # appends KILL_SWITCH_DEACTIVATED, then reports state
```

**4. The composed gate (`core/policy/gate.py`)** — `evaluate_gate(session, context)`
runs all 10 checks **exhaustively** (not short-circuiting): every check always runs, and
every individual result — pass or fail — is written to the ledger as
`POLICY_GATE_EVALUATED`, followed by one `POLICY_GATE_DECISION` event for the overall
outcome. This is deliberate: the skill spec requires every check's decision on the
ledger, and an operator debugging a denial benefits from seeing every reason at once
(e.g. "over budget AND in a DND window") rather than only the first. Only on an overall
`ALLOW` does `evaluate_gate` append `MONEY_ACTION_INTENT` — strictly before returning to
the caller (checklist item #10, "before any hypothetical execution") — and, if an
incentive is involved, `INCENTIVE_COMMITTED`. `MONEY_ACTION_INTENT` also doubles as the
single append-only source that idempotency, attempt-count, and cooldown replay from, so
there is exactly one record of "an action was approved here", not a parallel table.

This phase does not execute anything — `core/act/` does not exist yet. `evaluate_gate`
only ever returns ALLOW/DENY; nothing here calls Razorpay or sends a message.

## Regulatory constraints (Phase 5)

Researched 2026-08-22 with live web search/fetch against primary and secondary sources.
Per CLAUDE.md's zero-fabrication rule, anything not independently verified from an
authoritative source is marked as such below rather than encoded as if it were
confirmed.

**Verified — RBI e-mandate pre-debit notification, 24 hours.** Fetched directly from
rbi.org.in: the *Digital Payments – E-mandate Framework, 2026*
(RBI/DPSS/2026-27/396, dated 2026-04-21, which consolidates and repeals eight prior
e-mandate circulars issued since 2019) states: *"An issuer shall send a pre-transaction
notification to the customer, at least 24 hours prior to the actual charge / debit."*
This is encoded as `rbi_emandate_pre_debit_notice_hours = 24.0` in `core/config.py` and
enforced by `check_rbi_pre_debit_notice` in `core/policy/guardrails.py`.
Source: https://rbi.org.in/scripts/NotificationUser.aspx?Mode=0&Id=13374

**Best-effort / unverified — NPCI UPI AutoPay max attempts (4) and peak-hour windows
(10:00–13:00, 17:00–21:30 IST).** Multiple independent secondary sources (payments-
industry blogs and news coverage, not NPCI's own text) consistently describe an NPCI
tightening effective 2025-08-01: each AutoPay mandate gets one original execution plus
three retries (4 total) before auto-cancellation, and execution is prohibited during
"peak" windows of 10:00–13:00 and 17:00–21:30 IST. Sources found:
- https://gokiwi.in/blog/major-changes-by-npci-on-upi-in-2025/
- https://paytm.com/blog/payments/upi/upi-rules-update-august-1-npci-new-guidelines/
- https://ibsintelligence.com/ibsi-news/npci-tightens-upi-api-rules-to-boost-resilience-fraud-controls/

Attempts to fetch NPCI's own operating circular PDFs directly (e.g.
`UPI_OC_No_223_FY_2025_26_Enhancement_of_UPI_Autopay...pdf` and the
`npci.org.in/what-we-do/upi/circular` index) returned HTTP 403 in this environment, so
the exact circular text could not be independently confirmed. These numbers therefore
match CLAUDE.md §3's stated constraints and are corroborated by consistent, converging
secondary reporting, but are treated as **conservative defaults, not confirmed primary-
source numbers** — encoded as `npci_upi_autopay_max_attempts = 4` (env-overridable in
`core/config.py`) and the `NPCI_PEAK_WINDOWS_IST` constant in
`core/policy/guardrails.py`, both commented accordingly. Before this policy engine
governs a real money action against these thresholds, someone with authenticated/direct
access to npci.org.in should confirm the exact operating circular text.

**Not regulatory — communication cooldown (6 hours).** There is no RBI/NPCI rule
governing a generic minimum gap between two dunning/reminder messages. `default_
cooldown_hours = 6.0` is adopted directly from
`.claude/skills/money-action-gate/SKILL.md`'s own worked example (item 5 of the
checklist table) as a reasonable, fully configurable default — not presented as a
regulatory requirement anywhere in code or docs.
