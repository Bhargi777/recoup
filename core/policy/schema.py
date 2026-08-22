"""Pydantic schema for policy playbooks.

Every YAML file under ``core/policy/playbooks/`` is validated against
``Playbook`` at load time (see ``core/policy/loader.py``). A malformed
playbook (missing field, wrong type, ceiling out of range, unknown cohort or
stopping rule) MUST fail loudly at load time - never silently no-op - per
CLAUDE.md SS4 (zero fabrication / honest failure) and the money-action-gate
skill's mandate that policy constraints are hard-coded and deterministic.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# The four cohorts a trigger_conditions.cohorts entry may reference. Sourced
# from core.ingest.synthetic.COHORTS - imported lazily inside the validator to
# avoid a hard import-time dependency cycle between policy and ingest.
KNOWN_COHORTS = frozenset(
    {
        "one_time_checkout_failure",
        "checkout_abandonment",
        "subscription_mandate_failure",
        "overdue_b2b_invoice",
    }
)

# Closed set of stopping-rule identifiers a playbook may declare. Kept small
# and enumerated deliberately - anything not in this set is a typo, not a new
# feature, and must fail validation rather than be silently ignored.
KNOWN_STOPPING_RULES = frozenset(
    {
        "already_paid",
        "invoice_settled",
        "max_attempts_reached",
        "customer_opted_out",
        "kill_switch_active",
    }
)

# Closed set of intervention-ladder step identifiers. "incentive_offer" is
# only valid on a step list belonging to a playbook whose incentive_ceiling
# value is > 0 - enforced by Playbook.check_incentive_step_requires_ceiling.
KNOWN_STEPS = frozenset(
    {
        "reminder_message",
        "payment_link",
        "incentive_offer",
        "pre_debit_notification",
        "mandate_retry",
        "escalate_to_human",
    }
)

_OFFSET_PATTERN = re.compile(r"^T\+\d+h?$")


class TriggerConditions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cohorts: list[str] = Field(min_length=1)

    @field_validator("cohorts")
    @classmethod
    def cohorts_known(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - KNOWN_COHORTS)
        if unknown:
            raise ValueError(f"unknown cohort(s) in trigger_conditions.cohorts: {unknown}")
        return value


class LadderStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: str
    offset: str
    channel: str | None = None
    notes: str | None = None

    @field_validator("step")
    @classmethod
    def step_known(cls, value: str) -> str:
        if value not in KNOWN_STEPS:
            raise ValueError(
                f"unknown intervention step {value!r}; must be one of {sorted(KNOWN_STEPS)}"
            )
        return value

    @field_validator("offset")
    @classmethod
    def offset_well_formed(cls, value: str) -> str:
        if not _OFFSET_PATTERN.match(value):
            raise ValueError(
                f"offset {value!r} must match 'T+<int>' or 'T+<int>h' (e.g. 'T+0', 'T+24h')"
            )
        return value


class IncentiveCeiling(BaseModel):
    """A hard per-action incentive cap. ``value`` is always >= 0.

    ``type: amount_inr`` caps the absolute rupee incentive; ``type: percent``
    caps it as a percentage of the payment/invoice amount. A ceiling of 0 (of
    either type) means "no incentive may ever be offered" - this is a real,
    enforced value, never a comment (money-action-gate skill: overdue_b2b_invoice
    MUST be 0%).
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["amount_inr", "percent"]
    value: float = Field(ge=0)

    @model_validator(mode="after")
    def percent_within_100(self) -> IncentiveCeiling:
        if self.type == "percent" and self.value > 100:
            raise ValueError("percent incentive_ceiling.value cannot exceed 100")
        return self


class Playbook(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root_cause: str
    trigger_conditions: TriggerConditions
    intervention_ladder: list[LadderStep] = Field(min_length=1)
    incentive_ceiling: IncentiveCeiling
    max_attempts: int = Field(ge=1, le=20)
    stopping_rules: list[str] = Field(min_length=1)

    @field_validator("stopping_rules")
    @classmethod
    def stopping_rules_known(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - KNOWN_STOPPING_RULES)
        if unknown:
            raise ValueError(f"unknown stopping_rule(s): {unknown}")
        return value

    @model_validator(mode="after")
    def incentive_step_requires_nonzero_ceiling(self) -> Playbook:
        has_incentive_step = any(
            step.step == "incentive_offer" for step in self.intervention_ladder
        )
        if has_incentive_step and self.incentive_ceiling.value <= 0:
            raise ValueError(
                f"{self.root_cause}: intervention_ladder includes 'incentive_offer' "
                "but incentive_ceiling.value is 0 - remove the step or raise the ceiling"
            )
        return self
