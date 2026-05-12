from __future__ import annotations

import inspect
from typing import get_type_hints

from hyperloop.reconciliation.models.merge_result import (
    MergeOutcome,
    MergeResult,
)
from hyperloop.reconciliation.ports.workspace_manager import WorkspaceManager


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
