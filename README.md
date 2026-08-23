# recoup

AI-powered revenue recovery engine for Razorpay **Test Mode** (Buildathon Track 03: AI Revenue Recovery).

> Status: Phase 8 (Dashboard + Report) — feature complete. The architecture, ground rules, and
> money-action invariants live in [CLAUDE.md](CLAUDE.md) — read that first. Real, freshly-run
> numbers for this phase are in [REPORT.md](REPORT.md).

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

Phase 5 itself does not execute anything — `evaluate_gate` only ever returns ALLOW/DENY;
nothing in `core/policy` calls Razorpay or sends a message. Execution is Phase 6, below.

## Execution + Experiment (Phase 6)

Phase 6 adds the pieces downstream of the gate: **executors** that actually do something
with an ALLOW decision, a **deterministic randomized holdout** so "did the intervention
help" is a real question with a real answer, and a **statistically correct uplift +
Wilson-CI pipeline** to answer it. Read this section's last subsection
("Honesty of the numbers below") before quoting anything from it.

### Action executors (`core/act/`)

One executor per intervention-ladder step type in `core.policy.schema.KNOWN_STEPS`
(`core/act/executors.py`). Every executor takes the gate's already-computed
`PolicyDecision` and **refuses to run** — a real, tested code path, not an assumed
precondition — if `allowed` is not `True`. Every call, refused or not, emits exactly one
ledger event:

| Step | What it does | Ledger event |
| :-- | :-- | :-- |
| `reminder_message` | Drafts a deterministic template message (`core/act/templates.py`) keyed by root cause. No LLM. Not dispatched — no SMS/email gateway is integrated in this codebase. | `ACTION_MESSAGE_DRAFTED` |
| `incentive_offer` | Same as above, with the incentive amount/percent from the `GateContext`. | `ACTION_MESSAGE_DRAFTED` |
| `pre_debit_notification` | Same template mechanism, RBI e-mandate notice text. | `ACTION_MESSAGE_DRAFTED` |
| `mandate_retry` | Ledger-only: Phase 2's verified `RazorpayClient` surface has no mandate-retry-trigger endpoint, so this records the retry as SCHEDULED rather than fabricating a dispatch. | `ACTION_MANDATE_RETRY_SCHEDULED` |
| `escalate_to_human` | Writes to the human exception queue. No external call. | `EXCEPTION_QUEUE_ENQUEUED` |
| `payment_link` | **The only executor with a real external integration.** `--dry-run`: never constructs or touches a `RazorpayClient` — logs what would have been sent. `--live`: calls the real, unmodified `RazorpayClient.create_payment_link` from Phase 2. | `ACTION_SIMULATED_DRY_RUN` or `ACTION_PAYMENT_LINK_EXECUTED_LIVE` |
| refused (any step) | Gate did not allow it. | `ACTION_REFUSED_NOT_ALLOWED` |

Every executor has a matching `rollback_*`/`compensate_*` handler
(money-action-gate SKILL.md §3). `payment_link`'s compensation is ledger-side only:
Razorpay's Test Mode payment-links API has no verified cancel endpoint in
[`.claude/skills/razorpay-testmode/SKILL.md`](.claude/skills/razorpay-testmode/SKILL.md)'s
catalog, and none is fabricated here — `rollback_payment_link` marks the link cancelled in
the audit trail so downstream attempt/cooldown/budget logic treats it as inactive.
`tests/test_act_executors.py::test_payment_link_dry_run_never_touches_http_layer` proves
the dry-run guarantee with an `httpx.MockTransport` spy that fails the test if it is ever
called.

### Deterministic holdout (`core/experiment/holdout.py`)

`assign_group(customer_id, holdout_percent, seed)` hashes `f"{seed}:{customer_id}"` with
SHA-256 and buckets the result into `"treatment"`/`"control"` — a pure function with no
database read, so the same customer lands in the same group on every run, forever, for a
given seed. **The control group never reaches the policy gate or any executor — enforced
in `core.eval.batch_runner.run_batch`, not just documented** (see
`tests/test_eval_batch_runner.py::test_control_arm_never_reaches_gate_or_executor`).

### Simulated outcome + uplift + Wilson CI (`core/experiment/`)

`simulated_outcome.py` is an explicitly labeled **simulation**: this environment has no
real Razorpay test-mode credentials and no real customer payment behavior to observe (a
gap confirmed since Phase 2), so there is no honest way to know whether any synthetic
customer "really" recovered. The module's docstring states in capital letters that it is
not real payment behavior. It assigns each root cause an illustrative baseline recovery
rate (control-arm expectation) and applies a flat **+8 percentage point** illustrative
treatment uplift — both documented as assumptions, not measurements. Every outcome this
module's caller records to the ledger carries `outcome_source: "simulated"`
(mirroring Phase 3's `source: "synthetic"` field), and
`tests/test_eval_batch_runner.py::test_every_simulated_outcome_event_is_labeled` fails the
build if that label is ever dropped.

`core/experiment/stats.py` implements the **Wilson score interval** (not a normal
approximation) per
[`.claude/skills/honest-metrics/SKILL.md`](.claude/skills/honest-metrics/SKILL.md) §3,
verified in `tests/test_experiment_stats.py` against a hand-computable textbook reference
case (n=10, k=8 → 95% CI ≈ (0.49, 0.94)). `core/experiment/uplift.py` composes both arms'
intervals into an `UpliftReport`.

### The batch orchestrator (`recoup run-batch`)

```bash
recoup run-batch            # --dry-run is the default: full pipeline, nothing external called
recoup run-batch --live     # real RazorpayClient calls for payment_link (will fail auth here)
```

For every one of the 600 synthetic records: `diagnose()` → `assign_group()` → if
**control**: log `HOLDOUT_NO_INTERVENTION` + a simulated outcome, **stop — no gate, no
executor call**. If **treatment**: gate the *first* intervention-ladder step of that
record's root-cause playbook (every committed playbook's first step is `T+0`; walking the
full multi-day ladder would require simulating the passage of time across multiple runs,
out of scope for one batch pass) → if allowed, run the matching executor and log a
simulated outcome; if blocked, log the block reason into a **separate bucket, excluded
from the treatment/control comparison** (never counted as "did not recover" —
honest-metrics SKILL.md §5).

`--live` constructs a real `RazorpayClient` against `api.razorpay.com` — genuine code,
not a stub. Within this dataset's first-touch scope no record's *first* ladder step
happens to be `payment_link` (verified: every playbook's step 0 is `reminder_message`
except `risk_blocked`'s, which is `escalate_to_human`), so this specific 600-record batch
run does not itself trigger a live HTTP call either way. The live `payment_link` path
itself is exercised directly (mocked transport) in
`tests/test_act_executors.py::test_payment_link_live_calls_client_and_logs_executed`, and
was manually re-confirmed during Phase 6 development with a real, unmocked HTTPS request
to `api.razorpay.com` using dummy `rzp_test_` credentials, which returned a real
`401 {"error":{"code":"BAD_REQUEST_ERROR","description":"Authentication failed"}}` —
the same failure mode Phase 2's PR already established, not fabricated here.

### A real, timed run (not estimated)

Run on this branch against a fresh database, `recoup run-batch` (`--dry-run`, the
default):

```
run-batch (dry_run) complete in 51.94s
  records processed     : 600
  diagnosis abstained    : 0
  treatment / control    : 516 / 84 (actual control % = 14.00)
  blocked by gate        : 0
  executed actions:
    escalate_to_human           : 4
    reminder_message            : 512
  ** uplift below is computed over a SIMULATED outcome model
     (core.experiment.simulated_outcome) - NOT real observed Razorpay payments **
  [SIMULATED] treatment recovery rate: 0.3798 (95% Wilson CI 0.3390-0.4225, n=516)
  [SIMULATED] control recovery rate  : 0.3214 (95% Wilson CI 0.2313-0.4272, n=84)
  [SIMULATED] uplift (treatment - control): +0.0584
```

`blocked by gate: 0` is itself an honest result, not a cherry pick: with zero incentive
spend on every first-touch action in this dataset (first steps are never
`incentive_offer`) and a clean idempotency key per record, nothing in this particular pass
trips a guardrail. The gate's block path is real and tested directly —
`tests/test_eval_batch_runner.py::test_blocked_records_are_tracked_separately_from_the_comparison`
forces every treatment action to be blocked by activating the kill switch first, and
asserts the blocked bucket is populated and excluded from the comparison.

### Honesty of the numbers above

**Every uplift and recovery-rate figure above is computed over
`core.experiment.simulated_outcome` — a labeled simulation, not observed real Razorpay
payment behavior.** There is no real customer traffic or live test-mode credentials in
this environment to measure a real uplift against. This is not fabrication: fabrication
would be presenting `+0.0584` as real recovered revenue. What is real and independently
verifiable here is the *mechanism* — a genuine deterministic diagnosis, a genuine
deterministic randomized holdout split, a genuine 10-check policy gate, genuine-or-honestly-
simulated executors, and a correctly implemented Wilson-CI uplift calculation — exercised
end to end against synthetic inputs, exactly like Phase 3's synthetic data and Phase 4's
synthetic held-out eval already were. `records processed: 600`, `51.94s`, and the
treatment/control counts above are real measurements of a real run of this code, not
estimates.

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

## Chaos + graceful failure (Phase 7)

`core/chaos/scenarios.py` proves — with real code execution against the real pipeline,
not assumptions — that the resilience mechanics built in earlier phases actually hold
under injected failure. Each scenario first runs a small (15-record) real
diagnose → holdout → gate batch through `core.eval.batch_runner.run_batch` in
`--dry-run`, then injects one failure mode against a real `RazorpayClient` (via
`httpx.MockTransport`, the same pattern Phase 2's own tests use — nothing here ever
touches the network) or the real webhook handler:

```bash
recoup chaos --inject gateway_5xx        # 2 injected 502s, then a real retry succeeds
recoup chaos --inject rate_limit         # a 429 with Retry-After, honored verbatim
recoup chaos --inject webhook_replay     # the same webhook delivered twice
recoup chaos --inject duplicate_callback # the same record run through gate+executor twice
```

Each prints a `[PASS]`/`[FAIL]` line per check with a literal mock-call-count or
ledger-event-count backing it — e.g. `gateway_5xx` asserts the mocked transport received
*exactly* 3 requests (2 injected failures + 1 success) and exactly one
`ACTION_PAYMENT_LINK_EXECUTED_LIVE` event, not "it didn't crash." Every scenario ends by
calling `core.ledger.verify_chain` and asserting `ok=True` — chaos injection stresses
external calls, never the ledger's own integrity. A matching pytest exists per scenario
in `tests/test_chaos_scenarios.py`, checking the identical assertions the CLI prints.

**`duplicate_callback` is the literal proof the spec asks for by name**: a duplicate
webhook, retried job, or re-run-after-crash cannot produce a second payment link. It runs
one record through the real `evaluate_gate` → `execute_payment_link` cycle twice with the
same idempotency key and checks the mocked Razorpay transport's actual request count —
exactly 1 across both runs, with the second `evaluate_gate` call itself blocked by
`check_idempotency` rather than silently re-approved.

**Real gaps were found and fixed while building this, not papered over with a test that
dodges them:**
- `check_idempotency` previously blocked an idempotency_key permanently once
  `MONEY_ACTION_INTENT` was recorded, even if the real executor call that followed never
  actually happened (gateway down, retries/circuit-breaker exhausted) — stranding that
  record forever. It now treats a key whose most recent OUTCOME event is the new
  `ACTION_EXECUTION_FAILED` as retryable, while a key that reached a real terminal action
  stays permanently blocked.
- `check_attempt_limits` and `check_cooldown` had the identical blind spot one layer
  deeper: both counted every `MONEY_ACTION_INTENT` as a real customer-facing attempt, even
  one whose execution then failed. Fixing only `check_idempotency` was not enough — a
  retried record would pass idempotency but still get silently re-blocked by an artificial
  cooldown window (started by a message the customer never received) or an inflated
  attempt count. Both checks now share one `_was_a_real_attempt` helper with the same
  retry-after-failure logic. Finding this took an actual two-run integration test, not
  just a unit test of `check_idempotency` in isolation — the unit-level fix looked
  complete and still left the queue stuck.
- Building that shared logic surfaced a subtler bug in the lookup itself:
  `evaluate_gate` logs a `POLICY_GATE_EVALUATED` event after *every* one of the 10 checks,
  each carrying the same `idempotency_key` as the context under evaluation. A naive "what
  was the last event for this key" scan run partway through a single `evaluate_gate` call
  would see an *earlier check's own* `POLICY_GATE_EVALUATED` entry from that same call and
  mistake it for the final outcome — masking a real `ACTION_EXECUTION_FAILED` from an
  earlier run. The lookup now skips `POLICY_GATE_EVALUATED`/`POLICY_GATE_DECISION`
  entries, since neither is ever a real action outcome.
- `run_batch` previously let a live executor's `RazorpayAPIError`/`CircuitOpenError`/
  `httpx.TransportError` propagate and abort the entire batch, silently never processing
  any record after the failing one. It now catches exactly those transient failures per
  record, logs `ACTION_EXECUTION_FAILED`, and keeps draining the queue — this is what
  makes "queue drains correctly on recovery" true rather than aspirational; see
  `tests/test_eval_batch_runner_recovery.py` for the end-to-end proof (one record fails,
  the rest of that batch still completes, a second run picks up exactly the failed
  record and completes it, and no record that already succeeded is reprocessed).

**Honest scope note on `webhook_replay`**: `core.ingest.webhooks.handle_webhook_event`
only ever appends ledger events in this codebase — it never calls an executor or
`RazorpayClient` (verified by reading the module, not assumed). Webhooks are purely
observational here; `run_batch` is the only code path that reaches an executor. So
`webhook_replay` proves "a duplicate delivery never double-writes the domain ledger
event," and the stronger "cannot produce a second real action" guarantee is proven at the
run-batch/executor layer instead, by `duplicate_callback`.

## Dashboard (Phase 8)

`dashboard/` is a React + Vite + TypeScript + Tailwind operator console, now wired to a
real read-only API (`core/api`, mounted onto `core/ingest/webhook_app.py`) instead of the
Phase 8 scaffold's placeholder state. Run the API and the dashboard in two terminals:

```bash
# terminal 1 — the API (reuses the existing ingest FastAPI app)
recoup serve --port 8000

# terminal 2 — the dashboard dev server
cd dashboard
cp .env.example .env.local   # VITE_API_BASE_URL, defaults to http://127.0.0.1:8000
npm install
npm run dev
```

What's live now, per page:

- **Pipeline** — real `AtRiskRecord` rows grouped by cohort (`/api/pipeline`), including
  each record's diagnosed root cause where one exists.
- **Decisions** — real `POLICY_GATE_DECISION` ledger events (`/api/decisions`) with a
  plain-English "why" derived deterministically from the gate's own `reason` string — no
  LLM involved in that explanation.
- **Ledger** — paginated real `LedgerEvent` rows (`/api/ledger`) plus a working "Verify
  chain" button that calls the real `core.ledger.verify_chain` (`/api/ledger/verify`).
- **Guardrails** — real blocked-check rows from `POLICY_GATE_EVALUATED` events
  (`/api/guardrails`), explicitly distinguishing a correctly-blocked action from a
  guardrail violation (see REPORT.md section 4).
- **Metrics** — real diagnosis P/R/F1 (`core.eval.diagnosis_eval.evaluate_holdout`) and
  real, **[SIMULATED]**-labeled uplift + Wilson CI (`core.eval.batch_runner.run_batch`),
  with the label rendered directly on the metric tiles and panels, not hidden in a
  tooltip. This endpoint runs the real pipeline live and can take up to a minute.
- **Kill switch** — the top-bar control now calls the real `GET`/`POST /api/kill-switch`,
  which itself only calls `core.policy.activate_kill_switch` /
  `deactivate_kill_switch` — real ledger-replayed state, not a demo stub.

Nothing in `dashboard/` is scaffold-only as of this phase. CORS on the API is permissive
for `localhost`/`127.0.0.1` origins only — a deliberate, disclosed demo-environment
choice (see `core/ingest/webhook_app.py`), not a production posture.

## AI judgment

CLAUDE.md §4 is explicit that LLMs are never the sole authority for a money action. This
section collects, in one place, every point across all eight phases where this system
deliberately chose a deterministic path over an LLM, and the one place it uses an LLM at
all:

**Deterministic, no LLM involved:**

- **Root-cause diagnosis** — `core/diagnose/mapper.py`'s closed-taxonomy lookup resolves
  diagnoses first; on this repo's committed synthetic dataset it reaches 100% coverage
  (see REPORT.md section 2 — a real, freshly-measured number, not an estimate).
- **The policy gate** — `core/policy/gate.py` and all 10 checks in
  `core/policy/guardrails.py` (budget, attempt limits, cooldown, quiet hours, RBI/NPCI
  mandate rules, kill switch) are plain Python comparisons against ledger-replayed state.
  No model call anywhere in `core/policy`.
- **Message drafting** — `core/act/templates.py` is a fixed set of f-string templates
  keyed by root cause. `reminder_message`, `incentive_offer`, and
  `pre_debit_notification` in `core/act/executors.py` call only these templates; nothing
  customer-facing is model-generated.
- **The holdout split** — `core/experiment/holdout.py`'s treatment/control assignment is
  a deterministic hash of `(customer_id, split_seed)`, reproducible byte-for-byte on any
  re-run — not a random draw a model could influence.
- **The decisions dashboard's "why"** — `core/api/decisions.py` derives its plain-English
  explanation from the gate's own `reason` string with a fixed lookup table, not a
  generated summary.

**The one LLM integration point, with a hard confidence gate:**

- `core/diagnose/llm_classifier.py` is a secondary fallback, only ever consulted when the
  deterministic mapper finds no match. Its output is a label + confidence; a plain
  Python comparison (`confidence >= CONFIDENCE_THRESHOLD` = 0.80,
  `apply_confidence_gate`) — never the model itself — decides whether to trust it or
  route to `ABSTAIN`. Every `ABSTAIN` goes to the human exception queue
  (`EXCEPTION_QUEUE_ENQUEUED` / `DIAGNOSIS_ABSTAINED`). No `ANTHROPIC_API_KEY` is
  configured in this environment, so this path was not exercised in REPORT.md's real run
  — it is covered instead by `tests/test_diagnose_llm_classifier.py`'s injected-fake unit
  tests, which exercise both the confident-label and the abstain branches.

## Demo script (~3 minutes)

1. **Boot both processes** (see "Dashboard" above): `recoup serve --port 8000` in one
   terminal, `npm run dev` in `dashboard/` in another. Open the dashboard URL.
2. **Generate data**: `recoup generate-synthetic-data` — point at the **Pipeline** page;
   refresh to show 600 real records across the four cohorts.
3. **Diagnose**: `recoup eval-diagnosis` — read the real macro F1 / confusion matrix /
   abstain rate printed in the terminal; note it matches REPORT.md section 2.
4. **Run the batch**: `recoup run-batch` — point at the **Decisions** page for the real
   `POLICY_GATE_DECISION` feed with plain-English reasons, then **Metrics** for the real
   (clearly [SIMULATED]-labeled) uplift + Wilson CI and the exception list.
5. **Show a guardrail actually block something**: run `recoup run-batch` a *second* time
   against the same database — point at the **Guardrails** page; `idempotency_verification`
   and `cooldown_interval` now show real non-zero blocked counts, proving the gate refuses
   to re-approve an already-actioned record.
6. **Prove zero violations**: `recoup chaos --inject duplicate_callback` — walk through the
   printed `[PASS]` lines (exactly one HTTP request across two attempts, exactly one
   `MONEY_ACTION_INTENT`); this is the literal "duplicate can't double-charge" guarantee.
7. **Flip the kill switch**: click it live in the dashboard top bar, then show
   `recoup kill-switch status` printing the same real state from the terminal — one
   source of truth, two views.
8. **Close on the ledger**: `recoup verify-chain` (or the dashboard's Ledger page "Verify
   chain" button) — point at the real event count and `ok=True`, then note REPORT.md as
   the leave-behind with every number in this demo reproduced and cited.
