"""SIMULATED PAYMENT-RECOVERY OUTCOME MODEL - NOT OBSERVED REAL PAYMENT
BEHAVIOR.

THIS MODULE IS A LABELED SIMULATION, built to exercise the holdout + uplift
+ Wilson-CI STATISTICAL PIPELINE end to end (core.experiment.holdout,
core.experiment.uplift/stats) because this environment has no real Razorpay
test-mode credentials and no real customer payment behavior to observe
(confirmed absent since Phase 2). It answers "did this customer recover"
with a deterministic coin flip drawn from an assumed model, NOT a fact about
any real payment. Nothing here is a claim that any of these 600 synthetic
customers actually paid.

Every caller that records a value from this module MUST tag the resulting
ledger event with ``outcome_source: "simulated"`` (mirroring the
``source: "synthetic"`` field Phase 3's ``core.ingest.synthetic`` already
established for input data) - see ``core.eval.batch_runner``. This is not
fabrication: fabrication would be presenting this number as real recovered
revenue. What this module implements is a correctly-built statistical
mechanism exercised against synthetic, clearly labeled inputs, exactly like
Phase 3's synthetic data and Phase 4's synthetic held-out eval.

Design
------
``simulated_outcome`` is a pure, deterministic function of
``(record_id, root_cause, group, seed)`` via SHA-256 - the same inputs
always produce the same outcome, so re-running a batch never reshuffles who
"recovered" (same determinism contract as ``core.experiment.holdout``).

``BASELINE_RECOVERY_RATE`` is a per-root_cause probability that a customer
self-cures with NO intervention at all (i.e. the control arm's expected
rate) - illustrative values chosen to be directionally plausible (technical/
gateway failures are transient and self-resolve more often; risk-blocked
payments almost never do) but NOT derived from any real dataset.

``TREATMENT_UPLIFT_PP`` is a flat +8 percentage-point bump applied only to
the treatment arm - an illustrative assumed effect size (dunning/recovery-
messaging literature broadly reports mid-single- to low-double-digit
percentage-point uplifts), again NOT derived from any real observation in
this project. Changing either constant only changes the demo's simulated
numbers; it never changes what is claimed as real.
"""

from __future__ import annotations

import hashlib

from core.experiment.holdout import Group

# Illustrative, NOT measured. See module docstring.
BASELINE_RECOVERY_RATE: dict[str, float] = {
    "card_expired": 0.30,
    "incorrect_cvv": 0.45,
    "card_not_enabled_online": 0.25,
    "card_blocked": 0.15,
    "insufficient_funds": 0.35,
    "limit_exceeded": 0.30,
    "authentication_failed": 0.40,
    "abandonment": 0.20,
    "risk_blocked": 0.10,
    "card_declined_generic": 0.25,
    "bank_technical_error": 0.50,
    "gateway_technical_error": 0.50,
    "invalid_vpa": 0.20,
    "vpa_resolution_failed": 0.30,
    "credit_failed": 0.35,
    "invoice_overdue": 0.20,
}
_DEFAULT_BASELINE_RATE = 0.30

# Illustrative, NOT measured. See module docstring.
TREATMENT_UPLIFT_PP = 0.08


def baseline_recovery_rate(root_cause: str) -> float:
    return BASELINE_RECOVERY_RATE.get(root_cause, _DEFAULT_BASELINE_RATE)


def simulated_outcome(record_id: str, root_cause: str, group: Group, seed: int) -> bool:
    """Deterministically simulate whether one record "recovered".

    Pure function of (record_id, root_cause, group, seed) - no I/O, no
    reliance on call order. Draws a uniform value in [0, 1) from SHA-256 of
    the inputs and compares it against the assumed recovery probability for
    this root cause and group (baseline, plus the treatment uplift if this
    record is in the treatment arm).
    """
    probability = baseline_recovery_rate(root_cause)
    if group == "treatment":
        probability += TREATMENT_UPLIFT_PP
    probability = min(max(probability, 0.0), 1.0)

    digest = hashlib.sha256(f"outcome:{seed}:{record_id}:{group}".encode("utf-8")).hexdigest()
    draw = int(digest[:8], 16) / 0xFFFFFFFF
    return draw < probability
