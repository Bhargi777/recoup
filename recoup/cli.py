"""Typer CLI entrypoint for recoup."""

import typer
from sqlmodel import Session

from core import __version__
from core.config import get_settings
from core.eval.diagnosis_eval import evaluate_holdout
from core.ingest.synthetic import init_synthetic_schema, run_generation
from core.ledger import get_engine, init_ledger_schema, verify_chain
from core.policy import activate_kill_switch, deactivate_kill_switch, is_kill_switch_active

app = typer.Typer(
    name="recoup",
    help="AI-powered revenue recovery engine (Razorpay Test Mode only).",
    no_args_is_help=True,
)


@app.command()
def version() -> None:
    """Print the installed recoup version."""
    typer.echo(f"recoup {__version__}")


@app.command(name="serve")
def serve(
    host: str = "127.0.0.1",
    port: int = 8000,
) -> None:
    """Run the ingest FastAPI app (webhook receiver + health check)."""
    import uvicorn

    get_settings()  # fail fast on a bad rzp_test_ key before binding a port
    uvicorn.run("core.ingest.webhook_app:app", host=host, port=port)


@app.command(name="check-config")
def check_config() -> None:
    """Load settings, enforce the rzp_test_ boot guard, print masked configuration."""
    settings = get_settings()
    masked_key = (
        f"{settings.razorpay_key_id[:12]}..." if len(settings.razorpay_key_id) > 12 else "(unset)"
    )
    typer.echo("configuration OK")
    typer.echo(f"  razorpay_key_id       : {masked_key}")
    typer.echo(f"  database_url          : {settings.database_url}")
    typer.echo(f"  max_global_budget_inr : {settings.max_global_budget_inr}")
    dnd = f"{settings.dnd_start_hour}:00 - {settings.dnd_end_hour}:00"
    typer.echo(f"  quiet hours (DND)     : {dnd}")
    typer.echo(f"  holdout percent       : {settings.default_holdout_percent}")
    typer.echo(f"  split_seed            : {settings.split_seed}")
    typer.echo(f"  webhook secret set    : {bool(settings.razorpay_webhook_secret)}")


@app.command(name="verify-chain")
def verify_chain_command() -> None:
    """Verify the hash-chained audit ledger end to end, reporting any tamper location."""
    settings = get_settings()
    engine = get_engine(settings.database_url)
    init_ledger_schema(engine)

    with Session(engine) as session:
        result = verify_chain(session)

    if result.events_checked == 0:
        typer.echo("ledger is empty: 0 events, nothing to verify")
        raise typer.Exit(code=0)

    if result.ok:
        typer.secho(
            f"chain OK: {result.events_checked} events verified, no tampering detected",
            fg=typer.colors.GREEN,
        )
        raise typer.Exit(code=0)

    typer.secho(
        f"chain BROKEN at sequence {result.first_bad_sequence} "
        f"({result.events_checked} events checked)",
        fg=typer.colors.RED,
    )
    for err in result.errors:
        typer.echo(f"  {err}")
    raise typer.Exit(code=1)


@app.command(name="generate-synthetic-data")
def generate_synthetic_data(
    force: bool = typer.Option(
        False,
        "--force",
        help="Delete existing synthetic records first and regenerate (avoids silent duplication).",
    ),
) -> None:
    """Generate the Phase 3 synthetic at-risk-payment backfill (600 records, 4 cohorts).

    Refuses to run a second time (no-op) unless --force is passed, so a repeat
    invocation never silently doubles the dataset. All 600 records carry
    source: "synthetic" and each insert emits a SYNTHETIC_RECORD_INGESTED
    ledger event.
    """
    settings = get_settings()
    engine = get_engine(settings.database_url)
    init_ledger_schema(engine)
    init_synthetic_schema(engine)

    with Session(engine) as session:
        result = run_generation(session, seed=settings.split_seed, force=force)

    if result.skipped:
        typer.secho(
            "synthetic data already present; skipped (pass --force to regenerate)",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(code=0)

    typer.secho(f"generated {result.inserted} synthetic records", fg=typer.colors.GREEN)
    for cohort, count in sorted(result.cohort_counts.items()):
        typer.echo(f"  {cohort:<28}: {count}")
    typer.echo(f"  {'held_out':<28}: {result.held_out_count}")


@app.command(name="eval-diagnosis")
def eval_diagnosis() -> None:
    """Run the Phase 4 diagnosis pipeline against the 200 held-out synthetic
    records and print real, measured macro P/R/F1, confusion matrix,
    abstain rate, and coverage. Self-contained: generates the synthetic
    dataset first if the database is empty (never doubles it if already
    present, same guard as `generate-synthetic-data`).
    """
    settings = get_settings()
    engine = get_engine(settings.database_url)
    init_ledger_schema(engine)
    init_synthetic_schema(engine)

    with Session(engine) as session:
        run_generation(session, seed=settings.split_seed, force=False)
        report = evaluate_holdout(session)

    typer.secho(f"held-out records evaluated: {report.total}", fg=typer.colors.CYAN)
    typer.echo(f"  macro precision : {report.macro_precision:.4f}")
    typer.echo(f"  macro recall    : {report.macro_recall:.4f}")
    typer.echo(f"  macro f1        : {report.macro_f1:.4f}")
    typer.echo(f"  abstain rate    : {report.abstain_rate:.4f}")
    typer.echo("  coverage:")
    for method, count in sorted(report.coverage.items()):
        typer.echo(f"    {method:<14}: {count}")
    typer.echo("  per-class (precision / recall / f1 / support):")
    for label, stats in sorted(report.per_class.items()):
        typer.echo(
            f"    {label:<26}: {stats['precision']:.3f} / {stats['recall']:.3f} / "
            f"{stats['f1']:.3f} / {int(stats['support'])}"
        )
    typer.echo("  confusion matrix (true -> {predicted: count}):")
    for true_label, preds in sorted(report.confusion_matrix.items()):
        typer.echo(f"    {true_label}: {dict(sorted(preds.items()))}")


@app.command(name="kill-switch")
def kill_switch_command(
    action: str = typer.Argument(..., help="One of: on, off, status"),
    reason: str = typer.Option(
        "", "--reason", help="Why the switch is being toggled (recorded on the ledger event)."
    ),
) -> None:
    """Toggle or inspect the emergency kill switch.

    State is never stored in a mutable column - it is recomputed every time
    by replaying KILL_SWITCH_ACTIVATED / KILL_SWITCH_DEACTIVATED ledger
    events (same replay contract as `recoup verify-chain`), so this command
    doubles as a live proof that replay works.
    """
    action = action.lower()
    if action not in {"on", "off", "status"}:
        typer.secho(
            f"unknown action {action!r}; must be one of: on, off, status", fg=typer.colors.RED
        )
        raise typer.Exit(code=1)

    settings = get_settings()
    engine = get_engine(settings.database_url)
    init_ledger_schema(engine)

    with Session(engine) as session:
        if action == "on":
            activate_kill_switch(session, reason or "no reason given")
            typer.secho("kill switch ACTIVATED", fg=typer.colors.RED)
        elif action == "off":
            deactivate_kill_switch(session, reason or "no reason given")
            typer.secho("kill switch DEACTIVATED", fg=typer.colors.GREEN)

        active = is_kill_switch_active(session)

    color = typer.colors.RED if active else typer.colors.GREEN
    typer.secho(f"kill switch is currently {'ACTIVE' if active else 'INACTIVE'}", fg=color)


if __name__ == "__main__":
    app()
