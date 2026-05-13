from __future__ import annotations


import click

from hyperloop.cli.git import find_git_root
from hyperloop.reconciliation.adapters.git_plan_store import GitPlanStore
from hyperloop.reconciliation.models.configuration import (
    DEFAULT_CONFIG_FILENAME,
    Configuration,
)
from hyperloop.reconciliation.ports.plan_store import PlanStore


def create_plan_store_from_config() -> PlanStore:
    try:
        repo_path = find_git_root()
        config = Configuration.from_yaml(repo_path / DEFAULT_CONFIG_FILENAME)
        return GitPlanStore(
            repo_path=repo_path,
            plan_branch=config.plan_branch,
            plan_file=config.plan_file,
        )
    except click.ClickException:
        raise
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
