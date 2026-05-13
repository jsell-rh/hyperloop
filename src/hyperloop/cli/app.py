from __future__ import annotations

import click

from hyperloop.cli.commands.describe import describe
from hyperloop.cli.commands.get import get
from hyperloop.cli.commands.run import run
from hyperloop.cli.git import find_git_root
from hyperloop.reconciliation.adapters.git_plan_store import GitPlanStore
from hyperloop.reconciliation.models.configuration import (
    DEFAULT_CONFIG_FILENAME,
    Configuration,
)


@click.group()
@click.pass_context
def cli(ctx: click.Context) -> None:
    if ctx.obj is not None:
        return
    try:
        repo_path = find_git_root()
        config = Configuration.from_yaml(repo_path / DEFAULT_CONFIG_FILENAME)
        ctx.obj = GitPlanStore(
            repo_path=repo_path,
            plan_branch=config.plan_branch,
            plan_file=config.plan_file,
        )
    except click.ClickException:
        raise
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


cli.add_command(get)
cli.add_command(describe)
cli.add_command(run)
