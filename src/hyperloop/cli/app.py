from __future__ import annotations

import subprocess
from pathlib import Path

import click

from hyperloop.cli.commands.describe import describe
from hyperloop.cli.commands.get import get
from hyperloop.cli.commands.run import run
from hyperloop.reconciliation.adapters.git_plan_store import GitPlanStore
from hyperloop.reconciliation.models.configuration import Configuration

PLAN_FILE = "plan.json"


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


@click.group()
@click.pass_context
def cli(ctx: click.Context) -> None:
    if ctx.obj is not None:
        return
    try:
        repo_path = _find_git_root()
        config = Configuration.from_yaml(repo_path / ".hyperloop.yaml")
        ctx.obj = GitPlanStore(
            repo_path=repo_path,
            plan_branch=config.plan_branch,
            plan_file=PLAN_FILE,
        )
    except click.ClickException:
        raise
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


cli.add_command(get)
cli.add_command(describe)
cli.add_command(run)
