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
from hyperloop.compose import AgentTemplate
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

        if cmd == "agent" and len(args) > 1 and args[1] == "update":
            # agent update -> return agent JSON
            name = args[2] if len(args) > 2 else "unknown"
            print(json.dumps({"id": f"agent-id-{name}", "name": name}))
            sys.exit(0)

        if cmd == "agent" and len(args) > 1 and args[1] == "get":
            name = args[2] if len(args) > 2 else "unknown"
            ann = json.loads(os.environ.get("FAKE_AGENT_ANNOTATIONS", "{}"))
            cur = os.environ.get("FAKE_CURRENT_SESSION", "")
            obj = {"id": f"agent-id-{name}", "name": name, "annotations": ann}
            if cur:
                obj["current_session_id"] = cur
            print(json.dumps(obj))
            sys.exit(0)

        if cmd == "inbox" and len(args) > 1 and args[1] == "send":
            print("ok")
            sys.exit(0)

        if cmd == "start":
            print(json.dumps({"session_id": "ses-001"}))
            sys.exit(0)

        if cmd == "stop":
            print("stopped")
            sys.exit(0)

        if cmd == "session" and len(args) > 1 and args[1] == "events":
            # Emit a RUN_FINISHED event and exit
            import time as _t
            evt = {"type": "RUN_FINISHED", "result": {"total_cost_usd": 0.12, "num_turns": 5}}
            print(json.dumps(evt), flush=True)
            sys.exit(0)
    """)


def _slow_sse_behaviour() -> str:
    """SSE behaviour that delays briefly before emitting RUN_FINISHED.

    This ensures the poll-before-done test can observe "running".
    """
    return textwrap.dedent("""\
        cmd = args[0] if args else ""

        if cmd == "agent" and len(args) > 1 and args[1] == "update":
            name = args[2] if len(args) > 2 else "unknown"
            print(json.dumps({"id": f"agent-id-{name}", "name": name}))
            sys.exit(0)

        if cmd == "inbox" and len(args) > 1 and args[1] == "send":
            print("ok")
            sys.exit(0)

        if cmd == "start":
            print(json.dumps({"session_id": "ses-002"}))
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
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
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


def _make_runtime(
    acpctl: str,
    repo_path: str,
    log_path: Path | None = None,
) -> AmbientRuntime:
    """Create an AmbientRuntime with the fake acpctl and set log env."""
    if log_path is not None:
        os.environ["FAKE_ACPCTL_LOG"] = str(log_path)
    rt = AmbientRuntime(
        repo_path=repo_path,
        project_id="test-project",
        acpctl=acpctl,
        base_branch="main",
    )
    return rt


def _sync_default_agents(rt: AmbientRuntime) -> None:
    """Sync a minimal set of agents for testing."""
    templates = {
        "implementer": AgentTemplate(
            name="hyperloop-implementer",
            prompt="You are an implementer.",
            guidelines="Write clean code.",
            annotations={},
        ),
        "verifier": AgentTemplate(
            name="hyperloop-verifier",
            prompt="You are a verifier.",
            guidelines="Review carefully.",
            annotations={},
        ),
    }
    rt.sync_agents(templates)


def _read_log(log_path: Path) -> list[list[str]]:
    """Read the acpctl log and return list of arg lists."""
    if not log_path.exists():
        return []
    lines = log_path.read_text().strip().splitlines()
    return [json.loads(line) for line in lines]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSyncAgents:
    """sync_agents creates/updates Ambient agents from templates."""

    def test_sync_concatenates_prompt_and_guidelines(
        self, fake_acpctl: str, git_repo: str, acpctl_log: Path
    ) -> None:
        rt = _make_runtime(fake_acpctl, git_repo, acpctl_log)
        templates = {
            "implementer": AgentTemplate(
                name="hyperloop-implementer",
                prompt="Base prompt.",
                guidelines="Guideline text.",
                annotations={},
            ),
        }
        rt.sync_agents(templates)

        cmds = _read_log(acpctl_log)
        # Should have one agent update call
        assert len(cmds) == 1
        assert cmds[0][0] == "agent"
        assert cmds[0][1] == "update"
        assert cmds[0][2] == "hyperloop-implementer"

        # Find the --prompt arg
        prompt_idx = cmds[0].index("--prompt")
        prompt_val = cmds[0][prompt_idx + 1]
        assert "Base prompt." in prompt_val
        assert "## Guidelines" in prompt_val
        assert "Guideline text." in prompt_val

    def test_sync_populates_agents_dict(self, fake_acpctl: str, git_repo: str) -> None:
        rt = _make_runtime(fake_acpctl, git_repo)
        _sync_default_agents(rt)
        assert "implementer" in rt._agents
        assert "verifier" in rt._agents


class TestSpawn:
    """spawn sends inbox, starts session, returns handle."""

    def test_spawn_sends_inbox_starts_session(
        self, fake_acpctl: str, git_repo: str, acpctl_log: Path
    ) -> None:
        rt = _make_runtime(fake_acpctl, git_repo, acpctl_log)
        _sync_default_agents(rt)
        # Clear the log so we only see spawn commands
        acpctl_log.write_text("")

        handle = rt.spawn("task-001", "implementer", "Do the thing.", "feat/task-001")

        assert handle.task_id == "task-001"
        assert handle.role == "implementer"
        assert handle.session_id == "ses-001"

        cmds = _read_log(acpctl_log)
        # Commands: agent update (annotations), inbox send, start
        subcmds = [c[0] for c in cmds]
        assert "agent" in subcmds  # annotation update
        assert "inbox" in subcmds
        assert "start" in subcmds

    def test_spawn_records_session(self, fake_acpctl: str, git_repo: str) -> None:
        rt = _make_runtime(fake_acpctl, git_repo)
        _sync_default_agents(rt)
        rt.spawn("task-001", "implementer", "Do it.", "feat/task-001")
        assert rt._sessions["task-001"] == "ses-001"


class TestPoll:
    """poll returns running/done/failed based on SSE thread state."""

    def test_poll_returns_running_then_done(self, slow_acpctl: str, git_repo: str) -> None:
        rt = _make_runtime(slow_acpctl, git_repo)
        _sync_default_agents(rt)
        handle = rt.spawn("task-001", "implementer", "Work.", "feat/task-001")

        # Immediately after spawn, should be running (SSE delayed 0.3s)
        status = rt.poll(handle)
        assert status == "running"

        # Wait for SSE thread to finish
        time.sleep(0.6)
        status = rt.poll(handle)
        assert status == "done"

    def test_poll_returns_done_after_fast_sse(self, fake_acpctl: str, git_repo: str) -> None:
        rt = _make_runtime(fake_acpctl, git_repo)
        _sync_default_agents(rt)
        handle = rt.spawn("task-001", "implementer", "Work.", "feat/task-001")

        # SSE finishes near-instantly, wait briefly for thread
        time.sleep(0.2)
        status = rt.poll(handle)
        assert status == "done"


class TestReap:
    """reap fetches branch, reads review, stops session."""

    def test_reap_fetches_branch_reads_review(self, tmp_path: Path, acpctl_log: Path) -> None:
        """Set up a git repo with a remote that has a review file."""
        # Create a "remote" repo with a review file on a branch
        remote = tmp_path / "remote"
        remote.mkdir()
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "t@t",
        }
        subprocess.run(["git", "init", str(remote)], check=True, capture_output=True)
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
        subprocess.run(
            ["git", "-C", str(remote), "add", "."],
            check=True,
            capture_output=True,
        )
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

        # Clone it as the "local" repo
        local = tmp_path / "local"
        subprocess.run(
            ["git", "clone", str(remote), str(local)],
            check=True,
            capture_output=True,
        )

        # Create fake acpctl that returns agent annotations with correct branch
        behaviour = textwrap.dedent("""\
            cmd = args[0] if args else ""

            if cmd == "agent" and len(args) > 1 and args[1] == "update":
                name = args[2] if len(args) > 2 else "unknown"
                print(json.dumps({"id": f"agent-id-{name}", "name": name}))
                sys.exit(0)

            if cmd == "agent" and len(args) > 1 and args[1] == "get":
                name = args[2] if len(args) > 2 else "unknown"
                obj = {
                    "id": f"agent-id-{name}",
                    "name": name,
                    "annotations": {
                        "hyperloop.io/task-id": "task-001",
                        "hyperloop.io/branch": "feat/task-001",
                    },
                }
                print(json.dumps(obj))
                sys.exit(0)

            if cmd == "inbox" and len(args) > 1 and args[1] == "send":
                print("ok")
                sys.exit(0)

            if cmd == "start":
                print(json.dumps({"session_id": "ses-reap"}))
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
        _sync_default_agents(rt)
        acpctl_log.write_text("")

        handle = rt.spawn("task-001", "implementer", "Work.", "feat/task-001")
        time.sleep(0.2)  # let SSE thread finish

        result = rt.reap(handle)

        assert result.verdict == Verdict.FAIL
        assert result.findings == 2
        assert "Two issues" in result.detail

        # Verify stop was called
        cmds = _read_log(acpctl_log)
        stop_cmds = [c for c in cmds if c[0] == "stop"]
        assert len(stop_cmds) >= 1

    def test_reap_falls_back_when_no_review(self, tmp_path: Path, acpctl_log: Path) -> None:
        """When no review file exists, reap returns PASS fallback."""
        # Create a remote repo with no review on the branch
        remote = tmp_path / "remote"
        remote.mkdir()
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "t@t",
        }
        subprocess.run(["git", "init", str(remote)], check=True, capture_output=True)
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
            ["git", "-C", str(remote), "commit", "--allow-empty", "-m", "empty"],
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
        subprocess.run(
            ["git", "clone", str(remote), str(local)],
            check=True,
            capture_output=True,
        )

        behaviour = textwrap.dedent("""\
            cmd = args[0] if args else ""

            if cmd == "agent" and len(args) > 1 and args[1] == "update":
                name = args[2] if len(args) > 2 else "unknown"
                print(json.dumps({"id": f"agent-id-{name}", "name": name}))
                sys.exit(0)

            if cmd == "agent" and len(args) > 1 and args[1] == "get":
                name = args[2] if len(args) > 2 else "unknown"
                obj = {
                    "id": f"agent-id-{name}",
                    "name": name,
                    "annotations": {
                        "hyperloop.io/task-id": "task-002",
                        "hyperloop.io/branch": "feat/task-002",
                    },
                }
                print(json.dumps(obj))
                sys.exit(0)

            if cmd == "inbox" and len(args) > 1 and args[1] == "send":
                print("ok")
                sys.exit(0)

            if cmd == "start":
                print(json.dumps({"session_id": "ses-noreview"}))
                sys.exit(0)

            if cmd == "stop":
                print("stopped")
                sys.exit(0)

            if cmd == "session" and len(args) > 1 and args[1] == "events":
                evt = {"type": "RUN_FINISHED", "result": {}}
                print(json.dumps(evt), flush=True)
                sys.exit(0)
        """)
        acpctl_path = _write_fake_acpctl(tmp_path / "acpctl_norv", behaviour)

        rt = _make_runtime(acpctl_path, str(local), acpctl_log)
        _sync_default_agents(rt)

        handle = rt.spawn("task-002", "implementer", "Work.", "feat/task-002")
        time.sleep(0.2)

        result = rt.reap(handle)
        assert result.verdict == Verdict.PASS
        assert result.detail == "Agent completed"


class TestCancel:
    """cancel stops the session and cleans up."""

    def test_cancel_stops_session(self, fake_acpctl: str, git_repo: str, acpctl_log: Path) -> None:
        rt = _make_runtime(fake_acpctl, git_repo, acpctl_log)
        _sync_default_agents(rt)
        acpctl_log.write_text("")

        handle = rt.spawn("task-001", "implementer", "Work.", "feat/task-001")
        rt.cancel(handle)

        cmds = _read_log(acpctl_log)
        stop_cmds = [c for c in cmds if c[0] == "stop"]
        assert len(stop_cmds) == 1
        assert stop_cmds[0][1] == "ses-001"

        # Internal state should be cleaned up
        assert "task-001" not in rt._sessions


class TestFindOrphan:
    """find_orphan detects orphaned sessions via current_session_id."""

    def test_find_orphan_reads_current_session(self, tmp_path: Path, git_repo: str) -> None:
        behaviour = textwrap.dedent("""\
            cmd = args[0] if args else ""

            if cmd == "agent" and len(args) > 1 and args[1] == "update":
                name = args[2] if len(args) > 2 else "unknown"
                print(json.dumps({"id": f"agent-id-{name}", "name": name}))
                sys.exit(0)

            if cmd == "agent" and len(args) > 1 and args[1] == "get":
                name = args[2] if len(args) > 2 else "unknown"
                obj = {
                    "id": f"agent-id-{name}",
                    "name": name,
                    "current_session_id": "ses-orphan",
                    "annotations": {
                        "hyperloop.io/task-id": "task-099",
                        "hyperloop.io/branch": "feat/task-099",
                    },
                }
                print(json.dumps(obj))
                sys.exit(0)

            if cmd == "session" and len(args) > 1 and args[1] == "events":
                import time as _t
                _t.sleep(5)
                sys.exit(0)

            if cmd == "stop":
                print("stopped")
                sys.exit(0)
        """)
        acpctl_path = _write_fake_acpctl(tmp_path / "acpctl_orphan", behaviour)
        rt = _make_runtime(acpctl_path, git_repo)
        _sync_default_agents(rt)

        handle = rt.find_orphan("task-099", "feat/task-099")

        assert handle is not None
        assert handle.task_id == "task-099"
        assert handle.session_id == "ses-orphan"

    def test_find_orphan_returns_none_when_no_match(self, tmp_path: Path, git_repo: str) -> None:
        behaviour = textwrap.dedent("""\
            cmd = args[0] if args else ""

            if cmd == "agent" and len(args) > 1 and args[1] == "update":
                name = args[2] if len(args) > 2 else "unknown"
                print(json.dumps({"id": f"agent-id-{name}", "name": name}))
                sys.exit(0)

            if cmd == "agent" and len(args) > 1 and args[1] == "get":
                name = args[2] if len(args) > 2 else "unknown"
                obj = {
                    "id": f"agent-id-{name}",
                    "name": name,
                    "annotations": {
                        "hyperloop.io/task-id": "task-other",
                        "hyperloop.io/branch": "feat/task-other",
                    },
                }
                print(json.dumps(obj))
                sys.exit(0)
        """)
        acpctl_path = _write_fake_acpctl(tmp_path / "acpctl_no_orphan", behaviour)
        rt = _make_runtime(acpctl_path, git_repo)
        _sync_default_agents(rt)

        handle = rt.find_orphan("task-099", "feat/task-099")
        assert handle is None


class TestWorkerEpilogue:
    """worker_epilogue returns push instruction."""

    def test_worker_epilogue(self, fake_acpctl: str, git_repo: str) -> None:
        rt = _make_runtime(fake_acpctl, git_repo)
        assert "Push your branch" in rt.worker_epilogue()


class TestPushBranch:
    """push_branch calls git push."""

    def test_push_branch(self, tmp_path: Path) -> None:
        """Verify push_branch runs git push (using local clone with remote)."""
        # Set up a bare remote + clone
        bare = tmp_path / "bare.git"
        subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)

        local = tmp_path / "local"
        subprocess.run(
            ["git", "clone", str(bare), str(local)],
            check=True,
            capture_output=True,
        )
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "t@t",
        }
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
            ["git", "-C", str(local), "checkout", "-b", "feat/push-test"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(local), "commit", "--allow-empty", "-m", "branch"],
            check=True,
            capture_output=True,
            env=env,
        )

        fake = _write_fake_acpctl(tmp_path / "acpctl", _default_behaviour())
        rt = _make_runtime(fake, str(local))

        # Should not raise
        rt.push_branch("feat/push-test")

        # Verify the remote has the branch
        result = subprocess.run(
            ["git", "-C", str(bare), "branch"],
            check=True,
            capture_output=True,
            text=True,
        )
        assert "feat/push-test" in result.stdout
