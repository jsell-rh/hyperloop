from __future__ import annotations

from pathlib import Path

import pytest

from hyperloop.reconciliation.adapters.claude_sdk_executor import ClaudeSDKExecutor
from hyperloop.reconciliation.adapters.git_agent_runtime import GitAgentRuntime
from hyperloop.reconciliation.adapters.git_plan_store import GitPlanStore
from hyperloop.reconciliation.adapters.git_spec_source import GitSpecSource
from hyperloop.reconciliation.adapters.git_workspace_manager import GitWorkspaceManager
from hyperloop.reconciliation.adapters.kustomize_prompt_composer import (
    KustomizePromptComposer,
)
from hyperloop.reconciliation.adapters.composite_observer import CompositeObserver
from hyperloop.reconciliation.adapters.null_probe import NullProbe
from hyperloop.reconciliation.adapters.structlog_observer import StructlogObserver
from hyperloop.reconciliation.composition_root import build_executor, create_reconciler
from hyperloop.reconciliation.models.configuration import Configuration
from hyperloop.reconciliation.models.executor_type import ExecutorType
from hyperloop.reconciliation.reconciler import Reconciler

from .fakes.fake_agent_executor import FakeAgentExecutor
from .fakes.fake_kustomize_build_runner import FakeKustomizeBuildRunner


def _create(
    tmp_path: Path,
    *,
    config: Configuration | None = None,
    executor: FakeAgentExecutor | None = None,
    runner: FakeKustomizeBuildRunner | None = None,
) -> Reconciler:
    (tmp_path / "specs").mkdir(exist_ok=True)
    cfg = config or Configuration(specs_directory=str(tmp_path / "specs"))
    return create_reconciler(
        cfg,
        tmp_path,
        executor=executor or FakeAgentExecutor(),
        kustomize_runner=runner or FakeKustomizeBuildRunner(),
    )


class TestCreateReconciler:
    def test_returns_reconciler(self, tmp_path: Path) -> None:
        result = _create(tmp_path)

        assert isinstance(result, Reconciler)

    def test_propagates_convergence_bound(self, tmp_path: Path) -> None:
        (tmp_path / "specs").mkdir()
        config = Configuration(
            convergence_bound=5,
            specs_directory=str(tmp_path / "specs"),
        )

        reconciler = _create(tmp_path, config=config)

        assert reconciler._convergence_bound == 5

    def test_propagates_max_task_retries(self, tmp_path: Path) -> None:
        (tmp_path / "specs").mkdir()
        config = Configuration(
            max_task_retries=2,
            specs_directory=str(tmp_path / "specs"),
        )

        reconciler = _create(tmp_path, config=config)

        assert reconciler._max_task_retries == 2

    def test_propagates_max_concurrent_tasks(self, tmp_path: Path) -> None:
        (tmp_path / "specs").mkdir()
        config = Configuration(
            max_concurrent_tasks=3,
            specs_directory=str(tmp_path / "specs"),
        )

        reconciler = _create(tmp_path, config=config)

        assert reconciler._max_concurrent_tasks == 3

    def test_propagates_cycle_interval(self, tmp_path: Path) -> None:
        (tmp_path / "specs").mkdir()
        config = Configuration(
            cycle_interval_seconds=60,
            specs_directory=str(tmp_path / "specs"),
        )

        reconciler = _create(tmp_path, config=config)

        assert reconciler._cycle_interval_seconds == 60

    def test_propagates_max_integration_retries(self, tmp_path: Path) -> None:
        (tmp_path / "specs").mkdir()
        config = Configuration(
            max_integration_retries=5,
            specs_directory=str(tmp_path / "specs"),
        )

        reconciler = _create(tmp_path, config=config)

        assert reconciler._max_integration_retries == 5

    def test_propagates_max_redecompositions(self, tmp_path: Path) -> None:
        (tmp_path / "specs").mkdir()
        config = Configuration(
            max_redecompositions=2,
            specs_directory=str(tmp_path / "specs"),
        )

        reconciler = _create(tmp_path, config=config)

        assert reconciler._max_redecompositions == 2

    def test_observer_defaults_to_null_probe(self, tmp_path: Path) -> None:
        reconciler = _create(tmp_path)

        assert isinstance(reconciler._observer, NullProbe)

    def test_structlog_observer_adapter(self, tmp_path: Path) -> None:
        (tmp_path / "specs").mkdir()
        config = Configuration(
            observer_adapters=["structlog"],
            specs_directory=str(tmp_path / "specs"),
        )

        reconciler = _create(tmp_path, config=config)

        assert isinstance(reconciler._observer, StructlogObserver)

    def test_multiple_observer_adapters_uses_composite(self, tmp_path: Path) -> None:
        (tmp_path / "specs").mkdir()
        config = Configuration(
            observer_adapters=["structlog", "structlog"],
            specs_directory=str(tmp_path / "specs"),
        )

        reconciler = _create(tmp_path, config=config)

        assert isinstance(reconciler._observer, CompositeObserver)

    def test_unknown_observer_adapter_raises(self, tmp_path: Path) -> None:
        (tmp_path / "specs").mkdir()
        config = Configuration(
            observer_adapters=["unknown"],
            specs_directory=str(tmp_path / "specs"),
        )

        with pytest.raises(ValueError, match="unknown"):
            _create(tmp_path, config=config)

    def test_observer_shared_with_prompt_composer(self, tmp_path: Path) -> None:
        (tmp_path / "specs").mkdir()
        config = Configuration(
            observer_adapters=["structlog"],
            specs_directory=str(tmp_path / "specs"),
        )

        reconciler = _create(tmp_path, config=config)

        composer = reconciler._agent_runtime._prompt_composer
        assert isinstance(composer, KustomizePromptComposer)
        assert composer._observer is reconciler._observer

    def test_wires_git_plan_store(self, tmp_path: Path) -> None:
        (tmp_path / "specs").mkdir()
        config = Configuration(
            plan_branch="custom/plan",
            plan_file="state.json",
            specs_directory=str(tmp_path / "specs"),
        )

        reconciler = _create(tmp_path, config=config)

        plan_store = reconciler._plan_store
        assert isinstance(plan_store, GitPlanStore)
        assert plan_store._repo_path == tmp_path
        assert plan_store._plan_branch == "custom/plan"
        assert plan_store._plan_file == "state.json"

    def test_wires_git_spec_source(self, tmp_path: Path) -> None:
        (tmp_path / "specs").mkdir()
        config = Configuration(
            trunk_branch="develop",
            specs_directory=str(tmp_path / "specs"),
        )

        reconciler = _create(tmp_path, config=config)

        spec_source = reconciler._spec_source
        assert isinstance(spec_source, GitSpecSource)
        assert spec_source._repo_path == tmp_path
        assert spec_source._branch == "develop"
        assert spec_source._specs_dir == str(tmp_path / "specs")

    def test_wires_git_workspace_manager(self, tmp_path: Path) -> None:
        (tmp_path / "specs").mkdir()
        config = Configuration(
            trunk_branch="develop",
            branch_prefix="custom/",
            specs_directory=str(tmp_path / "specs"),
        )

        reconciler = _create(tmp_path, config=config)

        workspace_manager = reconciler._workspace_manager
        assert isinstance(workspace_manager, GitWorkspaceManager)
        assert workspace_manager._repo_path == tmp_path
        assert workspace_manager._trunk_branch == "develop"
        assert workspace_manager._branch_prefix == "custom/"

    def test_wires_executor_into_agent_runtime(self, tmp_path: Path) -> None:
        (tmp_path / "specs").mkdir()
        config = Configuration(
            branch_prefix="custom/",
            specs_directory=str(tmp_path / "specs"),
        )
        executor = FakeAgentExecutor()

        reconciler = _create(tmp_path, config=config, executor=executor)

        agent_runtime = reconciler._agent_runtime
        assert isinstance(agent_runtime, GitAgentRuntime)
        assert agent_runtime._repo_path == tmp_path
        assert agent_runtime._branch_prefix == "custom/"
        assert agent_runtime._executor is executor

    def test_wires_prompt_composer_into_agent_runtime(self, tmp_path: Path) -> None:
        reconciler = _create(tmp_path)

        agent_runtime = reconciler._agent_runtime
        assert isinstance(agent_runtime, GitAgentRuntime)
        assert isinstance(agent_runtime._prompt_composer, KustomizePromptComposer)

    def test_prompt_composer_uses_config_overlay_path(self, tmp_path: Path) -> None:
        (tmp_path / "specs").mkdir()
        config = Configuration(
            overlay_path=".custom/agents",
            specs_directory=str(tmp_path / "specs"),
        )

        reconciler = _create(tmp_path, config=config)

        composer = reconciler._agent_runtime._prompt_composer
        assert isinstance(composer, KustomizePromptComposer)
        assert composer._overlay_path == tmp_path / ".custom/agents"

    def test_prompt_composer_receives_observer(self, tmp_path: Path) -> None:
        reconciler = _create(tmp_path)

        composer = reconciler._agent_runtime._prompt_composer
        assert isinstance(composer, KustomizePromptComposer)
        assert composer._observer is reconciler._observer

    def test_prompt_composer_receives_kustomize_runner(self, tmp_path: Path) -> None:
        runner = FakeKustomizeBuildRunner()

        reconciler = _create(tmp_path, runner=runner)

        composer = reconciler._agent_runtime._prompt_composer
        assert isinstance(composer, KustomizePromptComposer)
        assert composer._runner is runner

    def test_wires_model_config_into_agent_runtime(self, tmp_path: Path) -> None:
        (tmp_path / "specs").mkdir()
        config = Configuration(
            implementation_model="claude-sonnet",
            verification_model="gemini-pro",
            decomposition_model="claude-opus",
            specs_directory=str(tmp_path / "specs"),
        )

        reconciler = _create(tmp_path, config=config)

        agent_runtime = reconciler._agent_runtime
        assert isinstance(agent_runtime, GitAgentRuntime)
        assert agent_runtime._implementation_model == "claude-sonnet"
        assert agent_runtime._verification_model == "gemini-pro"
        assert agent_runtime._decomposition_model == "claude-opus"

    def test_none_models_wired_by_default(self, tmp_path: Path) -> None:
        reconciler = _create(tmp_path)

        agent_runtime = reconciler._agent_runtime
        assert isinstance(agent_runtime, GitAgentRuntime)
        assert agent_runtime._implementation_model is None
        assert agent_runtime._verification_model is None
        assert agent_runtime._decomposition_model is None


class TestBuildExecutor:
    def test_claude_sdk_returns_claude_sdk_executor(self, tmp_path: Path) -> None:
        (tmp_path / "specs").mkdir()
        config = Configuration(
            executor_type=ExecutorType.CLAUDE_SDK,
            specs_directory=str(tmp_path / "specs"),
        )

        executor = build_executor(config, tmp_path)

        assert isinstance(executor, ClaudeSDKExecutor)

    def test_default_config_returns_claude_sdk_executor(self, tmp_path: Path) -> None:
        (tmp_path / "specs").mkdir()
        config = Configuration(specs_directory=str(tmp_path / "specs"))

        executor = build_executor(config, tmp_path)

        assert isinstance(executor, ClaudeSDKExecutor)

    def test_claude_sdk_uses_timeout_from_config(self, tmp_path: Path) -> None:
        (tmp_path / "specs").mkdir()
        config = Configuration(
            executor_timeout_seconds=600,
            specs_directory=str(tmp_path / "specs"),
        )

        executor = build_executor(config, tmp_path)

        assert isinstance(executor, ClaudeSDKExecutor)
        assert executor._timeout_seconds == 600

    def test_claude_sdk_uses_max_retries_from_config(self, tmp_path: Path) -> None:
        (tmp_path / "specs").mkdir()
        config = Configuration(
            executor_max_retries=5,
            specs_directory=str(tmp_path / "specs"),
        )

        executor = build_executor(config, tmp_path)

        assert isinstance(executor, ClaudeSDKExecutor)
        assert executor._max_retries == 5

    def test_claude_sdk_uses_branch_prefix_from_config(self, tmp_path: Path) -> None:
        (tmp_path / "specs").mkdir()
        config = Configuration(
            branch_prefix="custom/",
            specs_directory=str(tmp_path / "specs"),
        )

        executor = build_executor(config, tmp_path)

        assert isinstance(executor, ClaudeSDKExecutor)
        assert executor._branch_prefix == "custom/"

    def test_ambient_executor_raises_not_implemented(self, tmp_path: Path) -> None:
        (tmp_path / "specs").mkdir()
        config = Configuration(
            executor_type=ExecutorType.AMBIENT,
            repository_url="https://github.com/org/repo.git",
            project_identifier="my-project",
            specs_directory=str(tmp_path / "specs"),
        )

        with pytest.raises(NotImplementedError, match="ambient"):
            build_executor(config, tmp_path)

    def test_create_reconciler_builds_executor_from_config(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "specs").mkdir()
        config = Configuration(specs_directory=str(tmp_path / "specs"))
        runner = FakeKustomizeBuildRunner()

        reconciler = create_reconciler(config, tmp_path, kustomize_runner=runner)

        agent_runtime = reconciler._agent_runtime
        assert isinstance(agent_runtime, GitAgentRuntime)
        assert isinstance(agent_runtime._executor, ClaudeSDKExecutor)

    def test_create_reconciler_uses_injected_executor_over_config(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "specs").mkdir()
        config = Configuration(specs_directory=str(tmp_path / "specs"))
        executor = FakeAgentExecutor()
        runner = FakeKustomizeBuildRunner()

        reconciler = create_reconciler(
            config, tmp_path, executor=executor, kustomize_runner=runner
        )

        agent_runtime = reconciler._agent_runtime
        assert isinstance(agent_runtime, GitAgentRuntime)
        assert agent_runtime._executor is executor
