"""Tests for AmbientRuntime — uses a fake acpctl script, no mocks."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import textwrap
import time
from typing import TYPE_CHECKING

import pytest

from hyperloop.adapters.runtime.ambient import AmbientRuntime
from hyperloop.domain.model import Verdict

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Fake acpctl helpers
# ---------------------------------------------------------------------------


def _write_fake_acpctl(path: Path, behaviour: str) -> str:
    """Write a fake acpctl Python script and return its path.

    ``behaviour`` is injected verbatim into the script's dispatch logic.
    """
    header = textwrap.dedent("""\
        #!/usr/bin/env python3
        import json, os, sys

        args = sys.argv[1:]
        log_file = os.environ.get("FAKE_ACPCTL_LOG")
        if log_file:
            with open(log_file, "a") as f:
                f.write(json.dumps(args) + "\\n")

    """)
    script = header + behaviour + "\n# Default: print nothing, exit 0\n"
    path.write_text(script)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def _default_behaviour() -> str:
    """Standard dispatch logic for the fake acpctl."""
    return textwrap.dedent("""\
        cmd = args[0] if args else ""

        if cmd == "project" and len(args) > 1 and args[1] == "update":
            print("ok")
            sys.exit(0)

        if cmd == "create":
            resource = args[1] if len(args) > 1 else ""
            if resource == "session":
                print(json.dumps({"id": "ses-001", "name": "test-session"}))
                sys.exit(0)
            if resource == "project":
                print(json.dumps({"id": "proj-001", "name": "test-project"}))
                sys.exit(0)

        if cmd == "stop":
            print("stopped")
            sys.exit(0)

        if cmd == "get":
            resource = args[1] if len(args) > 1 else ""
            if resource in ("sessions", "session"):
                print(json.dumps({"items": [], "total": 0}))
                sys.exit(0)

        if cmd == "session" and len(args) > 1 and args[1] == "events":
            evt = {"type": "RUN_FINISHED", "result": {"total_cost_usd": 0.12, "num_turns": 5}}
            print(json.dumps(evt), flush=True)
            sys.exit(0)
    """)


def _slow_sse_behaviour() -> str:
    """SSE behaviour that delays briefly before emitting RUN_FINISHED."""
    return textwrap.dedent("""\
        cmd = args[0] if args else ""

        if cmd == "project" and len(args) > 1 and args[1] == "update":
            print("ok")
            sys.exit(0)

        if cmd == "create":
            resource = args[1] if len(args) > 1 else ""
            if resource == "session":
                print(json.dumps({"id": "ses-002", "name": "test-session"}))
                sys.exit(0)

        if cmd == "stop":
            print("stopped")
            sys.exit(0)

        if cmd == "session" and len(args) > 1 and args[1] == "events":
            import time as _t
            _t.sleep(0.3)
            evt = {"type": "RUN_FINISHED", "result": {}}
            print(json.dumps(evt), flush=True)
            sys.exit(0)
    """)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_acpctl(tmp_path: Path) -> str:
    """Return path to a fake acpctl with default behaviour."""
    return _write_fake_acpctl(tmp_path / "acpctl", _default_behaviour())


@pytest.fixture()
def slow_acpctl(tmp_path: Path) -> str:
    """Return path to a fake acpctl with delayed SSE."""
    return _write_fake_acpctl(tmp_path / "acpctl_slow", _slow_sse_behaviour())


@pytest.fixture()
def acpctl_log(tmp_path: Path) -> Path:
    """Return path to a log file where fake acpctl records commands."""
    return tmp_path / "acpctl.log"


@pytest.fixture()
def git_repo(tmp_path: Path) -> str:
    """Create a bare-minimum git repo for git operations."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--allow-empty", "-m", "init"],
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "t@t",
        },
    )
    return str(repo)


def _read_log(log_path: Path) -> list[list[str]]:
    """Read the acpctl command log."""
    if not log_path.exists():
        return []
    lines = log_path.read_text().strip().splitlines()
    result: list[list[str]] = []
    for line in lines:
        parsed: list[str] = json.loads(line)
        result.append(parsed)
    return result


def _make_runtime(
    acpctl: str,
    repo_path: str,
    log_path: Path | None = None,
    repo_url: str = "",
) -> AmbientRuntime:
    """Create an AmbientRuntime with the fake acpctl."""
    if log_path is not None:
        os.environ["FAKE_ACPCTL_LOG"] = str(log_path)
    return AmbientRuntime(
        repo_path=repo_path,
        project_id="test-project",
        acpctl=acpctl,
        base_branch="main",
        repo_url=repo_url,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEnsureProject:
    """ensure_project creates the project if it doesn't exist."""

    def test_ensure_existing_project(
        self, fake_acpctl: str, git_repo: str, acpctl_log: Path
    ) -> None:
        rt = _make_runtime(fake_acpctl, git_repo, acpctl_log)
        rt.ensure_project()

        cmds = _read_log(acpctl_log)
        assert len(cmds) == 1
        assert cmds[0][0] == "project"
        assert cmds[0][1] == "update"


class TestSpawn:
    """spawn creates a session with prompt and repo_url."""

    def test_spawn_creates_session(self, fake_acpctl: str, git_repo: str, acpctl_log: Path) -> None:
        rt = _make_runtime(
            fake_acpctl, git_repo, acpctl_log, repo_url="https://github.com/test/repo"
        )

        handle = rt.spawn("task-001", "implementer", "Do the thing.", "feat/task-001")

        assert handle.task_id == "task-001"
        assert handle.role == "implementer"
        assert handle.session_id == "ses-001"

        cmds = _read_log(acpctl_log)
        # Should have one create session command
        create_cmds = [c for c in cmds if c[0] == "create" and c[1] == "session"]
        assert len(create_cmds) == 1

        cmd = create_cmds[0]
        assert "--prompt" in cmd
        assert "--repo-url" in cmd
        repo_idx = cmd.index("--repo-url")
        assert cmd[repo_idx + 1] == "https://github.com/test/repo"

    def test_spawn_without_repo_url(
        self, fake_acpctl: str, git_repo: str, acpctl_log: Path
    ) -> None:
        rt = _make_runtime(fake_acpctl, git_repo, acpctl_log)

        handle = rt.spawn("task-001", "implementer", "Do the thing.", "feat/task-001")
        assert handle.session_id == "ses-001"

        cmds = _read_log(acpctl_log)
        create_cmds = [c for c in cmds if c[0] == "create" and c[1] == "session"]
        cmd = create_cmds[0]
        assert "--repo-url" not in cmd


class TestPoll:
    """poll reads from SSE-populated completion dict."""

    def test_poll_returns_done_after_sse(self, fake_acpctl: str, git_repo: str) -> None:
        rt = _make_runtime(fake_acpctl, git_repo)
        handle = rt.spawn("task-001", "implementer", "Work.", "feat/task-001")

        # SSE fires immediately in default behaviour, give thread a moment
        time.sleep(0.5)
        assert rt.poll(handle) == "done"

    def test_poll_returns_running_then_done(self, slow_acpctl: str, git_repo: str) -> None:
        rt = _make_runtime(slow_acpctl, git_repo)
        handle = rt.spawn("task-001", "implementer", "Work.", "feat/task-001")

        # Immediately should be running (SSE delays 0.3s)
        assert rt.poll(handle) == "running"

        # After delay, should be done
        time.sleep(1.0)
        assert rt.poll(handle) == "done"


class TestReap:
    """reap fetches branch and reads review file."""

    def test_reap_fetches_branch_reads_review(self, tmp_path: Path, acpctl_log: Path) -> None:
        """Set up a git repo with a remote that has a review file."""
        remote = tmp_path / "remote"
        remote.mkdir()
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "t@t",
        }
        subprocess.run(["git", "init", "-b", "main", str(remote)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(remote), "commit", "--allow-empty", "-m", "init"],
            check=True,
            capture_output=True,
            env=env,
        )
        # Create branch with review file
        subprocess.run(
            ["git", "-C", str(remote), "checkout", "-b", "feat/task-001"],
            check=True,
            capture_output=True,
        )
        reviews_dir = remote / ".hyperloop" / "state" / "reviews"
        reviews_dir.mkdir(parents=True)
        (reviews_dir / "task-001-round-0.md").write_text(
            "---\ntask_id: task-001\nround: 0\nrole: verifier\n"
            "verdict: fail\nfindings: 2\n---\nTwo issues found.\n"
        )
        subprocess.run(["git", "-C", str(remote), "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(remote), "commit", "-m", "review"],
            check=True,
            capture_output=True,
            env=env,
        )
        subprocess.run(
            ["git", "-C", str(remote), "checkout", "main"],
            check=True,
            capture_output=True,
        )

        # Clone it
        local = tmp_path / "local"
        subprocess.run(["git", "clone", str(remote), str(local)], check=True, capture_output=True)

        # Fake acpctl for this test
        behaviour = textwrap.dedent("""\
            cmd = args[0] if args else ""

            if cmd == "create" and len(args) > 1 and args[1] == "session":
                print(json.dumps({"id": "ses-reap", "name": "test-session"}))
                sys.exit(0)

            if cmd == "stop":
                print("stopped")
                sys.exit(0)

            if cmd == "session" and len(args) > 1 and args[1] == "events":
                evt = {"type": "RUN_FINISHED", "result": {}}
                print(json.dumps(evt), flush=True)
                sys.exit(0)
        """)
        acpctl_path = _write_fake_acpctl(tmp_path / "acpctl_reap", behaviour)

        rt = _make_runtime(acpctl_path, str(local), acpctl_log)
        handle = rt.spawn("task-001", "implementer", "Work.", "feat/task-001")

        # Wait for SSE to finish
        time.sleep(0.5)
        assert rt.poll(handle) == "done"

        result = rt.reap(handle)
        assert result.verdict == Verdict.FAIL
        assert result.findings == 2
        assert "Two issues found" in result.detail

    def test_reap_falls_back_when_no_review(self, tmp_path: Path, acpctl_log: Path) -> None:
        """When no review file exists, reap returns PASS fallback."""
        remote = tmp_path / "remote"
        remote.mkdir()
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "t@t",
        }
        subprocess.run(["git", "init", "-b", "main", str(remote)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(remote), "commit", "--allow-empty", "-m", "init"],
            check=True,
            capture_output=True,
            env=env,
        )
        subprocess.run(
            ["git", "-C", str(remote), "checkout", "-b", "feat/task-002"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(remote), "commit", "--allow-empty", "-m", "work"],
            check=True,
            capture_output=True,
            env=env,
        )
        subprocess.run(
            ["git", "-C", str(remote), "checkout", "main"],
            check=True,
            capture_output=True,
        )
        local = tmp_path / "local"
        subprocess.run(["git", "clone", str(remote), str(local)], check=True, capture_output=True)

        behaviour = textwrap.dedent("""\
            cmd = args[0] if args else ""

            if cmd == "create" and len(args) > 1 and args[1] == "session":
                print(json.dumps({"id": "ses-noreview", "name": "test-session"}))
                sys.exit(0)

            if cmd == "stop":
                print("stopped")
                sys.exit(0)

            if cmd == "session" and len(args) > 1 and args[1] == "events":
                evt = {"type": "RUN_FINISHED", "result": {}}
                print(json.dumps(evt), flush=True)
                sys.exit(0)
        """)
        acpctl_path = _write_fake_acpctl(tmp_path / "acpctl_noreview", behaviour)

        rt = _make_runtime(acpctl_path, str(local), acpctl_log)
        handle = rt.spawn("task-002", "implementer", "Work.", "feat/task-002")

        time.sleep(0.5)
        result = rt.reap(handle)
        assert result.verdict == Verdict.PASS
        assert result.detail == "Agent completed"


class TestCancel:
    """cancel stops session and cleans up."""

    def test_cancel_stops_session(self, fake_acpctl: str, git_repo: str, acpctl_log: Path) -> None:
        rt = _make_runtime(fake_acpctl, git_repo, acpctl_log)
        handle = rt.spawn("task-001", "implementer", "Work.", "feat/task-001")
        acpctl_log.write_text("")  # Clear log

        rt.cancel(handle)

        cmds = _read_log(acpctl_log)
        stop_cmds = [c for c in cmds if c[0] == "stop"]
        assert len(stop_cmds) == 1


class TestFindOrphan:
    """find_orphan scans sessions by name prefix."""

    def test_find_orphan_matches_running_session(self, tmp_path: Path, acpctl_log: Path) -> None:
        behaviour = textwrap.dedent("""\
            cmd = args[0] if args else ""

            if cmd == "get" and len(args) > 1 and args[1] in ("sessions", "session"):
                sessions = {
                    "items": [
                        {
                            "id": "ses-orphan",
                            "name": "hyperloop-task-001-implementer",
                            "phase": "Running",
                        }
                    ],
                    "total": 1,
                }
                print(json.dumps(sessions))
                sys.exit(0)

            if cmd == "session" and len(args) > 1 and args[1] == "events":
                import time as _t
                _t.sleep(0.3)
                evt = {"type": "RUN_FINISHED", "result": {}}
                print(json.dumps(evt), flush=True)
                sys.exit(0)
        """)
        acpctl_path = _write_fake_acpctl(tmp_path / "acpctl_orphan", behaviour)
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "--allow-empty", "-m", "init"],
            check=True,
            capture_output=True,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "test",
                "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "test",
                "GIT_COMMITTER_EMAIL": "t@t",
            },
        )

        rt = _make_runtime(acpctl_path, str(repo), acpctl_log)
        handle = rt.find_orphan("task-001", "feat/task-001")

        assert handle is not None
        assert handle.task_id == "task-001"
        assert handle.session_id == "ses-orphan"

    def test_find_orphan_returns_none_when_no_match(self, fake_acpctl: str, git_repo: str) -> None:
        rt = _make_runtime(fake_acpctl, git_repo)
        handle = rt.find_orphan("task-999", "feat/task-999")
        assert handle is None


class TestWorkerEpilogue:
    """worker_epilogue returns push instruction."""

    def test_worker_epilogue(self, fake_acpctl: str, git_repo: str) -> None:
        rt = _make_runtime(fake_acpctl, git_repo)
        assert "Push" in rt.worker_epilogue()


class TestPushBranch:
    """push_branch calls git push."""

    def test_push_branch(self, tmp_path: Path) -> None:
        remote = tmp_path / "remote"
        remote.mkdir()
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "t@t",
        }
        subprocess.run(
            ["git", "init", "-b", "main", "--bare", str(remote)], check=True, capture_output=True
        )

        local = tmp_path / "local"
        subprocess.run(["git", "clone", str(remote), str(local)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(local), "commit", "--allow-empty", "-m", "init"],
            check=True,
            capture_output=True,
            env=env,
        )
        subprocess.run(
            ["git", "-C", str(local), "push", "-u", "origin", "main"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(local), "checkout", "-b", "test-branch"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(local), "commit", "--allow-empty", "-m", "work"],
            check=True,
            capture_output=True,
            env=env,
        )

        acpctl_path = _write_fake_acpctl(tmp_path / "acpctl", _default_behaviour())
        rt = _make_runtime(acpctl_path, str(local))
        rt.push_branch("test-branch")

        # Verify branch exists on remote
        result = subprocess.run(
            ["git", "-C", str(remote), "branch"],
            check=True,
            capture_output=True,
            text=True,
        )
        assert "test-branch" in result.stdout
