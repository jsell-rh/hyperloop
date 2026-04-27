"""Tests for the dashboard API endpoints.

Uses FastAPI TestClient with temporary git repos seeded with
task files and spec files to verify all endpoints.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest
import yaml

if TYPE_CHECKING:
    from pathlib import Path
from fastapi.testclient import TestClient

from dashboard.server import deps
from dashboard.server.app import create_app


def _init_git_repo(path: Path) -> None:
    """Initialize a bare git repo with an initial commit."""
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
    # Create an initial commit so HEAD exists
    (path / ".gitkeep").write_text("")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "--no-verify", "-m", "init"],
        check=True,
        capture_output=True,
    )


def _write_task_file(repo: Path, task_id: str, fm: dict[str, object]) -> None:
    """Write a task file to the hyperloop/state branch via the store API."""
    from hyperloop.adapters.git.state import GitStateStore
    from hyperloop.domain.model import Phase, Task, TaskStatus

    status_map = {
        "not-started": TaskStatus.NOT_STARTED,
        "in-progress": TaskStatus.IN_PROGRESS,
        "complete": TaskStatus.COMPLETED,
        "completed": TaskStatus.COMPLETED,
        "failed": TaskStatus.FAILED,
    }
    task = Task(
        id=fm["id"],  # type: ignore[arg-type]
        title=fm["title"],  # type: ignore[arg-type]
        spec_ref=fm["spec_ref"],  # type: ignore[arg-type]
        status=status_map[fm["status"]],  # type: ignore[index]
        phase=Phase(str(fm["phase"])) if fm.get("phase") else None,  # type: ignore[index]
        deps=tuple(fm.get("deps", ())),  # type: ignore[arg-type]
        round=fm.get("round", 0),  # type: ignore[arg-type]
        branch=fm.get("branch"),  # type: ignore[arg-type]
        pr=fm.get("pr"),  # type: ignore[arg-type]
    )
    store = GitStateStore(repo)
    store.add_task(task)
    store.persist(f"seed {task_id}")


def _write_spec_file(repo: Path, spec_path: str, content: str) -> None:
    """Write a spec file and commit it so git show HEAD:path works."""
    full_path = repo / spec_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content)


def _commit_all(repo: Path, message: str = "seed") -> None:
    """Stage all and commit."""
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--no-verify", "-m", message],
        check=True,
        capture_output=True,
    )


def _make_client(repo: Path) -> TestClient:
    """Create a TestClient pointing at a temp repo.

    Initializes deps directly rather than relying on lifespan,
    since TestClient context manager usage varies across versions.
    """
    deps.init(repo)
    app = create_app(str(repo))
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture
def seeded_repo(tmp_path: Path) -> Path:
    """Create a temp git repo with two tasks and one spec."""
    from hyperloop.adapters.git.state import GitStateStore
    from hyperloop.domain.model import Phase, Task, TaskStatus

    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    _write_spec_file(repo, "specs/widget.md", "# Widget Feature\n\nBuild the widget.\n")
    _commit_all(repo)

    store = GitStateStore(repo)
    store.add_task(
        Task(
            id="task-001",
            title="Build widget",
            spec_ref="specs/widget.md@abc123",
            status=TaskStatus.IN_PROGRESS,
            phase=Phase("implementer"),
            deps=(),
            round=1,
            branch="hyperloop/task-001",
            pr="https://github.com/owner/repo/pull/1",
        )
    )
    store.add_task(
        Task(
            id="task-002",
            title="Test widget",
            spec_ref="specs/widget.md@abc123",
            status=TaskStatus.NOT_STARTED,
            phase=None,
            deps=("task-001",),
            round=0,
            branch=None,
            pr=None,
        )
    )
    store.store_review("task-001", 0, "verifier", "fail", "Tests fail: missing null check.")
    store.persist("seed tasks")
    return repo


class TestHealth:
    def test_health_returns_ok(self, seeded_repo: Path) -> None:
        client = _make_client(seeded_repo)
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["state_store"] == "git"
        assert data["spec_source"] == "git"
        assert str(seeded_repo) in data["repo_path"]


class TestTasks:
    def test_list_all_tasks(self, seeded_repo: Path) -> None:
        client = _make_client(seeded_repo)
        resp = client.get("/api/tasks")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        ids = {t["id"] for t in data}
        assert ids == {"task-001", "task-002"}

    def test_filter_by_status(self, seeded_repo: Path) -> None:
        client = _make_client(seeded_repo)
        resp = client.get("/api/tasks", params={"status": "in-progress"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == "task-001"

    def test_filter_by_spec_ref(self, seeded_repo: Path) -> None:
        client = _make_client(seeded_repo)
        resp = client.get("/api/tasks", params={"spec_ref": "specs/widget.md"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    def test_task_detail(self, seeded_repo: Path) -> None:
        client = _make_client(seeded_repo)
        resp = client.get("/api/tasks/task-001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "task-001"
        assert data["status"] == "in-progress"
        assert data["phase"] == "implementer"
        assert data["deps"] == []
        assert len(data["reviews"]) == 1
        review = data["reviews"][0]
        assert review["round"] == 0
        assert review["role"] == "verifier"
        assert review["verdict"] == "fail"
        assert "null check" in review["detail"]

    def test_task_detail_with_deps(self, seeded_repo: Path) -> None:
        client = _make_client(seeded_repo)
        resp = client.get("/api/tasks/task-002")
        assert resp.status_code == 200
        data = resp.json()
        assert data["deps"] == ["task-001"]
        assert data["reviews"] == []

    def test_task_detail_deps_detail(self, seeded_repo: Path) -> None:
        client = _make_client(seeded_repo)
        resp = client.get("/api/tasks/task-002")
        assert resp.status_code == 200
        data = resp.json()
        deps_detail = data["deps_detail"]
        assert len(deps_detail) == 1
        assert deps_detail[0]["id"] == "task-001"
        assert deps_detail[0]["title"] == "Build widget"
        assert deps_detail[0]["status"] == "in-progress"

    def test_task_detail_no_deps_has_empty_detail(self, seeded_repo: Path) -> None:
        client = _make_client(seeded_repo)
        resp = client.get("/api/tasks/task-001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["deps_detail"] == []

    def test_task_not_found(self, seeded_repo: Path) -> None:
        client = _make_client(seeded_repo)
        resp = client.get("/api/tasks/task-999")
        assert resp.status_code == 404


class TestSpecs:
    def test_list_specs(self, seeded_repo: Path) -> None:
        client = _make_client(seeded_repo)
        resp = client.get("/api/specs")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        widget_spec = next(s for s in data if s["spec_ref"] == "specs/widget.md")
        assert widget_spec["title"] == "Widget Feature"
        assert widget_spec["tasks_total"] == 2
        assert widget_spec["tasks_in_progress"] == 1
        assert widget_spec["tasks_not_started"] == 1
        assert widget_spec["tasks_complete"] == 0
        assert widget_spec["tasks_failed"] == 0
        # New sync metadata fields are present
        assert "drift_type" in widget_spec
        assert "stage" in widget_spec
        assert "current_sha" in widget_spec
        assert "pinned_sha" in widget_spec

    def test_list_specs_includes_drift_and_stage(self, seeded_repo: Path) -> None:
        """Spec listing includes drift_type and stage fields.

        The seeded repo has tasks pinned to a fake SHA (abc123), so
        the spec should show freshness drift since the current blob SHA
        differs from the pinned SHA.
        """
        client = _make_client(seeded_repo)
        resp = client.get("/api/specs")
        data = resp.json()
        widget_spec = next(s for s in data if s["spec_ref"] == "specs/widget.md")
        # Pinned to abc123 but file has a real blob SHA -> freshness drift
        assert widget_spec["drift_type"] == "freshness"
        assert widget_spec["stage"] == "freshness-drift"
        assert widget_spec["pinned_sha"] == "abc123"
        assert widget_spec["current_sha"] is not None
        assert widget_spec["current_sha"] != "abc123"

    def test_spec_with_no_tasks_shows_written_and_coverage(self, tmp_path: Path) -> None:
        """A spec with no tasks and no summary shows stage 'written' and drift_type 'coverage'."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        _write_spec_file(repo, "specs/orphan.md", "# Orphan Feature\n\nNo tasks here.\n")
        _commit_all(repo)

        client = _make_client(repo)
        resp = client.get("/api/specs")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        spec = data[0]
        assert spec["spec_ref"] == "specs/orphan.md"
        assert spec["stage"] == "written"
        assert spec["drift_type"] == "coverage"
        assert "no tasks" in spec["drift_detail"]
        assert spec["tasks_total"] == 0

    def test_spec_with_completed_tasks_pending_audit(self, tmp_path: Path) -> None:
        """A spec where all tasks are completed but no audit shows 'pending-audit'."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        _write_spec_file(repo, "specs/done.md", "# Done Feature\n\nAll done.\n")
        _commit_all(repo)

        # Get the real blob SHA so pinned SHA matches (no freshness drift)
        sha = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD:specs/done.md"],
            capture_output=True,
            text=True,
        ).stdout.strip()

        _write_task_file(
            repo,
            "task-100",
            {
                "id": "task-100",
                "title": "Complete task",
                "spec_ref": f"specs/done.md@{sha}",
                "status": "complete",
                "phase": None,
                "deps": [],
                "round": 1,
                "branch": None,
                "pr": None,
            },
        )

        client = _make_client(repo)
        resp = client.get("/api/specs")
        data = resp.json()
        spec = next(s for s in data if s["spec_ref"] == "specs/done.md")
        assert spec["stage"] == "pending-audit"
        assert spec["drift_type"] is None

    def test_spec_with_completed_tasks_converged(self, tmp_path: Path) -> None:
        """A spec where all tasks completed and audit says 'aligned' shows 'converged'."""
        import json
        from datetime import UTC, datetime

        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        _write_spec_file(repo, "specs/aligned.md", "# Aligned Spec\n\nDone.\n")
        _commit_all(repo)

        sha = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD:specs/aligned.md"],
            capture_output=True,
            text=True,
        ).stdout.strip()

        _write_task_file(
            repo,
            "task-200",
            {
                "id": "task-200",
                "title": "Aligned task",
                "spec_ref": f"specs/aligned.md@{sha}",
                "status": "complete",
                "phase": None,
                "deps": [],
                "round": 1,
                "branch": None,
                "pr": None,
            },
        )

        # Write audit event
        events_dir = tmp_path / "cache"
        events_dir.mkdir()
        events_path = events_dir / "events.jsonl"
        now = datetime.now(UTC).isoformat()
        event = {
            "ts": now,
            "event": "audit_ran",
            "spec_ref": "specs/aligned.md",
            "result": "aligned",
            "cycle": 1,
            "duration_s": 5.0,
        }
        events_path.write_text(json.dumps(event) + "\n")

        pointer_dir = repo / ".hyperloop"
        pointer_dir.mkdir(parents=True, exist_ok=True)
        (pointer_dir / ".dashboard-events-path").write_text(str(events_path))
        _commit_all(repo)

        client = _make_client(repo)
        resp = client.get("/api/specs")
        data = resp.json()
        spec = next(s for s in data if s["spec_ref"] == "specs/aligned.md")
        assert spec["stage"] == "converged"
        assert spec["drift_type"] is None
        assert spec["last_audit_result"] == "aligned"

    def test_baselined_spec_shows_baselined_stage(self, tmp_path: Path) -> None:
        """A spec with a summary but no tasks shows stage 'baselined'."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        _write_spec_file(repo, "specs/legacy.md", "# Legacy Spec\n\nPre-hyperloop.\n")
        _commit_all(repo)

        sha = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD:specs/legacy.md"],
            capture_output=True,
            text=True,
        ).stdout.strip()

        # Write a summary for this spec
        from hyperloop.adapters.git.state import GitStateStore

        store = GitStateStore(repo)
        summary_yaml = yaml.dump(
            {
                "spec_path": "specs/legacy.md",
                "spec_ref": f"specs/legacy.md@{sha}",
                "total_tasks": 3,
                "completed": 3,
                "failed": 0,
                "last_audit": "2025-01-01T00:00:00Z",
                "last_audit_result": "aligned",
            }
        )
        store.store_summary("specs/legacy.md", summary_yaml)
        store.persist("add summary")

        client = _make_client(repo)
        resp = client.get("/api/specs")
        data = resp.json()
        spec = next(s for s in data if s["spec_ref"] == "specs/legacy.md")
        assert spec["stage"] == "baselined"
        assert spec["drift_type"] is None
        assert spec["last_audit_result"] == "aligned"

    def test_spec_drift_detail_freshness(self, tmp_path: Path) -> None:
        """Drift detail endpoint returns old/new content for freshness drift."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        _write_spec_file(repo, "specs/drifted.md", "# Drifted Spec\n\nOriginal content.\n")
        _commit_all(repo)

        old_sha = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD:specs/drifted.md"],
            capture_output=True,
            text=True,
        ).stdout.strip()

        # Pin task to old SHA
        _write_task_file(
            repo,
            "task-300",
            {
                "id": "task-300",
                "title": "Drifted task",
                "spec_ref": f"specs/drifted.md@{old_sha}",
                "status": "complete",
                "phase": None,
                "deps": [],
                "round": 1,
                "branch": None,
                "pr": None,
            },
        )

        # Modify the spec to create freshness drift
        _write_spec_file(repo, "specs/drifted.md", "# Drifted Spec\n\nUpdated content.\n")
        _commit_all(repo, "modify spec")

        client = _make_client(repo)
        resp = client.get("/api/specs/specs/drifted.md/drift")
        assert resp.status_code == 200
        data = resp.json()
        assert data["spec_ref"] == "specs/drifted.md"
        assert data["drift_type"] == "freshness"
        assert data["old_sha"] == old_sha
        assert data["new_sha"] is not None
        assert data["new_sha"] != old_sha
        assert data["old_content"] is not None
        assert "Original content" in data["old_content"]
        assert data["new_content"] is not None
        assert "Updated content" in data["new_content"]

    def test_spec_drift_detail_no_drift(self, tmp_path: Path) -> None:
        """Drift detail endpoint returns no drift when SHAs match."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        _write_spec_file(repo, "specs/stable.md", "# Stable Spec\n\nNo changes.\n")
        _commit_all(repo)

        sha = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD:specs/stable.md"],
            capture_output=True,
            text=True,
        ).stdout.strip()

        _write_task_file(
            repo,
            "task-400",
            {
                "id": "task-400",
                "title": "Stable task",
                "spec_ref": f"specs/stable.md@{sha}",
                "status": "in-progress",
                "phase": "implementer",
                "deps": [],
                "round": 0,
                "branch": None,
                "pr": None,
            },
        )

        client = _make_client(repo)
        resp = client.get("/api/specs/specs/stable.md/drift")
        assert resp.status_code == 200
        data = resp.json()
        assert data["drift_type"] is None
        assert data["old_content"] is None
        assert data["new_content"] is None

    def test_spec_drift_detail_not_found(self, tmp_path: Path) -> None:
        """Drift detail endpoint returns 404 for missing spec."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        client = _make_client(repo)
        resp = client.get("/api/specs/specs/missing.md/drift")
        assert resp.status_code == 404

    def test_spec_detail(self, seeded_repo: Path) -> None:
        client = _make_client(seeded_repo)
        resp = client.get("/api/specs/specs/widget.md")
        assert resp.status_code == 200
        data = resp.json()
        assert data["spec_ref"] == "specs/widget.md"
        assert "Widget Feature" in data["content"]
        assert len(data["tasks"]) == 2

    def test_spec_not_found(self, seeded_repo: Path) -> None:
        client = _make_client(seeded_repo)
        resp = client.get("/api/specs/specs/nonexistent.md")
        assert resp.status_code == 404


class TestSummary:
    def test_summary_counts(self, seeded_repo: Path) -> None:
        client = _make_client(seeded_repo)
        resp = client.get("/api/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["not_started"] == 1
        assert data["in_progress"] == 1
        assert data["complete"] == 0
        assert data["failed"] == 0
        assert data["specs_total"] == 1
        assert data["specs_complete"] == 0


class TestEmptyRepo:
    def test_empty_repo_endpoints(self, tmp_path: Path) -> None:
        """All endpoints return gracefully on a repo with no tasks."""
        repo = tmp_path / "empty"
        repo.mkdir()
        _init_git_repo(repo)
        client = _make_client(repo)

        assert client.get("/api/health").status_code == 200
        assert client.get("/api/tasks").json() == []
        assert client.get("/api/specs").json() == []

        summary_data = client.get("/api/summary").json()
        assert summary_data["total"] == 0
        assert summary_data["specs_total"] == 0


class TestPipeline:
    def test_pipeline_returns_steps(self, tmp_path: Path) -> None:
        """Pipeline endpoint returns flattened steps from process.yaml."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        # Write a process.yaml in base/
        base_dir = repo / "base"
        base_dir.mkdir()
        process_yaml = {
            "apiVersion": "hyperloop.io/v1",
            "kind": "Process",
            "metadata": {"name": "default"},
            "pipeline": [
                {"loop": [{"agent": "implementer"}, {"agent": "verifier"}]},
                {"gate": "pr-require-label"},
                {"action": "merge-pr"},
            ],
        }
        (base_dir / "process.yaml").write_text(yaml.dump(process_yaml))
        _commit_all(repo)

        client = _make_client(repo)
        resp = client.get("/api/pipeline")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 4
        assert data[0] == {"name": "implementer", "type": "agent"}
        assert data[1] == {"name": "verifier", "type": "agent"}
        assert data[2] == {"name": "pr-require-label", "type": "gate"}
        assert data[3] == {"name": "merge-pr", "type": "action"}

    def test_pipeline_empty_when_no_process(self, tmp_path: Path) -> None:
        """Pipeline endpoint returns empty list when no process.yaml exists."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        client = _make_client(repo)
        resp = client.get("/api/pipeline")
        assert resp.status_code == 200
        assert resp.json() == []


class TestPromptReconstruction:
    def test_prompt_returns_sections(self, tmp_path: Path) -> None:
        """Prompt endpoint returns reconstructed prompt sections for a task."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        # Write an agent template
        base_dir = repo / "base"
        base_dir.mkdir()
        agent_yaml = {
            "apiVersion": "hyperloop.io/v1",
            "kind": "Agent",
            "metadata": {"name": "implementer"},
            "prompt": "You are implementing task {task_id}.",
            "guidelines": "Follow the code style.",
        }
        (base_dir / "implementer.yaml").write_text(yaml.dump(agent_yaml))

        _write_spec_file(repo, "specs/widget.md", "# Widget\n\nBuild it.\n")
        _write_task_file(
            repo,
            "task-001",
            {
                "id": "task-001",
                "title": "Build widget",
                "spec_ref": "specs/widget.md@abc",
                "status": "in-progress",
                "phase": "implementer",
                "deps": [],
                "round": 1,
                "branch": "hyperloop/task-001",
                "pr": None,
            },
        )
        _commit_all(repo)

        client = _make_client(repo)
        resp = client.get("/api/tasks/task-001/prompt")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1

        # The implementer prompt should be first (current phase)
        impl = data[0]
        assert impl["role"] == "implementer"
        sections = impl["sections"]
        labels = [s["label"] for s in sections]
        assert "prompt" in labels
        assert "guidelines" in labels
        assert "spec" in labels

        # Verify variable substitution happened
        prompt_section = next(s for s in sections if s["label"] == "prompt")
        assert "task-001" in prompt_section["content"]

    def test_prompt_empty_when_no_templates(self, tmp_path: Path) -> None:
        """Prompt endpoint returns empty list when no agent templates exist."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        _write_task_file(
            repo,
            "task-001",
            {
                "id": "task-001",
                "title": "A task",
                "spec_ref": "specs/a.md",
                "status": "not-started",
                "phase": None,
                "deps": [],
                "round": 0,
                "branch": None,
                "pr": None,
            },
        )

        client = _make_client(repo)
        resp = client.get("/api/tasks/task-001/prompt")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_prompt_not_found_for_missing_task(self, tmp_path: Path) -> None:
        """Prompt endpoint returns 404 for unknown task."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        client = _make_client(repo)
        resp = client.get("/api/tasks/task-999/prompt")
        assert resp.status_code == 404


class TestCompleteSpec:
    def test_spec_complete_when_all_terminal_with_at_least_one_complete(
        self, tmp_path: Path
    ) -> None:
        """A spec is complete when all tasks are terminal and at least one is complete."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        _write_spec_file(repo, "specs/done.md", "# Done Feature\n\nDone.\n")
        _write_task_file(
            repo,
            "task-010",
            {
                "id": "task-010",
                "title": "Complete task",
                "spec_ref": "specs/done.md@def456",
                "status": "complete",
                "phase": None,
                "deps": [],
                "round": 2,
                "branch": "hyperloop/task-010",
                "pr": None,
            },
        )
        _write_task_file(
            repo,
            "task-011",
            {
                "id": "task-011",
                "title": "Failed task",
                "spec_ref": "specs/done.md@def456",
                "status": "failed",
                "phase": None,
                "deps": [],
                "round": 3,
                "branch": "hyperloop/task-011",
                "pr": None,
            },
        )
        _commit_all(repo)
        client = _make_client(repo)

        data = client.get("/api/summary").json()
        assert data["specs_complete"] == 1
        assert data["specs_total"] == 1


class TestGraph:
    def test_graph_returns_nodes_and_edges(self, seeded_repo: Path) -> None:
        """Graph endpoint returns nodes with status and edges from deps."""
        client = _make_client(seeded_repo)
        resp = client.get("/api/tasks/graph")
        assert resp.status_code == 200
        data = resp.json()

        assert len(data["nodes"]) == 2
        ids = {n["id"] for n in data["nodes"]}
        assert ids == {"task-001", "task-002"}

        # task-002 depends on task-001
        assert len(data["edges"]) == 1
        edge = data["edges"][0]
        assert edge["from_id"] == "task-001"
        assert edge["to_id"] == "task-002"

    def test_graph_node_fields(self, seeded_repo: Path) -> None:
        """Graph nodes include status, phase, spec_ref without version, and round."""
        client = _make_client(seeded_repo)
        data = client.get("/api/tasks/graph").json()

        task_001 = next(n for n in data["nodes"] if n["id"] == "task-001")
        assert task_001["status"] == "in-progress"
        assert task_001["phase"] == "implementer"
        assert task_001["spec_ref"] == "specs/widget.md"  # no @version
        assert task_001["round"] == 1

        task_002 = next(n for n in data["nodes"] if n["id"] == "task-002")
        assert task_002["round"] == 0

    def test_graph_critical_path(self, seeded_repo: Path) -> None:
        """Critical path includes the longest chain of non-terminal tasks."""
        client = _make_client(seeded_repo)
        data = client.get("/api/tasks/graph").json()

        # Both tasks are non-terminal (in-progress and not-started)
        # task-001 -> task-002 is the longest path
        assert "task-001" in data["critical_path"]
        assert "task-002" in data["critical_path"]

    def test_graph_empty_repo(self, tmp_path: Path) -> None:
        """Graph endpoint returns empty data for a repo with no tasks."""
        repo = tmp_path / "empty"
        repo.mkdir()
        _init_git_repo(repo)
        client = _make_client(repo)

        resp = client.get("/api/tasks/graph")
        assert resp.status_code == 200
        data = resp.json()
        assert data["nodes"] == []
        assert data["edges"] == []
        assert data["critical_path"] == []

    def test_critical_path_excludes_terminal_tasks(self, tmp_path: Path) -> None:
        """Critical path only includes non-terminal tasks."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        _write_task_file(
            repo,
            "task-a",
            {
                "id": "task-a",
                "title": "Complete",
                "spec_ref": "specs/a.md",
                "status": "complete",
                "phase": None,
                "deps": [],
                "round": 1,
                "branch": None,
                "pr": None,
            },
        )
        _write_task_file(
            repo,
            "task-b",
            {
                "id": "task-b",
                "title": "In progress",
                "spec_ref": "specs/a.md",
                "status": "in-progress",
                "phase": "implementer",
                "deps": ["task-a"],
                "round": 0,
                "branch": None,
                "pr": None,
            },
        )
        client = _make_client(repo)
        data = client.get("/api/tasks/graph").json()

        # task-a is complete so not on critical path
        # task-b depends on task-a, but task-a is terminal
        # so critical path is just task-b (the only non-terminal)
        assert "task-a" not in data["critical_path"]
        assert "task-b" in data["critical_path"]


class TestActivity:
    def test_activity_no_events(self, tmp_path: Path) -> None:
        """Returns enabled=false when no events file exists."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        client = _make_client(repo)

        resp = client.get("/api/activity")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is False
        assert data["current_cycle"] == 0
        assert data["cycles"] == []
        assert data["active_workers"] == []
        assert data["tasks_in_flight"] == []
        assert data["flattened_events"] == []

    def test_activity_with_events(self, tmp_path: Path) -> None:
        """Parses JSONL events and returns grouped cycles."""
        import json
        from datetime import UTC, datetime

        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        # Write events JSONL file
        events_dir = tmp_path / "cache"
        events_dir.mkdir()
        events_path = events_dir / "events.jsonl"

        now = datetime.now(UTC).isoformat()
        events = [
            {
                "ts": now,
                "event": "cycle_started",
                "cycle": 1,
                "active_workers": 0,
                "not_started": 2,
                "in_progress": 0,
                "complete": 0,
                "failed": 0,
            },
            {
                "ts": now,
                "event": "worker_spawned",
                "task_id": "task-001",
                "role": "implementer",
                "branch": "hyperloop/task-001",
                "round": 0,
                "cycle": 1,
                "spec_ref": "specs/a.md",
            },
            {
                "ts": now,
                "event": "task_advanced",
                "task_id": "task-001",
                "from_phase": None,
                "to_phase": "implementer",
                "from_status": "not-started",
                "to_status": "in-progress",
                "round": 0,
                "cycle": 1,
                "spec_ref": "specs/a.md",
            },
            {
                "ts": now,
                "event": "cycle_completed",
                "cycle": 1,
                "active_workers": 1,
                "not_started": 1,
                "in_progress": 1,
                "complete": 0,
                "failed": 0,
                "spawned_ids": ["task-001"],
                "reaped_ids": [],
                "duration_s": 2.5,
            },
        ]
        with open(events_path, "w") as f:
            for ev in events:
                f.write(json.dumps(ev) + "\n")

        # Write pointer file
        pointer_dir = repo / ".hyperloop"
        pointer_dir.mkdir(parents=True, exist_ok=True)
        (pointer_dir / ".dashboard-events-path").write_text(str(events_path))
        _commit_all(repo)

        client = _make_client(repo)
        resp = client.get("/api/activity")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert data["current_cycle"] == 1
        assert len(data["cycles"]) == 1
        cycle = data["cycles"][0]
        assert cycle["cycle"] == 1
        assert cycle["duration_s"] == 2.5
        assert len(cycle["phases"]["spawn"]["spawned"]) == 1
        assert cycle["phases"]["spawn"]["spawned"][0]["task_id"] == "task-001"
        assert len(cycle["phases"]["advance"]["transitions"]) == 1
        # Worker is still active (spawned but not reaped)
        assert len(data["active_workers"]) == 1
        assert data["active_workers"][0]["task_id"] == "task-001"
        # Flattened events: worker_spawned + task_advanced (not cycle bookkeeping)
        assert len(data["flattened_events"]) == 2
        event_types = [e["event_type"] for e in data["flattened_events"]]
        assert "worker_spawned" in event_types
        assert "task_advanced" in event_types
        # tasks_in_flight: no task files in this repo, so empty
        assert data["tasks_in_flight"] == []

    def test_activity_tasks_in_flight(self, tmp_path: Path) -> None:
        """Returns in-flight tasks with worker history."""
        import json
        from datetime import UTC, datetime

        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        # Write an in-progress task
        _write_task_file(
            repo,
            "task-001",
            {
                "id": "task-001",
                "title": "Build widget",
                "spec_ref": "specs/widget.md@abc123",
                "status": "in-progress",
                "phase": "implementer",
                "deps": [],
                "round": 2,
                "branch": "hyperloop/task-001",
                "pr": None,
            },
        )

        # Write events with a reaped worker and an active worker
        events_dir = tmp_path / "cache"
        events_dir.mkdir()
        events_path = events_dir / "events.jsonl"

        now = datetime.now(UTC).isoformat()
        events = [
            {
                "ts": now,
                "event": "cycle_started",
                "cycle": 1,
            },
            {
                "ts": now,
                "event": "worker_spawned",
                "task_id": "task-001",
                "role": "implementer",
                "round": 1,
                "cycle": 1,
                "spec_ref": "specs/widget.md",
            },
            {
                "ts": now,
                "event": "worker_reaped",
                "task_id": "task-001",
                "role": "implementer",
                "round": 1,
                "cycle": 2,
                "verdict": "fail",
                "duration_s": 120.5,
            },
            {
                "ts": now,
                "event": "worker_spawned",
                "task_id": "task-001",
                "role": "implementer",
                "round": 2,
                "cycle": 3,
                "spec_ref": "specs/widget.md",
            },
        ]
        with open(events_path, "w") as f:
            for ev in events:
                f.write(json.dumps(ev) + "\n")

        pointer_dir = repo / ".hyperloop"
        pointer_dir.mkdir(parents=True, exist_ok=True)
        (pointer_dir / ".dashboard-events-path").write_text(str(events_path))
        _commit_all(repo)

        client = _make_client(repo)
        resp = client.get("/api/activity")
        assert resp.status_code == 200
        data = resp.json()

        # Should have one in-flight task
        assert len(data["tasks_in_flight"]) == 1
        task = data["tasks_in_flight"][0]
        assert task["task_id"] == "task-001"
        assert task["title"] == "Build widget"
        assert task["phase"] == "implementer"
        assert task["round"] == 2
        assert task["spec_ref"] == "specs/widget.md"
        # Should have one history entry (the reaped worker)
        assert len(task["worker_history"]) == 1
        assert task["worker_history"][0]["role"] == "implementer"
        assert task["worker_history"][0]["verdict"] == "fail"
        assert task["worker_history"][0]["duration_s"] == 120.5
        # Should have a current worker (the second spawn, not yet reaped)
        assert task["current_worker"] is not None
        assert task["current_worker"]["role"] == "implementer"

    def test_file_probe_writes_events(self, tmp_path: Path) -> None:
        """FileProbe writes JSONL events to disk."""
        import json

        from hyperloop.adapters.probe.file import FileProbe

        events_path = tmp_path / "events.jsonl"
        probe = FileProbe(events_path, max_events=100)

        probe.cycle_started(
            cycle=1,
            active_workers=0,
            not_started=5,
            in_progress=0,
            complete=0,
            failed=0,
        )
        probe.worker_spawned(
            task_id="task-001",
            role="implementer",
            branch="hyperloop/task-001",
            round=0,
            cycle=1,
            spec_ref="specs/a.md",
        )

        assert events_path.exists()
        lines = events_path.read_text().strip().splitlines()
        assert len(lines) == 2

        ev1 = json.loads(lines[0])
        assert ev1["event"] == "cycle_started"
        assert ev1["cycle"] == 1

        ev2 = json.loads(lines[1])
        assert ev2["event"] == "worker_spawned"
        assert ev2["task_id"] == "task-001"

    def test_file_probe_truncates_on_startup(self, tmp_path: Path) -> None:
        """FileProbe truncates to max_events when file exceeds limit."""
        import json

        from hyperloop.adapters.probe.file import FileProbe

        events_path = tmp_path / "events.jsonl"
        # Write 10 events
        with open(events_path, "w") as f:
            for i in range(10):
                f.write(json.dumps({"ts": "2024-01-01", "event": "test", "n": i}) + "\n")

        # Create probe with max_events=5 -- should truncate on startup
        _probe = FileProbe(events_path, max_events=5)
        lines = events_path.read_text().strip().splitlines()
        assert len(lines) == 5

        # Should keep the last 5
        first = json.loads(lines[0])
        assert first["n"] == 5

    def test_file_probe_serializes_tuples(self, tmp_path: Path) -> None:
        """FileProbe serializes tuples to lists."""
        import json

        from hyperloop.adapters.probe.file import FileProbe

        events_path = tmp_path / "events.jsonl"
        probe = FileProbe(events_path)

        probe.cycle_completed(
            cycle=1,
            active_workers=0,
            not_started=0,
            in_progress=0,
            complete=1,
            failed=0,
            spawned_ids=("task-001",),
            reaped_ids=(),
            duration_s=1.0,
        )

        lines = events_path.read_text().strip().splitlines()
        ev = json.loads(lines[0])
        assert ev["spawned_ids"] == ["task-001"]
        assert ev["reaped_ids"] == []


class TestAuditTimeline:
    """Tests for the audit_timeline field on CycleDetail."""

    def test_audit_timeline_with_parallel_auditors(self, tmp_path: Path) -> None:
        """Cycle with audit events returns a populated audit_timeline."""
        import json
        from datetime import UTC, datetime, timedelta

        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        events_dir = tmp_path / "cache"
        events_dir.mkdir()
        events_path = events_dir / "events.jsonl"

        base = datetime.now(UTC)
        events = [
            {
                "ts": base.isoformat(),
                "event": "cycle_started",
                "cycle": 1,
            },
            # Two auditors started in parallel
            {
                "ts": base.isoformat(),
                "event": "audit_started",
                "spec_ref": "specs/widget.md",
                "cycle": 1,
            },
            {
                "ts": (base + timedelta(seconds=0.1)).isoformat(),
                "event": "audit_started",
                "spec_ref": "specs/auth.md",
                "cycle": 1,
            },
            # First auditor finishes
            {
                "ts": (base + timedelta(seconds=12.0)).isoformat(),
                "event": "audit_ran",
                "spec_ref": "specs/widget.md",
                "result": "aligned",
                "cycle": 1,
                "duration_s": 12.0,
            },
            # Second auditor finishes
            {
                "ts": (base + timedelta(seconds=15.2)).isoformat(),
                "event": "audit_ran",
                "spec_ref": "specs/auth.md",
                "result": "misaligned",
                "cycle": 1,
                "duration_s": 15.1,
            },
            {
                "ts": (base + timedelta(seconds=16.0)).isoformat(),
                "event": "cycle_completed",
                "cycle": 1,
                "duration_s": 16.0,
            },
        ]
        with open(events_path, "w") as f:
            for ev in events:
                f.write(json.dumps(ev) + "\n")

        pointer_dir = repo / ".hyperloop"
        pointer_dir.mkdir(parents=True, exist_ok=True)
        (pointer_dir / ".dashboard-events-path").write_text(str(events_path))
        _commit_all(repo)

        client = _make_client(repo)
        resp = client.get("/api/activity")
        assert resp.status_code == 200
        data = resp.json()

        cycle = data["cycles"][0]
        timeline = cycle["audit_timeline"]
        assert timeline is not None
        assert len(timeline["entries"]) == 2
        assert timeline["total_duration_s"] == 15.1
        assert timeline["max_parallelism"] == 2

        # Verify individual entries
        entries_by_spec = {e["spec_ref"]: e for e in timeline["entries"]}
        assert entries_by_spec["specs/widget.md"]["result"] == "aligned"
        assert entries_by_spec["specs/widget.md"]["duration_s"] == 12.0
        assert entries_by_spec["specs/widget.md"]["started_at"] != ""
        assert entries_by_spec["specs/auth.md"]["result"] == "misaligned"
        assert entries_by_spec["specs/auth.md"]["duration_s"] == 15.1

    def test_audit_timeline_none_when_no_audits(self, tmp_path: Path) -> None:
        """Cycle without audit events has audit_timeline = null."""
        import json
        from datetime import UTC, datetime

        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        events_dir = tmp_path / "cache"
        events_dir.mkdir()
        events_path = events_dir / "events.jsonl"

        now = datetime.now(UTC).isoformat()
        events = [
            {"ts": now, "event": "cycle_started", "cycle": 1},
            {"ts": now, "event": "cycle_completed", "cycle": 1, "duration_s": 1.0},
        ]
        with open(events_path, "w") as f:
            for ev in events:
                f.write(json.dumps(ev) + "\n")

        pointer_dir = repo / ".hyperloop"
        pointer_dir.mkdir(parents=True, exist_ok=True)
        (pointer_dir / ".dashboard-events-path").write_text(str(events_path))
        _commit_all(repo)

        client = _make_client(repo)
        data = client.get("/api/activity").json()

        cycle = data["cycles"][0]
        assert cycle["audit_timeline"] is None

    def test_audit_timeline_single_auditor(self, tmp_path: Path) -> None:
        """Cycle with a single auditor has max_parallelism = 1."""
        import json
        from datetime import UTC, datetime

        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        events_dir = tmp_path / "cache"
        events_dir.mkdir()
        events_path = events_dir / "events.jsonl"

        now = datetime.now(UTC)
        events = [
            {"ts": now.isoformat(), "event": "cycle_started", "cycle": 1},
            {
                "ts": now.isoformat(),
                "event": "audit_started",
                "spec_ref": "specs/only.md",
                "cycle": 1,
            },
            {
                "ts": now.isoformat(),
                "event": "audit_ran",
                "spec_ref": "specs/only.md",
                "result": "aligned",
                "cycle": 1,
                "duration_s": 5.3,
            },
            {"ts": now.isoformat(), "event": "cycle_completed", "cycle": 1, "duration_s": 6.0},
        ]
        with open(events_path, "w") as f:
            for ev in events:
                f.write(json.dumps(ev) + "\n")

        pointer_dir = repo / ".hyperloop"
        pointer_dir.mkdir(parents=True, exist_ok=True)
        (pointer_dir / ".dashboard-events-path").write_text(str(events_path))
        _commit_all(repo)

        client = _make_client(repo)
        data = client.get("/api/activity").json()

        timeline = data["cycles"][0]["audit_timeline"]
        assert timeline is not None
        assert len(timeline["entries"]) == 1
        assert timeline["max_parallelism"] == 1
        assert timeline["total_duration_s"] == 5.3
        assert timeline["entries"][0]["result"] == "aligned"

    def test_audit_timeline_fallback_without_audit_started(self, tmp_path: Path) -> None:
        """Audit timeline works even without audit_started events (uses subtraction)."""
        import json
        from datetime import UTC, datetime, timedelta

        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        events_dir = tmp_path / "cache"
        events_dir.mkdir()
        events_path = events_dir / "events.jsonl"

        now = datetime.now(UTC)
        events = [
            {"ts": now.isoformat(), "event": "cycle_started", "cycle": 1},
            # No audit_started events — only audit_ran
            {
                "ts": (now + timedelta(seconds=10)).isoformat(),
                "event": "audit_ran",
                "spec_ref": "specs/a.md",
                "result": "aligned",
                "cycle": 1,
                "duration_s": 10.0,
            },
            {
                "ts": (now + timedelta(seconds=11)).isoformat(),
                "event": "cycle_completed",
                "cycle": 1,
                "duration_s": 11.0,
            },
        ]
        with open(events_path, "w") as f:
            for ev in events:
                f.write(json.dumps(ev) + "\n")

        pointer_dir = repo / ".hyperloop"
        pointer_dir.mkdir(parents=True, exist_ok=True)
        (pointer_dir / ".dashboard-events-path").write_text(str(events_path))
        _commit_all(repo)

        client = _make_client(repo)
        data = client.get("/api/activity").json()

        timeline = data["cycles"][0]["audit_timeline"]
        assert timeline is not None
        assert len(timeline["entries"]) == 1
        # started_at should be approximated by subtracting duration from ts
        assert timeline["entries"][0]["started_at"] != ""


class TestProcess:
    def test_process_returns_pipeline_tree(self, tmp_path: Path) -> None:
        """Process endpoint preserves pipeline nesting."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        process_dir = repo / ".hyperloop" / "agents" / "process"
        process_dir.mkdir(parents=True)
        process_yaml = {
            "apiVersion": "hyperloop.io/v1",
            "kind": "Process",
            "metadata": {"name": "default"},
            "pipeline": [
                {"loop": [{"agent": "implementer"}, {"agent": "verifier"}]},
                {"gate": "pr-require-label"},
                {"action": "merge-pr"},
            ],
            "gates": {"pr-require-label": {"type": "label"}},
            "actions": {"merge-pr": {"type": "pr-merge"}},
            "hooks": {"after_reap": [{"type": "process-improver"}]},
        }
        (process_dir / "process.yaml").write_text(yaml.dump(process_yaml))
        _commit_all(repo)

        client = _make_client(repo)
        resp = client.get("/api/process")
        assert resp.status_code == 200
        data = resp.json()

        phases = data["phases"]
        phase_order = data["phase_order"]
        assert phase_order == ["implementer", "verifier", "pr-require-label", "merge-pr"]
        assert phases["implementer"]["on_pass"] == "verifier"
        assert phases["implementer"]["on_fail"] == "implementer"
        assert phases["verifier"]["on_pass"] == "pr-require-label"
        assert phases["verifier"]["on_fail"] == "implementer"
        assert phases["pr-require-label"]["run"] == "gate:pr-require-label"
        assert phases["merge-pr"]["run"] == "action:merge-pr"

    def test_process_returns_gates_and_actions(self, tmp_path: Path) -> None:
        """Process endpoint returns gate and action configs."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        process_dir = repo / ".hyperloop" / "agents" / "process"
        process_dir.mkdir(parents=True)
        process_yaml: dict[str, object] = {
            "apiVersion": "hyperloop.io/v1",
            "kind": "Process",
            "metadata": {"name": "default"},
            "pipeline": [],
            "gates": {"my-gate": {"type": "label", "required": True}},
            "actions": {"my-action": {"type": "pr-merge"}},
        }
        (process_dir / "process.yaml").write_text(yaml.dump(process_yaml))
        _commit_all(repo)

        client = _make_client(repo)
        data = client.get("/api/process").json()

        assert data["gates"]["my-gate"]["type"] == "label"
        assert data["actions"]["my-action"]["type"] == "pr-merge"

    def test_process_reads_learning_overlays(self, tmp_path: Path) -> None:
        """Process endpoint reads *-overlay.yaml files for process learning."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        process_dir = repo / ".hyperloop" / "agents" / "process"
        process_dir.mkdir(parents=True)
        (process_dir / "process.yaml").write_text(yaml.dump({"kind": "Process", "pipeline": []}))
        (process_dir / "implementer-overlay.yaml").write_text(
            yaml.dump({"guidelines": "- Do not delete files\n- Run tests"})
        )
        (process_dir / "verifier-overlay.yaml").write_text(
            yaml.dump({"guidelines": "- Run full test suite"})
        )
        _commit_all(repo)

        client = _make_client(repo)
        data = client.get("/api/process").json()

        learning = data["process_learning"]
        assert "implementer" in learning["patched_agents"]
        assert "verifier" in learning["patched_agents"]
        assert "Do not delete files" in learning["guidelines"]["implementer"]
        assert "full test suite" in learning["guidelines"]["verifier"]

    def test_process_no_learning_when_no_overlays(self, tmp_path: Path) -> None:
        """Process learning is empty when no overlay files exist."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        process_dir = repo / ".hyperloop" / "agents" / "process"
        process_dir.mkdir(parents=True)
        (process_dir / "process.yaml").write_text(yaml.dump({"kind": "Process", "pipeline": []}))
        _commit_all(repo)

        client = _make_client(repo)
        data = client.get("/api/process").json()

        assert data["process_learning"]["patched_agents"] == []
        assert data["process_learning"]["guidelines"] == {}

    def test_process_empty_when_no_process_yaml(self, tmp_path: Path) -> None:
        """Process endpoint returns gracefully when no process.yaml exists."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        client = _make_client(repo)
        resp = client.get("/api/process")
        assert resp.status_code == 200
        data = resp.json()

        assert data["phases"] == {}
        assert data["phase_order"] == []
        assert data["gates"] == {}
        assert data["actions"] == {}
        assert data["hooks"] == {}

    def test_process_raw_yaml_present(self, tmp_path: Path) -> None:
        """Process endpoint includes raw YAML for display."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        process_dir = repo / ".hyperloop" / "agents" / "process"
        process_dir.mkdir(parents=True)
        process_yaml = {
            "kind": "Process",
            "pipeline": [{"agent": "implementer"}],
        }
        (process_dir / "process.yaml").write_text(yaml.dump(process_yaml))
        _commit_all(repo)

        client = _make_client(repo)
        data = client.get("/api/process").json()

        assert "implementer" in data["pipeline_raw"]

    def test_process_source_file_present(self, tmp_path: Path) -> None:
        """Process endpoint returns the source file path."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        process_dir = repo / ".hyperloop" / "agents" / "process"
        process_dir.mkdir(parents=True)
        (process_dir / "process.yaml").write_text(yaml.dump({"kind": "Process", "pipeline": []}))
        _commit_all(repo)

        client = _make_client(repo)
        data = client.get("/api/process").json()

        assert "process.yaml" in data["source_file"]


class TestControlRestart:
    """POST /api/tasks/{task_id}/restart resets phase and increments round."""

    def test_restart_resets_phase_and_increments_round(self, seeded_repo: Path) -> None:
        client = _make_client(seeded_repo)
        # task-001 is at phase implementer, round 1
        resp = client.post(
            "/api/tasks/task-001/restart",
            json={"expected_round": 1},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

        # Verify the task was updated
        task_resp = client.get("/api/tasks/task-001").json()
        assert task_resp["status"] == "in-progress"
        assert task_resp["round"] == 2

    def test_restart_version_conflict(self, seeded_repo: Path) -> None:
        client = _make_client(seeded_repo)
        # task-001 is at round 1, send wrong expected_round
        resp = client.post(
            "/api/tasks/task-001/restart",
            json={"expected_round": 0},
        )
        assert resp.status_code == 409

    def test_restart_not_found(self, seeded_repo: Path) -> None:
        client = _make_client(seeded_repo)
        resp = client.post(
            "/api/tasks/task-999/restart",
            json={"expected_round": 0},
        )
        assert resp.status_code == 404


class TestControlRetire:
    """POST /api/tasks/{task_id}/retire transitions to FAILED."""

    def test_retire_sets_status_to_failed(self, seeded_repo: Path) -> None:
        client = _make_client(seeded_repo)
        resp = client.post(
            "/api/tasks/task-001/retire",
            json={"expected_round": 1},
        )
        assert resp.status_code == 200

        task_resp = client.get("/api/tasks/task-001").json()
        assert task_resp["status"] == "failed"

    def test_retire_version_conflict(self, seeded_repo: Path) -> None:
        client = _make_client(seeded_repo)
        resp = client.post(
            "/api/tasks/task-001/retire",
            json={"expected_round": 99},
        )
        assert resp.status_code == 409

    def test_retire_not_found(self, seeded_repo: Path) -> None:
        client = _make_client(seeded_repo)
        resp = client.post(
            "/api/tasks/task-999/retire",
            json={"expected_round": 0},
        )
        assert resp.status_code == 404


class TestControlForceClear:
    """POST /api/tasks/{task_id}/force-clear advances past a signal step."""

    def test_force_clear_advances_past_signal(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        # Write a process.yaml with a signal step
        process_dir = repo / ".hyperloop" / "agents" / "process"
        process_dir.mkdir(parents=True)
        process_yaml = {
            "apiVersion": "hyperloop.io/v1",
            "kind": "Process",
            "metadata": {"name": "default"},
            "phases": {
                "implement": {
                    "run": "agent implementer",
                    "on_pass": "await-review",
                    "on_fail": "implement",
                },
                "await-review": {
                    "run": "signal human-approval",
                    "on_pass": "done",
                    "on_fail": "implement",
                    "on_wait": "await-review",
                },
            },
        }
        (process_dir / "process.yaml").write_text(yaml.dump(process_yaml))

        # Create a task stuck at the signal step
        _write_task_file(
            repo,
            "task-001",
            {
                "id": "task-001",
                "title": "Build widget",
                "spec_ref": "specs/widget.md",
                "status": "in-progress",
                "phase": "await-review",
                "deps": [],
                "round": 1,
                "branch": "hyperloop/task-001",
                "pr": None,
            },
        )
        _commit_all(repo)

        client = _make_client(repo)
        resp = client.post(
            "/api/tasks/task-001/force-clear",
            json={"expected_round": 1},
        )
        assert resp.status_code == 200

        # Task should have advanced to the on_pass target (done -> completed)
        task_resp = client.get("/api/tasks/task-001").json()
        assert task_resp["status"] == "completed"

    def test_force_clear_version_conflict(self, seeded_repo: Path) -> None:
        client = _make_client(seeded_repo)
        resp = client.post(
            "/api/tasks/task-001/force-clear",
            json={"expected_round": 99},
        )
        assert resp.status_code == 409

    def test_force_clear_not_found(self, seeded_repo: Path) -> None:
        client = _make_client(seeded_repo)
        resp = client.post(
            "/api/tasks/task-999/force-clear",
            json={"expected_round": 0},
        )
        assert resp.status_code == 404


class TestAgents:
    def test_agents_list(self, tmp_path: Path) -> None:
        """Returns agents from kustomize build (fallback to base/ YAML)."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        base_dir = repo / "base"
        base_dir.mkdir()
        agent_yaml = {
            "apiVersion": "hyperloop.io/v1",
            "kind": "Agent",
            "metadata": {"name": "implementer"},
            "prompt": "You are implementing a task.",
            "guidelines": "Follow the style guide.",
        }
        (base_dir / "implementer.yaml").write_text(yaml.dump(agent_yaml))

        verifier_yaml = {
            "apiVersion": "hyperloop.io/v1",
            "kind": "Agent",
            "metadata": {"name": "verifier"},
            "prompt": "You are verifying a task.",
            "guidelines": "",
        }
        (base_dir / "verifier.yaml").write_text(yaml.dump(verifier_yaml))
        _commit_all(repo)

        client = _make_client(repo)
        resp = client.get("/api/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        names = [a["name"] for a in data]
        assert "implementer" in names
        assert "verifier" in names

        impl = next(a for a in data if a["name"] == "implementer")
        assert "implementing a task" in impl["prompt"]
        assert impl["guidelines"] == "Follow the style guide."
        assert impl["has_process_patches"] is False
        assert impl["process_overlay_guidelines"] is None
        assert impl["process_overlay_file"] is None

    def test_agents_with_process_overlay(self, tmp_path: Path) -> None:
        """Agents with process overlay files are flagged correctly."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        base_dir = repo / "base"
        base_dir.mkdir()
        agent_yaml = {
            "apiVersion": "hyperloop.io/v1",
            "kind": "Agent",
            "metadata": {"name": "implementer"},
            "prompt": "You are implementing.",
            "guidelines": "Do not delete files.",
        }
        (base_dir / "implementer.yaml").write_text(yaml.dump(agent_yaml))

        process_dir = repo / ".hyperloop" / "agents" / "process"
        process_dir.mkdir(parents=True)
        overlay = {
            "metadata": {"name": "implementer"},
            "guidelines": "- Run tests before submitting.",
        }
        (process_dir / "implementer-overlay.yaml").write_text(yaml.dump(overlay))
        _commit_all(repo)

        client = _make_client(repo)
        data = client.get("/api/agents").json()
        assert len(data) == 1

        impl = data[0]
        assert impl["has_process_patches"] is True
        assert impl["process_overlay_guidelines"] == "- Run tests before submitting."
        assert "implementer-overlay.yaml" in impl["process_overlay_file"]

    def test_agents_empty_repo(self, tmp_path: Path) -> None:
        """Returns empty list when no agent templates exist."""
        repo = tmp_path / "empty"
        repo.mkdir()
        _init_git_repo(repo)

        client = _make_client(repo)
        resp = client.get("/api/agents")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_agents_checks_empty(self, tmp_path: Path) -> None:
        """No checks dir returns empty list."""
        repo = tmp_path / "empty"
        repo.mkdir()
        _init_git_repo(repo)

        client = _make_client(repo)
        resp = client.get("/api/agents/checks")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_agents_checks_returns_scripts(self, tmp_path: Path) -> None:
        """Check scripts endpoint returns script content."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        checks_dir = repo / ".hyperloop" / "checks"
        checks_dir.mkdir(parents=True)
        script_content = "#!/bin/bash\necho 'running checks'\n"
        (checks_dir / "no-deletions.sh").write_text(script_content)
        _commit_all(repo)

        client = _make_client(repo)
        resp = client.get("/api/agents/checks")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "no-deletions.sh"
        assert data[0]["path"] == ".hyperloop/checks/no-deletions.sh"
        assert "running checks" in data[0]["content"]


def _write_events_jsonl(repo: Path, tmp_path: Path, events: list[dict[str, object]]) -> None:
    """Write events JSONL and pointer file for a test repo."""
    import json

    events_dir = tmp_path / "cache"
    events_dir.mkdir(exist_ok=True)
    events_path = events_dir / "events.jsonl"
    with open(events_path, "w") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")

    pointer_dir = repo / ".hyperloop"
    pointer_dir.mkdir(parents=True, exist_ok=True)
    (pointer_dir / ".dashboard-events-path").write_text(str(events_path))


class TestAgentRoster:
    def test_roster_returns_metrics_for_roles_with_data(self, tmp_path: Path) -> None:
        """Agent roster computes success rate, avg duration, and failure patterns."""
        from datetime import UTC, datetime

        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        now = datetime.now(UTC).isoformat()
        events: list[dict[str, object]] = [
            {
                "ts": now,
                "event": "worker_reaped",
                "task_id": "task-001",
                "role": "implementer",
                "verdict": "pass",
                "duration_s": 60.0,
                "cycle": 1,
            },
            {
                "ts": now,
                "event": "worker_reaped",
                "task_id": "task-002",
                "role": "implementer",
                "verdict": "pass",
                "duration_s": 90.0,
                "cycle": 1,
            },
            {
                "ts": now,
                "event": "worker_reaped",
                "task_id": "task-003",
                "role": "implementer",
                "verdict": "fail",
                "duration_s": 30.0,
                "detail": "Tests fail: missing null check",
                "cycle": 2,
            },
            {
                "ts": now,
                "event": "worker_reaped",
                "task_id": "task-004",
                "role": "verifier",
                "verdict": "pass",
                "duration_s": 20.0,
                "cycle": 2,
            },
        ]
        _write_events_jsonl(repo, tmp_path, events)
        _commit_all(repo)

        client = _make_client(repo)
        resp = client.get("/api/agents/roster")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

        impl = next(r for r in data if r["role"] == "implementer")
        assert impl["total_executions"] == 3
        # 2 pass out of 3 total = 0.667
        assert impl["success_rate"] == pytest.approx(0.667, abs=0.001)
        # avg of 60, 90, 30 = 60.0
        assert impl["avg_duration_s"] == 60.0
        assert len(impl["failure_patterns"]) == 1
        assert "null check" in impl["failure_patterns"][0]

        verifier = next(r for r in data if r["role"] == "verifier")
        assert verifier["total_executions"] == 1
        assert verifier["success_rate"] == 1.0
        assert verifier["avg_duration_s"] == 20.0
        assert verifier["failure_patterns"] == []

    def test_roster_returns_empty_when_no_events(self, tmp_path: Path) -> None:
        """Agent roster returns empty list when no events file exists."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        client = _make_client(repo)
        resp = client.get("/api/agents/roster")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_roster_returns_none_metrics_for_roles_with_no_worker_events(
        self,
        tmp_path: Path,
    ) -> None:
        """Roster returns empty when events exist but no worker_reaped events."""
        from datetime import UTC, datetime

        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        now = datetime.now(UTC).isoformat()
        events: list[dict[str, object]] = [
            {"ts": now, "event": "cycle_started", "cycle": 1},
            {"ts": now, "event": "cycle_completed", "cycle": 1, "duration_s": 1.0},
        ]
        _write_events_jsonl(repo, tmp_path, events)
        _commit_all(repo)

        client = _make_client(repo)
        resp = client.get("/api/agents/roster")
        assert resp.status_code == 200
        assert resp.json() == []


class TestTrendMetrics:
    def test_trend_returns_per_cycle_data(self, tmp_path: Path) -> None:
        """Trend metrics returns convergence and throughput per cycle."""
        from datetime import UTC, datetime

        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        now = datetime.now(UTC).isoformat()
        events: list[dict[str, object]] = [
            {"ts": now, "event": "cycle_started", "cycle": 1},
            {
                "ts": now,
                "event": "worker_reaped",
                "task_id": "task-001",
                "role": "implementer",
                "verdict": "pass",
                "duration_s": 45.0,
                "cycle": 1,
            },
            {
                "ts": now,
                "event": "task_completed",
                "task_id": "task-001",
                "cycle": 1,
            },
            {
                "ts": now,
                "event": "convergence_marked",
                "spec_ref": "specs/widget.md",
                "cycle": 1,
            },
            {"ts": now, "event": "cycle_completed", "cycle": 1, "duration_s": 5.0},
            {"ts": now, "event": "cycle_started", "cycle": 2},
            {
                "ts": now,
                "event": "worker_reaped",
                "task_id": "task-002",
                "role": "verifier",
                "verdict": "fail",
                "duration_s": 30.0,
                "cycle": 2,
            },
            {
                "ts": now,
                "event": "task_failed",
                "task_id": "task-002",
                "cycle": 2,
            },
            {"ts": now, "event": "cycle_completed", "cycle": 2, "duration_s": 3.0},
        ]
        _write_events_jsonl(repo, tmp_path, events)
        _commit_all(repo)

        client = _make_client(repo)
        resp = client.get("/api/metrics/trend", params={"cycles": 10})
        assert resp.status_code == 200
        data = resp.json()

        assert data["cycles_analyzed"] == 2
        assert data["total_tasks_completed"] == 1
        assert data["total_tasks_failed"] == 1
        # avg duration: (45 + 30) / 2 = 37.5
        assert data["avg_worker_duration_s"] == 37.5

        # Convergence trend
        conv = data["convergence_trend"]
        assert len(conv) == 2
        assert conv[0]["cycle"] == 1
        assert conv[0]["converged_count"] == 1
        # Convergence accumulates across cycles
        assert conv[1]["cycle"] == 2
        assert conv[1]["converged_count"] == 1

        # Throughput
        tp = data["task_throughput"]
        assert len(tp) == 2
        assert tp[0]["completed"] == 1
        assert tp[0]["failed"] == 0
        assert tp[1]["completed"] == 0
        assert tp[1]["failed"] == 1

    def test_trend_empty_when_no_events(self, tmp_path: Path) -> None:
        """Trend metrics returns zeroed response when no events exist."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        client = _make_client(repo)
        resp = client.get("/api/metrics/trend")
        assert resp.status_code == 200
        data = resp.json()
        assert data["cycles_analyzed"] == 0
        assert data["convergence_trend"] == []
        assert data["task_throughput"] == []
        assert data["avg_worker_duration_s"] is None
        assert data["total_tasks_completed"] == 0
        assert data["total_tasks_failed"] == 0

    def test_trend_respects_cycles_param(self, tmp_path: Path) -> None:
        """Trend metrics only returns data for the last N cycles."""
        from datetime import UTC, datetime

        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        now = datetime.now(UTC).isoformat()
        events: list[dict[str, object]] = []
        for c in range(1, 6):
            events.append({"ts": now, "event": "cycle_started", "cycle": c})
            events.append(
                {
                    "ts": now,
                    "event": "cycle_completed",
                    "cycle": c,
                    "duration_s": 1.0,
                }
            )
        _write_events_jsonl(repo, tmp_path, events)
        _commit_all(repo)

        client = _make_client(repo)
        resp = client.get("/api/metrics/trend", params={"cycles": 2})
        assert resp.status_code == 200
        data = resp.json()
        assert data["cycles_analyzed"] == 2
        # Should only contain cycles 4 and 5
        cycle_nums = [p["cycle"] for p in data["convergence_trend"]]
        assert cycle_nums == [4, 5]


class TestWorkerHeartbeatsStructured:
    def test_heartbeats_return_structured_per_worker_data(
        self,
        tmp_path: Path,
    ) -> None:
        """Worker heartbeats returns per-worker structured detail."""
        import json
        from datetime import UTC, datetime

        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        now = datetime.now(UTC)
        events_dir = tmp_path / "cache"
        events_dir.mkdir()
        events_path = events_dir / "events.jsonl"

        events = [
            {
                "ts": now.isoformat(),
                "event": "worker_message",
                "task_id": "task-001",
                "role": "implementer",
                "message_type": "text",
                "content": "thinking...",
            },
            {
                "ts": now.isoformat(),
                "event": "worker_message",
                "task_id": "task-001",
                "role": "implementer",
                "message_type": "tool_use",
                "content": "bash ls -la",
            },
            {
                "ts": now.isoformat(),
                "event": "worker_message",
                "task_id": "task-002",
                "role": "verifier",
                "message_type": "text",
                "content": "checking tests",
            },
        ]
        with open(events_path, "w") as f:
            for ev in events:
                f.write(json.dumps(ev) + "\n")

        pointer_dir = repo / ".hyperloop"
        pointer_dir.mkdir(parents=True, exist_ok=True)
        (pointer_dir / ".dashboard-events-path").write_text(str(events_path))
        _commit_all(repo)

        client = _make_client(repo)
        resp = client.get("/api/activity/worker-heartbeats")
        assert resp.status_code == 200
        data = resp.json()

        assert "heartbeats" in data
        assert "server_time" in data
        heartbeats = data["heartbeats"]
        assert len(heartbeats) == 2

        hb_by_task = {h["task_id"]: h for h in heartbeats}

        # task-001 had two messages, last was tool_use
        hb1 = hb_by_task["task-001"]
        assert hb1["role"] == "implementer"
        assert hb1["last_message_type"] == "tool_use"
        assert hb1["last_tool_name"] == "bash"
        assert hb1["message_count_since"] == 2
        assert hb1["seconds_since_last"] >= 0

        # task-002 had one text message
        hb2 = hb_by_task["task-002"]
        assert hb2["role"] == "verifier"
        assert hb2["last_message_type"] == "text"
        assert hb2["last_tool_name"] is None
        assert hb2["message_count_since"] == 1
