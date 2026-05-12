from __future__ import annotations

import pytest

from hyperloop.reconciliation.models.merge_result import (
    MergeOutcome,
    MergeResult,
)
from tests.reconciliation.fakes.fake_workspace_manager import (
    FakeWorkspaceManager,
)


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


class TestIntegrate:
    def test_returns_integration_identifier(self) -> None:
        manager = FakeWorkspaceManager()
        manager.create_delivery_workspace("abc123")

        integration_id = manager.integrate("abc123", "specs/auth.spec.md")

        assert isinstance(integration_id, str)
        assert len(integration_id) > 0

    def test_records_integration_request(self) -> None:
        manager = FakeWorkspaceManager()
        manager.create_delivery_workspace("abc123")

        manager.integrate("abc123", "specs/auth.spec.md")

        assert len(manager.integrations) == 1
        assert manager.integrations[0] == ("abc123", "specs/auth.spec.md")

    def test_returns_configured_integration_id(self) -> None:
        manager = FakeWorkspaceManager()
        manager.create_delivery_workspace("abc123")
        manager.set_integration_id("abc123", "https://github.com/org/repo/pull/42")

        integration_id = manager.integrate("abc123", "specs/auth.spec.md")

        assert integration_id == "https://github.com/org/repo/pull/42"

    def test_requires_delivery_workspace(self) -> None:
        manager = FakeWorkspaceManager()

        with pytest.raises(ValueError, match="No delivery workspace"):
            manager.integrate("abc123", "specs/auth.spec.md")


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
