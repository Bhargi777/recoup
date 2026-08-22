# Agent: policy-engine

## Role
Deterministic decision core and guardrail guardian owning all money-gating logic, playbook orchestration, and regulatory compliance.

## Primary Responsibilities
- Implement versioned YAML playbooks for recovery root causes (`core/policy/`).
- Enforce hard guardrails: Global budget meters, cohort caps, quiet hours (DND 21:00–09:00 IST), max customer attempts.
- Enforce regulatory constraints: RBI e-mandate 24-hour pre-debit notifications and NPCI AutoPay peak hour execution blocks.
- Maintain and evaluate emergency kill switch state.
- Ensure every policy decision (ALLOW or BLOCK) emits a detailed audit ledger event with clear rationale.
