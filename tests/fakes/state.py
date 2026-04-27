"""InMemoryStateStore — complete in-memory implementation of the StateStore port.

A first-class fake, tested via contract tests, reusable across all tests.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import yaml

from hyperloop.domain.model import (
    Phase,
    Task,
    TaskStatus,
    World,
)

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class ReviewRecord:
    """In-memory representation of a review file."""

    task_id: str
    round: int
    role: str
    verdict: str
    detail: str


class InMemoryStateStore:
    """In-memory implementation of the StateStore protocol."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._reviews: list[ReviewRecord] = []
        self._epochs: dict[str, str] = {}
        self._files: dict[str, str] = {}
        self._summaries: dict[str, str] = {}
        self.committed_messages: list[str] = []

    # -- Setup helpers (for tests) ------------------------------------------

    def add_task(self, task: Task) -> None:
        """Seed a task into the store (test helper, not part of the port)."""
        self._tasks[task.id] = task

    def set_file(self, path: str, content: str) -> None:
        """Seed a file into the store (test helper, not part of the port)."""
        self._files[path] = content

    def set_task_pr(self, task_id: str, pr_url: str) -> None:
        """Set the PR URL on a task."""
        old = self._tasks[task_id]
        self._tasks[task_id] = Task(
            id=old.id,
            title=old.title,
            spec_ref=old.spec_ref,
            status=old.status,
            phase=old.phase,
            deps=old.deps,
            round=old.round,
            branch=old.branch,
            pr=pr_url,
        )

    def set_task_branch(self, task_id: str, branch: str) -> None:
        """Set the branch name on a task."""
        old = self._tasks[task_id]
        self._tasks[task_id] = Task(
            id=old.id,
            title=old.title,
            spec_ref=old.spec_ref,
            status=old.status,
            phase=old.phase,
            deps=old.deps,
            round=old.round,
            branch=branch,
            pr=old.pr,
        )

    def set_spec_ref(self, task_id: str, spec_ref: str) -> None:
        """Pin the spec_ref on a task."""
        old = self._tasks[task_id]
        self._tasks[task_id] = Task(
            id=old.id,
            title=old.title,
            spec_ref=spec_ref,
            status=old.status,
            phase=old.phase,
            deps=old.deps,
            round=old.round,
            branch=old.branch,
            pr=old.pr,
        )

    # -- StateStore protocol ------------------------------------------------

    def get_world(self) -> World:
        """Return a complete snapshot of all tasks, workers, and the current epoch."""
        return World(
            tasks=dict(self._tasks),
            workers={},
            epoch=self._epochs.get("intake", ""),
        )

    def get_task(self, task_id: str) -> Task:
        """Return a single task by ID. Raises KeyError if not found."""
        return self._tasks[task_id]

    def transition_task(
        self,
        task_id: str,
        status: TaskStatus,
        phase: Phase | None,
        round: int | None = None,
    ) -> None:
        """Update a task's status, phase, and optionally round."""
        old = self._tasks[task_id]
        self._tasks[task_id] = Task(
            id=old.id,
            title=old.title,
            spec_ref=old.spec_ref,
            status=status,
            phase=phase,
            deps=old.deps,
            round=round if round is not None else old.round,
            branch=old.branch,
            pr=old.pr,
        )

    def store_review(
        self,
        task_id: str,
        round: int,
        role: str,
        verdict: str,
        detail: str,
    ) -> None:
        """Write a review record for a task round."""
        self._reviews.append(
            ReviewRecord(
                task_id=task_id,
                round=round,
                role=role,
                verdict=verdict,
                detail=detail,
            )
        )

    def get_findings(self, task_id: str) -> str:
        """Return findings from the latest review for a task. Empty string if none."""
        matching = [r for r in self._reviews if r.task_id == task_id]
        if not matching:
            return ""
        latest = max(matching, key=lambda r: r.round)
        return latest.detail

    def get_epoch(self, key: str) -> str:
        """Return the content fingerprint for skip logic. Empty string if unset."""
        return self._epochs.get(key, "")

    def set_epoch(self, key: str, value: str) -> None:
        """Record a last-run marker."""
        self._epochs[key] = value

    def list_files(self, pattern: str) -> list[str]:
        """List file paths matching a glob pattern against in-memory files.

        Uses pathlib.Path.glob semantics: ``*`` does not cross ``/``,
        ``**`` matches zero or more directories.
        """
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for p in self._files:
                fp = root / p
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.touch()
            return sorted(str(p.relative_to(root)) for p in root.glob(pattern) if p.is_file())

    def read_file(self, path: str) -> str | None:
        """Read a file from the in-memory filesystem. Returns None if not found."""
        return self._files.get(path)

    def reset_task(self, task_id: str) -> None:
        """Reset a task to not-started with cleared branch, PR, and round."""
        old = self._tasks[task_id]
        self._tasks[task_id] = Task(
            id=old.id,
            title=old.title,
            spec_ref=old.spec_ref,
            status=TaskStatus.NOT_STARTED,
            phase=None,
            deps=old.deps,
            round=0,
            branch=None,
            pr=None,
        )

    def delete_task(self, task_id: str) -> None:
        """Remove a task from the store (used by GC pruning)."""
        self._tasks.pop(task_id, None)

    def store_summary(self, spec_path: str, summary_data: str) -> None:
        """Write a summary record for a spec (YAML content)."""
        self._summaries[spec_path] = summary_data

    def get_summary(self, spec_path: str) -> str | None:
        """Read a summary record for a spec. Returns None if not found."""
        return self._summaries.get(spec_path)

    def list_summaries(self) -> dict[str, str]:
        """Return all summary records as {spec_path: yaml_content}."""
        return dict(self._summaries)

    def ingest_external_tasks(self, directory: Path) -> list[str]:
        """Scan directory for task .md files, parse and add new tasks.

        Returns list of ingested task IDs (sorted). Skips tasks whose IDs
        already exist. Does NOT persist -- caller must call persist() after.
        Does NOT delete source files -- caller handles cleanup.
        """
        ingested: list[str] = []
        for task_file in sorted(directory.glob("*.md")):
            task_id = task_file.stem
            if task_id in self._tasks:
                continue
            content = task_file.read_text()
            match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
            if not match:
                continue
            try:
                fm = yaml.safe_load(match.group(1))
                if not isinstance(fm, dict):
                    continue
                d = cast("dict[str, object]", fm)
                raw_deps = d.get("deps", [])
                dep_list = cast("list[object]", raw_deps) if isinstance(raw_deps, list) else []
                task = Task(
                    id=str(d["id"]),
                    title=str(d.get("title", "")),
                    spec_ref=str(d.get("spec_ref", "")),
                    status=TaskStatus.NOT_STARTED,
                    phase=None,
                    deps=tuple(str(item) for item in dep_list),
                    round=0,
                    branch=None,
                    pr=None,
                )
                self._tasks[task.id] = task
                ingested.append(task.id)
            except (ValueError, KeyError, TypeError, AttributeError, yaml.YAMLError):
                continue
        return ingested

    def list_review_contents(self, task_id: str) -> list[str]:
        """Return raw content of all review files for a task, sorted by round."""
        matching = sorted(
            (r for r in self._reviews if r.task_id == task_id),
            key=lambda r: r.round,
        )
        contents: list[str] = []
        for r in matching:
            fm = {
                "task_id": r.task_id,
                "round": r.round,
                "role": r.role,
                "verdict": r.verdict,
            }
            fm_text = yaml.dump(fm, default_flow_style=False, sort_keys=False)
            contents.append(f"---\n{fm_text}---\n{r.detail}")
        return contents

    def persist(self, message: str) -> None:
        """Record the persist message (no-op for in-memory, but stores for test assertions)."""
        self.committed_messages.append(message)

    def sync(self) -> str | None:
        """No-op for in-memory store — no remote to sync with."""
        return None
