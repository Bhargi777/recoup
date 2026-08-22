"""Loads and validates the YAML playbooks under ``core/policy/playbooks/``.

A malformed playbook fails loudly at load time (raises ``PlaybookLoadError``),
never silently no-ops - see CLAUDE.md SS4. Completeness against the closed
root-cause taxonomy (``core.diagnose.mapper`` / ``core.ingest.synthetic``) is
checked separately by ``validate_taxonomy_completeness`` so callers can decide
whether a partial playbook set is acceptable (it never is in production, but
tests exercise both states independently).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from core.policy.schema import Playbook

PLAYBOOK_DIR = Path(__file__).parent / "playbooks"


class PlaybookLoadError(RuntimeError):
    """Raised when a playbook YAML file fails schema validation or parsing."""


def load_playbooks(directory: Path | None = None) -> dict[str, Playbook]:
    """Load and validate every ``*.yaml`` file in ``directory``.

    Returns a mapping of ``root_cause -> Playbook``. Raises ``PlaybookLoadError``
    immediately on the first malformed file (bad YAML syntax, schema violation,
    or a root_cause that duplicates another file's) with the offending file
    path in the message.
    """
    directory = directory or PLAYBOOK_DIR
    playbooks: dict[str, Playbook] = {}

    for path in sorted(directory.glob("*.yaml")):
        try:
            raw = yaml.safe_load(path.read_text())
        except yaml.YAMLError as exc:
            raise PlaybookLoadError(f"{path}: invalid YAML syntax: {exc}") from exc

        if not isinstance(raw, dict):
            raise PlaybookLoadError(
                f"{path}: playbook must be a YAML mapping, got {type(raw).__name__}"
            )

        try:
            playbook = Playbook.model_validate(raw)
        except ValidationError as exc:
            raise PlaybookLoadError(f"{path}: schema validation failed: {exc}") from exc

        if playbook.root_cause != path.stem:
            raise PlaybookLoadError(
                f"{path}: root_cause {playbook.root_cause!r} does not match "
                f"filename stem {path.stem!r}"
            )

        if playbook.root_cause in playbooks:
            raise PlaybookLoadError(
                f"{path}: duplicate root_cause {playbook.root_cause!r} "
                f"(already loaded from another file)"
            )

        playbooks[playbook.root_cause] = playbook

    return playbooks


def validate_taxonomy_completeness(
    playbooks: dict[str, Playbook], taxonomy: frozenset[str] | set[str]
) -> None:
    """Every taxonomy label has exactly one playbook; no playbook references
    a label outside the taxonomy. Raises ``PlaybookLoadError`` describing the
    exact mismatch (never silently ignores missing or extra playbooks).
    """
    playbook_labels = set(playbooks.keys())
    taxonomy_labels = set(taxonomy)

    missing = taxonomy_labels - playbook_labels
    extra = playbook_labels - taxonomy_labels

    if missing or extra:
        problems = []
        if missing:
            problems.append(f"missing playbooks for root causes: {sorted(missing)}")
        if extra:
            problems.append(
                f"playbooks reference root causes outside the taxonomy: {sorted(extra)}"
            )
        raise PlaybookLoadError("; ".join(problems))
