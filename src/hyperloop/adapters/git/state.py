"""GitStateStore — reads/writes state on an orphan git branch.

Implements the StateStore protocol by persisting task/review/summary files
on a dedicated orphan branch ``hyperloop/state``. Reads use ``git show``
to avoid checkout. Writes buffer in memory and ``persist()`` commits via
git plumbing (temporary index) without touching the working tree.
"""

from __future__ import annotations

import contextlib
import os
import re
import subprocess
import tempfile
from typing import TYPE_CHECKING, cast

import yaml

from hyperloop.domain.model import Phase, Task, TaskStatus, World

if TYPE_CHECKING:
    from pathlib import Path

STATE_BRANCH = "hyperloop/state"
STATE_PREFIX = ".hyperloop/state"

# Map between kebab-case/underscore YAML values and TaskStatus enum members
_STATUS_FROM_YAML: dict[str, TaskStatus] = {
    "not-started": TaskStatus.NOT_STARTED,
    "not_started": TaskStatus.NOT_STARTED,
    "in-progress": TaskStatus.IN_PROGRESS,
    "in_progress": TaskStatus.IN_PROGRESS,
    "complete": TaskStatus.COMPLETED,
    "completed": TaskStatus.COMPLETED,
    "failed": TaskStatus.FAILED,
}


# Map LLM-written field aliases to canonical field names
_FIELD_ALIASES: dict[str, str] = {
    "name": "title",
    "spec": "spec_ref",
    "spec_path": "spec_ref",
    "specification": "spec_ref",
    "dependencies": "deps",
    "depends_on": "deps",
    "depends": "deps",
}


def _normalize_frontmatter(fm: dict[str, object]) -> dict[str, object]:
    """Map LLM-written field aliases to canonical names."""
    normalized: dict[str, object] = {}
    for key, value in fm.items():
        canonical = _FIELD_ALIASES.get(key, key)
        normalized[canonical] = value
    return normalized


_STATUS_TO_YAML: dict[TaskStatus, str] = {v: k for k, v in _STATUS_FROM_YAML.items()}
# Ensure COMPLETE maps to "complete" consistently
_STATUS_TO_YAML[TaskStatus.COMPLETED] = "complete"


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
        frontmatter: dict[str, object] | None = yaml.safe_load(fm_raw)
    except yaml.YAMLError:
        frontmatter = _parse_frontmatter_lenient(fm_raw)
    if frontmatter is None:
        msg = "Empty YAML frontmatter"
        raise ValueError(msg)
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
    fm = _normalize_frontmatter(fm)
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


def _task_to_frontmatter(task: Task) -> dict[str, object]:
    """Convert a Task domain object to a frontmatter dict."""
    return {
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


def _serialize_review_file(task_id: str, round: int, role: str, verdict: str, detail: str) -> str:
    """Serialize a review into file content."""
    fm = {
        "task_id": task_id,
        "round": round,
        "role": role,
        "verdict": verdict,
    }
    fm_text = yaml.dump(fm, default_flow_style=False, sort_keys=False)
    return f"---\n{fm_text}---\n{detail}"


class GitStateStore:
    """StateStore implementation using an orphan git branch for state persistence.

    State lives on ``hyperloop/state``, reads use ``git show``,
    writes buffer in memory, and ``persist()`` commits via git plumbing
    without touching the working tree or main branch.
    """

    def __init__(self, repo_path: Path) -> None:
        self._repo = repo_path
        self._epochs: dict[str, str] = {}
        self._bootstrapped = False
        # Buffered writes: path -> content (relative to repo root)
        self._buffer: dict[str, str] = {}
        # Paths to remove from the state branch on next persist
        self._deletions: set[str] = set()

    def _ensure_bootstrapped(self) -> None:
        """Lazily bootstrap the state branch on first access."""
        if not self._bootstrapped:
            self.bootstrap()

    def _git(self, *args: str, env: dict[str, str] | None = None, timeout: float = 30.0) -> str:
        """Run a git command in the repo and return stdout."""
        full_env = dict(os.environ)
        if env:
            full_env.update(env)
        result = subprocess.run(
            ["git", "-C", str(self._repo), *args],
            check=True,
            capture_output=True,
            text=True,
            env=full_env,
            timeout=timeout,
        )
        return result.stdout.strip()

    def _git_try(self, *args: str) -> str | None:
        """Run a git command, return stdout or None on failure."""
        try:
            return self._git(*args)
        except subprocess.CalledProcessError:
            return None

    def _branch_exists(self) -> bool:
        """Check if the state branch exists locally."""
        return self._git_try("rev-parse", "--verify", f"refs/heads/{STATE_BRANCH}") is not None

    # -- Bootstrap -------------------------------------------------------------

    def bootstrap(self) -> None:
        """Ensure the state branch exists. Create orphan if needed."""
        if self._bootstrapped:
            return

        if self._branch_exists():
            self._bootstrapped = True
            return

        # Check remote (with timeout to avoid hanging on auth)
        remotes = self._git_try("remote")
        if remotes:
            with contextlib.suppress(subprocess.CalledProcessError, subprocess.TimeoutExpired):
                subprocess.run(
                    ["git", "-C", str(self._repo), "fetch", "origin", STATE_BRANCH],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
            if self._git_try("rev-parse", "--verify", f"refs/remotes/origin/{STATE_BRANCH}"):
                self._git("branch", STATE_BRANCH, f"origin/{STATE_BRANCH}")
                self._bootstrapped = True
                return

        # Create orphan branch via plumbing
        self._create_orphan_branch()
        self._bootstrapped = True

    def _create_orphan_branch(self) -> None:
        """Create the orphan state branch with empty directory structure using plumbing."""
        result = subprocess.run(
            ["git", "-C", str(self._repo), "hash-object", "-w", "--stdin"],
            input="",
            check=True,
            capture_output=True,
            text=True,
        )
        empty_blob = result.stdout.strip()

        # Build tree using mktree
        # We need nested trees: .hyperloop/state/{tasks,reviews,summaries}/.gitkeep
        # Build from leaves up

        # Leaf tree: contains .gitkeep
        leaf_tree_input = f"100644 blob {empty_blob}\t.gitkeep\n"
        result = subprocess.run(
            ["git", "-C", str(self._repo), "mktree"],
            input=leaf_tree_input,
            check=True,
            capture_output=True,
            text=True,
        )
        leaf_tree = result.stdout.strip()

        # state tree: tasks/, reviews/, summaries/
        state_tree_input = (
            f"040000 tree {leaf_tree}\treviews\n"
            f"040000 tree {leaf_tree}\tsummaries\n"
            f"040000 tree {leaf_tree}\ttasks\n"
        )
        result = subprocess.run(
            ["git", "-C", str(self._repo), "mktree"],
            input=state_tree_input,
            check=True,
            capture_output=True,
            text=True,
        )
        state_tree = result.stdout.strip()

        # .hyperloop tree: state/
        hyperloop_tree_input = f"040000 tree {state_tree}\tstate\n"
        result = subprocess.run(
            ["git", "-C", str(self._repo), "mktree"],
            input=hyperloop_tree_input,
            check=True,
            capture_output=True,
            text=True,
        )
        hyperloop_tree = result.stdout.strip()

        # Root tree: .hyperloop/
        root_tree_input = f"040000 tree {hyperloop_tree}\t.hyperloop\n"
        result = subprocess.run(
            ["git", "-C", str(self._repo), "mktree"],
            input=root_tree_input,
            check=True,
            capture_output=True,
            text=True,
        )
        root_tree = result.stdout.strip()

        # Commit tree (no parent — orphan)
        result = subprocess.run(
            [
                "git",
                "-C",
                str(self._repo),
                "commit-tree",
                root_tree,
                "-m",
                "chore: initialize state branch",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        commit_sha = result.stdout.strip()

        # Create branch ref
        self._git("update-ref", f"refs/heads/{STATE_BRANCH}", commit_sha)

    # -- Read operations (git show) -------------------------------------------

    def _git_show(self, path: str) -> str | None:
        """Read a file from the state branch via ``git show``. Returns None if not found."""
        return self._git_try("show", f"{STATE_BRANCH}:{path}")

    def _read_task_fm(self, task_id: str) -> dict[str, object]:
        """Read and parse a task file from the state branch or buffer.

        Raises KeyError if not found.
        """
        buf_path = f"{STATE_PREFIX}/tasks/{task_id}.md"

        # Check deletions first
        if buf_path in self._deletions:
            raise KeyError(task_id)

        # Check buffer first
        if buf_path in self._buffer:
            return _parse_task_file(self._buffer[buf_path])

        # Read from branch
        content = self._git_show(buf_path)
        if content is None:
            raise KeyError(task_id)
        return _parse_task_file(content)

    def _write_task_to_buffer(self, task_id: str, fm: dict[str, object]) -> None:
        """Buffer a task file write."""
        path = f"{STATE_PREFIX}/tasks/{task_id}.md"
        self._buffer[path] = _serialize_task_file(fm)

    def _list_task_ids_on_branch(self) -> list[str]:
        """List all task IDs on the state branch."""
        tree_output = self._git_try("ls-tree", "-r", "--name-only", STATE_BRANCH)
        if not tree_output:
            return []
        task_ids: list[str] = []
        for line in tree_output.splitlines():
            if line.startswith(f"{STATE_PREFIX}/tasks/") and line.endswith(".md"):
                filename = line.split("/")[-1]
                task_id = filename.removesuffix(".md")
                if task_id != ".gitkeep":
                    task_ids.append(task_id)
        return task_ids

    def _list_review_paths_on_branch(self, task_id: str) -> list[str]:
        """List all review file paths for a task on the state branch."""
        tree_output = self._git_try("ls-tree", "-r", "--name-only", STATE_BRANCH)
        if not tree_output:
            return []
        prefix = f"{STATE_PREFIX}/reviews/{task_id}-round-"
        return sorted(
            line
            for line in tree_output.splitlines()
            if line.startswith(prefix) and line.endswith(".md")
        )

    # -- StateStore protocol ---------------------------------------------------

    def get_world(self) -> World:
        """Return a complete snapshot of all tasks, workers, and the current epoch."""
        self._ensure_bootstrapped()
        tasks: dict[str, Task] = {}

        # Read from branch
        for task_id in self._list_task_ids_on_branch():
            buf_path = f"{STATE_PREFIX}/tasks/{task_id}.md"
            if buf_path in self._deletions:
                continue  # Pending deletion, skip
            if buf_path in self._buffer:
                continue  # Will be handled below
            content = self._git_show(buf_path)
            if content is None:
                continue
            try:
                fm = _parse_task_file(content)
                task = _frontmatter_to_task(fm)
                tasks[task.id] = task
            except (ValueError, KeyError, TypeError, AttributeError, yaml.YAMLError):
                continue

        # Overlay buffered tasks
        for path, content in self._buffer.items():
            if path.startswith(f"{STATE_PREFIX}/tasks/") and path.endswith(".md"):
                try:
                    fm = _parse_task_file(content)
                    task = _frontmatter_to_task(fm)
                    tasks[task.id] = task
                except (ValueError, KeyError, TypeError, AttributeError, yaml.YAMLError):
                    continue

        try:
            epoch = self._git("rev-parse", "HEAD")
        except subprocess.CalledProcessError:
            epoch = ""

        return World(tasks=tasks, workers={}, epoch=epoch)

    def get_task(self, task_id: str) -> Task:
        """Return a single task by ID. Raises KeyError if not found."""
        self._ensure_bootstrapped()
        fm = self._read_task_fm(task_id)
        return _frontmatter_to_task(fm)

    def transition_task(
        self,
        task_id: str,
        status: TaskStatus,
        phase: Phase | None,
        round: int | None = None,
    ) -> None:
        """Update a task's status, phase, and optionally round."""
        self._ensure_bootstrapped()
        fm = self._read_task_fm(task_id)
        fm["status"] = _STATUS_TO_YAML[status]
        fm["phase"] = str(phase) if phase is not None else None
        if round is not None:
            fm["round"] = round
        self._write_task_to_buffer(task_id, fm)

    def store_review(
        self,
        task_id: str,
        round: int,
        role: str,
        verdict: str,
        detail: str,
    ) -> None:
        """Buffer a review file write."""
        self._ensure_bootstrapped()
        path = f"{STATE_PREFIX}/reviews/{task_id}-round-{round}.md"
        self._buffer[path] = _serialize_review_file(task_id, round, role, verdict, detail)

    def list_review_contents(self, task_id: str) -> list[str]:
        """Return the raw content of every review file for a task, sorted by round."""
        self._ensure_bootstrapped()
        # Collect review paths from both branch and buffer
        branch_paths = self._list_review_paths_on_branch(task_id)
        buf_paths = sorted(
            p
            for p in self._buffer
            if p.startswith(f"{STATE_PREFIX}/reviews/{task_id}-round-") and p.endswith(".md")
        )
        # Merge and deduplicate, buffer takes precedence
        all_paths = dict.fromkeys(branch_paths)
        for p in buf_paths:
            all_paths[p] = None
        sorted_paths = sorted(all_paths.keys())

        contents: list[str] = []
        for path in sorted_paths:
            if path in self._buffer:
                contents.append(self._buffer[path])
            else:
                content = self._git_show(path)
                if content is not None:
                    contents.append(content)
        return contents

    def get_findings(self, task_id: str) -> str:
        """Return findings from the latest review for a task. Empty string if none."""
        self._ensure_bootstrapped()
        # Collect review paths from both branch and buffer
        branch_paths = self._list_review_paths_on_branch(task_id)
        buf_paths = sorted(
            p
            for p in self._buffer
            if p.startswith(f"{STATE_PREFIX}/reviews/{task_id}-round-") and p.endswith(".md")
        )
        # Merge and deduplicate, buffer takes precedence
        all_paths = dict.fromkeys(branch_paths)
        for p in buf_paths:
            all_paths[p] = None
        sorted_paths = sorted(all_paths.keys())

        if not sorted_paths:
            return ""

        latest_path = sorted_paths[-1]

        # Read from buffer first, then branch
        if latest_path in self._buffer:
            content = self._buffer[latest_path]
        else:
            content = self._git_show(latest_path)
            if content is None:
                return ""

        match = re.match(r"^---\n.*?\n---\n(.*)", content, re.DOTALL)
        return match.group(1).strip() if match else content.strip()

    def get_epoch(self, key: str) -> str:
        """Return content fingerprint.

        'head' returns git HEAD SHA of main. Others use in-memory dict.
        """
        self._ensure_bootstrapped()
        if key == "head":
            try:
                return self._git("rev-parse", "HEAD")
            except subprocess.CalledProcessError:
                return ""
        return self._epochs.get(key, "")

    def set_epoch(self, key: str, value: str) -> None:
        """Record a last-run marker."""
        self._ensure_bootstrapped()
        self._epochs[key] = value

    def list_files(self, pattern: str) -> list[str]:
        """List file paths matching a glob pattern relative to the repo root.

        Searches the working tree (main branch), not the state branch.
        """
        self._ensure_bootstrapped()
        return sorted(
            str(p.relative_to(self._repo)) for p in self._repo.glob(pattern) if p.is_file()
        )

    def read_file(self, path: str) -> str | None:
        """Read a file from the repo working tree. Returns None if it does not exist."""
        self._ensure_bootstrapped()
        if not path:
            return None
        file_path = self._repo / path
        if not file_path.is_file():
            return None
        return file_path.read_text()

    def set_task_branch(self, task_id: str, branch: str) -> None:
        """Set the branch name on a task file."""
        self._ensure_bootstrapped()
        fm = self._read_task_fm(task_id)
        fm["branch"] = branch
        self._write_task_to_buffer(task_id, fm)

    def set_task_pr(self, task_id: str, pr_url: str) -> None:
        """Set the PR URL on a task file."""
        self._ensure_bootstrapped()
        fm = self._read_task_fm(task_id)
        fm["pr"] = pr_url
        self._write_task_to_buffer(task_id, fm)

    def set_spec_ref(self, task_id: str, spec_ref: str) -> None:
        """Pin the spec_ref on a task file (e.g. append @sha after intake)."""
        self._ensure_bootstrapped()
        fm = self._read_task_fm(task_id)
        fm["spec_ref"] = spec_ref
        self._write_task_to_buffer(task_id, fm)

    def reset_task(self, task_id: str) -> None:
        """Reset a task to not-started with cleared branch, PR, and round."""
        self._ensure_bootstrapped()
        fm = self._read_task_fm(task_id)
        fm["status"] = "not-started"
        fm["phase"] = None
        fm["round"] = 0
        fm["branch"] = None
        fm["pr"] = None
        self._write_task_to_buffer(task_id, fm)

    def add_task(self, task: Task) -> None:
        """Add a new task to the store (buffered)."""
        self._ensure_bootstrapped()
        fm = _task_to_frontmatter(task)
        self._write_task_to_buffer(task.id, fm)

    def ingest_external_tasks(self, directory: Path) -> list[str]:
        """Scan directory for task .md files, parse and add new tasks.

        Returns list of ingested task IDs (sorted). Skips tasks whose IDs
        already exist. Does NOT persist -- caller must call persist() after.
        Does NOT delete source files -- caller handles cleanup.
        """
        self._ensure_bootstrapped()
        world = self.get_world()
        existing_ids = set(world.tasks.keys())
        ingested: list[str] = []

        for task_file in sorted(directory.glob("*.md")):
            task_id = task_file.stem
            if task_id in existing_ids:
                continue
            content = task_file.read_text()
            try:
                fm = _parse_task_file(content)
                task = _frontmatter_to_task(fm)
                self.add_task(task)
                ingested.append(task_id)
            except (ValueError, KeyError, TypeError, AttributeError, yaml.YAMLError):
                continue

        return ingested

    def delete_task(self, task_id: str) -> None:
        """Remove a task from the store (buffered for removal on next persist)."""
        self._ensure_bootstrapped()
        path = f"{STATE_PREFIX}/tasks/{task_id}.md"
        self._deletions.add(path)
        # Remove from write buffer if present so get_world() skips it
        self._buffer.pop(path, None)

    def store_summary(self, spec_path: str, summary_data: str) -> None:
        """Write a summary record for a spec (YAML content) to the state branch."""
        self._ensure_bootstrapped()
        # Normalize spec_path to a safe filename: specs/auth.md -> specs-auth.md.yaml
        safe_name = spec_path.replace("/", "-")
        path = f"{STATE_PREFIX}/summaries/{safe_name}.yaml"
        self._buffer[path] = summary_data

    def get_summary(self, spec_path: str) -> str | None:
        """Read a summary record for a spec from the state branch or buffer."""
        self._ensure_bootstrapped()
        safe_name = spec_path.replace("/", "-")
        path = f"{STATE_PREFIX}/summaries/{safe_name}.yaml"
        if path in self._buffer:
            content = self._buffer[path]
            return content if content else None
        return self._git_show(path)

    def list_summaries(self) -> dict[str, str]:
        """Return all summary records as {spec_path: yaml_content}."""
        self._ensure_bootstrapped()
        summaries: dict[str, str] = {}

        # Read from branch
        tree_output = self._git_try("ls-tree", "-r", "--name-only", STATE_BRANCH)
        if tree_output:
            prefix = f"{STATE_PREFIX}/summaries/"
            for line in tree_output.splitlines():
                if line.startswith(prefix) and line.endswith(".yaml"):
                    filename = line[len(prefix) :]
                    if filename == ".gitkeep":
                        continue
                    # Reverse the safe_name: specs-auth.md.yaml -> specs/auth.md
                    spec_path = filename.removesuffix(".yaml").replace("-", "/", 1)
                    if line not in self._buffer:
                        content = self._git_show(line)
                        if content is not None:
                            summaries[spec_path] = content

        # Overlay buffered summaries
        prefix = f"{STATE_PREFIX}/summaries/"
        for path, content in self._buffer.items():
            if path.startswith(prefix) and path.endswith(".yaml"):
                filename = path[len(prefix) :]
                if filename == ".gitkeep":
                    continue
                spec_path = filename.removesuffix(".yaml").replace("-", "/", 1)
                if content:
                    summaries[spec_path] = content

        return summaries

    def persist(self, message: str) -> None:
        """Commit buffered changes to the state branch via git plumbing.

        Uses a temporary index to stage changes and commit to the state
        branch without touching the working tree or the main branch index.
        No-ops when there is nothing to commit.
        """
        self._ensure_bootstrapped()
        if not self._buffer and not self._deletions:
            return

        with tempfile.NamedTemporaryFile(
            prefix="hyperloop-idx-",
            suffix=".tmp",
            delete=False,
            dir=str(self._repo),
        ) as tmp:
            tmp_index = tmp.name

        try:
            env = {"GIT_INDEX_FILE": tmp_index}

            # Read current state branch tree into temp index
            self._git("read-tree", STATE_BRANCH, env=env)

            # Remove deleted paths from the temp index
            for path in self._deletions:
                full_env = dict(os.environ)
                full_env["GIT_INDEX_FILE"] = tmp_index
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(self._repo),
                        "update-index",
                        "--force-remove",
                        path,
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                    env=full_env,
                )

            # Write each buffered file as a blob and update the temp index
            for path, content in self._buffer.items():
                # Create blob
                result = subprocess.run(
                    ["git", "-C", str(self._repo), "hash-object", "-w", "--stdin"],
                    input=content,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                blob_sha = result.stdout.strip()

                # Update index entry
                full_env = dict(os.environ)
                full_env["GIT_INDEX_FILE"] = tmp_index
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(self._repo),
                        "update-index",
                        "--add",
                        "--cacheinfo",
                        f"100644,{blob_sha},{path}",
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                    env=full_env,
                )

            # Write tree from temp index
            tree_sha = self._git("write-tree", env=env)

            # Check if tree is same as current (no-op)
            current_tree = self._git("rev-parse", f"{STATE_BRANCH}^{{tree}}")
            if tree_sha == current_tree:
                return

            # Commit tree to state branch
            parent_sha = self._git("rev-parse", STATE_BRANCH)
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self._repo),
                    "commit-tree",
                    tree_sha,
                    "-p",
                    parent_sha,
                    "-m",
                    message,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            commit_sha = result.stdout.strip()

            # Update state branch ref
            self._git("update-ref", f"refs/heads/{STATE_BRANCH}", commit_sha)

        finally:
            # Clean up temp index
            if os.path.exists(tmp_index):
                os.unlink(tmp_index)

        # Clear buffer and deletions after successful persist
        self._buffer.clear()
        self._deletions.clear()

    def sync(self) -> None:
        """Sync state branch with remote. Pull (rebase) then push. Best-effort."""
        self._ensure_bootstrapped()
        remotes = self._git_try("remote")
        if not remotes:
            return

        try:
            subprocess.run(
                ["git", "-C", str(self._repo), "fetch", "origin", STATE_BRANCH],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return

        remote_ref = self._git_try("rev-parse", "--verify", f"refs/remotes/origin/{STATE_BRANCH}")
        if not remote_ref:
            with contextlib.suppress(subprocess.CalledProcessError, subprocess.TimeoutExpired):
                subprocess.run(
                    ["git", "-C", str(self._repo), "push", "-u", "origin", STATE_BRANCH],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            return

        with contextlib.suppress(subprocess.CalledProcessError, subprocess.TimeoutExpired):
            subprocess.run(
                ["git", "-C", str(self._repo), "push", "origin", STATE_BRANCH],
                capture_output=True,
                text=True,
                timeout=30,
            )
