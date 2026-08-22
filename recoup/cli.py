"""Typer CLI entrypoint for recoup."""

import typer
from sqlmodel import Session

from core import __version__
from core.config import get_settings
from core.ledger import get_engine, init_ledger_schema, verify_chain

app = typer.Typer(
    name="recoup",
    help="AI-powered revenue recovery engine (Razorpay Test Mode only).",
    no_args_is_help=True,
)


@app.command()
def version() -> None:
    """Print the installed recoup version."""
    typer.echo(f"recoup {__version__}")


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


if __name__ == "__main__":
    app()
