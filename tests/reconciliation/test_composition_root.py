from __future__ import annotations

from pathlib import Path

from hyperloop.reconciliation.adapters.git_agent_runtime import GitAgentRuntime
from hyperloop.reconciliation.adapters.git_plan_store import GitPlanStore
from hyperloop.reconciliation.adapters.git_spec_source import GitSpecSource
from hyperloop.reconciliation.adapters.git_workspace_manager import GitWorkspaceManager
from hyperloop.reconciliation.adapters.null_probe import NullProbe
from hyperloop.reconciliation.composition_root import create_reconciler
from hyperloop.reconciliation.models.configuration import Configuration
from hyperloop.reconciliation.reconciler import Reconciler

from .fakes.fake_agent_executor import FakeAgentExecutor


class TestCreateReconciler:
    def test_returns_reconciler(self, tmp_path: Path) -> None:
        (tmp_path / "specs").mkdir()
        config = Configuration(specs_directory=str(tmp_path / "specs"))
        executor = FakeAgentExecutor()

        result = create_reconciler(config, tmp_path, executor=executor)

        assert isinstance(result, Reconciler)

    def test_propagates_convergence_bound(self, tmp_path: Path) -> None:
        (tmp_path / "specs").mkdir()
        config = Configuration(
            convergence_bound=5,
            specs_directory=str(tmp_path / "specs"),
        )
        executor = FakeAgentExecutor()

        reconciler = create_reconciler(config, tmp_path, executor=executor)

        assert reconciler._convergence_bound == 5

    def test_propagates_max_task_retries(self, tmp_path: Path) -> None:
        (tmp_path / "specs").mkdir()
        config = Configuration(
            max_task_retries=2,
            specs_directory=str(tmp_path / "specs"),
        )
        executor = FakeAgentExecutor()

        reconciler = create_reconciler(config, tmp_path, executor=executor)

        assert reconciler._max_task_retries == 2

    def test_propagates_max_concurrent_tasks(self, tmp_path: Path) -> None:
        (tmp_path / "specs").mkdir()
        config = Configuration(
            max_concurrent_tasks=3,
            specs_directory=str(tmp_path / "specs"),
        )
        executor = FakeAgentExecutor()

        reconciler = create_reconciler(config, tmp_path, executor=executor)

        assert reconciler._max_concurrent_tasks == 3

    def test_propagates_cycle_interval(self, tmp_path: Path) -> None:
        (tmp_path / "specs").mkdir()
        config = Configuration(
            cycle_interval_seconds=60,
            specs_directory=str(tmp_path / "specs"),
        )
        executor = FakeAgentExecutor()

        reconciler = create_reconciler(config, tmp_path, executor=executor)

        assert reconciler._cycle_interval_seconds == 60

    def test_propagates_max_integration_retries(self, tmp_path: Path) -> None:
        (tmp_path / "specs").mkdir()
        config = Configuration(
            max_integration_retries=5,
            specs_directory=str(tmp_path / "specs"),
        )
        executor = FakeAgentExecutor()

        reconciler = create_reconciler(config, tmp_path, executor=executor)

        assert reconciler._max_integration_retries == 5

    def test_propagates_max_redecompositions(self, tmp_path: Path) -> None:
        (tmp_path / "specs").mkdir()
        config = Configuration(
            max_redecompositions=2,
            specs_directory=str(tmp_path / "specs"),
        )
        executor = FakeAgentExecutor()

        reconciler = create_reconciler(config, tmp_path, executor=executor)

        assert reconciler._max_redecompositions == 2

    def test_observer_defaults_to_null_probe(self, tmp_path: Path) -> None:
        (tmp_path / "specs").mkdir()
        config = Configuration(specs_directory=str(tmp_path / "specs"))
        executor = FakeAgentExecutor()

        reconciler = create_reconciler(config, tmp_path, executor=executor)

        assert isinstance(reconciler._observer, NullProbe)

    def test_wires_git_plan_store(self, tmp_path: Path) -> None:
        (tmp_path / "specs").mkdir()
        config = Configuration(
            plan_branch="custom/plan",
            plan_file="state.json",
            specs_directory=str(tmp_path / "specs"),
        )
        executor = FakeAgentExecutor()

        reconciler = create_reconciler(config, tmp_path, executor=executor)

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
        executor = FakeAgentExecutor()

        reconciler = create_reconciler(config, tmp_path, executor=executor)

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
        executor = FakeAgentExecutor()

        reconciler = create_reconciler(config, tmp_path, executor=executor)

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

        reconciler = create_reconciler(config, tmp_path, executor=executor)

        agent_runtime = reconciler._agent_runtime
        assert isinstance(agent_runtime, GitAgentRuntime)
        assert agent_runtime._repo_path == tmp_path
        assert agent_runtime._branch_prefix == "custom/"
        assert agent_runtime._executor is executor
