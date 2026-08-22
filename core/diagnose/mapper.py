"""Deterministic error-code / cohort -> root-cause mapper (Phase 4 - Diagnosis).

This is the *first* and primary diagnosis path (CLAUDE.md SS4: "Root-cause
diagnosis uses a deterministic error-code mapper first (~80% coverage)").
Everything it can resolve, it resolves without ever calling an LLM.

The taxonomy is NOT reinvented here. It is imported directly from
``core.ingest.synthetic.ROOT_CAUSE_MAP`` - the exact same closed set of
root-cause labels the Phase 3 generator used to build ``true_root_cause``.
Importing (rather than copying) means the mapper and the generator can never
silently drift into two parallel taxonomies.

Source of truth for the mapping itself is
``.claude/skills/razorpay-testmode/SKILL.md`` SS5 (cards) and SS6 (UPI) - the
"recoup strategy" column there is what ``ROOT_CAUSE_MAP`` encodes as a root
cause label. SS7 lists banned/unverified codes that must never appear as a
key here; ``test_mapper.py`` asserts that directly.

The ``overdue_b2b_invoice`` cohort has no gateway error at all by design (see
synthetic.py's module docstring) - it is diagnosed by its own deterministic
cohort rule, not by falling through the error-reason table.
"""

from __future__ import annotations

from core.ingest.synthetic import COHORT_INVOICE, ROOT_CAUSE_MAP

# Re-exported so callers/tests have one place to import the mapping from
# without reaching into core.ingest.synthetic directly.
ERROR_REASON_TO_ROOT_CAUSE: dict[str, str] = ROOT_CAUSE_MAP

INVOICE_ROOT_CAUSE = "invoice_overdue"

# SKILL.md SS7 - codes that appeared in earlier drafts but could not be
# verified against official docs. They must never be mapper keys.
BANNED_ERROR_REASONS: frozenset[str] = frozenset(
    {
        "expired_card",
        "mandate_inactive",
        "amount_limit_exceeded",
        "bank_account_invalid",
        "network_failure",
    }
)


def map_cohort(cohort: str | None) -> str | None:
    """Cohort-level deterministic rule. Currently only the invoice cohort,
    which never has a gateway error to look up."""
    if cohort == COHORT_INVOICE:
        return INVOICE_ROOT_CAUSE
    return None


def map_error_reason(error_reason: str | None) -> str | None:
    """Look up a verified ``error.reason`` value in the closed taxonomy.

    Returns ``None`` if ``error_reason`` is missing or not in the verified
    catalog (i.e. the deterministic path could not resolve it) - callers are
    expected to fall through to the LLM path in that case.
    """
    if not error_reason:
        return None
    return ERROR_REASON_TO_ROOT_CAUSE.get(error_reason)


def deterministic_diagnose(
    cohort: str | None, error_code: str | None, error_reason: str | None
) -> str | None:
    """The full deterministic mapper: cohort rule first, then error-reason lookup.

    ``error_code`` is accepted for interface symmetry with the raw Razorpay
    error anatomy (SKILL.md SS2) but is not itself a lookup key here -
    ``error.reason`` is documented as "the primary join key for our
    deterministic mapper" and that's what synthetic.py's records key on too.
    """
    cohort_result = map_cohort(cohort)
    if cohort_result is not None:
        return cohort_result
    return map_error_reason(error_reason)
