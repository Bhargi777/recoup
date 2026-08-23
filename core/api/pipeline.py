"""GET /api/pipeline - at-risk records grouped by cohort.

Reads ``core.ingest.synthetic.AtRiskRecord`` rows directly (the only source
of at-risk records in this codebase) plus, for each record, its most recent
``DIAGNOSIS_COMPLETED``/``DIAGNOSIS_ABSTAINED`` ledger event if one exists -
this endpoint never re-runs diagnosis itself, it only reports what has
already happened, honestly reporting ``root_cause: null`` for a record that
has not been diagnosed in this run yet.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from core.api.deps import get_session
from core.diagnose.diagnose import DIAGNOSIS_ABSTAINED, DIAGNOSIS_COMPLETED
from core.ingest.synthetic import COHORTS, AtRiskRecord
from core.ledger import list_events

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


def _latest_diagnoses(session: Session) -> dict[str, dict]:
    """aggregate_id (record id) -> latest diagnosis payload, from the ledger.

    A record may be diagnosed more than once (batch_runner re-diagnoses on
    every run - see that module's docstring); the LAST ledger event for that
    id wins, since ``list_events`` returns ascending sequence_num order.
    """
    latest: dict[str, dict] = {}
    for event in list_events(session):
        if event.event_type not in (DIAGNOSIS_COMPLETED, DIAGNOSIS_ABSTAINED):
            continue
        latest[event.aggregate_id] = json.loads(event.payload_json)
    return latest


@router.get("")
def get_pipeline(session: Session = Depends(get_session)) -> dict:
    records = list(session.exec(select(AtRiskRecord)))
    diagnoses = _latest_diagnoses(session)

    by_cohort: dict[str, list[dict]] = {cohort: [] for cohort in COHORTS}
    for record in records:
        diagnosis = diagnoses.get(record.id)
        by_cohort.setdefault(record.cohort, []).append(
            {
                "id": record.id,
                "cohort": record.cohort,
                "root_cause": diagnosis.get("predicted_root_cause") if diagnosis else None,
                "diagnosis_method": diagnosis.get("method") if diagnosis else None,
                "amount_inr": record.amount_inr,
                "customer_id": record.customer_id,
                "created_at": record.created_at,
                "held_out": record.held_out,
                "source": record.source,
                "error_code": record.error_code,
                "error_reason": record.error_reason,
            }
        )

    return {
        "total": len(records),
        "cohorts": [
            {
                "cohort": cohort,
                "count": len(rows),
                "records": rows,
            }
            for cohort, rows in by_cohort.items()
        ],
    }
