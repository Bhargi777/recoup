"""The input to ``evaluate_gate`` - everything a guardrail check needs to know
about one proposed money action, before any execution happens.

This module owns no state and calls nothing external; it is a plain data
container. All timestamps are timezone-aware UTC ``datetime`` objects -
guardrails convert to IST internally where the rule is IST-local (quiet
hours, NPCI peak hours).
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

IST = ZoneInfo("Asia/Kolkata")


class GateContext(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    # Idempotency (checklist #1).
    idempotency_key: str

    # Who/what this action is for. ``aggregate_id`` is the ledger aggregate
    # (payment/invoice/mandate id) that attempt counts, cooldowns, and
    # idempotency lookups are scoped to - matching
    # core.ledger.store.events_for_aggregate.
    aggregate_id: str
    customer_id: str
    cohort: str
    root_cause: str

    # What this action is (checklist #10's MONEY_ACTION_INTENT payload, and
    # what determines whether the incentive/RBI/NPCI checks even apply).
    action_type: str = Field(
        description="One of the KNOWN_STEPS identifiers in core.policy.schema, "
        "e.g. 'reminder_message', 'incentive_offer', 'mandate_retry'."
    )
    incentive_amount_inr: float = Field(default=0.0, ge=0)
    incentive_percent: float = Field(default=0.0, ge=0, le=100)

    # RBI/NPCI mandate-specific facts (checklist #7, #8). Only meaningful
    # when this action IS a mandate/UPI AutoPay debit attempt.
    is_emandate_debit: bool = False
    is_upi_autopay_execution: bool = False
    pre_debit_notification_sent_at: datetime | None = None

    # When this action would actually be dispatched/executed - what quiet
    # hours and NPCI peak-hour restrictions are evaluated against.
    proposed_action_at: datetime

    # Evaluation "now" - defaults to real UTC now but is overridable so tests
    # can exercise exact IST boundary instants deterministically.
    now: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("proposed_action_at", "now", "pre_debit_notification_sent_at")
    @classmethod
    def must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("datetime fields on GateContext must be timezone-aware")
        return value

    def proposed_action_at_ist(self) -> datetime:
        return self.proposed_action_at.astimezone(IST)
