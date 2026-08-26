# recoup — Phase 8 Final Report

Every number in this report was produced by running the real code in this
repository, in this task, against a fresh database
(`recoup_report.db`, `sqlite:///recoup_report.db`), in this order:

```
recoup generate-synthetic-data
recoup eval-diagnosis
recoup run-batch            # first pass, fresh ledger
recoup run-batch            # second pass, same ledger, demonstrates blocking
recoup chaos --inject gateway_5xx
recoup chaos --inject rate_limit
recoup chaos --inject webhook_replay
recoup chaos --inject duplicate_callback
recoup verify-chain
```

Nothing below is estimated, copied from an earlier PR description, or
assumed. Where a number comes from a simulation rather than real observed
Razorpay payment behavior, that is stated in the same breath as the number,
every time, per `.claude/skills/honest-metrics/SKILL.md`.

---

## 1. Throughput

`recoup run-batch` (dry-run), first pass against the freshly generated
600-record synthetic dataset:

| Metric | Value |
|---|---|
| Records processed | 600 |
| Elapsed wall time | 55.53s (`run-batch (dry_run) complete in 55.53s`) |
| Diagnosis abstained | 0 |
| Treatment / control split | 516 / 84 (actual control % = 14.00, target 15%) |
| Blocked by gate | 0 (first pass — see section 4 for a non-empty run) |
| Executed actions | reminder_message x 512, escalate_to_human x 4 |

600 records end-to-end (diagnose -> holdout assignment -> policy gate ->
execute -> simulated outcome) in ~55.5 seconds on this machine, single
process, SQLite. Most of that time is the ledger's per-event commit() (one
write per ledger event; ~16.4k events total accumulate across this report's
full command sequence — see section 6).

---

## 2. Diagnosis metrics (real, `recoup eval-diagnosis`)

Run against the real, committed 200-record held-out split (`held_out:
true`, sealed by `split_seed=42`, see `core/ingest/synthetic.py`), using
the real deterministic-mapper-first, LLM-fallback-second `diagnose()`
orchestrator (no `ANTHROPIC_API_KEY` is configured in this environment, so
the LLM path was never invoked; every record here resolved via the
deterministic mapper).

| Metric | Value |
|---|---|
| Held-out records evaluated | 200 |
| Macro precision | 1.0000 |
| Macro recall | 1.0000 |
| Macro F1 | 1.0000 |
| Abstain rate | 0.0000 |
| Coverage | deterministic: 200, llm: 0, abstain: 0 |

Full per-class precision/recall/F1 (all 1.000; support in parentheses):
abandonment (52), authentication_failed (12), bank_technical_error (17),
card_declined_generic (5), card_expired (13), credit_failed (5),
gateway_technical_error (7), incorrect_cvv (3), insufficient_funds (32),
invalid_vpa (1), invoice_overdue (45), limit_exceeded (6), risk_blocked (1),
vpa_resolution_failed (1).

**Why this is 100%, honestly**: the synthetic dataset's `error_reason`
values are drawn directly from the same closed taxonomy the deterministic
mapper (`core/diagnose/mapper.py`) resolves against (see
`core/ingest/synthetic.py`'s module docstring) — this measures "does the
mapper correctly cover the taxonomy it was built for", not "does this
diagnose real-world free text the mapper has never seen". The LLM
secondary-classifier path (`core/diagnose/llm_classifier.py`) exists and is
unit-tested via dependency injection, but is not exercised by this real run
because nothing in this run needed it.

---

## 3. Recovery uplift with CI — [SIMULATED]

This entire section is computed over `core.experiment.simulated_outcome` —
an explicitly labeled simulation, NOT real observed Razorpay payment
behavior. There are no live Razorpay test-mode credentials or real customer
traffic in this environment (Phase 2's open gap, see section 7). Treat
every number below as "does the statistical pipeline work correctly",
never as "this many real rupees were recovered".

From the first `run-batch` pass (fresh ledger, 600 records):

| Arm | Recovery rate (point estimate) | 95% Wilson CI | n |
|---|---|---|---|
| [SIMULATED] Treatment | 0.3798 | 0.3390 – 0.4225 | 516 |
| [SIMULATED] Control | 0.3214 | 0.2313 – 0.4272 | 84 |
| [SIMULATED] Uplift (treatment − control) | +0.0584 (+5.84pp) | — | — |

Per `honest-metrics` SKILL.md: n is published alongside every rate above;
the control arm's CI is visibly wider (n=84 vs n=516) — read the point
estimate with that in mind, not as a precise number.

---

## 4. Guardrail violations (zero) vs. correctly blocked actions (non-empty)

These are two different claims and this report does not conflate them.

**Addendum (2026-08-26)**: this section's original run (Phase 7, four scenarios)
predates the `check_not_already_settled` guardrail and chaos scenario 5,
added after a self-review found `stopping_rules: [already_paid]` was
schema-validated but never runtime-enforced (README's Policy Engine section
has the full disclosure, including the two `stopping_rules` entries -
`max_attempts_reached`, `customer_opted_out` - that remain open). Scenario
5's row below is from a fresh, real run captured at the time of this
addendum; the other four rows are unchanged from the original report run
and are not re-timestamped.

### 4a. Guardrail violations: 0

A guardrail violation would mean the gate was bypassed entirely — a double
charge, a budget-cap breach, a kill-switch-ignored action. Phase 7's five
chaos scenarios exist specifically to prove this never happens, and all
five passed for real:

| Scenario | Result | Key real evidence |
|---|---|---|
| gateway_5xx | PASS (8/8 checks) | Retried through 2 injected 502s then succeeded exactly once (RAZORPAY_CREATE_PAYMENT_LINK_SUCCEEDED x1, ACTION_PAYMENT_LINK_EXECUTED_LIVE x1); circuit breaker recovered to CLOSED; ledger chain valid (245 events checked) |
| rate_limit | PASS (6/6 checks) | Honored the server's real Retry-After: 3 header exactly (time.sleep([3.0]), no blind jitter); exactly one action executed after the 429; ledger chain valid (244 events checked) |
| webhook_replay | PASS (4/4 checks) | First delivery recorded, identical replay deduped (status="duplicate"); PAYMENT_LINK_PAID written exactly once; ledger chain valid (3 events checked) |
| duplicate_callback | PASS (7/7 checks) | Second evaluate_gate() call for the same idempotency_key was correctly BLOCKED (idempotency_verification, cooldown_interval); the duplicate executor call was refused, never re-sent; exactly 1 HTTP request across both runs; exactly one MONEY_ACTION_INTENT and one ACTION_PAYMENT_LINK_EXECUTED_LIVE recorded; ledger chain valid (255 events checked) |
| paid_during_flight | PASS (7/7 checks) | Seeded a real, deterministically-selected TREATMENT-arm record (`synth_one_time_checkout_failure_0000`); a real-shaped `payment_link.paid` webhook (with `reference_id` set the way Razorpay echoes it) was recorded; a batch run over that same database produced exactly one `ACTION_SKIPPED_ALREADY_PAID` event and zero executor-dispatch events for that record after the webhook fired; ledger chain valid (242 events checked) |

Every scenario also independently re-verified the hash chain (verify_chain)
after injection — tamper detection stayed green throughout.

### 4b. Correctly blocked actions: 516 (non-empty, by design)

The first `run-batch` pass above shows "blocked by gate: 0" — expected,
since nothing had been attempted against this ledger yet for the gate to
block on. Running `run-batch` a second time against the same ledger (same
600 records, same idempotency keys) produces exactly the blocking behavior
the gate exists for:

| Metric | Second pass |
|---|---|
| Blocked by gate | 516 |
| idempotency_verification | 516 |
| cooldown_interval | 512 |
| Executed actions | none (all 516 previously-actioned records correctly refused re-execution) |
| Elapsed | 105.72s |

This is the guardrail working as designed, not a violation: every one of
those 516 blocks is the idempotency_verification check correctly refusing
to re-approve an action already approved in the first pass (and, for 512 of
them, the cooldown_interval check independently agreeing it is too soon to
contact the same customer again). Section 4a's duplicate_callback chaos
scenario proves the same mechanism end to end against a mocked Razorpay
transport (1 real HTTP call across two attempts).

---

## 5. Unresolved exceptions, with reasons

Across the entire command sequence for this report (200 held-out
diagnose() calls from eval-diagnosis, plus 600 x 2 more from the two
run-batch passes):

- DIAGNOSIS_ABSTAINED events: 0. The deterministic mapper resolved every
  record it was asked to diagnose in this run — see section 2 for why that
  is expected on this synthetic dataset, not evidence the ABSTAIN path is
  unreachable (see tests/test_diagnose_orchestrator.py and
  tests/test_eval_diagnosis.py for direct, injected coverage of it).
- EXCEPTION_QUEUE_ENQUEUED events: 4 (from the first run-batch pass). All 4
  are root_cause="risk_blocked", action_type="escalate_to_human",
  cohort="one_time_checkout_failure" — this is the risk_blocked playbook's
  intervention ladder correctly starting at escalate_to_human
  (core/policy/playbooks/risk_blocked.yaml) rather than attempting an
  automated recovery action on a payment the issuer's own risk engine
  already blocked. This is a real routing-to-human decision by playbook
  design, not a diagnosis failure — honestly reported as such rather than
  conflated with an ABSTAIN.

No other exception category exists in this run. If a future run against
live traffic produces ABSTAIN cases, they would appear here with the same
honesty.

---

## 6. Ledger integrity

`recoup verify-chain` against the full accumulated ledger for this report
(every event from generate-synthetic-data, eval-diagnosis, both run-batch
passes, run in sequence on one database):

```
chain OK: 16436 events verified, no tampering detected
```

---

## 7. What we'd need real data for

Honest, specific gaps, not vague caveats:

1. **A live Razorpay test-mode payment-link proof.** RAZORPAY_KEY_ID /
   RAZORPAY_KEY_SECRET in this environment are dummy values
   (rzp_test_dummy); execute_payment_link's --live path
   (core/act/executors.py) makes a real HTTP call that would fail Razorpay
   auth here. Real rzp_test_ credentials would let section 1's throughput
   numbers include at least one genuinely created, genuinely verified
   test-mode payment link end to end (Phase 2's open gap).
2. **Real customer payment behavior, not core.experiment.simulated_outcome.**
   Every number in section 3 is a simulation built to exercise the
   holdout/uplift statistical pipeline honestly, not a claim about real
   recovered revenue. Nothing in this report claims otherwise, but it
   bears repeating here: replacing the simulated-outcome model with real
   observed payment outcomes (via webhooks — core/ingest/webhooks.py
   already records PAYMENT_LINK_PAID and similar events) is the single
   highest-value gap before any uplift number here should influence a real
   decision (Phase 6's open gap).
3. **An authoritative NPCI operating-circular confirmation.** The
   npci_upi_autopay_max_attempts=4 and NPCI peak-window constraints
   (core/policy/guardrails.py's NPCI_PEAK_WINDOWS_IST) are sourced from
   corroborating secondary sources because the primary NPCI operating
   circular PDF returned a 403 when fetched directly during Phase 5 (see
   core/config.py's npci_upi_autopay_max_attempts docstring and README.md
   "Regulatory constraints (Phase 5)"). Treated as a conservative
   best-effort default, not a verified regulatory citation.
4. **Real SMS/email/push gateway integration.** reminder_message,
   incentive_offer, and pre_debit_notification (section 1's 512 executed
   reminder_message actions) only draft a deterministic message and ledger
   it (ACTION_MESSAGE_DRAFTED, dispatched: false) — there is no
   SMS/email/push transport wired anywhere in this codebase
   (core/act/executors.py's module docstring). A drafted message and a
   delivered message are not the same claim, and this report does not
   conflate them.

---

## 8. AI judgment boundary

See README.md's "AI judgment" section for the full, cited breakdown. In
summary, for this specific run: the deterministic mapper resolved 100% of
diagnoses (section 2); the policy gate (section 4) is entirely
deterministic; message drafting used only core/act/templates.py's plain
f-strings; and the holdout split (sections 1, 3) is a pure function of
SPLIT_SEED=42. The one LLM integration point in this codebase,
core/diagnose/llm_classifier.py, was not invoked in this run (no
deterministic-mapper miss occurred to trigger its fallback path) and is
covered instead by tests/test_diagnose_llm_classifier.py's injected-fake
unit tests.

---

## 9. Every money action replayable from decision_id to a human-readable
   explanation (addendum, 2026-08-26)

This addendum postdates the original run above. `recoup replay
<event_id_or_idempotency_key>` (and its dashboard counterpart, `GET
/api/decisions/{event_id}`) now demonstrates this directly, not just via
`recoup verify-chain` (whole-chain integrity) or the Decisions feed
(browsable, not single-lookup). Real output, from a real `recoup run-batch`
run against the full 600-record dataset — see README.md's Policy Engine
section for the full transcript (11 `POLICY_GATE_EVALUATED` rows, one per
guardrail check, plus the overall decision and its downstream event, all in
sequence order with the same plain-English "why" the dashboard shows for
the identical event).
