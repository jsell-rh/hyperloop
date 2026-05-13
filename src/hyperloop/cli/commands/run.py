from __future__ import annotations

from pathlib import Path

import click

from hyperloop.reconciliation.models.configuration import Configuration
from hyperloop.reconciliation.reconciler import Reconciler


@click.command()
@click.option(
    "--config", "config_path", default=None, help="Path to configuration file"
)
@click.pass_context
def run(ctx: click.Context, config_path: str | None) -> None:
    if isinstance(ctx.obj, Reconciler):
        ctx.obj.run()
        return

    path = Path(config_path) if config_path else Path(".hyperloop.yaml")
    try:
        Configuration.from_yaml(path)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    raise click.ClickException(
        "No agent executor available. "
        "An AgentExecutor implementation is required to run the reconciler."
    )
