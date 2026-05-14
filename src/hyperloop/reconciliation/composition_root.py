from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from hyperloop.reconciliation.adapters.acpctl_platform_runner import (
    AcpctlPlatformRunner,
)
from hyperloop.reconciliation.adapters.agent_executor import AgentExecutor
from hyperloop.reconciliation.adapters.ambient_executor import AmbientExecutor
from hyperloop.reconciliation.adapters.claude_sdk_executor import ClaudeSDKExecutor
from hyperloop.reconciliation.adapters.claude_sdk_runner import ClaudeSDKRunner
from hyperloop.reconciliation.adapters.git_agent_runtime import GitAgentRuntime
from hyperloop.reconciliation.adapters.git_plan_store import GitPlanStore
from hyperloop.reconciliation.adapters.git_spec_source import GitSpecSource
from hyperloop.reconciliation.adapters.git_workspace_manager import GitWorkspaceManager
from hyperloop.reconciliation.adapters.kustomize_build_runner import (
    KustomizeBuildRunner,
)
from hyperloop.reconciliation.adapters.kustomize_prompt_composer import (
    KustomizePromptComposer,
)
from hyperloop.reconciliation.adapters.composite_observer import CompositeObserver
from hyperloop.reconciliation.adapters.null_probe import NullProbe
from hyperloop.reconciliation.adapters.structlog_observer import StructlogObserver
from hyperloop.reconciliation.ports.observer import Observer
from hyperloop.reconciliation.adapters.subprocess_kustomize_build_runner import (
    SubprocessKustomizeBuildRunner,
)
from hyperloop.reconciliation.models.agent_role import AgentRole
from hyperloop.reconciliation.models.configuration import Configuration
from hyperloop.reconciliation.models.executor_type import ExecutorType
from hyperloop.reconciliation.models.observer_adapter import ObserverAdapter
from hyperloop.reconciliation.reconciler import Reconciler


_OBSERVER_REGISTRY: dict[ObserverAdapter, type[Observer]] = {
    ObserverAdapter.STRUCTLOG: StructlogObserver,
}


def _build_observer(adapter_names: list[ObserverAdapter]) -> Observer:
    if not adapter_names:
        return NullProbe()

    adapters: list[Observer] = []
    for name in adapter_names:
        adapter_cls = _OBSERVER_REGISTRY.get(name)
        if adapter_cls is None:
            raise ValueError(
                f"Unknown observer adapter: {name!r}. "
                f"Available: {sorted(_OBSERVER_REGISTRY)}"
            )
        adapters.append(adapter_cls())

    if len(adapters) == 1:
        return adapters[0]
    return CompositeObserver(adapters)


def build_executor(
    config: Configuration, repo_path: Path, observer: Observer | None = None
) -> AgentExecutor:
    if config.executor_type == ExecutorType.CLAUDE_SDK:
        on_message = _make_observer_callback(observer) if observer else None
        return ClaudeSDKExecutor(
            repo_path,
            sdk_runner=ClaudeSDKRunner(on_message=on_message),
            timeout_seconds=config.executor_timeout_seconds,
            max_retries=config.executor_max_retries,
            branch_prefix=config.branch_prefix,
        )
    if config.executor_type == ExecutorType.AMBIENT:
        assert config.repository_url is not None
        assert config.project_name is not None
        return AmbientExecutor(
            repo_path,
            platform_runner=AcpctlPlatformRunner(
                acpctl_path=config.acpctl_path,
            ),
            repository_url=config.repository_url,
            project_name=config.project_name,
            timeout_seconds=config.executor_timeout_seconds,
            max_retries=config.executor_max_retries,
            max_tokens=config.executor_max_tokens,
            branch_prefix=config.branch_prefix,
        )
    raise ValueError(f"Unknown executor_type: {config.executor_type!r}")


def _make_observer_callback(
    observer: Observer,
) -> Callable[[str, str, str], None]:
    def _callback(kind: str, branch: str, detail: str) -> None:
        if kind == "tool_use":
            observer.agent_tool_use(
                branch=branch, tool=detail.split(":")[0], input_preview=detail
            )
        elif kind == "text":
            observer.agent_text(branch=branch, text_preview=detail)
        elif kind == "progress":
            observer.agent_progress(branch=branch, description=detail)
        else:
            observer.agent_error(branch=branch, error=detail)

    return _callback


def create_reconciler(
    config: Configuration,
    repo_path: Path,
    *,
    executor: AgentExecutor | None = None,
    kustomize_runner: KustomizeBuildRunner | None = None,
) -> Reconciler:
    observer = _build_observer(config.observer_adapters)
    resolved_executor = executor or build_executor(config, repo_path, observer)

    runner = kustomize_runner or SubprocessKustomizeBuildRunner()

    prompt_composer = KustomizePromptComposer(
        overlay_path=repo_path / config.overlay_path,
        kustomize_runner=runner,
        observer=observer,
    )
    prompt_composer.validate({role.value for role in AgentRole})

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
        executor=resolved_executor,
        prompt_composer=prompt_composer,
        implementation_model=config.implementation_model,
        verification_model=config.verification_model,
        decomposition_model=config.decomposition_model,
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
