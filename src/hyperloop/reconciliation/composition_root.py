from __future__ import annotations

from pathlib import Path

from hyperloop.reconciliation.adapters.agent_executor import AgentExecutor
from hyperloop.reconciliation.adapters.git_agent_runtime import GitAgentRuntime
from hyperloop.reconciliation.adapters.git_plan_store import GitPlanStore
from hyperloop.reconciliation.adapters.git_spec_source import GitSpecSource
from hyperloop.reconciliation.adapters.git_workspace_manager import GitWorkspaceManager
from hyperloop.reconciliation.adapters.null_probe import NullProbe
from hyperloop.reconciliation.models.configuration import Configuration
from hyperloop.reconciliation.reconciler import Reconciler


def create_reconciler(
    config: Configuration,
    repo_path: Path,
    *,
    executor: AgentExecutor,
) -> Reconciler:
    observer = NullProbe()

    plan_store = GitPlanStore(
        repo_path=repo_path,
        plan_branch=config.plan_branch,
        plan_file=config.plan_file,
    )

    spec_source = GitSpecSource(
        repo_path=repo_path,
        specs_dir=config.specs_directory,
        branch=config.trunk_branch,
    )

    workspace_manager = GitWorkspaceManager(
        repo_path=repo_path,
        branch_prefix=config.branch_prefix,
        trunk_branch=config.trunk_branch,
    )

    agent_runtime = GitAgentRuntime(
        repo_path=repo_path,
        branch_prefix=config.branch_prefix,
        executor=executor,
    )

    return Reconciler(
        spec_source=spec_source,
        plan_store=plan_store,
        observer=observer,
        agent_runtime=agent_runtime,
        workspace_manager=workspace_manager,
        max_concurrent_tasks=config.max_concurrent_tasks,
        convergence_bound=config.convergence_bound,
        max_integration_retries=config.max_integration_retries,
        max_task_retries=config.max_task_retries,
        max_redecompositions=config.max_redecompositions,
        cycle_interval_seconds=config.cycle_interval_seconds,
    )
