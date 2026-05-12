from __future__ import annotations

from typing import Protocol

import click


class Reconciler(Protocol):
    def run(self) -> None: ...


@click.command()
@click.option(
    "--config", "config_path", default=None, help="Path to configuration file"
)
@click.pass_obj
def run(reconciler: Reconciler, config_path: str | None) -> None:
    reconciler.run()
