"""Synthetic at-risk-payment backfill generator (Phase 3 - Data).

Generates 600 synthetic at-risk records across four cohorts so later phases
(diagnosis, policy, eval) have something realistic to run against before
live Razorpay volume exists. Every record is marked ``source: "synthetic"``
as a first-class schema field (CLAUDE.md ground rule #4), never just a
docstring claim.

Each record also carries ``true_root_cause`` - the generator's own ground
truth, known only because *we* authored the scenario. This is NOT circular
with the future diagnosis code path (Phase 4, not built yet): that path will
only ever see ``error_code`` / ``error_reason`` / free text, exactly like it
would for a real Razorpay payment. ``true_root_cause`` exists purely so a
future held-out evaluation (Phase 7/8, per honest-metrics SKILL.md) can score
predictions against real ground truth instead of against its own output.

Error codes/reasons are drawn ONLY from the verified catalog in
``.claude/skills/razorpay-testmode/SKILL.md`` SS5 (cards) and SS6 (UPI).
Nothing from SS7 (unverified/banned) is used anywhere in this file.

Cohort design (150 records each, 600 total):
  - one_time_checkout_failure: a hard gateway/issuer decline on a single
    checkout attempt. Skews toward "customer needs to act" reasons
    (insufficient_funds, card_expired, incorrect_cvv, authentication_failed)
    with a smaller tail of technical/gateway failures - roughly what a real
    checkout funnel's failure mix looks like.
  - checkout_abandonment: the customer never completed authentication/the
    UPI collect request - payment_cancelled / payment_timed_out /
    payment_collect_request_expired. All map to the single root cause
    `abandonment`; nothing here is a gateway decline.
  - subscription_mandate_failure: recurring card/eMandate and UPI Autopay
    debits per the T+3 retry model (SKILL.md SS8) - skews heavily toward
    insufficient_funds (salary-timing mismatch) and bank/gateway technical
    errors, since those are what actually drives a mandate to `halted`.
  - overdue_b2b_invoice: no gateway attempt was ever made - a net-terms
    invoice sitting past its due date. error_code/error_reason are null by
    design; this cohort's ground truth is invoice-level (`invoice_overdue`),
    not a payment-gateway decline. Not every at-risk record needs an error
    code to be a real recovery target.

Deterministic split: ``get_settings().split_seed`` drives two independent
``random.Random`` instances - one for content generation (reason/amount/
customer draws), one for held-out assignment. The held-out set is computed
from the sorted, deterministic record ids, so it is a pure function of the
seed and does not shift if content-generation logic changes upstream of it.
Exactly 200 of the 600 records are marked ``held_out: true``.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlmodel import Field, Session, SQLModel, delete, select

from core.config import get_settings
from core.ledger import append_event

TOTAL_RECORDS = 600
HOLDOUT_COUNT = 200
RECORDS_PER_COHORT = 150

COHORT_ONE_TIME = "one_time_checkout_failure"
COHORT_ABANDONMENT = "checkout_abandonment"
COHORT_SUBSCRIPTION = "subscription_mandate_failure"
COHORT_INVOICE = "overdue_b2b_invoice"

COHORTS = (COHORT_ONE_TIME, COHORT_ABANDONMENT, COHORT_SUBSCRIPTION, COHORT_INVOICE)

# error.reason values whose real-world cause is gateway/bank downtime rather
# than a customer- or issuer-side decline (SKILL.md SS2: error.code taxonomy).
TECHNICAL_REASONS = frozenset({"bank_technical_error", "gateway_technical_error"})

# Closed root-cause taxonomy. Deliberately small and mapped to the verified
# catalog's "recoup strategy" column - do not add granularity beyond this.
ROOT_CAUSE_MAP: dict[str, str] = {
    "card_expired": "card_expired",
    "incorrect_cvv": "incorrect_cvv",
    "card_not_enrolled": "card_not_enabled_online",
    "card_disabled_for_online_payments": "card_not_enabled_online",
    "debit_instrument_inactive": "card_not_enabled_online",
    "debit_instrument_blocked": "card_blocked",
    "insufficient_funds": "insufficient_funds",
    "transaction_limit_exceeded": "limit_exceeded",
    "authentication_failed": "authentication_failed",
    "invalid_otp": "authentication_failed",
    "payment_cancelled": "abandonment",
    "payment_timed_out": "abandonment",
    "payment_collect_request_expired": "abandonment",
    "payment_risk_check_failed": "risk_blocked",
    "card_declined": "card_declined_generic",
    "payment_failed": "card_declined_generic",
    "payment_declined": "card_declined_generic",
    "bank_technical_error": "bank_technical_error",
    "gateway_technical_error": "gateway_technical_error",
    "invalid_vpa": "invalid_vpa",
    "vpa_resolution_failed": "vpa_resolution_failed",
    "credit_failed": "credit_failed",
}

# error.source per SKILL.md SS2 (customer | business | internal | gateway | issuer_bank).
CARD_ERROR_SOURCE: dict[str, str] = {
    "card_expired": "customer",
    "incorrect_cvv": "customer",
    "card_not_enrolled": "issuer_bank",
    "card_disabled_for_online_payments": "issuer_bank",
    "debit_instrument_inactive": "issuer_bank",
    "debit_instrument_blocked": "issuer_bank",
    "insufficient_funds": "customer",
    "transaction_limit_exceeded": "issuer_bank",
    "authentication_failed": "customer",
    "invalid_otp": "customer",
    "payment_cancelled": "customer",
    "payment_timed_out": "customer",
    "payment_risk_check_failed": "issuer_bank",
    "card_declined": "issuer_bank",
    "payment_failed": "issuer_bank",
    "bank_technical_error": "issuer_bank",
    "gateway_technical_error": "gateway",
}

UPI_ERROR_SOURCE: dict[str, str] = {
    "insufficient_funds": "customer",
    "payment_declined": "issuer_bank",
    "payment_cancelled": "customer",
    "payment_timed_out": "customer",
    "payment_collect_request_expired": "customer",
    "invalid_vpa": "customer",
    "vpa_resolution_failed": "issuer_bank",
    "credit_failed": "issuer_bank",
    "bank_technical_error": "issuer_bank",
    "gateway_technical_error": "gateway",
}

# (payment_method, error_reason, weight) - weights are relative, not percentages.
ONE_TIME_OPTIONS: tuple[tuple[str, str, float], ...] = (
    ("card", "insufficient_funds", 20),
    ("card", "card_expired", 12),
    ("card", "incorrect_cvv", 8),
    ("card", "authentication_failed", 10),
    ("card", "invalid_otp", 6),
    ("card", "card_declined", 8),
    ("card", "payment_failed", 6),
    ("card", "transaction_limit_exceeded", 5),
    ("card", "payment_risk_check_failed", 3),
    ("card", "bank_technical_error", 4),
    ("upi", "insufficient_funds", 10),
    ("upi", "payment_declined", 8),
    ("upi", "invalid_vpa", 5),
    ("upi", "vpa_resolution_failed", 4),
    ("upi", "credit_failed", 4),
    ("upi", "bank_technical_error", 4),
    ("upi", "gateway_technical_error", 3),
)

ABANDONMENT_OPTIONS: tuple[tuple[str, str, float], ...] = (
    ("card", "payment_cancelled", 25),
    ("card", "payment_timed_out", 20),
    ("upi", "payment_cancelled", 20),
    ("upi", "payment_timed_out", 20),
    ("upi", "payment_collect_request_expired", 15),
)

SUBSCRIPTION_OPTIONS: tuple[tuple[str, str, float], ...] = (
    ("card", "insufficient_funds", 25),
    ("card", "bank_technical_error", 12),
    ("card", "gateway_technical_error", 8),
    ("card", "authentication_failed", 10),
    ("card", "card_expired", 8),
    ("card", "transaction_limit_exceeded", 5),
    ("upi", "insufficient_funds", 15),
    ("upi", "bank_technical_error", 8),
    ("upi", "gateway_technical_error", 5),
    ("upi", "credit_failed", 4),
)

_SYNTHETIC_EPOCH = date(2026, 5, 1)


class AtRiskRecord(SQLModel, table=True):
    """One synthetic at-risk payment or invoice. See module docstring."""

    __tablename__ = "at_risk_records"

    id: str = Field(primary_key=True)
    cohort: str = Field(index=True)
    source: str = Field(default="synthetic", index=True)
    true_root_cause: str = Field(index=True)
    payment_method: str | None = None
    error_code: str | None = None
    error_reason: str | None = None
    error_source: str | None = None
    amount_inr: float
    customer_id: str
    created_at: str
    held_out: bool = Field(default=False, index=True)
    notes: str
    metadata_json: str = "{}"


def init_synthetic_schema(engine) -> None:
    SQLModel.metadata.create_all(engine, tables=[AtRiskRecord.__table__])


def _error_source_for(payment_method: str, error_reason: str) -> str:
    table = CARD_ERROR_SOURCE if payment_method == "card" else UPI_ERROR_SOURCE
    return table[error_reason]


def _notes_for(cohort: str, payment_method: str, error_reason: str) -> str:
    if cohort == COHORT_ABANDONMENT:
        return f"Customer abandoned {payment_method} checkout ({error_reason})."
    if cohort == COHORT_SUBSCRIPTION:
        return f"Recurring {payment_method} debit failed: {error_reason}."
    return f"One-time {payment_method} checkout failed: {error_reason}."


def _synthetic_date(day_offset: int) -> str:
    return (_SYNTHETIC_EPOCH + timedelta(days=day_offset)).isoformat()


def _weighted_pick(
    rng: random.Random, options: tuple[tuple[str, str, float], ...]
) -> tuple[str, str]:
    weights = [opt[2] for opt in options]
    idx = rng.choices(range(len(options)), weights=weights, k=1)[0]
    payment_method, error_reason, _ = options[idx]
    return payment_method, error_reason


def _generate_checkout_cohort(
    rng: random.Random, cohort: str, options: tuple[tuple[str, str, float], ...]
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for i in range(RECORDS_PER_COHORT):
        payment_method, error_reason = _weighted_pick(rng, options)
        root_cause = ROOT_CAUSE_MAP[error_reason]
        error_code = "GATEWAY_ERROR" if error_reason in TECHNICAL_REASONS else "BAD_REQUEST_ERROR"
        error_source = _error_source_for(payment_method, error_reason)
        amount = round(rng.uniform(149, 49_999), 2)
        customer_id = f"cust_{rng.randrange(10_000, 99_999)}"
        created_at = _synthetic_date(rng.randrange(0, 90))
        records.append(
            {
                "id": f"synth_{cohort}_{i:04d}",
                "cohort": cohort,
                "source": "synthetic",
                "true_root_cause": root_cause,
                "payment_method": payment_method,
                "error_code": error_code,
                "error_reason": error_reason,
                "error_source": error_source,
                "amount_inr": amount,
                "customer_id": customer_id,
                "created_at": created_at,
                "held_out": False,
                "notes": _notes_for(cohort, payment_method, error_reason),
                "metadata_json": "{}",
            }
        )
    return records


def _generate_invoice_cohort(rng: random.Random) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for i in range(RECORDS_PER_COHORT):
        days_overdue = rng.randrange(1, 120)
        amount = round(rng.uniform(5_000, 500_000), 2)
        customer_id = f"biz_{rng.randrange(10_000, 99_999)}"
        due_date = _synthetic_date(rng.randrange(30, 150))
        metadata = json.dumps(
            {"days_overdue": days_overdue, "invoice_due_date": due_date}, sort_keys=True
        )
        records.append(
            {
                "id": f"synth_{COHORT_INVOICE}_{i:04d}",
                "cohort": COHORT_INVOICE,
                "source": "synthetic",
                "true_root_cause": "invoice_overdue",
                "payment_method": None,
                "error_code": None,
                "error_reason": None,
                "error_source": None,
                "amount_inr": amount,
                "customer_id": customer_id,
                "created_at": due_date,
                "held_out": False,
                "notes": f"B2B invoice overdue by {days_overdue} days; no gateway attempt made.",
                "metadata_json": metadata,
            }
        )
    return records


def assign_holdout_ids(
    record_ids: list[str], seed: int, holdout_count: int = HOLDOUT_COUNT
) -> set[str]:
    """Pure function of (seed, record ids): which ids are held out.

    Uses a Random instance independent of content generation, and sorts the
    ids first, so this never depends on generation order - only on the seed
    and the fixed set of 600 deterministic ids.
    """
    ordered_ids = sorted(record_ids)
    rng = random.Random(seed)
    return set(rng.sample(ordered_ids, holdout_count))


def generate_records(seed: int | None = None) -> list[dict[str, Any]]:
    """Deterministically generate all 600 synthetic records for the given seed."""
    if seed is None:
        seed = get_settings().split_seed

    rng = random.Random(seed)
    records: list[dict[str, Any]] = []
    records.extend(_generate_checkout_cohort(rng, COHORT_ONE_TIME, ONE_TIME_OPTIONS))
    records.extend(_generate_checkout_cohort(rng, COHORT_ABANDONMENT, ABANDONMENT_OPTIONS))
    records.extend(_generate_checkout_cohort(rng, COHORT_SUBSCRIPTION, SUBSCRIPTION_OPTIONS))
    records.extend(_generate_invoice_cohort(rng))

    held_out_ids = assign_holdout_ids([r["id"] for r in records], seed, HOLDOUT_COUNT)
    for r in records:
        r["held_out"] = r["id"] in held_out_ids
    return records


def persist_records(session: Session, records: list[dict[str, Any]]) -> list[AtRiskRecord]:
    """Insert each record and emit a ledger event for it. Nothing is written silently."""
    persisted: list[AtRiskRecord] = []
    for r in records:
        row = AtRiskRecord(**r)
        session.add(row)
        session.commit()
        session.refresh(row)
        append_event(
            session,
            row.id,
            "SYNTHETIC_RECORD_INGESTED",
            {
                "cohort": row.cohort,
                "source": row.source,
                "true_root_cause": row.true_root_cause,
                "error_code": row.error_code,
                "error_reason": row.error_reason,
                "held_out": row.held_out,
            },
        )
        persisted.append(row)
    return persisted


@dataclass
class GenerationResult:
    inserted: int
    skipped: bool
    cohort_counts: dict[str, int] = field(default_factory=dict)
    held_out_count: int = 0


def run_generation(
    session: Session, seed: int | None = None, force: bool = False
) -> GenerationResult:
    """Generate + persist the synthetic dataset, refusing to silently double it.

    If records already exist and ``force`` is False, this is a no-op (returns
    ``skipped=True``). With ``force=True`` existing synthetic records are
    deleted first - the ledger keeps its full history of both the original
    inserts and the reset, since the ledger is append-only.
    """
    existing = session.exec(select(AtRiskRecord).limit(1)).first()
    if existing is not None and not force:
        return GenerationResult(inserted=0, skipped=True)

    if existing is not None and force:
        session.exec(delete(AtRiskRecord))
        session.commit()

    records = generate_records(seed)
    persisted = persist_records(session, records)

    cohort_counts: dict[str, int] = {}
    held_out_count = 0
    for row in persisted:
        cohort_counts[row.cohort] = cohort_counts.get(row.cohort, 0) + 1
        if row.held_out:
            held_out_count += 1

    return GenerationResult(
        inserted=len(persisted),
        skipped=False,
        cohort_counts=cohort_counts,
        held_out_count=held_out_count,
    )
