from __future__ import annotations

import subprocess
from pathlib import Path

import click
import structlog

from hyperloop.reconciliation.composition_root import create_reconciler
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


def _find_git_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise click.ClickException("Not a git repository")
    return Path(result.stdout.strip())


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

    try:
        repo_path = _find_git_root()
    except click.ClickException:
        raise
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    path = Path(config_path) if config_path else repo_path / DEFAULT_CONFIG_FILENAME
    try:
        config = Configuration.from_yaml(path)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    factory = ctx.obj if callable(ctx.obj) else create_reconciler
    try:
        reconciler = factory(config, repo_path)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    reconciler.run()
