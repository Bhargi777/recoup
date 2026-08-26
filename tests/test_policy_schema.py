"""Playbook schema validation and taxonomy completeness."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from core.diagnose.mapper import ERROR_REASON_TO_ROOT_CAUSE, INVOICE_ROOT_CAUSE
from core.policy.loader import PlaybookLoadError, load_playbooks, validate_taxonomy_completeness
from core.policy.schema import IncentiveCeiling, LadderStep, Playbook, TriggerConditions

TAXONOMY = set(ERROR_REASON_TO_ROOT_CAUSE.values()) | {INVOICE_ROOT_CAUSE}

VALID_PLAYBOOK = {
    "root_cause": "card_expired",
    "trigger_conditions": {"cohorts": ["one_time_checkout_failure"]},
    "intervention_ladder": [{"step": "reminder_message", "offset": "T+0"}],
    "incentive_ceiling": {"type": "amount_inr", "value": 0},
    "max_attempts": 3,
    "stopping_rules": ["already_paid", "max_attempts_reached"],
}


def _copy_with(**overrides):
    data = {**VALID_PLAYBOOK, **overrides}
    return data


def test_valid_playbook_parses() -> None:
    playbook = Playbook.model_validate(VALID_PLAYBOOK)
    assert playbook.root_cause == "card_expired"
    assert playbook.incentive_ceiling.value == 0


def test_missing_required_field_fails_loudly() -> None:
    data = {k: v for k, v in VALID_PLAYBOOK.items() if k != "max_attempts"}
    with pytest.raises(ValidationError):
        Playbook.model_validate(data)


def test_unknown_cohort_fails() -> None:
    data = _copy_with(trigger_conditions={"cohorts": ["not_a_real_cohort"]})
    with pytest.raises(ValidationError):
        Playbook.model_validate(data)


def test_unknown_ladder_step_fails() -> None:
    data = _copy_with(intervention_ladder=[{"step": "send_carrier_pigeon", "offset": "T+0"}])
    with pytest.raises(ValidationError):
        Playbook.model_validate(data)


def test_malformed_offset_fails() -> None:
    data = _copy_with(intervention_ladder=[{"step": "reminder_message", "offset": "next tuesday"}])
    with pytest.raises(ValidationError):
        Playbook.model_validate(data)


def test_incentive_ceiling_wrong_type_fails() -> None:
    data = _copy_with(incentive_ceiling={"type": "amount_inr", "value": "a lot"})
    with pytest.raises(ValidationError):
        Playbook.model_validate(data)


def test_incentive_ceiling_negative_value_fails() -> None:
    data = _copy_with(incentive_ceiling={"type": "amount_inr", "value": -50})
    with pytest.raises(ValidationError):
        Playbook.model_validate(data)


def test_percent_ceiling_over_100_fails() -> None:
    data = _copy_with(incentive_ceiling={"type": "percent", "value": 150})
    with pytest.raises(ValidationError):
        Playbook.model_validate(data)


def test_unknown_stopping_rule_fails() -> None:
    data = _copy_with(stopping_rules=["invoice_is_now_forgiven"])
    with pytest.raises(ValidationError):
        Playbook.model_validate(data)


def test_incentive_offer_step_requires_nonzero_ceiling() -> None:
    data = _copy_with(
        intervention_ladder=[{"step": "incentive_offer", "offset": "T+0"}],
        incentive_ceiling={"type": "amount_inr", "value": 0},
    )
    with pytest.raises(ValidationError):
        Playbook.model_validate(data)


def test_extra_field_rejected() -> None:
    data = _copy_with(unexpected_field="surprise")
    with pytest.raises(ValidationError):
        Playbook.model_validate(data)


# --- loader: malformed YAML file on disk ------------------------------------


def test_loader_rejects_malformed_yaml_file(tmp_path: Path) -> None:
    bad = tmp_path / "card_expired.yaml"
    bad.write_text("root_cause: card_expired\nmax_attempts: not_a_number\n")
    with pytest.raises(PlaybookLoadError):
        load_playbooks(tmp_path)


def test_loader_rejects_invalid_yaml_syntax(tmp_path: Path) -> None:
    bad = tmp_path / "card_expired.yaml"
    bad.write_text("root_cause: [unterminated\n")
    with pytest.raises(PlaybookLoadError):
        load_playbooks(tmp_path)


def test_loader_rejects_filename_root_cause_mismatch(tmp_path: Path) -> None:
    bad = tmp_path / "wrong_name.yaml"
    bad.write_text(yaml.safe_dump(VALID_PLAYBOOK))
    with pytest.raises(PlaybookLoadError):
        load_playbooks(tmp_path)


def test_loader_loads_valid_directory(tmp_path: Path) -> None:
    good = tmp_path / "card_expired.yaml"
    good.write_text(yaml.safe_dump(VALID_PLAYBOOK))
    playbooks = load_playbooks(tmp_path)
    assert set(playbooks) == {"card_expired"}


# --- real playbooks under core/policy/playbooks/ ----------------------------


def test_real_playbook_directory_loads_cleanly() -> None:
    playbooks = load_playbooks()
    assert len(playbooks) == 16


def test_taxonomy_completeness_real_playbooks() -> None:
    playbooks = load_playbooks()
    validate_taxonomy_completeness(playbooks, TAXONOMY)


def test_taxonomy_matches_diagnosis_mapper_exactly() -> None:
    playbooks = load_playbooks()
    assert set(playbooks.keys()) == TAXONOMY


def test_overdue_b2b_invoice_ceiling_is_exactly_zero() -> None:
    playbooks = load_playbooks()
    ceiling = playbooks["invoice_overdue"].incentive_ceiling
    assert ceiling.value == 0


def test_completeness_detects_missing_playbook() -> None:
    playbooks = load_playbooks()
    incomplete = dict(playbooks)
    del incomplete["invoice_overdue"]
    with pytest.raises(PlaybookLoadError):
        validate_taxonomy_completeness(incomplete, TAXONOMY)


def test_completeness_detects_extra_playbook_outside_taxonomy() -> None:
    playbooks = load_playbooks()
    extra = dict(playbooks)
    extra["not_a_real_root_cause"] = extra["card_expired"]
    with pytest.raises(PlaybookLoadError):
        validate_taxonomy_completeness(extra, TAXONOMY)


# --- sub-model sanity (exercised directly, not just via Playbook) ----------


def test_trigger_conditions_requires_nonempty_cohorts() -> None:
    with pytest.raises(ValidationError):
        TriggerConditions.model_validate({"cohorts": []})


def test_ladder_step_accepts_hour_offset() -> None:
    step = LadderStep.model_validate({"step": "payment_link", "offset": "T+24h"})
    assert step.offset == "T+24h"


def test_incentive_ceiling_percent_type_accepts_100() -> None:
    ceiling = IncentiveCeiling.model_validate({"type": "percent", "value": 100})
    assert ceiling.value == 100
