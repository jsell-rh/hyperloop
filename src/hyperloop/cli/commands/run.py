from __future__ import annotations

from pathlib import Path

import click
import structlog

from hyperloop.cli.git import find_git_root
from hyperloop.reconciliation.composition_root import create_reconciler
from hyperloop.reconciliation.models.configuration import (
    DEFAULT_CONFIG_FILENAME,
    Configuration,
)
from hyperloop.reconciliation.models.executor_type import ExecutorType
from hyperloop.reconciliation.models.observer_adapter import ObserverAdapter
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
@click.option(
    "--executor-type",
    type=click.Choice([e.value for e in ExecutorType], case_sensitive=False),
    default=None,
    help="Executor type (overrides config file)",
)
@click.option(
    "--repository-url", default=None, help="Repository clone URL (ambient executor)"
)
@click.option(
    "--project-name", default=None, help="Platform project name (ambient executor)"
)
@click.option(
    "--acpctl-path", default=None, help="Path to acpctl binary (ambient executor)"
)
@click.pass_context
def run(
    ctx: click.Context,
    config_path: str | None,
    executor_type: str | None,
    repository_url: str | None,
    project_name: str | None,
    acpctl_path: str | None,
) -> None:
    _configure_structlog()

    if isinstance(ctx.obj, Reconciler):
        ctx.obj.run()
        return

    try:
        repo_path = find_git_root()
    except click.ClickException:
        raise
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    path = Path(config_path) if config_path else repo_path / DEFAULT_CONFIG_FILENAME
    try:
        config = Configuration.from_yaml(path)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    cli_overrides: dict[str, object] = {}
    if executor_type is not None:
        cli_overrides["executor_type"] = ExecutorType(executor_type)
    if repository_url is not None:
        cli_overrides["repository_url"] = repository_url
    if project_name is not None:
        cli_overrides["project_name"] = project_name
    if acpctl_path is not None:
        cli_overrides["acpctl_path"] = acpctl_path

    if ObserverAdapter.STRUCTLOG not in config.observer_adapters:
        cli_overrides["observer_adapters"] = [
            *config.observer_adapters,
            ObserverAdapter.STRUCTLOG,
        ]

    if cli_overrides:
        config = config.model_copy(update=cli_overrides)

    factory = ctx.obj if callable(ctx.obj) else create_reconciler
    try:
        reconciler = factory(config, repo_path)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    reconciler.run()
