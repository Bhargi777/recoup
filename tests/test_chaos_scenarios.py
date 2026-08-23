"""Phase 7: one real pytest test per chaos injection type.

Each test checks the exact same guarantee the ``recoup chaos --inject``
CLI's report claims - literal mock-call counts and ledger-event counts, not
"it didn't crash". See core/chaos/scenarios.py's module docstring for what
is real (the diagnose->holdout->gate pipeline, RazorpayClient's real
retry/circuit-breaker path) versus injected (the HTTP failure itself, via
httpx.MockTransport - never real network).
"""

import pytest
from sqlmodel import Session

from core.chaos.scenarios import (
    run_duplicate_callback_scenario,
    run_gateway_5xx_scenario,
    run_rate_limit_scenario,
    run_webhook_replay_scenario,
)
from core.ledger import get_engine, init_ledger_schema, verify_chain


@pytest.fixture()
def session():
    engine = get_engine("sqlite:///:memory:")
    init_ledger_schema(engine)
    with Session(engine) as s:
        yield s


def _all_passed(report) -> str:
    """Full report text for a failed-assertion message, not just True/False."""
    return report.as_text()


def test_gateway_5xx_retries_then_succeeds_exactly_once(session: Session) -> None:
    report = run_gateway_5xx_scenario(session)
    assert report.ok, _all_passed(report)

    by_name = {c.name: c for c in report.checks}
    assert by_name["retry_path_actually_exercised"].passed
    assert by_name["circuit_breaker_recovered_to_closed"].passed
    assert by_name["no_duplicate_payment_link_in_ledger"].passed
    assert by_name["ledger_tells_full_retry_story_in_order"].passed
    assert by_name["ledger_chain_still_valid"].passed


def test_rate_limit_honors_retry_after_and_acts_exactly_once(session: Session) -> None:
    report = run_rate_limit_scenario(session)
    assert report.ok, _all_passed(report)

    by_name = {c.name: c for c in report.checks}
    assert by_name["client_actually_waited_the_retry_after_value"].passed
    assert by_name["exactly_one_action_after_429"].passed
    assert by_name["no_duplicate_payment_link_in_ledger"].passed


def test_webhook_replay_is_deduped_and_never_double_writes_ledger(session: Session) -> None:
    report = run_webhook_replay_scenario(session)
    assert report.ok, _all_passed(report)

    by_name = {c.name: c for c in report.checks}
    assert by_name["first_delivery_recorded_second_deduped"].passed
    assert by_name["duplicate_never_double_writes_the_ledger"].passed


def test_duplicate_callback_cannot_produce_a_second_payment_link(session: Session) -> None:
    """The literal guarantee the Phase 7 spec asks for by name: a duplicate
    webhook/retried job/re-run-after-crash cannot produce a second payment
    link. Checked via the mocked transport's actual request count, not an
    assumption."""
    report = run_duplicate_callback_scenario(session)
    assert report.ok, _all_passed(report)

    by_name = {c.name: c for c in report.checks}
    assert by_name["second_run_gate_blocked_by_idempotency"].passed
    assert by_name["second_run_executor_refused_not_executed"].passed
    assert by_name["exactly_one_http_request_across_both_runs"].passed
    assert by_name["exactly_one_money_action_intent_for_this_idempotency_key"].passed


def test_all_four_scenarios_share_one_database_without_seed_collision(session: Session) -> None:
    """recoup chaos can run multiple injection types back to back against the
    same database (proven here in-process); smoke-seeding must be
    idempotent across them - this is the real gap that was found and fixed
    while wiring this module up (see its module docstring)."""
    reports = [
        run_gateway_5xx_scenario(session),
        run_rate_limit_scenario(session),
        run_webhook_replay_scenario(session),
        run_duplicate_callback_scenario(session),
    ]
    for report in reports:
        assert report.ok, _all_passed(report)

    verification = verify_chain(session)
    assert verification.ok, verification.errors
