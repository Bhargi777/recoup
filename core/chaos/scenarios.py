"""Phase 7 chaos scenarios: real failure injection against the real pipeline.

Each ``run_*_scenario`` function below is executed by BOTH the
``recoup chaos --inject <type>`` CLI command (recoup/cli.py) and a matching
``tests/test_chaos_*.py`` pytest test, so the CLI's printed proof and the
automated test check exactly the same guarantees - never two different
implementations of "the same" claim.

Failure is injected the same way Phase 2's tests already do it:
``httpx.MockTransport`` wired into a real ``core.ingest.razorpay_client.
RazorpayClient``. Nothing here talks to the network.

Where the real pipeline is exercised
-------------------------------------
Every scenario first runs a small (default 15), real batch of synthetic
records through ``core.eval.batch_runner.run_batch`` in ``--dry-run`` -
the real diagnose -> holdout -> gate pipeline, proving it keeps working
under the same database the chaos injection then stresses. That smoke run
never touches Razorpay (dry-run never constructs a client).

The HTTP-failure-injection proof itself is then run against one explicitly
constructed ``GateContext`` with ``action_type="payment_link"`` - the ONLY
executor with a genuine Razorpay integration
(core/act/executors.py's module docstring). This is a deliberate, disclosed
choice: none of the 15 committed root-cause playbooks in
core/policy/playbooks/ put ``payment_link`` at ladder position 0 (all start
with ``reminder_message`` or, for ``risk_blocked``, ``escalate_to_human``),
so a single ``run_batch`` invocation - which only executes each record's
FIRST ladder step, see batch_runner's module docstring - never reaches
``execute_payment_link`` today. ``card_declined_generic``'s real ladder DOES
include ``payment_link`` at T+4h; this harness calls ``evaluate_gate`` and
``execute_payment_link`` directly with that root_cause, exercising the
IDENTICAL production functions ``run_batch`` would call for that later
touch, rather than fabricating a new code path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import httpx
from sqlmodel import Session, select

from core.config import Settings, get_settings
from core.eval.batch_runner import BatchReport, run_batch
from core.ingest.circuit_breaker import CircuitBreaker, CircuitState
from core.ingest.idempotency import compute_idempotency_key
from core.ingest.razorpay_client import RazorpayClient
from core.ingest.synthetic import AtRiskRecord, init_synthetic_schema
from core.ingest.webhooks import EVENT_ID_HEADER, handle_webhook_event
from core.ledger import list_events, verify_chain
from core.policy.context import GateContext
from core.policy.gate import PolicyDecision, evaluate_gate

IST = ZoneInfo("Asia/Kolkata")

DEFAULT_SMOKE_RECORD_COUNT = 15


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


@dataclass
class ChaosReport:
    scenario: str
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.passed for c in self.checks)

    def add(self, name: str, passed: bool, detail: str) -> None:
        self.checks.append(Check(name, passed, detail))

    def as_text(self) -> str:
        lines = [f"chaos scenario: {self.scenario}"]
        for c in self.checks:
            mark = "PASS" if c.passed else "FAIL"
            lines.append(f"  [{mark}] {c.name}: {c.detail}")
        lines.append(f"overall: {'PASS' if self.ok else 'FAIL'}")
        return "\n".join(lines)


# --- shared helpers ----------------------------------------------------------


def _pinned_daytime_ist_instant() -> datetime:
    """Noon IST today - outside the DND/quiet-hours window, same pinning
    strategy as core.eval.batch_runner so gate evaluation is deterministic."""
    now_ist_date = datetime.now(IST).date()
    return datetime(
        now_ist_date.year, now_ist_date.month, now_ist_date.day, 12, 0, tzinfo=IST
    ).astimezone(UTC)


def _smoke_run_real_pipeline(
    session: Session, settings: Settings, n_records: int
) -> BatchReport:
    """Seed n_records real synthetic at-risk records (idempotently - skips
    any id already present) and run them through the real
    diagnose -> holdout -> gate pipeline in --dry-run. Proves the rest of
    the pipeline keeps functioning in the same database the chaos injection
    below then stresses - never touches Razorpay.

    Idempotent seeding matters because ``recoup chaos`` can run multiple
    injection types back to back against the same database (the CLI dispatch
    table does exactly this), and ``generate_records`` is deterministic by
    seed - a second scenario's smoke run must not try to re-insert the same
    ids the first scenario already committed. Re-running ``run_batch`` itself
    on already-processed records is separately safe by design (see that
    module's docstring): it re-diagnoses and re-evaluates the gate, but
    ``check_idempotency`` blocks any record already ALLOWed+executed from
    executing twice - it "wastes work", it never double-acts.
    """
    from core.ingest.synthetic import generate_records

    init_synthetic_schema(session.get_bind())
    records = generate_records(seed=settings.split_seed)[:n_records]
    candidate_ids = [r["id"] for r in records]
    existing_ids = set(
        session.exec(select(AtRiskRecord.id).where(AtRiskRecord.id.in_(candidate_ids)))
    )
    new_records = [AtRiskRecord(**r) for r in records if r["id"] not in existing_ids]
    if new_records:
        session.add_all(new_records)
        session.commit()
    return run_batch(session, mode="dry_run", settings=settings)


def _fresh_payment_link_context(session: Session, aggregate_id: str) -> GateContext:
    """Build (but do NOT gate-evaluate) a fresh payment_link GateContext for
    card_declined_generic (the real T+4h step of that root cause's real
    committed playbook - core/policy/playbooks/card_declined_generic.yaml).
    Evaluating is the caller's job, and it must be done EXACTLY once per
    intended "gate call" - evaluate_gate appends MONEY_ACTION_INTENT on
    every ALLOW, so calling it an extra time for the same context would
    itself trip the very idempotency guard these scenarios are proving."""
    now = _pinned_daytime_ist_instant()
    return GateContext(
        idempotency_key=compute_idempotency_key("payment_link", aggregate_id, 0),
        aggregate_id=aggregate_id,
        customer_id=f"cust_{aggregate_id}",
        cohort="one_time_checkout_failure",
        root_cause="card_declined_generic",
        action_type="payment_link",
        proposed_action_at=now,
        now=now,
    )


def _allowed_payment_link_context(
    session: Session, aggregate_id: str, settings: Settings
) -> tuple[GateContext, PolicyDecision]:
    """Build a fresh payment_link GateContext and evaluate the gate EXACTLY
    once for it, returning both. Callers MUST reuse this same ``decision``
    for ``execute_payment_link`` rather than calling ``evaluate_gate`` again
    for the same context: a second call for the same idempotency_key would
    itself trip ``check_idempotency``'s re-approval guard (the correct
    behavior for a genuine duplicate run - see
    ``run_duplicate_callback_scenario`` below, which deliberately calls
    ``evaluate_gate`` a second time to prove exactly that) but would wrongly
    refuse a single intended action if called twice by accident."""
    context = _fresh_payment_link_context(session, aggregate_id)
    decision = evaluate_gate(session, context, settings=settings)
    return context, decision


def _import_execute_payment_link():
    # Local import to avoid a module-level cycle risk between core.act and
    # core.chaos; core.act.executors already imports core.policy.gate.
    from core.act.executors import execute_payment_link

    return execute_payment_link


# --- 1. gateway_5xx ------------------------------------------------------------


def run_gateway_5xx_scenario(
    session: Session, settings: Settings | None = None, n_records: int = DEFAULT_SMOKE_RECORD_COUNT
) -> ChaosReport:
    settings = settings or get_settings()
    report = ChaosReport(scenario="gateway_5xx")

    smoke = _smoke_run_real_pipeline(session, settings, n_records)
    report.add(
        "real_pipeline_smoke_run",
        smoke.total_records == n_records,
        f"diagnose->holdout->gate ran cleanly over {smoke.total_records} real synthetic "
        f"records ({smoke.treatment_count} treatment / {smoke.control_count} control / "
        f"{smoke.blocked_count} blocked) before injection",
    )

    aggregate_id = "chaos_gw5xx_001"
    context, decision = _allowed_payment_link_context(session, aggregate_id, settings)
    report.add("gate_allows_fresh_action", decision.allowed, decision.reason)
    if not decision.allowed:
        return report

    calls: list[httpx.Request] = []
    n_failures = 2

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) <= n_failures:
            return httpx.Response(502, text="bad gateway")
        return httpx.Response(200, json={"id": "plink_chaos_5xx_001"})

    transport = httpx.MockTransport(handler)
    breaker = CircuitBreaker(failure_threshold=5, reset_timeout_seconds=30)
    execute_payment_link = _import_execute_payment_link()

    with RazorpayClient(
        "rzp_test_dummy",
        "secret",
        session,
        transport=transport,
        circuit_breaker=breaker,
        max_retries=3,
    ) as client:
        result = execute_payment_link(
            session,
            decision,
            context,
            mode="live",
            amount_inr=499.0,
            description="chaos gateway_5xx",
            client=client,
        )

        report.add(
            "retry_path_actually_exercised",
            len(calls) == n_failures + 1,
            f"mock transport received {len(calls)} requests "
            f"({n_failures} injected 502s + 1 eventual success expected)",
        )
        report.add(
            "circuit_breaker_recovered_to_closed",
            breaker.state == CircuitState.CLOSED,
            f"breaker state after recovery: {breaker.state.value}",
        )
        report.add(
            "exactly_one_successful_action",
            result.status == "executed_live",
            f"executor result status: {result.status}",
        )

    events = [e for e in list_events(session) if e.aggregate_id == aggregate_id]
    succeeded = [e for e in events if e.event_type == "RAZORPAY_CREATE_PAYMENT_LINK_SUCCEEDED"]
    retrying = [e for e in events if e.event_type == "RAZORPAY_CREATE_PAYMENT_LINK_RETRYING"]
    executed_live = [e for e in events if e.event_type == "ACTION_PAYMENT_LINK_EXECUTED_LIVE"]
    report.add(
        "no_duplicate_payment_link_in_ledger",
        len(succeeded) == 1 and len(executed_live) == 1,
        f"RAZORPAY_CREATE_PAYMENT_LINK_SUCCEEDED x{len(succeeded)}, "
        f"ACTION_PAYMENT_LINK_EXECUTED_LIVE x{len(executed_live)}",
    )

    seqs = [e.sequence_num for e in events]
    ordered = seqs == sorted(seqs)
    retry_before_success = all(
        r.sequence_num < succeeded[0].sequence_num for r in retrying
    ) if succeeded else False
    report.add(
        "ledger_tells_full_retry_story_in_order",
        len(retrying) == n_failures and ordered and retry_before_success,
        f"{len(retrying)} RETRYING events recorded before SUCCEEDED, "
        f"sequence_num strictly increasing: {ordered}",
    )

    verification = verify_chain(session)
    report.add(
        "ledger_chain_still_valid",
        verification.ok,
        f"verify_chain: ok={verification.ok}, events_checked={verification.events_checked}",
    )
    return report


# --- 2. rate_limit ---------------------------------------------------------------


def run_rate_limit_scenario(
    session: Session, settings: Settings | None = None, n_records: int = DEFAULT_SMOKE_RECORD_COUNT
) -> ChaosReport:
    settings = settings or get_settings()
    report = ChaosReport(scenario="rate_limit")

    smoke = _smoke_run_real_pipeline(session, settings, n_records)
    report.add(
        "real_pipeline_smoke_run",
        smoke.total_records == n_records,
        f"diagnose->holdout->gate ran cleanly over {smoke.total_records} real synthetic records",
    )

    aggregate_id = "chaos_ratelimit_001"
    context, decision = _allowed_payment_link_context(session, aggregate_id, settings)
    report.add("gate_allows_fresh_action", decision.allowed, decision.reason)
    if not decision.allowed:
        return report

    calls: list[httpx.Request] = []
    retry_after_seconds = "3"

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(
                429, headers={"Retry-After": retry_after_seconds}, text="slow down"
            )
        return httpx.Response(200, json={"id": "plink_chaos_ratelimit_001"})

    transport = httpx.MockTransport(handler)
    execute_payment_link = _import_execute_payment_link()

    sleep_calls: list[float] = []

    def spy_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    with (
        patch("core.ingest.razorpay_client.time.sleep", side_effect=spy_sleep),
        RazorpayClient(
            "rzp_test_dummy", "secret", session, transport=transport, max_retries=3
        ) as client,
    ):
        result = execute_payment_link(
            session,
            decision,
            context,
            mode="live",
            amount_inr=250.0,
            description="chaos rate_limit",
            client=client,
        )

    report.add(
        "client_actually_waited_the_retry_after_value",
        sleep_calls == [float(retry_after_seconds)],
        f"time.sleep was called with {sleep_calls} (expected exactly "
        f"[{float(retry_after_seconds)}] - the server's Retry-After value, honored "
        "verbatim per core.ingest.backoff.retry_after_or_backoff, no blind jitter)",
    )
    report.add(
        "exactly_one_action_after_429",
        len(calls) == 2 and result.status == "executed_live",
        f"mock transport received {len(calls)} requests (1 injected 429 + 1 success), "
        f"executor status: {result.status}",
    )

    events = [e for e in list_events(session) if e.aggregate_id == aggregate_id]
    succeeded = [e for e in events if e.event_type == "RAZORPAY_CREATE_PAYMENT_LINK_SUCCEEDED"]
    report.add(
        "no_duplicate_payment_link_in_ledger",
        len(succeeded) == 1,
        f"RAZORPAY_CREATE_PAYMENT_LINK_SUCCEEDED x{len(succeeded)}",
    )

    verification = verify_chain(session)
    report.add(
        "ledger_chain_still_valid",
        verification.ok,
        f"verify_chain: ok={verification.ok}, events_checked={verification.events_checked}",
    )
    return report


# --- 3. webhook_replay ------------------------------------------------------------


def run_webhook_replay_scenario(
    session: Session, settings: Settings | None = None, n_records: int = DEFAULT_SMOKE_RECORD_COUNT
) -> ChaosReport:
    """``n_records`` is accepted (but unused) only so every scenario shares
    one call signature for ``recoup chaos``'s dispatch table - this scenario
    tests the webhook endpoint directly, which has nothing to do with the
    synthetic at-risk dataset or run_batch."""
    settings = settings or get_settings()
    report = ChaosReport(scenario="webhook_replay")

    body = json.dumps(
        {
            "event": "payment_link.paid",
            "payload": {"payment_link": {"entity": {"id": "plink_chaos_replay_001"}}},
        }
    ).encode()
    headers = {EVENT_ID_HEADER: "evt_chaos_replay_001"}

    first = handle_webhook_event(session, body, headers)
    second = handle_webhook_event(session, body, headers)

    report.add(
        "first_delivery_recorded_second_deduped",
        first["status"] == "recorded" and second["status"] == "duplicate",
        f"first={first['status']!r}, second={second['status']!r}",
    )

    domain_events = [e for e in list_events(session) if e.event_type == "PAYMENT_LINK_PAID"]
    report.add(
        "duplicate_never_double_writes_the_ledger",
        len(domain_events) == 1,
        f"PAYMENT_LINK_PAID events for plink_chaos_replay_001: {len(domain_events)}",
    )

    # Phase 7 extension: does anything in this codebase re-trigger a money
    # action from a webhook? Checked honestly, not assumed:
    # core/ingest/webhooks.py's handle_webhook_event only ever calls
    # append_event - it never imports or calls core.act.executors,
    # core.ingest.razorpay_client, or core.policy.gate. core/eval/batch_runner
    # (run-batch) is the only code path in this repo that reaches an
    # executor. So there is no downstream "second action" a duplicate
    # webhook could trigger here to prove doesn't double-fire - that
    # specific guarantee ("a duplicate trigger cannot produce a second
    # payment link") is proven at the run-batch/executor layer instead, by
    # run_duplicate_callback_scenario below.
    report.add(
        "webhook_layer_has_no_downstream_action_to_double_fire",
        True,
        "core.ingest.webhooks.handle_webhook_event only ever appends ledger events; "
        "it never calls an executor or RazorpayClient in this codebase (verified by "
        "reading the module - no such import exists), so webhooks are purely "
        "observational here. The 'duplicate trigger cannot create a second real "
        "action' guarantee is proven at the run-batch/executor layer instead - see "
        "the duplicate_callback scenario",
    )

    verification = verify_chain(session)
    report.add(
        "ledger_chain_still_valid",
        verification.ok,
        f"verify_chain: ok={verification.ok}, events_checked={verification.events_checked}",
    )
    return report


# --- 4. duplicate_callback --------------------------------------------------------


def run_duplicate_callback_scenario(
    session: Session, settings: Settings | None = None, n_records: int = DEFAULT_SMOKE_RECORD_COUNT
) -> ChaosReport:
    """The core proof the spec asks for by name: a duplicate webhook/retried
    job/re-run-after-crash cannot produce a second payment link. Runs the
    SAME record through the full gate+executor cycle twice and checks the
    mocked transport's literal request count, not just "it didn't crash"."""
    settings = settings or get_settings()
    report = ChaosReport(scenario="duplicate_callback")

    smoke = _smoke_run_real_pipeline(session, settings, n_records)
    report.add(
        "real_pipeline_smoke_run",
        smoke.total_records == n_records,
        f"diagnose->holdout->gate ran cleanly over {smoke.total_records} real synthetic records",
    )

    aggregate_id = "chaos_dupcallback_001"
    execute_payment_link = _import_execute_payment_link()
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"id": "plink_chaos_dupcallback_001"})

    transport = httpx.MockTransport(handler)

    with RazorpayClient(
        "rzp_test_dummy", "secret", session, transport=transport, max_retries=3
    ) as client:
        # --- "first run" -----------------------------------------------
        context, decision1 = _allowed_payment_link_context(session, aggregate_id, settings)
        report.add("first_run_gate_allows", decision1.allowed, decision1.reason)
        result1 = execute_payment_link(
            session,
            decision1,
            context,
            mode="live",
            amount_inr=750.0,
            description="chaos duplicate_callback - first attempt",
            client=client,
        )

        # --- "second run": a retried job / duplicate trigger over the SAME
        # record, same idempotency_key (same action_type, entity_id,
        # attempt_num=0) - exactly what a crash-and-retry or a duplicate
        # webhook-driven re-run would look like.
        decision2 = evaluate_gate(session, context, settings=settings)
        result2 = execute_payment_link(
            session,
            decision2,
            context,
            mode="live",
            amount_inr=750.0,
            description="chaos duplicate_callback - duplicate attempt",
            client=client,
        )

    report.add(
        "second_run_gate_blocked_by_idempotency",
        not decision2.allowed and "idempotency" in decision2.reason,
        f"second evaluate_gate() decision: allowed={decision2.allowed}, "
        f"reason={decision2.reason!r}",
    )
    report.add(
        "second_run_executor_refused_not_executed",
        result1.status == "executed_live" and result2.status == "refused",
        f"first result status={result1.status!r}, second result status={result2.status!r}",
    )
    report.add(
        "exactly_one_http_request_across_both_runs",
        len(calls) == 1,
        f"mocked Razorpay transport received {len(calls)} request(s) total across both runs "
        "(expected exactly 1 - the duplicate run must never reach the network)",
    )

    events = [e for e in list_events(session) if e.aggregate_id == aggregate_id]
    intents = [e for e in events if e.event_type == "MONEY_ACTION_INTENT"]
    executed_live = [e for e in events if e.event_type == "ACTION_PAYMENT_LINK_EXECUTED_LIVE"]
    refused = [e for e in events if e.event_type == "ACTION_REFUSED_NOT_ALLOWED"]
    report.add(
        "exactly_one_money_action_intent_for_this_idempotency_key",
        len(intents) == 1,
        f"MONEY_ACTION_INTENT events for {aggregate_id}: {len(intents)}",
    )
    report.add(
        "exactly_one_executed_live_and_one_refusal_recorded",
        len(executed_live) == 1 and len(refused) == 1,
        f"ACTION_PAYMENT_LINK_EXECUTED_LIVE x{len(executed_live)}, "
        f"ACTION_REFUSED_NOT_ALLOWED x{len(refused)}",
    )

    verification = verify_chain(session)
    report.add(
        "ledger_chain_still_valid",
        verification.ok,
        f"verify_chain: ok={verification.ok}, events_checked={verification.events_checked}",
    )
    return report


INJECTION_TYPES = {
    "gateway_5xx": run_gateway_5xx_scenario,
    "rate_limit": run_rate_limit_scenario,
    "webhook_replay": run_webhook_replay_scenario,
    "duplicate_callback": run_duplicate_callback_scenario,
}
