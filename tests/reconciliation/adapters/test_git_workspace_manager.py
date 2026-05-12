from __future__ import annotations

import os
import subprocess
from pathlib import Path


from hyperloop.reconciliation.adapters.git_workspace_manager import (
    GitWorkspaceManager,
)
from hyperloop.reconciliation.models.merge_result import MergeOutcome, MergeResult


def _git(
    repo: Path, *args: str, input: str | None = None, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        input=input,
        check=check,
    )


def _branch_exists_local(repo: Path, branch: str) -> bool:
    result = _git(repo, "rev-parse", "--verify", f"refs/heads/{branch}", check=False)
    return result.returncode == 0


def _branch_exists_remote(remote: Path, branch: str) -> bool:
    result = _git(remote, "rev-parse", "--verify", f"refs/heads/{branch}", check=False)
    return result.returncode == 0


def _create_work_commit(repo: Path, branch: str, filename: str, content: str) -> None:
    _git(repo, "checkout", branch)
    (repo / filename).write_text(content)
    _git(repo, "add", filename)
    _git(repo, "commit", "-m", f"Add {filename}")
    _git(repo, "checkout", "main")


def _push_branch(repo: Path, branch: str) -> None:
    _git(repo, "push", "origin", branch)


BRANCH_PREFIX = "hyperloop/"
TRUNK = "main"
BLOB_SHA = "abc123"


def _make_manager(repo_path: Path) -> GitWorkspaceManager:
    return GitWorkspaceManager(
        repo_path,
        branch_prefix=BRANCH_PREFIX,
        trunk_branch=TRUNK,
        remote="origin",
    )


def _delivery(blob_sha: str) -> str:
    return f"{BRANCH_PREFIX}spec/{blob_sha}/delivery"


def _task(blob_sha: str, task_id: int) -> str:
    return f"{BRANCH_PREFIX}spec/{blob_sha}/task/{task_id}"


def _verifier(blob_sha: str) -> str:
    return f"{BRANCH_PREFIX}spec/{blob_sha}/verifier"


class TestCreateDeliveryWorkspace:
    def test_creates_branch_from_trunk_head(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        trunk_head = _git(local, "rev-parse", "main").stdout.strip()

        manager = _make_manager(local)
        manager.create_delivery_workspace(BLOB_SHA)

        delivery_head = _git(local, "rev-parse", _delivery(BLOB_SHA)).stdout.strip()
        assert delivery_head == trunk_head

    def test_returns_workspace_id(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        manager = _make_manager(local)

        workspace_id = manager.create_delivery_workspace(BLOB_SHA)

        assert workspace_id == f"delivery/{BLOB_SHA}"

    def test_idempotent(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        manager = _make_manager(local)

        first = manager.create_delivery_workspace(BLOB_SHA)
        second = manager.create_delivery_workspace(BLOB_SHA)

        assert first == second

    def test_pushes_branch_to_remote(self, git_env: tuple[Path, Path]) -> None:
        local, remote = git_env
        manager = _make_manager(local)

        manager.create_delivery_workspace(BLOB_SHA)

        assert _branch_exists_remote(remote, _delivery(BLOB_SHA))

    def test_separate_workspaces_per_blob_sha(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        manager = _make_manager(local)

        ws1 = manager.create_delivery_workspace("abc123")
        ws2 = manager.create_delivery_workspace("def456")

        assert ws1 != ws2
        assert _branch_exists_local(local, _delivery("abc123"))
        assert _branch_exists_local(local, _delivery("def456"))


class TestCreateTaskWorkspace:
    def test_creates_branch_from_delivery(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        manager = _make_manager(local)
        manager.create_delivery_workspace(BLOB_SHA)

        delivery_head = _git(local, "rev-parse", _delivery(BLOB_SHA)).stdout.strip()

        manager.create_task_workspace(BLOB_SHA, 5, "implement login")

        parent_of_briefing = _git(
            local, "rev-parse", f"{_task(BLOB_SHA, 5)}~1"
        ).stdout.strip()
        assert parent_of_briefing == delivery_head

    def test_returns_workspace_id(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        manager = _make_manager(local)
        manager.create_delivery_workspace(BLOB_SHA)

        workspace_id = manager.create_task_workspace(BLOB_SHA, 5, "implement login")

        assert workspace_id == f"task/{BLOB_SHA}/5"

    def test_creates_empty_commit_with_briefing(
        self, git_env: tuple[Path, Path]
    ) -> None:
        local, _ = git_env
        manager = _make_manager(local)
        manager.create_delivery_workspace(BLOB_SHA)

        briefing = "Task 5: implement login\nSpec: auth.spec.md"
        manager.create_task_workspace(BLOB_SHA, 5, briefing)

        message = _git(
            local, "log", "-1", "--format=%B", _task(BLOB_SHA, 5)
        ).stdout.strip()
        assert "implement login" in message
        assert "auth.spec.md" in message

    def test_briefing_commit_has_no_file_changes(
        self, git_env: tuple[Path, Path]
    ) -> None:
        local, _ = git_env
        manager = _make_manager(local)
        manager.create_delivery_workspace(BLOB_SHA)
        manager.create_task_workspace(BLOB_SHA, 5, "implement login")

        result = _git(
            local,
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            _task(BLOB_SHA, 5),
        )
        assert result.stdout.strip() == ""

    def test_pushes_branch_to_remote(self, git_env: tuple[Path, Path]) -> None:
        local, remote = git_env
        manager = _make_manager(local)
        manager.create_delivery_workspace(BLOB_SHA)

        manager.create_task_workspace(BLOB_SHA, 5, "implement login")

        assert _branch_exists_remote(remote, _task(BLOB_SHA, 5))

    def test_idempotent(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        manager = _make_manager(local)
        manager.create_delivery_workspace(BLOB_SHA)

        first = manager.create_task_workspace(BLOB_SHA, 5, "task 5")
        second = manager.create_task_workspace(BLOB_SHA, 5, "task 5")

        assert first == second

    def test_multiple_tasks_for_same_spec(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        manager = _make_manager(local)
        manager.create_delivery_workspace(BLOB_SHA)

        ws1 = manager.create_task_workspace(BLOB_SHA, 5, "task 5")
        ws2 = manager.create_task_workspace(BLOB_SHA, 6, "task 6")

        assert ws1 != ws2
        assert _branch_exists_local(local, _task(BLOB_SHA, 5))
        assert _branch_exists_local(local, _task(BLOB_SHA, 6))


class TestCreateVerificationWorkspace:
    def test_creates_branch_from_delivery(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        manager = _make_manager(local)
        manager.create_delivery_workspace(BLOB_SHA)

        delivery_head = _git(local, "rev-parse", _delivery(BLOB_SHA)).stdout.strip()

        manager.create_verification_workspace(BLOB_SHA)

        verifier_head = _git(local, "rev-parse", _verifier(BLOB_SHA)).stdout.strip()
        assert verifier_head == delivery_head

    def test_returns_workspace_id(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        manager = _make_manager(local)
        manager.create_delivery_workspace(BLOB_SHA)

        workspace_id = manager.create_verification_workspace(BLOB_SHA)

        assert workspace_id == f"verification/{BLOB_SHA}"

    def test_recreates_on_second_call(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        manager = _make_manager(local)
        manager.create_delivery_workspace(BLOB_SHA)

        manager.create_verification_workspace(BLOB_SHA)

        _create_work_commit(local, _verifier(BLOB_SHA), "check.txt", "checking")
        old_head = _git(local, "rev-parse", _verifier(BLOB_SHA)).stdout.strip()

        manager.create_verification_workspace(BLOB_SHA)

        new_head = _git(local, "rev-parse", _verifier(BLOB_SHA)).stdout.strip()
        assert new_head != old_head

        delivery_head = _git(local, "rev-parse", _delivery(BLOB_SHA)).stdout.strip()
        assert new_head == delivery_head

    def test_pushes_branch_to_remote(self, git_env: tuple[Path, Path]) -> None:
        local, remote = git_env
        manager = _make_manager(local)
        manager.create_delivery_workspace(BLOB_SHA)

        manager.create_verification_workspace(BLOB_SHA)

        assert _branch_exists_remote(remote, _verifier(BLOB_SHA))


class TestMergeTask:
    def test_clean_merge_returns_success(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        manager = _make_manager(local)
        manager.create_delivery_workspace(BLOB_SHA)
        manager.create_task_workspace(BLOB_SHA, 5, "task 5")

        task_branch = _task(BLOB_SHA, 5)
        _create_work_commit(local, task_branch, "login.py", "def login(): pass")
        _push_branch(local, task_branch)

        result = manager.merge_task(BLOB_SHA, 5)

        assert result.outcome == MergeOutcome.SUCCESS
        assert result.conflict_details is None

    def test_merge_incorporates_task_work(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        manager = _make_manager(local)
        manager.create_delivery_workspace(BLOB_SHA)
        manager.create_task_workspace(BLOB_SHA, 5, "task 5")

        task_branch = _task(BLOB_SHA, 5)
        _create_work_commit(local, task_branch, "login.py", "def login(): pass")
        _push_branch(local, task_branch)

        manager.merge_task(BLOB_SHA, 5)

        result = _git(local, "show", f"{_delivery(BLOB_SHA)}:login.py")
        assert "def login(): pass" in result.stdout

    def test_deletes_local_task_branch_on_success(
        self, git_env: tuple[Path, Path]
    ) -> None:
        local, _ = git_env
        manager = _make_manager(local)
        manager.create_delivery_workspace(BLOB_SHA)
        manager.create_task_workspace(BLOB_SHA, 5, "task 5")

        task_branch = _task(BLOB_SHA, 5)
        _create_work_commit(local, task_branch, "login.py", "def login(): pass")
        _push_branch(local, task_branch)

        manager.merge_task(BLOB_SHA, 5)

        assert not _branch_exists_local(local, task_branch)

    def test_deletes_remote_task_branch_on_success(
        self, git_env: tuple[Path, Path]
    ) -> None:
        local, remote = git_env
        manager = _make_manager(local)
        manager.create_delivery_workspace(BLOB_SHA)
        manager.create_task_workspace(BLOB_SHA, 5, "task 5")

        task_branch = _task(BLOB_SHA, 5)
        _create_work_commit(local, task_branch, "login.py", "def login(): pass")
        _push_branch(local, task_branch)

        manager.merge_task(BLOB_SHA, 5)

        assert not _branch_exists_remote(remote, task_branch)

    def test_pushes_merged_delivery_branch(self, git_env: tuple[Path, Path]) -> None:
        local, remote = git_env
        manager = _make_manager(local)
        manager.create_delivery_workspace(BLOB_SHA)
        manager.create_task_workspace(BLOB_SHA, 5, "task 5")

        task_branch = _task(BLOB_SHA, 5)
        _create_work_commit(local, task_branch, "login.py", "def login(): pass")
        _push_branch(local, task_branch)

        manager.merge_task(BLOB_SHA, 5)

        delivery_branch = _delivery(BLOB_SHA)
        local_head = _git(local, "rev-parse", delivery_branch).stdout.strip()
        remote_head = _git(
            remote, "rev-parse", f"refs/heads/{delivery_branch}"
        ).stdout.strip()
        assert local_head == remote_head

    def test_conflict_returns_conflict_result(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        manager = _make_manager(local)
        manager.create_delivery_workspace(BLOB_SHA)
        manager.create_task_workspace(BLOB_SHA, 5, "task 5")

        delivery_branch = _delivery(BLOB_SHA)
        task_branch = _task(BLOB_SHA, 5)

        _create_work_commit(local, delivery_branch, "shared.py", "delivery version")
        _push_branch(local, delivery_branch)
        _create_work_commit(local, task_branch, "shared.py", "task version")
        _push_branch(local, task_branch)

        result = manager.merge_task(BLOB_SHA, 5)

        assert result.outcome == MergeOutcome.CONFLICT
        assert result.conflict_details is not None

    def test_conflict_preserves_task_branch(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        manager = _make_manager(local)
        manager.create_delivery_workspace(BLOB_SHA)
        manager.create_task_workspace(BLOB_SHA, 5, "task 5")

        delivery_branch = _delivery(BLOB_SHA)
        task_branch = _task(BLOB_SHA, 5)

        _create_work_commit(local, delivery_branch, "shared.py", "delivery version")
        _push_branch(local, delivery_branch)
        _create_work_commit(local, task_branch, "shared.py", "task version")
        _push_branch(local, task_branch)

        manager.merge_task(BLOB_SHA, 5)

        assert _branch_exists_local(local, task_branch)


class TestIntegrate:
    def test_pushes_delivery_branch_to_remote(
        self, git_env: tuple[Path, Path], tmp_path: Path
    ) -> None:
        local, remote = git_env
        manager = _make_manager(local)
        manager.create_delivery_workspace(BLOB_SHA)

        delivery_branch = _delivery(BLOB_SHA)
        _create_work_commit(local, delivery_branch, "login.py", "def login(): pass")

        self._setup_fake_gh(tmp_path)
        integration_id = manager.integrate(
            BLOB_SHA, "specs/auth.spec.md", "Implement auth", "Auth module"
        )

        local_head = _git(local, "rev-parse", delivery_branch).stdout.strip()
        remote_head = _git(
            remote, "rev-parse", f"refs/heads/{delivery_branch}"
        ).stdout.strip()
        assert local_head == remote_head
        assert isinstance(integration_id, str)
        assert len(integration_id) > 0

    def test_pr_forwards_title_and_body(
        self, git_env: tuple[Path, Path], tmp_path: Path
    ) -> None:
        local, _ = git_env
        manager = _make_manager(local)
        manager.create_delivery_workspace(BLOB_SHA)

        args_file = self._setup_fake_gh(tmp_path)
        manager.integrate(
            BLOB_SHA, "specs/auth.spec.md", "Implement auth", "Auth module"
        )

        captured_args = args_file.read_text()
        assert "Implement auth" in captured_args
        assert "Auth module" in captured_args

    def test_pr_targets_trunk(self, git_env: tuple[Path, Path], tmp_path: Path) -> None:
        local, _ = git_env
        manager = _make_manager(local)
        manager.create_delivery_workspace(BLOB_SHA)

        args_file = self._setup_fake_gh(tmp_path)
        manager.integrate(
            BLOB_SHA, "specs/auth.spec.md", "Implement auth", "Auth module"
        )

        captured_args = args_file.read_text()
        assert TRUNK in captured_args

    def test_returns_pr_url(self, git_env: tuple[Path, Path], tmp_path: Path) -> None:
        local, _ = git_env
        manager = _make_manager(local)
        manager.create_delivery_workspace(BLOB_SHA)

        self._setup_fake_gh(tmp_path)
        url = manager.integrate(
            BLOB_SHA, "specs/auth.spec.md", "Implement auth", "Auth module"
        )

        assert url == "https://github.com/test/repo/pull/1"

    @staticmethod
    def _setup_fake_gh(tmp_path: Path) -> Path:
        bin_dir = tmp_path / "fakebin"
        bin_dir.mkdir(exist_ok=True)
        args_file = tmp_path / "gh_args.txt"
        script = bin_dir / "gh"
        script.write_text(
            "#!/bin/bash\n"
            f'echo "$@" > {args_file}\n'
            'echo "https://github.com/test/repo/pull/1"\n'
        )
        script.chmod(0o755)
        os.environ["PATH"] = f"{bin_dir}:{os.environ.get('PATH', '')}"
        return args_file


class TestCleanup:
    def test_deletes_delivery_branch(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        manager = _make_manager(local)
        manager.create_delivery_workspace(BLOB_SHA)

        manager.cleanup(BLOB_SHA)

        assert not _branch_exists_local(local, _delivery(BLOB_SHA))

    def test_deletes_task_branches(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        manager = _make_manager(local)
        manager.create_delivery_workspace(BLOB_SHA)
        manager.create_task_workspace(BLOB_SHA, 5, "task 5")
        manager.create_task_workspace(BLOB_SHA, 6, "task 6")

        manager.cleanup(BLOB_SHA)

        assert not _branch_exists_local(local, _task(BLOB_SHA, 5))
        assert not _branch_exists_local(local, _task(BLOB_SHA, 6))

    def test_deletes_verifier_branch(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        manager = _make_manager(local)
        manager.create_delivery_workspace(BLOB_SHA)
        manager.create_verification_workspace(BLOB_SHA)

        manager.cleanup(BLOB_SHA)

        assert not _branch_exists_local(local, _verifier(BLOB_SHA))

    def test_deletes_remote_refs(self, git_env: tuple[Path, Path]) -> None:
        local, remote = git_env
        manager = _make_manager(local)
        manager.create_delivery_workspace(BLOB_SHA)
        manager.create_task_workspace(BLOB_SHA, 5, "task 5")
        manager.create_verification_workspace(BLOB_SHA)

        manager.cleanup(BLOB_SHA)

        assert not _branch_exists_remote(remote, _delivery(BLOB_SHA))
        assert not _branch_exists_remote(remote, _task(BLOB_SHA, 5))
        assert not _branch_exists_remote(remote, _verifier(BLOB_SHA))

    def test_does_not_affect_other_specs(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        manager = _make_manager(local)
        manager.create_delivery_workspace("abc123")
        manager.create_delivery_workspace("def456")
        manager.create_task_workspace("def456", 7, "task 7")

        manager.cleanup("abc123")

        assert _branch_exists_local(local, _delivery("def456"))
        assert _branch_exists_local(local, _task("def456", 7))

    def test_idempotent(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        manager = _make_manager(local)
        manager.create_delivery_workspace(BLOB_SHA)

        manager.cleanup(BLOB_SHA)
        manager.cleanup(BLOB_SHA)

        assert not _branch_exists_local(local, _delivery(BLOB_SHA))


class TestCleanupVerification:
    def test_deletes_verifier_branch(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        manager = _make_manager(local)
        manager.create_delivery_workspace(BLOB_SHA)
        manager.create_verification_workspace(BLOB_SHA)

        manager.cleanup_verification(BLOB_SHA)

        assert not _branch_exists_local(local, _verifier(BLOB_SHA))

    def test_deletes_remote_verifier_branch(self, git_env: tuple[Path, Path]) -> None:
        local, remote = git_env
        manager = _make_manager(local)
        manager.create_delivery_workspace(BLOB_SHA)
        manager.create_verification_workspace(BLOB_SHA)

        manager.cleanup_verification(BLOB_SHA)

        assert not _branch_exists_remote(remote, _verifier(BLOB_SHA))

    def test_preserves_delivery_branch(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        manager = _make_manager(local)
        manager.create_delivery_workspace(BLOB_SHA)
        manager.create_verification_workspace(BLOB_SHA)

        manager.cleanup_verification(BLOB_SHA)

        assert _branch_exists_local(local, _delivery(BLOB_SHA))

    def test_preserves_task_branches(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        manager = _make_manager(local)
        manager.create_delivery_workspace(BLOB_SHA)
        manager.create_task_workspace(BLOB_SHA, 5, "task 5")
        manager.create_verification_workspace(BLOB_SHA)

        manager.cleanup_verification(BLOB_SHA)

        assert _branch_exists_local(local, _task(BLOB_SHA, 5))

    def test_idempotent(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        manager = _make_manager(local)
        manager.create_delivery_workspace(BLOB_SHA)

        manager.cleanup_verification(BLOB_SHA)

        assert _branch_exists_local(local, _delivery(BLOB_SHA))


class TestCustomBranchPrefix:
    def test_create_delivery_uses_prefix(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        prefix = "myloop/"
        manager = GitWorkspaceManager(
            local, branch_prefix=prefix, trunk_branch=TRUNK, remote="origin"
        )

        manager.create_delivery_workspace(BLOB_SHA)

        assert _branch_exists_local(local, f"{prefix}spec/{BLOB_SHA}/delivery")

    def test_create_task_uses_prefix(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        prefix = "myloop/"
        manager = GitWorkspaceManager(
            local, branch_prefix=prefix, trunk_branch=TRUNK, remote="origin"
        )

        manager.create_delivery_workspace(BLOB_SHA)
        manager.create_task_workspace(BLOB_SHA, 5, "task 5")

        assert _branch_exists_local(local, f"{prefix}spec/{BLOB_SHA}/task/5")

    def test_cleanup_uses_prefix(self, git_env: tuple[Path, Path]) -> None:
        local, _ = git_env
        prefix = "myloop/"
        manager = GitWorkspaceManager(
            local, branch_prefix=prefix, trunk_branch=TRUNK, remote="origin"
        )

        manager.create_delivery_workspace(BLOB_SHA)
        manager.create_task_workspace(BLOB_SHA, 5, "task 5")
        manager.cleanup(BLOB_SHA)

        assert not _branch_exists_local(local, f"{prefix}spec/{BLOB_SHA}/delivery")
        assert not _branch_exists_local(local, f"{prefix}spec/{BLOB_SHA}/task/5")


class TestProtocolConformance:
    def test_has_create_delivery_workspace(self) -> None:
        from typing import get_type_hints

        hints = get_type_hints(GitWorkspaceManager.create_delivery_workspace)
        assert hints["blob_sha"] is str
        assert hints["return"] is str

    def test_has_create_task_workspace(self) -> None:
        from typing import get_type_hints

        hints = get_type_hints(GitWorkspaceManager.create_task_workspace)
        assert hints["blob_sha"] is str
        assert hints["task_id"] is int
        assert hints["briefing"] is str
        assert hints["return"] is str

    def test_has_create_verification_workspace(self) -> None:
        from typing import get_type_hints

        hints = get_type_hints(GitWorkspaceManager.create_verification_workspace)
        assert hints["blob_sha"] is str
        assert hints["return"] is str

    def test_has_merge_task(self) -> None:
        from typing import get_type_hints

        hints = get_type_hints(GitWorkspaceManager.merge_task)
        assert hints["blob_sha"] is str
        assert hints["task_id"] is int
        assert hints["return"] is MergeResult

    def test_has_integrate(self) -> None:
        from typing import get_type_hints

        hints = get_type_hints(GitWorkspaceManager.integrate)
        assert hints["blob_sha"] is str
        assert hints["spec_path"] is str
        assert hints["title"] is str
        assert hints["body"] is str
        assert hints["return"] is str

    def test_has_cleanup(self) -> None:
        from typing import get_type_hints

        hints = get_type_hints(GitWorkspaceManager.cleanup)
        assert hints["blob_sha"] is str
        assert hints["return"] is type(None)

    def test_has_cleanup_verification(self) -> None:
        from typing import get_type_hints

        hints = get_type_hints(GitWorkspaceManager.cleanup_verification)
        assert hints["blob_sha"] is str
        assert hints["return"] is type(None)

    def test_adapter_imports_from_domain(self) -> None:
        import inspect

        import hyperloop.reconciliation.adapters.git_workspace_manager as module

        source = inspect.getsource(module)
        assert "hyperloop.reconciliation.models" in source
