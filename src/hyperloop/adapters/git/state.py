"""GitStateStore — reads/writes task files in a git repo.

Implements the StateStore protocol by parsing YAML frontmatter task files
and using git for persistence.  Task files are pure metadata (frontmatter
only); review findings live in separate review files.
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
    "complete": TaskStatus.COMPLETED,  # legacy alias
    "completed": TaskStatus.COMPLETED,
    "failed": TaskStatus.FAILED,
}

_STATUS_TO_YAML: dict[TaskStatus, str] = {v: k for k, v in _STATUS_FROM_YAML.items()}
_STATUS_TO_YAML[TaskStatus.COMPLETED] = "completed"


def _parse_task_file(content: str) -> dict[str, object]:
    """Parse a task file into a frontmatter dict.

    The file format is pure YAML frontmatter delimited by ``---`` lines.
    Falls back to quoting bare values when agents write unquoted colons
    (e.g. ``title: Todo (view mode: checkbox)``).
    """
    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not match:
        msg = "Task file missing YAML frontmatter"
        raise ValueError(msg)
    fm_raw = match.group(1)
    try:
        frontmatter: dict[str, object] = yaml.safe_load(fm_raw)
    except yaml.YAMLError:
        frontmatter = _parse_frontmatter_lenient(fm_raw)
    return frontmatter


def _parse_frontmatter_lenient(fm_raw: str) -> dict[str, object]:
    """Line-based fallback parser for agent-written frontmatter with unquoted colons."""
    result: dict[str, object] = {}
    for line in fm_raw.splitlines():
        if not line.strip():
            continue
        colon_pos = line.find(":")
        if colon_pos == -1:
            continue
        key = line[:colon_pos].strip()
        value = line[colon_pos + 1 :].strip()
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            result[key] = [v.strip() for v in inner.split(",")] if inner else []
        elif value.lower() in ("null", "~", ""):
            result[key] = None
        elif value.isdigit():
            result[key] = int(value)
        else:
            result[key] = value
    return result


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

    raw_pr_title = fm.get("pr_title")
    pr_title = str(raw_pr_title) if raw_pr_title is not None else None

    raw_pr_desc = fm.get("pr_description")
    pr_description = str(raw_pr_desc) if raw_pr_desc is not None else None

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
        pr_title=pr_title,
        pr_description=pr_description,
    )


def _serialize_task_file(fm: dict[str, object]) -> str:
    """Serialize frontmatter dict into a task file string (pure metadata)."""
    ordered_keys = [
        "id",
        "title",
        "spec_ref",
        "status",
        "phase",
        "deps",
        "round",
        "branch",
        "pr",
        "pr_title",
        "pr_description",
    ]
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
    return "---\n" + fm_text + "---\n"


class GitStateStore:
    """StateStore implementation backed by task files in a git repository."""

    def __init__(self, repo_path: Path) -> None:
        self._repo = repo_path
        self._tasks_dir = repo_path / ".hyperloop" / "state" / "tasks"
        self._reviews_dir = repo_path / ".hyperloop" / "state" / "reviews"
        self._epochs: dict[str, str] = {}

    def _task_file_path(self, task_id: str) -> Path:
        return self._tasks_dir / f"{task_id}.md"

    def _read_task_file(self, task_id: str) -> dict[str, object]:
        """Read and parse a task file. Raises KeyError if not found."""
        path = self._task_file_path(task_id)
        if not path.exists():
            raise KeyError(task_id)
        return _parse_task_file(path.read_text())

    def _write_task_file(self, task_id: str, fm: dict[str, object]) -> None:
        """Write a task file to disk (does NOT commit)."""
        path = self._task_file_path(task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_serialize_task_file(fm))

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
                try:
                    fm = _parse_task_file(task_file.read_text())
                    task = _frontmatter_to_task(fm)
                    tasks[task.id] = task
                except (ValueError, yaml.YAMLError, KeyError):
                    continue

        try:
            epoch = self._git("rev-parse", "HEAD")
        except subprocess.CalledProcessError:
            epoch = ""

        return World(tasks=tasks, workers={}, epoch=epoch)

    def get_task(self, task_id: str) -> Task:
        """Return a single task by ID. Raises KeyError if not found."""
        fm = self._read_task_file(task_id)
        return _frontmatter_to_task(fm)

    def transition_task(
        self,
        task_id: str,
        status: TaskStatus,
        phase: Phase | None,
        round: int | None = None,
    ) -> None:
        """Update a task's status, phase, and optionally round."""
        fm = self._read_task_file(task_id)
        fm["status"] = _STATUS_TO_YAML[status]
        fm["phase"] = str(phase) if phase is not None else None
        if round is not None:
            fm["round"] = round
        self._write_task_file(task_id, fm)

    def store_review(
        self,
        task_id: str,
        round: int,
        role: str,
        verdict: str,
        detail: str,
    ) -> None:
        """Write a review file for a task round."""
        self._reviews_dir.mkdir(parents=True, exist_ok=True)
        path = self._reviews_dir / f"{task_id}-round-{round}.md"
        fm = {
            "task_id": task_id,
            "round": round,
            "role": role,
            "verdict": verdict,
        }
        fm_text = yaml.dump(fm, default_flow_style=False, sort_keys=False)
        path.write_text(f"---\n{fm_text}---\n{detail}")

    def get_findings(self, task_id: str) -> str:
        """Return findings from the latest review for a task. Empty string if none."""
        if not self._reviews_dir.exists():
            return ""
        review_files = sorted(self._reviews_dir.glob(f"{task_id}-round-*.md"))
        if not review_files:
            return ""
        content = review_files[-1].read_text()
        match = re.match(r"^---\n.*?\n---\n(.*)", content, re.DOTALL)
        return match.group(1).strip() if match else content.strip()

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
        if not path:
            return None
        file_path = self._repo / path
        if not file_path.is_file():
            return None
        return file_path.read_text()

    def set_task_branch(self, task_id: str, branch: str) -> None:
        """Set the branch name on a task file."""
        fm = self._read_task_file(task_id)
        fm["branch"] = branch
        self._write_task_file(task_id, fm)

    def set_task_pr(self, task_id: str, pr_url: str) -> None:
        """Set the PR URL on a task file."""
        fm = self._read_task_file(task_id)
        fm["pr"] = pr_url
        self._write_task_file(task_id, fm)

    def set_spec_ref(self, task_id: str, spec_ref: str) -> None:
        """Pin the spec_ref on a task file (e.g. append @sha after intake)."""
        fm = self._read_task_file(task_id)
        fm["spec_ref"] = spec_ref
        self._write_task_file(task_id, fm)

    def reset_task(self, task_id: str) -> None:
        """Reset a task to not-started with cleared branch, PR, and round."""
        fm = self._read_task_file(task_id)
        fm["status"] = "not-started"
        fm["phase"] = None
        fm["round"] = 0
        fm["branch"] = None
        fm["pr"] = None
        self._write_task_file(task_id, fm)

    def add_task(self, task: Task) -> None:
        """Add a new task to the store."""
        fm: dict[str, object] = {
            "id": task.id,
            "title": task.title,
            "spec_ref": task.spec_ref,
            "status": _STATUS_TO_YAML[task.status],
            "phase": str(task.phase) if task.phase is not None else None,
            "deps": list(task.deps) if task.deps else [],
            "round": task.round,
            "branch": task.branch,
            "pr": task.pr,
            "pr_title": task.pr_title,
            "pr_description": task.pr_description,
        }
        self._write_task_file(task.id, fm)

    def persist(self, message: str) -> None:
        """Stage all changes and create a git commit.

        Uses --no-verify to skip pre-commit hooks. State commits are
        orchestrator bookkeeping (task status transitions, findings), not
        code changes — running linters and tests on them is incorrect and
        can cause infinite recursion when pre-commit hooks include pytest.

        No-ops gracefully when there is nothing to commit (e.g. after a
        serial agent that already committed its own changes).
        """
        import contextlib

        self._git("add", "-A")
        with contextlib.suppress(subprocess.CalledProcessError):
            self._git("commit", "--no-verify", "-m", message)

    def sync(self) -> None:
        """Pull from remote, then push local commits. Best-effort on both."""
        remotes = self._git("remote")
        if not remotes:
            return
        subprocess.run(
            ["git", "-C", str(self._repo), "pull", "--rebase", "--no-verify", "origin"],
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(self._repo), "push", "origin"],
            capture_output=True,
            text=True,
        )
