"""CLI smoke tests for `recoup replay <event_id_or_idempotency_key>`.

The decision_id used here is a real one, pulled from an actual run_batch
pass over real synthetic records - not fabricated - and cross-checked
against core.api.decisions.get_decisions()'s own output for the same
decision, so this test would fail if replay's "why" ever drifted from what
the dashboard's Decisions feed shows for the identical event.
"""

from typer.testing import CliRunner

from recoup.cli import app

runner = CliRunner()


def _seed_and_run_batch(db_path):
    from sqlmodel import Session

    from core.config import get_settings, reset_settings_cache
    from core.eval.batch_runner import run_batch
    from core.ingest.synthetic import AtRiskRecord, generate_records, init_synthetic_schema
    from core.ledger import get_engine, init_ledger_schema

    reset_settings_cache()
    settings = get_settings()
    engine = get_engine(f"sqlite:///{db_path}")
    init_ledger_schema(engine)
    init_synthetic_schema(engine)

    with Session(engine) as session:
        records = generate_records(seed=settings.split_seed)[:20]
        session.add_all([AtRiskRecord(**r) for r in records])
        session.commit()
        run_batch(session, mode="dry_run", settings=settings)


def _a_real_policy_gate_decision(db_path):
    """Pull one real POLICY_GATE_DECISION event from the batch run above -
    not a hand-picked or fabricated id."""
    from sqlmodel import Session

    from core.ledger import get_engine, list_events

    engine = get_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        return next(e for e in list_events(session) if e.event_type == "POLICY_GATE_DECISION")


def test_replay_prints_full_event_history_matching_the_decisions_feed(tmp_path, monkeypatch):
    from sqlmodel import Session

    from core.api.decisions import get_decisions
    from core.config import reset_settings_cache
    from core.ledger import get_engine

    db_path = tmp_path / "replay.db"
    _seed_and_run_batch(db_path)
    decision_event = _a_real_policy_gate_decision(db_path)

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    reset_settings_cache()
    try:
        result = runner.invoke(app, ["replay", decision_event.event_id])
        assert result.exit_code == 0
        assert decision_event.event_id in result.output
        assert "event history" in result.output
        assert "POLICY_GATE_EVALUATED" in result.output  # at least one sibling check event

        engine = get_engine(f"sqlite:///{db_path}")
        with Session(engine) as session:
            feed = get_decisions(limit=500, session=session)
        feed_entry = next(d for d in feed["decisions"] if d["event_id"] == decision_event.event_id)
        assert feed_entry["why"] in result.output
    finally:
        reset_settings_cache()


def test_replay_by_idempotency_key_finds_the_same_decision(tmp_path, monkeypatch):
    from core.config import reset_settings_cache

    db_path = tmp_path / "replay_by_key.db"
    _seed_and_run_batch(db_path)
    decision_event = _a_real_policy_gate_decision(db_path)

    import json

    idempotency_key = json.loads(decision_event.payload_json)["idempotency_key"]

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    reset_settings_cache()
    try:
        result = runner.invoke(app, ["replay", idempotency_key])
        assert result.exit_code == 0
        assert decision_event.event_id in result.output
    finally:
        reset_settings_cache()


def test_replay_unknown_key_reports_not_found_not_a_crash(tmp_path, monkeypatch):
    from core.config import reset_settings_cache

    db_path = tmp_path / "replay_empty.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    reset_settings_cache()
    try:
        result = runner.invoke(app, ["replay", "evt_does_not_exist"])
        assert result.exit_code == 1
        # A clean typer.Exit, not an unhandled exception/stack trace.
        assert isinstance(result.exception, SystemExit)
        assert "no matching decision found" in result.output
    finally:
        reset_settings_cache()
