"""Versioned YAML playbooks, guardrails, quiet hours, budget meter, kill switch.

Public surface: ``evaluate_gate`` (the only function allowed to decide
ALLOW/DENY for a money action), ``GateContext`` (its input), and the kill
switch helpers. See ``.claude/skills/money-action-gate/SKILL.md``.
"""

from core.policy.context import GateContext
from core.policy.gate import PolicyDecision, PolicyEngineError, evaluate_gate
from core.policy.guardrails import GateResult
from core.policy.kill_switch import (
    activate_kill_switch,
    deactivate_kill_switch,
    is_kill_switch_active,
)
from core.policy.loader import PlaybookLoadError, load_playbooks, validate_taxonomy_completeness
from core.policy.schema import Playbook

__all__ = [
    "GateContext",
    "GateResult",
    "Playbook",
    "PlaybookLoadError",
    "PolicyDecision",
    "PolicyEngineError",
    "activate_kill_switch",
    "deactivate_kill_switch",
    "evaluate_gate",
    "is_kill_switch_active",
    "load_playbooks",
    "validate_taxonomy_completeness",
]
