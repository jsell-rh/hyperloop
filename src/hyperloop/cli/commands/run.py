from __future__ import annotations

from pathlib import Path
from typing import Protocol

import click

from hyperloop.reconciliation.models.configuration import Configuration


class Reconciler(Protocol):
    def run(self, config: Configuration) -> None: ...


@click.command()
@click.option(
    "--config", "config_path", default=None, help="Path to configuration file"
)
@click.pass_obj
def run(reconciler: Reconciler, config_path: str | None) -> None:
    path = Path(config_path) if config_path else Path(".hyperloop.yaml")
    try:
        config = Configuration.from_yaml(path)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    reconciler.run(config)
