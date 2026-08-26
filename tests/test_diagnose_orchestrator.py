"""Orchestrator tests (core/diagnose/diagnose.py): resolution order, ABSTAIN
paths, and the one-ledger-event-per-diagnosis invariant.
"""

from dataclasses import dataclass

import pytest
from sqlmodel import Session

from core.diagnose.diagnose import (
    DIAGNOSIS_ABSTAINED,
    DIAGNOSIS_COMPLETED,
    METHOD_ABSTAIN,
    METHOD_DETERMINISTIC,
    METHOD_LLM,
    diagnose,
)
from core.diagnose.llm_classifier import ClassificationResult, LLMUnavailableError
from core.ledger import get_engine, init_ledger_schema, list_events


@dataclass
class FakeRecord:
    id: str
    cohort: str | None
    error_code: str | None
    error_reason: str | None
    notes: str | None


@pytest.fixture()
def session():
    engine = get_engine("sqlite:///:memory:")
    init_ledger_schema(engine)
    with Session(engine) as s:
        yield s


def test_deterministic_hit_emits_diagnosis_completed(session: Session):
    record = FakeRecord(
        id="synth_x_0001",
        cohort="one_time_checkout_failure",
        error_code="BAD_REQUEST_ERROR",
        error_reason="card_expired",
        notes="One-time card checkout failed: card_expired.",
    )
    result = diagnose(session, record)

    assert result.predicted_root_cause == "card_expired"
    assert result.method == METHOD_DETERMINISTIC

    events = list_events(session)
    assert len(events) == 1
    assert events[0].event_type == DIAGNOSIS_COMPLETED
    assert events[0].aggregate_id == "synth_x_0001"


def test_invoice_cohort_resolves_deterministically_not_abstain(session: Session):
    record = FakeRecord(
        id="synth_inv_0001",
        cohort="overdue_b2b_invoice",
        error_code=None,
        error_reason=None,
        notes="B2B invoice overdue by 40 days; no gateway attempt made.",
    )
    result = diagnose(session, record)

    assert result.predicted_root_cause == "invoice_overdue"
    assert result.method == METHOD_DETERMINISTIC


def test_no_deterministic_match_and_no_free_text_abstains(session: Session):
    record = FakeRecord(
        id="synth_amb_0001", cohort=None, error_code=None, error_reason=None, notes=None
    )
    result = diagnose(session, record)

    assert result.predicted_root_cause is None
    assert result.method == METHOD_ABSTAIN

    events = list_events(session)
    assert len(events) == 1
    assert events[0].event_type == DIAGNOSIS_ABSTAINED


def test_llm_fallback_used_when_deterministic_mapper_has_no_match(session: Session):
    record = FakeRecord(
        id="synth_amb_0002",
        cohort=None,
        error_code=None,
        error_reason=None,
        notes="customer says the mandate was cancelled by their bank",
    )

    def fake_classify(free_text: str) -> ClassificationResult:
        assert "mandate" in free_text
        return ClassificationResult(
            predicted_root_cause="mandate_cancelled", confidence=0.9, abstained=False
        )

    result = diagnose(session, record, classify_fn=fake_classify)

    assert result.method == METHOD_LLM
    assert result.predicted_root_cause == "mandate_cancelled"
    assert result.confidence == 0.9

    events = list_events(session)
    assert len(events) == 1
    assert events[0].event_type == DIAGNOSIS_COMPLETED


def test_llm_low_confidence_abstains(session: Session):
    record = FakeRecord(
        id="synth_amb_0003",
        cohort=None,
        error_code=None,
        error_reason=None,
        notes="ambiguous free text reason",
    )

    def fake_classify(free_text: str) -> ClassificationResult:
        return ClassificationResult(predicted_root_cause=None, confidence=0.5, abstained=True)

    result = diagnose(session, record, classify_fn=fake_classify)

    assert result.method == METHOD_ABSTAIN
    assert result.predicted_root_cause is None
    assert result.confidence == 0.5

    events = list_events(session)
    assert len(events) == 1
    assert events[0].event_type == DIAGNOSIS_ABSTAINED


def test_llm_unavailable_error_routes_to_abstain_not_a_crash(session: Session):
    record = FakeRecord(
        id="synth_amb_0004",
        cohort=None,
        error_code=None,
        error_reason=None,
        notes="ambiguous free text reason",
    )

    def raising_classify(free_text: str) -> ClassificationResult:
        raise LLMUnavailableError("no key configured")

    result = diagnose(session, record, classify_fn=raising_classify)

    assert result.method == METHOD_ABSTAIN
    assert result.predicted_root_cause is None

    events = list_events(session)
    assert len(events) == 1
    assert events[0].event_type == DIAGNOSIS_ABSTAINED


def test_every_diagnose_call_emits_exactly_one_ledger_event(session: Session):
    records = [
        FakeRecord("a", "one_time_checkout_failure", "BAD_REQUEST_ERROR", "card_expired", "n"),
        FakeRecord("b", "overdue_b2b_invoice", None, None, "n"),
        FakeRecord("c", None, None, None, None),
    ]
    for record in records:
        diagnose(session, record)

    events = list_events(session)
    assert len(events) == 3
    assert {e.aggregate_id for e in events} == {"a", "b", "c"}
