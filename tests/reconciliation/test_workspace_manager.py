from __future__ import annotations

import inspect
from typing import get_type_hints

import pytest

from hyperloop.reconciliation.models.merge_result import (
    MergeOutcome,
    MergeResult,
)
from hyperloop.reconciliation.ports.workspace_manager import WorkspaceManager
from tests.reconciliation.fakes.fake_workspace_manager import (
    FakeWorkspaceManager,
)


class TestWorkspaceManagerProtocol:
    def test_defines_create_delivery_workspace(self) -> None:
        assert hasattr(WorkspaceManager, "create_delivery_workspace")

    def test_defines_create_task_workspace(self) -> None:
        assert hasattr(WorkspaceManager, "create_task_workspace")

    def test_defines_create_verification_workspace(self) -> None:
        assert hasattr(WorkspaceManager, "create_verification_workspace")

    def test_defines_merge_task(self) -> None:
        assert hasattr(WorkspaceManager, "merge_task")

    def test_defines_integrate(self) -> None:
        assert hasattr(WorkspaceManager, "integrate")

    def test_defines_cleanup(self) -> None:
        assert hasattr(WorkspaceManager, "cleanup")

    def test_defines_cleanup_verification(self) -> None:
        assert hasattr(WorkspaceManager, "cleanup_verification")

    def test_no_extra_methods(self) -> None:
        methods = {
            name
            for name, _ in inspect.getmembers(
                WorkspaceManager, predicate=inspect.isfunction
            )
            if not name.startswith("_")
        }
        assert methods == {
            "create_delivery_workspace",
            "create_task_workspace",
            "create_verification_workspace",
            "merge_task",
            "integrate",
            "poll_integration",
            "rebase_delivery",
            "cleanup",
            "cleanup_verification",
        }

    def test_create_delivery_workspace_accepts_blob_sha(self) -> None:
        hints = get_type_hints(WorkspaceManager.create_delivery_workspace)
        assert hints["blob_sha"] is str

    def test_create_delivery_workspace_returns_str(self) -> None:
        hints = get_type_hints(WorkspaceManager.create_delivery_workspace)
        assert hints["return"] is str

    def test_create_task_workspace_accepts_blob_sha(self) -> None:
        hints = get_type_hints(WorkspaceManager.create_task_workspace)
        assert hints["blob_sha"] is str

    def test_create_task_workspace_accepts_task_id(self) -> None:
        hints = get_type_hints(WorkspaceManager.create_task_workspace)
        assert hints["task_id"] is int

    def test_create_task_workspace_accepts_briefing(self) -> None:
        hints = get_type_hints(WorkspaceManager.create_task_workspace)
        assert hints["briefing"] is str

    def test_create_task_workspace_returns_str(self) -> None:
        hints = get_type_hints(WorkspaceManager.create_task_workspace)
        assert hints["return"] is str

    def test_create_verification_workspace_accepts_blob_sha(self) -> None:
        hints = get_type_hints(WorkspaceManager.create_verification_workspace)
        assert hints["blob_sha"] is str

    def test_create_verification_workspace_returns_str(self) -> None:
        hints = get_type_hints(WorkspaceManager.create_verification_workspace)
        assert hints["return"] is str

    def test_merge_task_accepts_blob_sha(self) -> None:
        hints = get_type_hints(WorkspaceManager.merge_task)
        assert hints["blob_sha"] is str

    def test_merge_task_accepts_task_id(self) -> None:
        hints = get_type_hints(WorkspaceManager.merge_task)
        assert hints["task_id"] is int

    def test_merge_task_returns_merge_result(self) -> None:
        hints = get_type_hints(WorkspaceManager.merge_task)
        assert hints["return"] is MergeResult

    def test_integrate_accepts_blob_sha(self) -> None:
        hints = get_type_hints(WorkspaceManager.integrate)
        assert hints["blob_sha"] is str

    def test_integrate_accepts_spec_path(self) -> None:
        hints = get_type_hints(WorkspaceManager.integrate)
        assert hints["spec_path"] is str

    def test_integrate_returns_str(self) -> None:
        hints = get_type_hints(WorkspaceManager.integrate)
        assert hints["return"] is str

    def test_cleanup_accepts_blob_sha(self) -> None:
        hints = get_type_hints(WorkspaceManager.cleanup)
        assert hints["blob_sha"] is str

    def test_cleanup_returns_none(self) -> None:
        hints = get_type_hints(WorkspaceManager.cleanup)
        assert hints["return"] is type(None)

    def test_cleanup_verification_accepts_blob_sha(self) -> None:
        hints = get_type_hints(WorkspaceManager.cleanup_verification)
        assert hints["blob_sha"] is str

    def test_cleanup_verification_returns_none(self) -> None:
        hints = get_type_hints(WorkspaceManager.cleanup_verification)
        assert hints["return"] is type(None)

    def test_port_imports_only_domain_types(self) -> None:
        import hyperloop.reconciliation.ports.workspace_manager as module

        source = inspect.getsource(module)
        assert "adapters" not in source


class TestMergeOutcome:
    def test_values(self) -> None:
        assert MergeOutcome.SUCCESS == "Success"
        assert MergeOutcome.CONFLICT == "Conflict"

    def test_is_str_enum(self) -> None:
        assert isinstance(MergeOutcome.SUCCESS, str)


class TestMergeResult:
    def test_success_result(self) -> None:
        result = MergeResult(outcome=MergeOutcome.SUCCESS)
        assert result.outcome == MergeOutcome.SUCCESS
        assert result.conflict_details is None

    def test_conflict_result(self) -> None:
        result = MergeResult(
            outcome=MergeOutcome.CONFLICT,
            conflict_details="conflicting changes in auth.py",
        )
        assert result.outcome == MergeOutcome.CONFLICT
        assert result.conflict_details == "conflicting changes in auth.py"

    def test_is_frozen(self) -> None:
        result = MergeResult(outcome=MergeOutcome.SUCCESS)
        try:
            result.outcome = MergeOutcome.CONFLICT  # type: ignore[misc]
            assert False, "should have raised"
        except Exception:
            pass


class TestCreateDeliveryWorkspace:
    def test_creates_workspace(self) -> None:
        manager = FakeWorkspaceManager()

        workspace_id = manager.create_delivery_workspace("abc123")

        assert isinstance(workspace_id, str)
        assert manager.has_delivery_workspace("abc123")

    def test_returns_workspace_identifier(self) -> None:
        manager = FakeWorkspaceManager()

        workspace_id = manager.create_delivery_workspace("abc123")

        assert workspace_id == "delivery/abc123"

    def test_idempotent(self) -> None:
        manager = FakeWorkspaceManager()

        first = manager.create_delivery_workspace("abc123")
        second = manager.create_delivery_workspace("abc123")

        assert first == second
        assert manager.has_delivery_workspace("abc123")

    def test_separate_workspaces_per_blob_sha(self) -> None:
        manager = FakeWorkspaceManager()

        ws1 = manager.create_delivery_workspace("abc123")
        ws2 = manager.create_delivery_workspace("def456")

        assert ws1 != ws2
        assert manager.has_delivery_workspace("abc123")
        assert manager.has_delivery_workspace("def456")


class TestCreateTaskWorkspace:
    def test_creates_workspace(self) -> None:
        manager = FakeWorkspaceManager()
        manager.create_delivery_workspace("abc123")

        workspace_id = manager.create_task_workspace("abc123", 5, "implement login")

        assert isinstance(workspace_id, str)
        assert manager.has_task_workspace("abc123", 5)

    def test_returns_workspace_identifier(self) -> None:
        manager = FakeWorkspaceManager()
        manager.create_delivery_workspace("abc123")

        workspace_id = manager.create_task_workspace("abc123", 5, "implement login")

        assert workspace_id == "task/abc123/5"

    def test_requires_delivery_workspace(self) -> None:
        manager = FakeWorkspaceManager()

        with pytest.raises(ValueError, match="No delivery workspace"):
            manager.create_task_workspace("abc123", 5, "implement login")

    def test_records_briefing(self) -> None:
        manager = FakeWorkspaceManager()
        manager.create_delivery_workspace("abc123")

        manager.create_task_workspace(
            "abc123", 5, "Task 5: implement login\nSpec: auth.spec.md"
        )

        briefing = manager.get_task_briefing("abc123", 5)
        assert "implement login" in briefing
        assert "auth.spec.md" in briefing

    def test_multiple_tasks_for_same_spec(self) -> None:
        manager = FakeWorkspaceManager()
        manager.create_delivery_workspace("abc123")

        ws1 = manager.create_task_workspace("abc123", 5, "task 5")
        ws2 = manager.create_task_workspace("abc123", 6, "task 6")

        assert ws1 != ws2
        assert manager.has_task_workspace("abc123", 5)
        assert manager.has_task_workspace("abc123", 6)

    def test_idempotent(self) -> None:
        manager = FakeWorkspaceManager()
        manager.create_delivery_workspace("abc123")

        first = manager.create_task_workspace("abc123", 5, "task 5")
        second = manager.create_task_workspace("abc123", 5, "task 5")

        assert first == second
        assert manager.has_task_workspace("abc123", 5)


class TestCreateVerificationWorkspace:
    def test_creates_workspace(self) -> None:
        manager = FakeWorkspaceManager()
        manager.create_delivery_workspace("abc123")

        workspace_id = manager.create_verification_workspace("abc123")

        assert isinstance(workspace_id, str)
        assert manager.has_verification_workspace("abc123")

    def test_returns_workspace_identifier(self) -> None:
        manager = FakeWorkspaceManager()
        manager.create_delivery_workspace("abc123")

        workspace_id = manager.create_verification_workspace("abc123")

        assert workspace_id == "verification/abc123"

    def test_requires_delivery_workspace(self) -> None:
        manager = FakeWorkspaceManager()

        with pytest.raises(ValueError, match="No delivery workspace"):
            manager.create_verification_workspace("abc123")

    def test_recreates_on_second_call(self) -> None:
        manager = FakeWorkspaceManager()
        manager.create_delivery_workspace("abc123")

        first = manager.create_verification_workspace("abc123")
        second = manager.create_verification_workspace("abc123")

        assert first == second
        assert manager.has_verification_workspace("abc123")


class TestMergeTask:
    def test_success_removes_task_workspace(self) -> None:
        manager = FakeWorkspaceManager()
        manager.create_delivery_workspace("abc123")
        manager.create_task_workspace("abc123", 5, "task 5")

        result = manager.merge_task("abc123", 5)

        assert result.outcome == MergeOutcome.SUCCESS
        assert not manager.has_task_workspace("abc123", 5)

    def test_defaults_to_success(self) -> None:
        manager = FakeWorkspaceManager()
        manager.create_delivery_workspace("abc123")
        manager.create_task_workspace("abc123", 5, "task 5")

        result = manager.merge_task("abc123", 5)

        assert result.outcome == MergeOutcome.SUCCESS

    def test_conflict_preserves_task_workspace(self) -> None:
        manager = FakeWorkspaceManager()
        manager.create_delivery_workspace("abc123")
        manager.create_task_workspace("abc123", 5, "task 5")
        manager.set_merge_result(
            "abc123",
            5,
            MergeResult(
                outcome=MergeOutcome.CONFLICT,
                conflict_details="conflicting changes in auth.py",
            ),
        )

        result = manager.merge_task("abc123", 5)

        assert result.outcome == MergeOutcome.CONFLICT
        assert result.conflict_details == "conflicting changes in auth.py"
        assert manager.has_task_workspace("abc123", 5)

    def test_requires_task_workspace(self) -> None:
        manager = FakeWorkspaceManager()
        manager.create_delivery_workspace("abc123")

        with pytest.raises(ValueError, match="No task workspace"):
            manager.merge_task("abc123", 5)

    def test_requires_delivery_workspace(self) -> None:
        manager = FakeWorkspaceManager()

        with pytest.raises(ValueError, match="No delivery workspace"):
            manager.merge_task("abc123", 5)


class TestIntegrate:
    def test_returns_integration_identifier(self) -> None:
        manager = FakeWorkspaceManager()
        manager.create_delivery_workspace("abc123")

        integration_id = manager.integrate(
            "abc123", "specs/auth.spec.md", "PR title", "PR body"
        )

        assert isinstance(integration_id, str)
        assert len(integration_id) > 0

    def test_records_integration_request(self) -> None:
        manager = FakeWorkspaceManager()
        manager.create_delivery_workspace("abc123")

        manager.integrate("abc123", "specs/auth.spec.md", "PR title", "PR body")

        assert len(manager.integrations) == 1
        assert manager.integrations[0] == (
            "abc123",
            "specs/auth.spec.md",
            "PR title",
            "PR body",
        )

    def test_returns_configured_integration_id(self) -> None:
        manager = FakeWorkspaceManager()
        manager.create_delivery_workspace("abc123")
        manager.set_integration_id("abc123", "https://github.com/org/repo/pull/42")

        integration_id = manager.integrate(
            "abc123", "specs/auth.spec.md", "PR title", "PR body"
        )

        assert integration_id == "https://github.com/org/repo/pull/42"

    def test_requires_delivery_workspace(self) -> None:
        manager = FakeWorkspaceManager()

        with pytest.raises(ValueError, match="No delivery workspace"):
            manager.integrate("abc123", "specs/auth.spec.md", "PR title", "PR body")


class TestCleanup:
    def test_removes_delivery_workspace(self) -> None:
        manager = FakeWorkspaceManager()
        manager.create_delivery_workspace("abc123")

        manager.cleanup("abc123")

        assert not manager.has_delivery_workspace("abc123")

    def test_removes_all_task_workspaces(self) -> None:
        manager = FakeWorkspaceManager()
        manager.create_delivery_workspace("abc123")
        manager.create_task_workspace("abc123", 5, "task 5")
        manager.create_task_workspace("abc123", 6, "task 6")

        manager.cleanup("abc123")

        assert not manager.has_task_workspace("abc123", 5)
        assert not manager.has_task_workspace("abc123", 6)

    def test_removes_verification_workspace(self) -> None:
        manager = FakeWorkspaceManager()
        manager.create_delivery_workspace("abc123")
        manager.create_verification_workspace("abc123")

        manager.cleanup("abc123")

        assert not manager.has_verification_workspace("abc123")

    def test_does_not_affect_other_specs(self) -> None:
        manager = FakeWorkspaceManager()
        manager.create_delivery_workspace("abc123")
        manager.create_delivery_workspace("def456")
        manager.create_task_workspace("abc123", 5, "task 5")
        manager.create_task_workspace("def456", 7, "task 7")

        manager.cleanup("abc123")

        assert not manager.has_delivery_workspace("abc123")
        assert manager.has_delivery_workspace("def456")
        assert manager.has_task_workspace("def456", 7)

    def test_cleanup_nonexistent_is_noop(self) -> None:
        manager = FakeWorkspaceManager()

        manager.cleanup("nonexistent")

        assert not manager.has_delivery_workspace("nonexistent")

    def test_clears_configured_merge_results(self) -> None:
        manager = FakeWorkspaceManager()
        manager.create_delivery_workspace("abc123")
        manager.create_task_workspace("abc123", 5, "task 5")
        manager.set_merge_result(
            "abc123",
            5,
            MergeResult(outcome=MergeOutcome.CONFLICT, conflict_details="conflict"),
        )

        manager.cleanup("abc123")
        manager.create_delivery_workspace("abc123")
        manager.create_task_workspace("abc123", 5, "task 5 retry")

        result = manager.merge_task("abc123", 5)
        assert result.outcome == MergeOutcome.SUCCESS


class TestCleanupVerification:
    def test_removes_verification_workspace(self) -> None:
        manager = FakeWorkspaceManager()
        manager.create_delivery_workspace("abc123")
        manager.create_verification_workspace("abc123")

        manager.cleanup_verification("abc123")

        assert not manager.has_verification_workspace("abc123")

    def test_preserves_delivery_workspace(self) -> None:
        manager = FakeWorkspaceManager()
        manager.create_delivery_workspace("abc123")
        manager.create_verification_workspace("abc123")

        manager.cleanup_verification("abc123")

        assert manager.has_delivery_workspace("abc123")

    def test_preserves_task_workspaces(self) -> None:
        manager = FakeWorkspaceManager()
        manager.create_delivery_workspace("abc123")
        manager.create_task_workspace("abc123", 5, "task 5")
        manager.create_verification_workspace("abc123")

        manager.cleanup_verification("abc123")

        assert manager.has_task_workspace("abc123", 5)

    def test_cleanup_nonexistent_is_noop(self) -> None:
        manager = FakeWorkspaceManager()

        manager.cleanup_verification("nonexistent")

        assert not manager.has_verification_workspace("nonexistent")
