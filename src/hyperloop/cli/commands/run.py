from __future__ import annotations

from pathlib import Path

import click
import structlog

from hyperloop.reconciliation.models.configuration import (
    DEFAULT_CONFIG_FILENAME,
    Configuration,
)
from hyperloop.reconciliation.reconciler import Reconciler


def _configure_structlog() -> None:
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.PrintLoggerFactory(),
    )


@click.command()
@click.option(
    "--config", "config_path", default=None, help="Path to configuration file"
)
@click.pass_context
def run(ctx: click.Context, config_path: str | None) -> None:
    _configure_structlog()

    if isinstance(ctx.obj, Reconciler):
        ctx.obj.run()
        return

    path = Path(config_path) if config_path else Path(DEFAULT_CONFIG_FILENAME)
    try:
        Configuration.from_yaml(path)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    raise click.ClickException(
        "No agent executor available. "
        "An AgentExecutor implementation is required to run the reconciler."
    )
