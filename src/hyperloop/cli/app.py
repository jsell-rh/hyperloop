from __future__ import annotations

import click

from hyperloop.cli.commands.describe import describe
from hyperloop.cli.commands.get import get
from hyperloop.cli.commands.init import init
from hyperloop.cli.commands.run import run


@click.group()
@click.pass_context
def cli(ctx: click.Context) -> None:
    pass


cli.add_command(get)
cli.add_command(describe)
cli.add_command(init)
cli.add_command(run)
