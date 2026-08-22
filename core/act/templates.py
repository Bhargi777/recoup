"""Deterministic customer-facing message templates.

No LLM ever drafts or authorizes money-affecting content (CLAUDE.md SS4;
money-action-gate SKILL.md SS2: "LLM outputs ... are treated as untrusted
inputs"). Every string below is a plain Python f-string keyed by
``root_cause`` - fully reviewable at commit time, fully deterministic, zero
model calls, zero network calls.

Coverage is intentionally partial: a handful of root causes get a
specifically worded template; everything else falls back to
``_DEFAULT_REMINDER`` / ``_DEFAULT_INCENTIVE`` so every root cause in
``core.policy.schema.KNOWN_COHORTS``'s playbook set still gets a sensible,
non-empty message rather than a KeyError.
"""

from __future__ import annotations

_DEFAULT_REMINDER = (
    "Hi, your recent payment of Rs.{amount:.2f} did not go through. "
    "Please retry using the link we've sent, or reply if you need help."
)

REMINDER_TEMPLATES: dict[str, str] = {
    "card_expired": (
        "Hi, your recent payment of Rs.{amount:.2f} could not be completed because "
        "your card has expired. Please update your card details to complete payment."
    ),
    "incorrect_cvv": (
        "Hi, your recent payment of Rs.{amount:.2f} did not go through - the card "
        "security code entered did not match. Please try again with the correct CVV."
    ),
    "insufficient_funds": (
        "Hi, your recent payment of Rs.{amount:.2f} could not be completed due to "
        "insufficient balance. Please retry once funds are available."
    ),
    "abandonment": (
        "Hi, you were almost done! Complete your Rs.{amount:.2f} payment using the "
        "link below - it only takes a minute."
    ),
    "invoice_overdue": (
        "This is a reminder that an invoice of Rs.{amount:.2f} is now overdue. "
        "Please settle at your earliest convenience to avoid service disruption."
    ),
}

_DEFAULT_INCENTIVE = (
    "As a one-time gesture, we're offering Rs.{incentive_amount:.2f} off your "
    "Rs.{amount:.2f} payment if you complete it in the next 48 hours."
)

INCENTIVE_TEMPLATES: dict[str, str] = {
    "insufficient_funds": (
        "We understand timing can be tricky - here's Rs.{incentive_amount:.2f} off "
        "your Rs.{amount:.2f} payment if you complete it in the next 48 hours."
    ),
}

PRE_DEBIT_TEMPLATE = (
    "Notice: an automatic payment of Rs.{amount:.2f} is scheduled on or after "
    "{notice_hours:.0f} hours from now, per RBI e-mandate rules. Ensure sufficient "
    "balance is available, or manage your mandate in the app."
)


def reminder_message(root_cause: str, amount_inr: float) -> str:
    template = REMINDER_TEMPLATES.get(root_cause, _DEFAULT_REMINDER)
    return template.format(amount=amount_inr)


def incentive_message(
    root_cause: str, incentive_amount_inr: float, incentive_percent: float, amount_inr: float
) -> str:
    template = INCENTIVE_TEMPLATES.get(root_cause, _DEFAULT_INCENTIVE)
    effective_incentive = incentive_amount_inr if incentive_amount_inr > 0 else (
        amount_inr * incentive_percent / 100
    )
    return template.format(incentive_amount=effective_incentive, amount=amount_inr)


def pre_debit_notification_message(amount_inr: float, notice_hours: float) -> str:
    return PRE_DEBIT_TEMPLATE.format(amount=amount_inr, notice_hours=notice_hours)
