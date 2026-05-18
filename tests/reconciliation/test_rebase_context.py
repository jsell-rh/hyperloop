from __future__ import annotations

from hyperloop.reconciliation.models.rebase_context import RebaseContext


class TestRebaseContext:
    def test_stores_trunk_changes(self) -> None:
        ctx = RebaseContext(trunk_changes="Modified auth.py with new middleware")
        assert ctx.trunk_changes == "Modified auth.py with new middleware"

    def test_is_frozen(self) -> None:
        ctx = RebaseContext(trunk_changes="changes")
        try:
            ctx.trunk_changes = "other"  # type: ignore[misc]
            raise AssertionError("Expected frozen model to reject mutation")
        except Exception:
            pass
