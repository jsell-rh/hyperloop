"""Tests for hardened task file parsing and ingestion.

Covers:
- Empty frontmatter raises ValueError (Bug 4)
- TypeError from None frontmatter is caught during ingestion (Bug 1)
- Parse failures return failed paths for observability (Bug 2)
- Files are NOT deleted if persist fails (Bug 3)
- Underscore status variants are accepted (Bug 5)
- Alternative field names are normalized (Bug 6)
"""

from __future__ import annotations

from textwrap import dedent

import pytest

from hyperloop.adapters.git.state import (
    _frontmatter_to_task,
    _normalize_frontmatter,
    _parse_task_file,
)
from hyperloop.domain.model import TaskStatus

# ---------------------------------------------------------------------------
# Bug 4: Empty frontmatter guard
# ---------------------------------------------------------------------------


class TestParseTaskFileEmptyFrontmatter:
    def test_empty_frontmatter_raises_value_error(self) -> None:
        content = "---\n\n---\n"
        with pytest.raises(ValueError, match="Empty YAML frontmatter"):
            _parse_task_file(content)

    def test_whitespace_only_frontmatter_raises_value_error(self) -> None:
        content = "---\n   \n---\n"
        with pytest.raises(ValueError, match="Empty YAML frontmatter"):
            _parse_task_file(content)

    def test_valid_frontmatter_still_parses(self) -> None:
        content = dedent("""\
            ---
            id: task-001
            title: Test task
            spec_ref: specs/test.md
            status: not-started
            phase: null
            deps: []
            round: 0
            branch: null
            pr: null
            ---
        """)
        fm = _parse_task_file(content)
        assert fm["id"] == "task-001"


# ---------------------------------------------------------------------------
# Bug 5: Status normalization — underscore vs hyphen
# ---------------------------------------------------------------------------


class TestStatusNormalization:
    def test_hyphenated_not_started(self) -> None:
        fm = _make_fm(status="not-started")
        task = _frontmatter_to_task(fm)
        assert task.status == TaskStatus.NOT_STARTED

    def test_underscored_not_started(self) -> None:
        fm = _make_fm(status="not_started")
        task = _frontmatter_to_task(fm)
        assert task.status == TaskStatus.NOT_STARTED

    def test_hyphenated_in_progress(self) -> None:
        fm = _make_fm(status="in-progress")
        task = _frontmatter_to_task(fm)
        assert task.status == TaskStatus.IN_PROGRESS

    def test_underscored_in_progress(self) -> None:
        fm = _make_fm(status="in_progress")
        task = _frontmatter_to_task(fm)
        assert task.status == TaskStatus.IN_PROGRESS

    def test_complete_accepted(self) -> None:
        fm = _make_fm(status="complete")
        task = _frontmatter_to_task(fm)
        assert task.status == TaskStatus.COMPLETED

    def test_completed_accepted(self) -> None:
        fm = _make_fm(status="completed")
        task = _frontmatter_to_task(fm)
        assert task.status == TaskStatus.COMPLETED

    def test_failed_accepted(self) -> None:
        fm = _make_fm(status="failed")
        task = _frontmatter_to_task(fm)
        assert task.status == TaskStatus.FAILED


# ---------------------------------------------------------------------------
# Bug 6: Field name normalization for LLM-written files
# ---------------------------------------------------------------------------


class TestFieldNormalization:
    def test_name_maps_to_title(self) -> None:
        result = _normalize_frontmatter({"name": "My Task"})
        assert "title" in result
        assert result["title"] == "My Task"
        assert "name" not in result

    def test_spec_maps_to_spec_ref(self) -> None:
        result = _normalize_frontmatter({"spec": "specs/auth.md"})
        assert "spec_ref" in result
        assert result["spec_ref"] == "specs/auth.md"

    def test_spec_path_maps_to_spec_ref(self) -> None:
        result = _normalize_frontmatter({"spec_path": "specs/auth.md"})
        assert "spec_ref" in result

    def test_specification_maps_to_spec_ref(self) -> None:
        result = _normalize_frontmatter({"specification": "specs/auth.md"})
        assert "spec_ref" in result

    def test_dependencies_maps_to_deps(self) -> None:
        result = _normalize_frontmatter({"dependencies": ["task-001"]})
        assert "deps" in result
        assert result["deps"] == ["task-001"]

    def test_depends_on_maps_to_deps(self) -> None:
        result = _normalize_frontmatter({"depends_on": ["task-002"]})
        assert "deps" in result

    def test_depends_maps_to_deps(self) -> None:
        result = _normalize_frontmatter({"depends": ["task-003"]})
        assert "deps" in result

    def test_canonical_fields_unchanged(self) -> None:
        fm: dict[str, object] = {
            "id": "task-001",
            "title": "My Task",
            "spec_ref": "specs/foo.md",
            "status": "not-started",
            "deps": [],
        }
        result = _normalize_frontmatter(fm)
        assert result == fm

    def test_frontmatter_to_task_with_aliased_fields(self) -> None:
        fm: dict[str, object] = {
            "id": "task-099",
            "name": "Aliased Title",
            "spec": "specs/alias.md",
            "status": "not-started",
            "phase": None,
            "dependencies": ["task-001"],
            "round": 0,
            "branch": None,
            "pr": None,
        }
        task = _frontmatter_to_task(fm)
        assert task.title == "Aliased Title"
        assert task.spec_ref == "specs/alias.md"
        assert task.deps == ("task-001",)


# ---------------------------------------------------------------------------
# Bug 1 + 2: TypeError caught, malformed files skipped gracefully
# ---------------------------------------------------------------------------


class TestIngestWorkingTreeTasks:
    def test_none_frontmatter_does_not_crash(self, tmp_path: pytest.TempPathFactory) -> None:
        """Empty frontmatter yields None from yaml.safe_load; ingestion should not crash."""
        from hyperloop.cycle.intake import _ingest_working_tree_tasks
        from tests.fakes.state import InMemoryStateStore

        state = InMemoryStateStore()
        # Give the state store a _repo attribute so the function proceeds
        state._repo = str(tmp_path)  # type: ignore[attr-defined]

        tasks_dir = tmp_path / ".hyperloop" / "state" / "tasks"  # type: ignore[operator]
        tasks_dir.mkdir(parents=True)

        # Write a task file with empty frontmatter (yaml.safe_load returns None)
        (tasks_dir / "bad-task.md").write_text("---\n\n---\n")

        # Should NOT raise TypeError
        _ingest_working_tree_tasks(state)
        # Malformed files are skipped (not ingested, not deleted)
        assert (tasks_dir / "bad-task.md").exists()
        # No tasks added
        world = state.get_world()
        assert len(world.tasks) == 0

    def test_malformed_files_skipped(self, tmp_path: pytest.TempPathFactory) -> None:
        """Parse failures are silently skipped by ingest_external_tasks."""
        from hyperloop.cycle.intake import _ingest_working_tree_tasks
        from tests.fakes.state import InMemoryStateStore

        state = InMemoryStateStore()
        state._repo = str(tmp_path)  # type: ignore[attr-defined]

        tasks_dir = tmp_path / ".hyperloop" / "state" / "tasks"  # type: ignore[operator]
        tasks_dir.mkdir(parents=True)

        # Write an unparseable task file
        (tasks_dir / "garbled.md").write_text("---\n\n---\n")

        _ingest_working_tree_tasks(state)
        # No tasks added, malformed file remains
        world = state.get_world()
        assert len(world.tasks) == 0
        assert (tasks_dir / "garbled.md").exists()

    def test_successful_parse_adds_task(self, tmp_path: pytest.TempPathFactory) -> None:
        """Successfully parsed tasks are added to the store and source files deleted."""
        from hyperloop.cycle.intake import _ingest_working_tree_tasks
        from tests.fakes.state import InMemoryStateStore

        state = InMemoryStateStore()
        state._repo = str(tmp_path)  # type: ignore[attr-defined]

        tasks_dir = tmp_path / ".hyperloop" / "state" / "tasks"  # type: ignore[operator]
        tasks_dir.mkdir(parents=True)

        good_content = dedent("""\
            ---
            id: good-task
            title: Good task
            spec_ref: specs/good.md
            status: not-started
            phase: null
            deps: []
            round: 0
            branch: null
            pr: null
            ---
        """)
        (tasks_dir / "good-task.md").write_text(good_content)

        _ingest_working_tree_tasks(state)
        world = state.get_world()
        assert "good-task" in world.tasks


# ---------------------------------------------------------------------------
# Bug 3: Delete-before-persist
# ---------------------------------------------------------------------------


class TestDeleteAfterPersist:
    def test_files_not_deleted_if_persist_fails(self, tmp_path: pytest.TempPathFactory) -> None:
        """Task files must survive if state.persist() raises."""
        from hyperloop.cycle.intake import _ingest_working_tree_tasks
        from tests.fakes.state import InMemoryStateStore

        class FailingPersistStore(InMemoryStateStore):
            def persist(self, message: str) -> None:
                msg = "Simulated persist failure"
                raise RuntimeError(msg)

        state = FailingPersistStore()
        state._repo = str(tmp_path)  # type: ignore[attr-defined]

        tasks_dir = tmp_path / ".hyperloop" / "state" / "tasks"  # type: ignore[operator]
        tasks_dir.mkdir(parents=True)

        good_content = dedent("""\
            ---
            id: persist-test
            title: Persist test task
            spec_ref: specs/persist.md
            status: not-started
            phase: null
            deps: []
            round: 0
            branch: null
            pr: null
            ---
        """)
        (tasks_dir / "persist-test.md").write_text(good_content)

        with pytest.raises(RuntimeError, match="Simulated persist failure"):
            _ingest_working_tree_tasks(state)

        # File must still exist because persist failed
        assert (tasks_dir / "persist-test.md").exists()

    def test_files_deleted_after_successful_persist(self, tmp_path: pytest.TempPathFactory) -> None:
        """Task files should be removed after a successful persist."""
        from hyperloop.cycle.intake import _ingest_working_tree_tasks
        from tests.fakes.state import InMemoryStateStore

        state = InMemoryStateStore()
        state._repo = str(tmp_path)  # type: ignore[attr-defined]

        tasks_dir = tmp_path / ".hyperloop" / "state" / "tasks"  # type: ignore[operator]
        tasks_dir.mkdir(parents=True)

        good_content = dedent("""\
            ---
            id: delete-test
            title: Delete test task
            spec_ref: specs/delete.md
            status: not-started
            phase: null
            deps: []
            round: 0
            branch: null
            pr: null
            ---
        """)
        (tasks_dir / "delete-test.md").write_text(good_content)

        _ingest_working_tree_tasks(state)

        # File should be deleted after successful persist
        assert not (tasks_dir / "delete-test.md").exists()

    def test_malformed_file_not_deleted_good_file_deleted(
        self, tmp_path: pytest.TempPathFactory
    ) -> None:
        """Only successfully ingested files are deleted; malformed files remain."""
        from hyperloop.cycle.intake import _ingest_working_tree_tasks
        from tests.fakes.state import InMemoryStateStore

        state = InMemoryStateStore()
        state._repo = str(tmp_path)  # type: ignore[attr-defined]

        tasks_dir = tmp_path / ".hyperloop" / "state" / "tasks"  # type: ignore[operator]
        tasks_dir.mkdir(parents=True)

        # One bad, one good
        (tasks_dir / "bad-file.md").write_text("---\n\n---\n")
        good_content = dedent("""\
            ---
            id: good-one
            title: Good one
            spec_ref: specs/g.md
            status: not-started
            phase: null
            deps: []
            round: 0
            branch: null
            pr: null
            ---
        """)
        (tasks_dir / "good-one.md").write_text(good_content)

        _ingest_working_tree_tasks(state)
        # Good file deleted after successful ingestion
        assert not (tasks_dir / "good-one.md").exists()
        # Bad file remains (was not ingested, so not in the cleanup list)
        assert (tasks_dir / "bad-file.md").exists()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fm(
    *,
    status: str = "not-started",
    task_id: str = "task-001",
    title: str = "Test task",
    spec_ref: str = "specs/test.md",
) -> dict[str, object]:
    return {
        "id": task_id,
        "title": title,
        "spec_ref": spec_ref,
        "status": status,
        "phase": None,
        "deps": [],
        "round": 0,
        "branch": None,
        "pr": None,
    }
