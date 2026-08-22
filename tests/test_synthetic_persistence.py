"""Persistence + ledger-emission tests for the Phase 3 synthetic generator.

Every DB write must go through core.ledger.append_event - this file checks that
no insert happens silently, and that re-running the generator refuses to
silently double the dataset.
"""

import pytest
from sqlmodel import Session, select

from core.ingest.synthetic import (
    HOLDOUT_COUNT,
    TOTAL_RECORDS,
    AtRiskRecord,
    generate_records,
    init_synthetic_schema,
    persist_records,
    run_generation,
)
from core.ledger import get_engine, init_ledger_schema, list_events


@pytest.fixture()
def session():
    engine = get_engine("sqlite:///:memory:")
    init_ledger_schema(engine)
    init_synthetic_schema(engine)
    with Session(engine) as s:
        yield s


def test_persist_records_writes_all_rows(session: Session):
    records = generate_records(seed=42)
    persisted = persist_records(session, records)
    assert len(persisted) == TOTAL_RECORDS

    rows = session.exec(select(AtRiskRecord)).all()
    assert len(rows) == TOTAL_RECORDS


def test_persist_records_emits_one_ledger_event_per_insert(session: Session):
    records = generate_records(seed=42)
    persist_records(session, records)

    events = list_events(session)
    assert len(events) == TOTAL_RECORDS
    assert all(e.event_type == "SYNTHETIC_RECORD_INGESTED" for e in events)

    record_ids = {r["id"] for r in records}
    event_aggregate_ids = {e.aggregate_id for e in events}
    assert record_ids == event_aggregate_ids


def test_run_generation_populates_expected_counts(session: Session):
    result = run_generation(session, seed=42)
    assert result.skipped is False
    assert result.inserted == TOTAL_RECORDS
    assert result.held_out_count == HOLDOUT_COUNT
    assert sum(result.cohort_counts.values()) == TOTAL_RECORDS


def test_run_generation_refuses_to_duplicate_without_force(session: Session):
    first = run_generation(session, seed=42)
    second = run_generation(session, seed=42)

    assert first.skipped is False
    assert second.skipped is True
    assert second.inserted == 0

    rows = session.exec(select(AtRiskRecord)).all()
    assert len(rows) == TOTAL_RECORDS  # not doubled to 1200


def test_run_generation_with_force_resets_and_regenerates(session: Session):
    run_generation(session, seed=42)
    result = run_generation(session, seed=42, force=True)

    assert result.skipped is False
    assert result.inserted == TOTAL_RECORDS

    rows = session.exec(select(AtRiskRecord)).all()
    assert len(rows) == TOTAL_RECORDS  # still 600, not 1200
