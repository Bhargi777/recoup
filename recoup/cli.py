"""Typer CLI entrypoint for recoup."""

import typer

from core import __version__
from core.config import get_settings

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
def verify_chain() -> None:
    """Verify the hash-chained audit ledger end to end."""
    # Implemented in Phase 1 (feat/01-domain-ledger).
    typer.secho(
        "verify-chain: not implemented yet; the ledger ships in Phase 1.",
        fg=typer.colors.YELLOW,
    )
    raise typer.Exit(code=2)


if __name__ == "__main__":
    app()
