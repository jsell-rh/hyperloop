"""Contract tests for ingest_external_tasks and list_review_contents on StateStore.

Ensures both InMemoryStateStore and GitStateStore implement the new port
methods identically: ingest_external_tasks scans a directory for task .md
files and adds new tasks; list_review_contents returns raw review content.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from hyperloop.adapters.git.state import GitStateStore
from hyperloop.domain.model import Task, TaskStatus
from tests.fakes.state import InMemoryStateStore

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_TASK_CONTENT = """\
---
id: task-new-1
title: New widget feature
spec_ref: specs/widget.md
status: not-started
phase: null
deps: []
round: 0
branch: null
pr: null
---
"""

VALID_TASK_CONTENT_2 = """\
---
id: task-new-2
title: Another feature
spec_ref: specs/api.md
status: not-started
phase: null
deps: [task-new-1]
round: 0
branch: null
pr: null
---
"""

MALFORMED_CONTENT = """\
This file has no frontmatter at all.
Just some random text.
"""


def _init_git_repo(path: Path) -> None:
    """Create a git repo with an initial empty commit."""
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


def _seed_task() -> Task:
    return Task(
        id="task-001",
        title="Existing task",
        spec_ref="specs/existing.md",
        status=TaskStatus.NOT_STARTED,
        phase=None,
        deps=(),
        round=0,
        branch=None,
        pr=None,
    )


def _make_memory_store(task: Task) -> InMemoryStateStore:
    store = InMemoryStateStore()
    store.add_task(task)
    return store


def _make_git_store(tmp_path: Path) -> GitStateStore:
    _init_git_repo(tmp_path)
    store = GitStateStore(repo_path=tmp_path)
    store.bootstrap()
    task = _seed_task()
    store.add_task(task)
    store.persist("seed task-001")
    return store


@pytest.fixture(params=["memory", "git"])
def state_store(
    request: pytest.FixtureRequest, tmp_path: Path
) -> InMemoryStateStore | GitStateStore:
    task = _seed_task()
    if request.param == "memory":
        return _make_memory_store(task)
    return _make_git_store(tmp_path)


@pytest.fixture(params=["memory", "git"])
def empty_state_store(
    request: pytest.FixtureRequest, tmp_path: Path
) -> InMemoryStateStore | GitStateStore:
    if request.param == "memory":
        return InMemoryStateStore()
    _init_git_repo(tmp_path)
    store = GitStateStore(repo_path=tmp_path)
    store.bootstrap()
    return store


# ---------------------------------------------------------------------------
# ingest_external_tasks contract tests
# ---------------------------------------------------------------------------


class TestIngestExternalTasks:
    """Contract tests: ingest_external_tasks reads .md files and adds new tasks."""

    def test_ingests_valid_task_file(
        self, state_store: InMemoryStateStore | GitStateStore, tmp_path: Path
    ) -> None:
        tasks_dir = tmp_path / "ingest"
        tasks_dir.mkdir(exist_ok=True)
        (tasks_dir / "task-new-1.md").write_text(VALID_TASK_CONTENT)

        ingested = state_store.ingest_external_tasks(tasks_dir)

        assert ingested == ["task-new-1"]
        task = state_store.get_task("task-new-1")
        assert task.title == "New widget feature"
        assert task.spec_ref == "specs/widget.md"
        assert task.status == TaskStatus.NOT_STARTED

    def test_ingests_multiple_files_sorted(
        self, state_store: InMemoryStateStore | GitStateStore, tmp_path: Path
    ) -> None:
        tasks_dir = tmp_path / "ingest"
        tasks_dir.mkdir(exist_ok=True)
        (tasks_dir / "task-new-2.md").write_text(VALID_TASK_CONTENT_2)
        (tasks_dir / "task-new-1.md").write_text(VALID_TASK_CONTENT)

        ingested = state_store.ingest_external_tasks(tasks_dir)

        assert ingested == ["task-new-1", "task-new-2"]

    def test_skips_existing_task_ids(
        self, state_store: InMemoryStateStore | GitStateStore, tmp_path: Path
    ) -> None:
        tasks_dir = tmp_path / "ingest"
        tasks_dir.mkdir(exist_ok=True)
        # task-001 already exists in the store
        existing_content = """\
---
id: task-001
title: Duplicate
spec_ref: specs/dup.md
status: not-started
phase: null
deps: []
round: 0
branch: null
pr: null
---
"""
        (tasks_dir / "task-001.md").write_text(existing_content)

        ingested = state_store.ingest_external_tasks(tasks_dir)

        assert ingested == []
        # Original task is unchanged
        task = state_store.get_task("task-001")
        assert task.title == "Existing task"

    def test_handles_malformed_files_gracefully(
        self, state_store: InMemoryStateStore | GitStateStore, tmp_path: Path
    ) -> None:
        tasks_dir = tmp_path / "ingest"
        tasks_dir.mkdir(exist_ok=True)
        (tasks_dir / "bad-task.md").write_text(MALFORMED_CONTENT)
        (tasks_dir / "task-new-1.md").write_text(VALID_TASK_CONTENT)

        ingested = state_store.ingest_external_tasks(tasks_dir)

        # bad-task is skipped, task-new-1 is ingested
        assert ingested == ["task-new-1"]

    def test_returns_empty_list_for_empty_directory(
        self, state_store: InMemoryStateStore | GitStateStore, tmp_path: Path
    ) -> None:
        tasks_dir = tmp_path / "ingest"
        tasks_dir.mkdir(exist_ok=True)

        ingested = state_store.ingest_external_tasks(tasks_dir)

        assert ingested == []

    def test_does_not_persist(
        self, state_store: InMemoryStateStore | GitStateStore, tmp_path: Path
    ) -> None:
        """Caller is responsible for calling persist() after ingestion."""
        tasks_dir = tmp_path / "ingest"
        tasks_dir.mkdir(exist_ok=True)
        (tasks_dir / "task-new-1.md").write_text(VALID_TASK_CONTENT)

        state_store.ingest_external_tasks(tasks_dir)

        if isinstance(state_store, InMemoryStateStore):
            assert "ingest" not in " ".join(state_store.committed_messages)

    def test_does_not_delete_source_files(
        self, state_store: InMemoryStateStore | GitStateStore, tmp_path: Path
    ) -> None:
        """Caller is responsible for cleanup."""
        tasks_dir = tmp_path / "ingest"
        tasks_dir.mkdir(exist_ok=True)
        task_file = tasks_dir / "task-new-1.md"
        task_file.write_text(VALID_TASK_CONTENT)

        state_store.ingest_external_tasks(tasks_dir)

        assert task_file.exists()

    def test_ingested_task_has_deps(
        self, state_store: InMemoryStateStore | GitStateStore, tmp_path: Path
    ) -> None:
        tasks_dir = tmp_path / "ingest"
        tasks_dir.mkdir(exist_ok=True)
        (tasks_dir / "task-new-2.md").write_text(VALID_TASK_CONTENT_2)

        ingested = state_store.ingest_external_tasks(tasks_dir)

        assert ingested == ["task-new-2"]
        task = state_store.get_task("task-new-2")
        assert task.deps == ("task-new-1",)


# ---------------------------------------------------------------------------
# list_review_contents contract tests
# ---------------------------------------------------------------------------


class TestListReviewContents:
    """Contract tests: list_review_contents returns raw review file content."""

    def test_returns_empty_list_when_no_reviews(
        self, state_store: InMemoryStateStore | GitStateStore
    ) -> None:
        contents = state_store.list_review_contents("task-001")
        assert contents == []

    def test_returns_review_content_after_store_review(
        self, state_store: InMemoryStateStore | GitStateStore
    ) -> None:
        state_store.store_review("task-001", 1, "verifier", "fail", "Tests failed.")

        contents = state_store.list_review_contents("task-001")

        assert len(contents) == 1
        assert "Tests failed." in contents[0]
        assert "verifier" in contents[0]

    def test_returns_multiple_reviews_sorted_by_round(
        self, state_store: InMemoryStateStore | GitStateStore
    ) -> None:
        state_store.store_review("task-001", 1, "verifier", "fail", "Round 1 failed.")
        state_store.store_review("task-001", 2, "verifier", "pass", "Round 2 passed.")

        contents = state_store.list_review_contents("task-001")

        assert len(contents) == 2
        assert "Round 1 failed." in contents[0]
        assert "Round 2 passed." in contents[1]

    def test_returns_empty_for_unknown_task(
        self, empty_state_store: InMemoryStateStore | GitStateStore
    ) -> None:
        contents = empty_state_store.list_review_contents("nonexistent")
        assert contents == []
