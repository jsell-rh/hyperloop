"""Tests for four fixes: routing mismatch, delete_task ghosts, PhaseStep validation, World docs.

Fix 1: CompositeStepExecutor routes on the step names produced by extract_role().
Fix 2: delete_task removes files from state branch, not empty blobs.
Fix 3: PhaseStep.__post_init__ validates run string format at construction.
Fix 4: World docstring documents workers invariant.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from hyperloop.adapters.step_executor.composite import CompositeStepExecutor
from hyperloop.domain.model import (
    PhaseStep,
    StepOutcome,
    StepResult,
    StepType,
    Task,
    TaskStatus,
    World,
)

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _task(
    id: str = "task-001",
    pr: str | None = "https://github.com/org/repo/pull/1",
    branch: str | None = "hyperloop/task-001",
) -> Task:
    return Task(
        id=id,
        title=f"Task {id}",
        spec_ref=f"specs/{id}.md",
        status=TaskStatus.IN_PROGRESS,
        phase=None,
        deps=(),
        round=0,
        branch=branch,
        pr=pr,
    )


def _init_repo(path: Path) -> None:
    """Create a git repo with an initial empty commit on main."""
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@test.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "--no-verify", "--allow-empty", "-m", "init"],
        check=True,
        capture_output=True,
    )


def _git(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(path), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Fix 1: Routing mismatch — CompositeStepExecutor routes on actual step names
# ---------------------------------------------------------------------------


class _FakeStep:
    """Minimal step handler that records calls and returns ADVANCE."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(self, task: Task, step_name: str, args: dict[str, object]) -> StepResult:
        self.calls.append(step_name)
        return StepResult(outcome=StepOutcome.ADVANCE, detail="ok")


class TestCompositeRoutingFix:
    """CompositeStepExecutor must route on the step names that extract_role() produces."""

    def test_routes_merge_step_name(self) -> None:
        """'action merge' in process.yaml produces step_name='merge' via extract_role()."""
        fake_merge = _FakeStep()
        composite = CompositeStepExecutor(merge=fake_merge)  # type: ignore[arg-type]

        result = composite.execute(_task(), "merge", {})

        assert result.outcome == StepOutcome.ADVANCE
        assert fake_merge.calls == ["merge"]

    def test_routes_mark_ready_step_name(self) -> None:
        """'action mark-ready' produces step_name='mark-ready'."""
        fake_mark_ready = _FakeStep()
        composite = CompositeStepExecutor(mark_ready=fake_mark_ready)  # type: ignore[arg-type]

        result = composite.execute(_task(), "mark-ready", {})

        assert result.outcome == StepOutcome.ADVANCE
        assert fake_mark_ready.calls == ["mark-ready"]

    def test_routes_post_comment_step_name(self) -> None:
        """'action post-comment' produces step_name='post-comment'."""
        fake_post_comment = _FakeStep()
        composite = CompositeStepExecutor(post_comment=fake_post_comment)  # type: ignore[arg-type]

        result = composite.execute(_task(), "post-comment", {})

        assert result.outcome == StepOutcome.ADVANCE
        assert fake_post_comment.calls == ["post-comment"]

    def test_unknown_step_still_returns_retry(self) -> None:
        composite = CompositeStepExecutor()

        result = composite.execute(_task(), "unknown-action", {})

        assert result.outcome == StepOutcome.RETRY
        assert "Unknown step" in result.detail

    def test_routes_feedback_step_name(self) -> None:
        fake_feedback = _FakeStep()
        composite = CompositeStepExecutor(feedback=fake_feedback)  # type: ignore[arg-type]

        result = composite.execute(_task(), "feedback", {})

        assert result.outcome == StepOutcome.ADVANCE
        assert fake_feedback.calls == ["feedback"]


# ---------------------------------------------------------------------------
# Fix 2: delete_task removes files, not empty blobs
# ---------------------------------------------------------------------------


class TestDeleteTaskRemovesFiles:
    """delete_task must remove the file from the state branch, not leave an empty blob."""

    def test_deleted_task_not_in_world_after_persist(self, tmp_path: Path) -> None:
        from hyperloop.adapters.git.state import GitStateStore

        _init_repo(tmp_path)
        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()

        task = Task(
            id="task-to-delete",
            title="Doomed task",
            spec_ref="specs/doomed.md",
            status=TaskStatus.COMPLETED,
            phase=None,
            deps=(),
            round=3,
            branch=None,
            pr=None,
        )
        store.add_task(task)
        store.persist("add task")

        # Verify it exists
        world = store.get_world()
        assert "task-to-delete" in world.tasks

        # Delete and persist
        store.delete_task("task-to-delete")
        store.persist("delete task")

        # Verify removed from world
        world = store.get_world()
        assert "task-to-delete" not in world.tasks

    def test_deleted_task_file_not_in_tree(self, tmp_path: Path) -> None:
        from hyperloop.adapters.git.state import GitStateStore

        _init_repo(tmp_path)
        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()

        task = Task(
            id="task-ghost",
            title="Ghost task",
            spec_ref="specs/ghost.md",
            status=TaskStatus.COMPLETED,
            phase=None,
            deps=(),
            round=0,
            branch=None,
            pr=None,
        )
        store.add_task(task)
        store.persist("add task")

        # Verify file exists on branch
        tree = _git(tmp_path, "ls-tree", "-r", "--name-only", "hyperloop/state")
        assert ".hyperloop/state/tasks/task-ghost.md" in tree

        # Delete and persist
        store.delete_task("task-ghost")
        store.persist("delete ghost task")

        # File must be GONE from the tree, not an empty blob
        tree = _git(tmp_path, "ls-tree", "-r", "--name-only", "hyperloop/state")
        assert ".hyperloop/state/tasks/task-ghost.md" not in tree

    def test_deleted_task_raises_key_error_on_get(self, tmp_path: Path) -> None:
        from hyperloop.adapters.git.state import GitStateStore

        _init_repo(tmp_path)
        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()

        task = Task(
            id="task-gone",
            title="Gone task",
            spec_ref="specs/gone.md",
            status=TaskStatus.COMPLETED,
            phase=None,
            deps=(),
            round=0,
            branch=None,
            pr=None,
        )
        store.add_task(task)
        store.persist("add task")

        store.delete_task("task-gone")
        store.persist("delete task")

        # New store instance should not find the task
        store2 = GitStateStore(repo_path=tmp_path)
        store2.bootstrap()
        with pytest.raises(KeyError):
            store2.get_task("task-gone")

    def test_delete_and_write_in_same_persist(self, tmp_path: Path) -> None:
        """Deleting one task while writing another in the same persist works."""
        from hyperloop.adapters.git.state import GitStateStore

        _init_repo(tmp_path)
        store = GitStateStore(repo_path=tmp_path)
        store.bootstrap()

        task1 = Task(
            id="task-keep",
            title="Keep me",
            spec_ref="specs/keep.md",
            status=TaskStatus.IN_PROGRESS,
            phase=None,
            deps=(),
            round=0,
            branch=None,
            pr=None,
        )
        task2 = Task(
            id="task-delete",
            title="Delete me",
            spec_ref="specs/delete.md",
            status=TaskStatus.COMPLETED,
            phase=None,
            deps=(),
            round=0,
            branch=None,
            pr=None,
        )
        store.add_task(task1)
        store.add_task(task2)
        store.persist("add both")

        # Delete one, keep the other
        store.delete_task("task-delete")
        store.transition_task("task-keep", TaskStatus.COMPLETED, None)
        store.persist("mixed operations")

        world = store.get_world()
        assert "task-keep" in world.tasks
        assert "task-delete" not in world.tasks


# ---------------------------------------------------------------------------
# Fix 3: PhaseStep __post_init__ validation
# ---------------------------------------------------------------------------


class TestPhaseStepValidation:
    """PhaseStep must validate run string format at construction time."""

    def test_valid_run_string_accepted(self) -> None:
        step = PhaseStep(run="agent implementer", on_pass="verify", on_fail="implement")
        assert step.step_type == StepType.AGENT
        assert step.target == "implementer"

    def test_single_token_run_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="<type> <target>"):
            PhaseStep(run="agentimplementer", on_pass="verify", on_fail="implement")

    def test_empty_run_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="<type> <target>"):
            PhaseStep(run="", on_pass="verify", on_fail="implement")

    def test_unknown_step_type_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown step type"):
            PhaseStep(run="unknown foo", on_pass="done", on_fail="start")

    def test_action_step_type_property(self) -> None:
        step = PhaseStep(run="action merge", on_pass="done", on_fail="implement")
        assert step.step_type == StepType.ACTION
        assert step.target == "merge"

    def test_signal_step_type_property(self) -> None:
        step = PhaseStep(run="signal human-approval", on_pass="merge", on_fail="implement")
        assert step.step_type == StepType.SIGNAL
        assert step.target == "human-approval"

    def test_check_step_type_property(self) -> None:
        step = PhaseStep(run="check ci-status", on_pass="merge", on_fail="implement")
        assert step.step_type == StepType.CHECK
        assert step.target == "ci-status"

    def test_step_type_cached_property_consistent(self) -> None:
        step = PhaseStep(run="agent verifier", on_pass="merge", on_fail="implement")
        assert step.step_type is step.step_type  # same enum member
        assert step.target == step.target

    def test_frozen_dataclass_still_works(self) -> None:
        step = PhaseStep(run="agent implementer", on_pass="verify", on_fail="implement")
        with pytest.raises(AttributeError):
            step.run = "agent other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Fix 4: World docstring documents workers invariant
# ---------------------------------------------------------------------------


class TestWorldDocstring:
    """World must have a docstring documenting the workers invariant."""

    def test_world_has_docstring(self) -> None:
        assert World.__doc__ is not None

    def test_docstring_mentions_workers_empty(self) -> None:
        assert "workers" in World.__doc__  # type: ignore[operator]
        assert "empty" in World.__doc__  # type: ignore[operator]

    def test_docstring_mentions_build_world(self) -> None:
        assert "build_world" in World.__doc__  # type: ignore[operator]
