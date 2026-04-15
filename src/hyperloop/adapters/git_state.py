"""GitStateStore — reads/writes task files in a git repo.

Implements the StateStore protocol by parsing YAML frontmatter task files
and using git for persistence.
"""

from __future__ import annotations

import re
import subprocess
from typing import TYPE_CHECKING, cast

import yaml

from hyperloop.domain.model import Phase, Task, TaskStatus, World

if TYPE_CHECKING:
    from pathlib import Path

# Map between kebab-case YAML values and TaskStatus enum members
_STATUS_FROM_YAML: dict[str, TaskStatus] = {
    "not-started": TaskStatus.NOT_STARTED,
    "in-progress": TaskStatus.IN_PROGRESS,
    "needs-rebase": TaskStatus.NEEDS_REBASE,
    "complete": TaskStatus.COMPLETE,
    "failed": TaskStatus.FAILED,
}

_STATUS_TO_YAML: dict[TaskStatus, str] = {v: k for k, v in _STATUS_FROM_YAML.items()}


def _parse_task_file(content: str) -> tuple[dict[str, object], str]:
    """Parse a task file into (frontmatter_dict, body_text).

    The file format is YAML frontmatter delimited by --- lines, followed by
    markdown body.
    """
    match = re.match(r"^---\n(.*?)\n---\n(.*)", content, re.DOTALL)
    if not match:
        msg = "Task file missing YAML frontmatter"
        raise ValueError(msg)
    fm_raw = match.group(1)
    body = match.group(2)
    frontmatter: dict[str, object] = yaml.safe_load(fm_raw)
    return frontmatter, body


def _frontmatter_to_task(fm: dict[str, object]) -> Task:
    """Convert parsed YAML frontmatter into a Task domain object."""
    raw_status = str(fm["status"])
    status = _STATUS_FROM_YAML[raw_status]

    raw_phase = fm.get("phase")
    phase = Phase(str(raw_phase)) if raw_phase is not None else None

    raw_deps = fm.get("deps")
    dep_list = cast("list[object]", raw_deps) if isinstance(raw_deps, list) else []
    deps = tuple(str(d) for d in dep_list)

    raw_branch = fm.get("branch")
    branch = str(raw_branch) if raw_branch is not None else None

    raw_pr = fm.get("pr")
    pr = str(raw_pr) if raw_pr is not None else None

    return Task(
        id=str(fm["id"]),
        title=str(fm["title"]),
        spec_ref=str(fm["spec_ref"]),
        status=status,
        phase=phase,
        deps=deps,
        round=int(fm.get("round", 0)),  # type: ignore[arg-type]
        branch=branch,
        pr=pr,
    )


def _serialize_task_file(fm: dict[str, object], body: str) -> str:
    """Serialize frontmatter dict and body back into a task file string."""
    # Preserve a specific field order for readability
    ordered_keys = ["id", "title", "spec_ref", "status", "phase", "deps", "round", "branch", "pr"]
    ordered_fm: dict[str, object] = {}
    for key in ordered_keys:
        if key in fm:
            ordered_fm[key] = fm[key]
    for key in fm:
        if key not in ordered_keys:
            ordered_fm[key] = fm[key]

    fm_text = yaml.dump(
        ordered_fm,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
    return "---\n" + fm_text + "---\n" + body


class GitStateStore:
    """StateStore implementation backed by task files in a git repository."""

    def __init__(self, repo_path: Path, specs_dir: str = "specs") -> None:
        self._repo = repo_path
        self._specs_dir = specs_dir
        self._tasks_dir = repo_path / specs_dir / "tasks"
        self._epochs: dict[str, str] = {}

    def _task_file_path(self, task_id: str) -> Path:
        return self._tasks_dir / f"{task_id}.md"

    def _read_task_file(self, task_id: str) -> tuple[dict[str, object], str]:
        """Read and parse a task file. Raises KeyError if not found."""
        path = self._task_file_path(task_id)
        if not path.exists():
            raise KeyError(task_id)
        return _parse_task_file(path.read_text())

    def _write_task_file(self, task_id: str, fm: dict[str, object], body: str) -> None:
        """Write a task file to disk (does NOT commit)."""
        path = self._task_file_path(task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_serialize_task_file(fm, body))

    def _git(self, *args: str) -> str:
        """Run a git command in the repo and return stdout."""
        result = subprocess.run(
            ["git", "-C", str(self._repo), *args],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    # -- StateStore protocol ------------------------------------------------

    def get_world(self) -> World:
        """Return a complete snapshot of all tasks, workers, and the current epoch."""
        tasks: dict[str, Task] = {}
        if self._tasks_dir.exists():
            for task_file in sorted(self._tasks_dir.glob("task-*.md")):
                fm, _body = _parse_task_file(task_file.read_text())
                task = _frontmatter_to_task(fm)
                tasks[task.id] = task

        try:
            epoch = self._git("rev-parse", "HEAD")
        except subprocess.CalledProcessError:
            epoch = ""

        return World(tasks=tasks, workers={}, epoch=epoch)

    def get_task(self, task_id: str) -> Task:
        """Return a single task by ID. Raises KeyError if not found."""
        fm, _body = self._read_task_file(task_id)
        return _frontmatter_to_task(fm)

    def transition_task(
        self,
        task_id: str,
        status: TaskStatus,
        phase: Phase | None,
        round: int | None = None,
    ) -> None:
        """Update a task's status, phase, and optionally round."""
        fm, body = self._read_task_file(task_id)
        fm["status"] = _STATUS_TO_YAML[status]
        fm["phase"] = str(phase) if phase is not None else None
        if round is not None:
            fm["round"] = round
        self._write_task_file(task_id, fm, body)

    def store_findings(self, task_id: str, detail: str) -> None:
        """Append findings detail text to the task file's Findings section."""
        fm, body = self._read_task_file(task_id)
        body = _append_to_findings(body, detail)
        self._write_task_file(task_id, fm, body)

    def get_findings(self, task_id: str) -> str:
        """Return stored findings for a task. Empty string if none."""
        _fm, body = self._read_task_file(task_id)
        return _extract_findings(body)

    def clear_findings(self, task_id: str) -> None:
        """Clear the findings section of a task file."""
        fm, body = self._read_task_file(task_id)
        body = _clear_findings(body)
        self._write_task_file(task_id, fm, body)

    def get_epoch(self, key: str) -> str:
        """Return content fingerprint. 'head' returns git HEAD SHA. Others use in-memory dict."""
        if key == "head":
            try:
                return self._git("rev-parse", "HEAD")
            except subprocess.CalledProcessError:
                return ""
        return self._epochs.get(key, "")

    def set_epoch(self, key: str, value: str) -> None:
        """Record a last-run marker."""
        self._epochs[key] = value

    def list_files(self, pattern: str) -> list[str]:
        """List file paths matching a glob pattern relative to the repo root."""
        return sorted(
            str(p.relative_to(self._repo)) for p in self._repo.glob(pattern) if p.is_file()
        )

    def read_file(self, path: str) -> str | None:
        """Read a file from the repo. Returns None if it does not exist."""
        file_path = self._repo / path
        if not file_path.exists():
            return None
        return file_path.read_text()

    def set_task_pr(self, task_id: str, pr_url: str) -> None:
        """Set the PR URL on a task file."""
        fm, body = self._read_task_file(task_id)
        fm["pr"] = pr_url
        self._write_task_file(task_id, fm, body)

    def commit(self, message: str) -> None:
        """Stage all changes and create a git commit."""
        self._git("add", "-A")
        self._git("commit", "-m", message)


# ---------------------------------------------------------------------------
# Body manipulation helpers
# ---------------------------------------------------------------------------


def _append_to_findings(body: str, detail: str) -> str:
    """Append text to the ## Findings section of the markdown body."""
    # Find the ## Findings section
    findings_match = re.search(r"(## Findings\n)", body)
    if not findings_match:
        # No findings section — append one
        return body.rstrip() + "\n\n## Findings\n" + detail
    # Insert the detail at the end of the body (after existing findings content)
    # The findings section runs from the header to the end of the body
    findings_start = findings_match.end()
    existing = body[findings_start:]
    if existing.strip():
        # There's existing content — append after it
        return body.rstrip() + "\n" + detail
    else:
        # Empty findings section — add content
        return body[:findings_start] + detail


def _extract_findings(body: str) -> str:
    """Extract content from the ## Findings section. Returns empty string if none."""
    findings_match = re.search(r"## Findings\n", body)
    if not findings_match:
        return ""
    content = body[findings_match.end() :]
    return content.strip()


def _clear_findings(body: str) -> str:
    """Clear the content of the ## Findings section, preserving the header."""
    findings_match = re.search(r"(## Findings\n)", body)
    if not findings_match:
        return body
    return body[: findings_match.end()]
