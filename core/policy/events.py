"""Ledger event-type constants owned by the policy engine.

Per the audit-ledger state-replay contract, the kill switch and the budget
meter are NOT separate mutable tables - their current state/value is always
whatever ``replay`` computes from these event types. See
``core/policy/kill_switch.py`` and ``core/policy/budget.py``.
"""

# Emitted by evaluate_gate for every one of the 10 individual checks, pass or
# fail (money-action-gate SKILL.md: "Every gate decision - allow AND deny -
# goes to the ledger with a reason string").
POLICY_GATE_EVALUATED = "POLICY_GATE_EVALUATED"

# Emitted once per evaluate_gate call: the overall ALLOW/DENY outcome.
POLICY_GATE_DECISION = "POLICY_GATE_DECISION"

# Checklist item #10: the pre-action intent record, emitted BEFORE
# evaluate_gate returns ALLOW to its caller. Also doubles as the replay
# source for idempotency (#1), attempt counts (#4), and cooldown (#5), so
# there is exactly one append-only source of truth for "an action was
# approved here" instead of a parallel mutable table.
MONEY_ACTION_INTENT = "MONEY_ACTION_INTENT"

# Budget meter (checklist #2, #3): amount committed by one ALLOWed,
# incentive-bearing action. Global spend = sum of payload["amount_inr"]
# across all such events; cohort spend = the same sum filtered by
# payload["cohort"].
INCENTIVE_COMMITTED = "INCENTIVE_COMMITTED"

# Kill switch (checklist #9): current state is whichever of these two event
# types has the highest sequence_num. No separate "is_active" table exists.
KILL_SWITCH_ACTIVATED = "KILL_SWITCH_ACTIVATED"
KILL_SWITCH_DEACTIVATED = "KILL_SWITCH_DEACTIVATED"

# Aggregate id used for kill-switch events, which are global/system-wide
# rather than scoped to one customer or payment.
KILL_SWITCH_AGGREGATE_ID = "system:kill_switch"
