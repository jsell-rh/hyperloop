from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

from hyperloop.reconciliation.adapters.git_plan_store import GitPlanStore
from hyperloop.reconciliation.models import (
    EventType,
    Plan,
    SpecPlanStatus,
    Task,
    TaskStatus,
)

PLAN_BRANCH = "hyperloop/plan"
PLAN_FILE = "plan.json"


def _make_store(repo_path: Path) -> GitPlanStore:
    return GitPlanStore(
        repo_path,
        plan_branch=PLAN_BRANCH,
        plan_file=PLAN_FILE,
    )


def _git(
    repo: Path, *args: str, input: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        input=input,
        check=True,
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _build_populated_plan() -> Plan:
    plan = Plan()
    plan.add_spec("auth.spec.md", "abc123")
    plan.add_spec("users.spec.md", "xyz789")
    sp = plan.spec_plans[0]

    id1 = plan.next_task_id()
    id2 = plan.next_task_id()
    plan.add_tasks(
        sp,
        [
            Task(
                id=id1,
                spec_path=sp.path,
                spec_blob_sha=sp.blob_sha,
                name="Implement login",
                description="Build the login endpoint",
            ),
            Task(
                id=id2,
                spec_path=sp.path,
                spec_blob_sha=sp.blob_sha,
                name="Add auth middleware",
                description="Create JWT middleware",
                depends_on=[id1],
            ),
        ],
    )
    sp.tasks[0].status = TaskStatus.COMPLETE

    now = _utc_now()
    plan.record_event(
        reason="ReconcilerStarted",
        message="Started",
        event_type=EventType.NORMAL,
        timestamp=now,
    )
    sp.record_event(
        reason="TaskCompleted",
        message="Login done",
        event_type=EventType.NORMAL,
        timestamp=now,
    )

    return plan


class TestFirstRun:
    def test_returns_empty_plan(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        store = _make_store(local)
        plan = store.get_plan()

        assert plan.spec_plans == []
        assert plan.events == []
        assert plan.task_id_counter == 0

    def test_creates_orphan_branch(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        store = _make_store(local)
        store.get_plan()

        result = _git(local, "rev-parse", "--verify", f"refs/heads/{PLAN_BRANCH}")
        assert result.returncode == 0

    def test_orphan_branch_has_no_shared_history_with_trunk(
        self, git_env: tuple[Path, Path]
    ) -> None:
        local, _ = git_env
        store = _make_store(local)
        store.get_plan()

        result = subprocess.run(
            ["git", "merge-base", "main", PLAN_BRANCH],
            cwd=local,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0

    def test_orphan_branch_contains_only_plan_json(
        self, git_env: tuple[Path, Path]
    ) -> None:
        local, _ = git_env
        store = _make_store(local)
        store.get_plan()

        result = _git(local, "ls-tree", "--name-only", PLAN_BRANCH)
        files = result.stdout.strip().split("\n")
        assert files == [PLAN_FILE]

    def test_second_get_plan_returns_same_empty_plan(
        self, git_env: tuple[Path, Path]
    ) -> None:
        local, _ = git_env
        store = _make_store(local)
        store.get_plan()

        plan2 = store.get_plan()
        assert plan2.spec_plans == []
        assert plan2.events == []


class TestReadOperations:
    def test_reads_previously_written_plan(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        store = _make_store(local)
        plan = _build_populated_plan()
        store.write_plan(plan)

        restored = store.get_plan()
        assert len(restored.spec_plans) == 2
        assert restored.spec_plans[0].path == "auth.spec.md"
        assert restored.spec_plans[0].blob_sha == "abc123"

    def test_preserves_task_ids_and_status(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        store = _make_store(local)
        plan = _build_populated_plan()
        store.write_plan(plan)

        restored = store.get_plan()
        sp = restored.spec_plans[0]
        assert len(sp.tasks) == 2
        assert sp.tasks[0].id == 1
        assert sp.tasks[0].status == TaskStatus.COMPLETE
        assert sp.tasks[1].depends_on == [1]

    def test_preserves_events(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        store = _make_store(local)
        plan = _build_populated_plan()
        store.write_plan(plan)

        restored = store.get_plan()
        assert len(restored.events) == 1
        assert restored.events[0].reason == "ReconcilerStarted"

    def test_preserves_task_id_counter(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        store = _make_store(local)
        plan = _build_populated_plan()
        store.write_plan(plan)

        restored = store.get_plan()
        assert restored.task_id_counter == plan.task_id_counter

    def test_preserves_spec_plan_status(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        store = _make_store(local)
        plan = _build_populated_plan()
        store.write_plan(plan)

        restored = store.get_plan()
        assert restored.spec_plans[0].status == SpecPlanStatus.RECONCILING


class TestWriteOperations:
    def test_write_creates_commit_on_plan_branch(
        self, git_env: tuple[Path, Path]
    ) -> None:
        local, _ = git_env
        store = _make_store(local)
        store.get_plan()

        plan = Plan()
        plan.add_spec("auth.spec.md", "abc123")
        store.write_plan(plan)

        result = _git(local, "log", "--oneline", PLAN_BRANCH)
        lines = result.stdout.strip().split("\n")
        assert len(lines) == 2

    def test_multiple_writes_create_linear_history(
        self, git_env: tuple[Path, Path]
    ) -> None:
        local, _ = git_env
        store = _make_store(local)

        plan = Plan()
        plan.add_spec("auth.spec.md", "abc123")
        store.write_plan(plan)

        plan.add_spec("users.spec.md", "xyz789")
        store.write_plan(plan)

        plan.add_spec("orders.spec.md", "ghi012")
        store.write_plan(plan)

        result = _git(local, "log", "--oneline", PLAN_BRANCH)
        lines = result.stdout.strip().split("\n")
        assert len(lines) == 3

        result = _git(local, "log", "--format=%H", PLAN_BRANCH)
        shas = result.stdout.strip().split("\n")
        for i in range(len(shas) - 1):
            parent = _git(local, "rev-parse", f"{shas[i]}^").stdout.strip()
            assert parent == shas[i + 1]

    def test_write_pushes_to_remote(
        self, git_env: tuple[Path, Path], tmp_path: Path
    ) -> None:
        local, remote = git_env
        store = _make_store(local)
        plan = _build_populated_plan()
        store.write_plan(plan)

        other = tmp_path / "other"
        subprocess.run(
            ["git", "clone", str(remote), str(other)],
            check=True,
            capture_output=True,
        )
        _git(other, "config", "user.name", "Test User")
        _git(other, "config", "user.email", "test@example.com")

        other_store = _make_store(other)
        restored = other_store.get_plan()
        assert len(restored.spec_plans) == 2
        assert restored.spec_plans[0].path == "auth.spec.md"


class TestAtomicWrite:
    def test_all_changes_in_single_commit(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        store = _make_store(local)
        store.get_plan()

        plan = Plan()
        plan.add_spec("auth.spec.md", "abc123")
        plan.add_spec("users.spec.md", "xyz789")
        id1 = plan.next_task_id()
        plan.add_tasks(
            plan.spec_plans[0],
            [
                Task(
                    id=id1,
                    spec_path="auth.spec.md",
                    spec_blob_sha="abc123",
                    name="T1",
                    description="D1",
                )
            ],
        )
        now = _utc_now()
        plan.record_event(
            reason="Started",
            message="Go",
            event_type=EventType.NORMAL,
            timestamp=now,
        )
        store.write_plan(plan)

        result = _git(local, "log", "--oneline", PLAN_BRANCH)
        lines = result.stdout.strip().split("\n")
        assert len(lines) == 2

    def test_plan_branch_only_contains_plan_json(
        self, git_env: tuple[Path, Path]
    ) -> None:
        local, _ = git_env
        store = _make_store(local)
        plan = _build_populated_plan()
        store.write_plan(plan)

        result = _git(local, "ls-tree", "--name-only", PLAN_BRANCH)
        files = result.stdout.strip().split("\n")
        assert files == [PLAN_FILE]


class TestConcurrentAccess:
    def test_plan_survives_new_store_instance(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        store1 = _make_store(local)
        plan = _build_populated_plan()
        store1.write_plan(plan)

        store2 = _make_store(local)
        restored = store2.get_plan()
        assert len(restored.spec_plans) == 2

    def test_fetches_remote_changes(
        self, git_env: tuple[Path, Path], tmp_path: Path
    ) -> None:
        local, remote = git_env
        store = _make_store(local)
        plan = Plan()
        plan.add_spec("auth.spec.md", "abc123")
        store.write_plan(plan)

        other = tmp_path / "other"
        subprocess.run(
            ["git", "clone", str(remote), str(other)],
            check=True,
            capture_output=True,
        )
        _git(other, "config", "user.name", "Test User")
        _git(other, "config", "user.email", "test@example.com")

        other_store = _make_store(other)
        plan2 = other_store.get_plan()
        plan2.add_spec("users.spec.md", "xyz789")
        other_store.write_plan(plan2)

        refreshed = store.get_plan()
        assert len(refreshed.spec_plans) == 2

    def test_recovers_from_diverged_branch(
        self, git_env: tuple[Path, Path], tmp_path: Path
    ) -> None:
        local, remote = git_env
        store = _make_store(local)
        plan = Plan()
        plan.add_spec("auth.spec.md", "abc123")
        store.write_plan(plan)

        other = tmp_path / "other"
        subprocess.run(
            ["git", "clone", str(remote), str(other)],
            check=True,
            capture_output=True,
        )
        _git(other, "config", "user.name", "Test User")
        _git(other, "config", "user.email", "test@example.com")

        other_store = _make_store(other)
        plan2 = other_store.get_plan()
        plan2.add_spec("users.spec.md", "xyz789")
        other_store.write_plan(plan2)

        diverged_json = Plan().model_dump_json(indent=2) + "\n"
        blob = _git(
            local, "hash-object", "-w", "--stdin", input=diverged_json
        ).stdout.strip()
        tree = _git(
            local, "mktree", input=f"100644 blob {blob}\t{PLAN_FILE}"
        ).stdout.strip()
        parent = _git(local, "rev-parse", PLAN_BRANCH).stdout.strip()
        diverged_commit = _git(
            local, "commit-tree", tree, "-p", parent, "-m", "Diverged local"
        ).stdout.strip()
        _git(
            local,
            "update-ref",
            f"refs/heads/{PLAN_BRANCH}",
            diverged_commit,
        )

        refreshed = store.get_plan()
        assert len(refreshed.spec_plans) == 2
        paths = {sp.path for sp in refreshed.spec_plans}
        assert paths == {"auth.spec.md", "users.spec.md"}


class TestProtocolConformance:
    def test_has_get_plan_method(self) -> None:
        from typing import get_type_hints

        hints = get_type_hints(GitPlanStore.get_plan)
        assert hints["return"] is Plan

    def test_has_write_plan_method(self) -> None:
        from typing import get_type_hints

        hints = get_type_hints(GitPlanStore.write_plan)
        assert hints["plan"] is Plan
        assert hints["return"] is type(None)

    def test_adapter_imports_from_port_and_domain(self) -> None:
        import inspect

        import hyperloop.reconciliation.adapters.git_plan_store as module

        source = inspect.getsource(module)
        assert "hyperloop.reconciliation.models" in source
