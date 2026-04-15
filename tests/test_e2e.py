"""End-to-end integration tests for the hyperloop orchestrator.

Wires real GitStateStore + LocalRuntime + Orchestrator against a real git repo
with a deterministic fake "agent" shell script. No mocks.
"""

from __future__ import annotations

import os
import subprocess
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from hyperloop.adapters.git_state import GitStateStore
from hyperloop.adapters.local import LocalRuntime
from hyperloop.domain.model import (
    ActionStep,
    GateStep,
    LoopStep,
    Process,
    RoleStep,
    TaskStatus,
)
from hyperloop.loop import Orchestrator
from tests.fakes.pr import FakePRManager

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clean_git_env() -> dict[str, str]:
    """Strip GIT_* env vars so tests work inside pre-commit hooks."""
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("GIT_"):
            del env[key]
    return env


def _git(repo: Path, *args: str) -> str:
    """Run a git command in `repo` and return stdout."""
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=_clean_git_env(),
    )
    return result.stdout.strip()


def _init_repo(path: Path) -> None:
    """Create a git repo with user config and an initial commit."""
    env = _clean_git_env()
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True, env=env)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@test.com"],
        check=True,
        capture_output=True,
        env=env,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test"],
        check=True,
        capture_output=True,
        env=env,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "--allow-empty", "-m", "init"],
        check=True,
        capture_output=True,
        env=env,
    )


def _write_task_file(repo: Path, task_id: str, content: str) -> None:
    """Write a task file into the repo's specs/tasks directory."""
    tasks_dir = repo / "specs" / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    (tasks_dir / f"{task_id}.md").write_text(content)


def _write_spec_file(repo: Path, name: str, content: str) -> None:
    """Write a spec file into the repo's specs directory."""
    specs_dir = repo / "specs"
    specs_dir.mkdir(parents=True, exist_ok=True)
    (specs_dir / name).write_text(content)


def _commit_all(repo: Path, message: str) -> None:
    """Stage and commit all changes in the repo."""
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)


def _make_agent_script(tmp_path: Path, name: str, body: str) -> str:
    """Create an executable shell script and return its absolute path."""
    script_path = tmp_path / name
    script_path.write_text(body)
    script_path.chmod(0o755)
    return str(script_path)


# Pipeline used by basic e2e tests: LoopStep(implementer, verifier).
# No merge-pr step — keeps tests focused on the orchestrator loop logic.
E2E_PIPELINE = Process(
    name="e2e",
    intake=(),
    pipeline=(
        LoopStep(
            steps=(
                RoleStep(role="implementer", on_pass=None, on_fail=None),
                RoleStep(role="verifier", on_pass=None, on_fail=None),
            ),
        ),
    ),
)


TASK_CONTENT = dedent("""\
    ---
    id: {task_id}
    title: Implement example feature
    spec_ref: specs/example.md
    status: not-started
    phase: null
    deps: []
    round: 0
    branch: null
    pr: null
    ---

    ## Spec
    Build the example feature.

    ## Findings
    """)


# Pipeline with merge-pr step: LoopStep(implementer, verifier), then merge-pr.
E2E_MERGE_PIPELINE = Process(
    name="e2e-merge",
    intake=(),
    pipeline=(
        LoopStep(
            steps=(
                RoleStep(role="implementer", on_pass=None, on_fail=None),
                RoleStep(role="verifier", on_pass=None, on_fail=None),
            ),
        ),
        ActionStep(action="merge-pr"),
    ),
)

# Pipeline with gate: LoopStep(implementer) -> gate(human-pr-approval) -> merge-pr.
E2E_GATE_PIPELINE = Process(
    name="e2e-gate",
    intake=(),
    pipeline=(
        LoopStep(
            steps=(
                RoleStep(role="implementer", on_pass=None, on_fail=None),
                RoleStep(role="verifier", on_pass=None, on_fail=None),
            ),
        ),
        GateStep(gate="human-pr-approval"),
        ActionStep(action="merge-pr"),
    ),
)


# Minimal shell script that writes a passing .worker-result.json.
# Avoids git operations to keep execution time minimal (~10ms vs ~600ms).
PASS_AGENT_BODY = """\
#!/bin/bash
set -e
cat > /dev/null
cat > .worker-result.json <<'RESULT'
{"verdict": "pass", "findings": 0, "detail": "implemented"}
RESULT
"""

# Agent script that creates a file, commits it, and reports pass.
# Used by merge tests to verify code lands on the base branch.
COMMIT_AGENT_BODY = """\
#!/bin/bash
set -e
cat > /dev/null

# Strip GIT_* env vars (may interfere when running inside pre-commit)
for var in $(env | grep '^GIT_' | cut -d= -f1); do
    unset "$var"
done

# Only create the file if it doesn't already exist (idempotent across roles)
if [ ! -f feature.txt ]; then
    echo "hello from agent" > feature.txt
    git add feature.txt
    git commit -m "feat: add feature.txt"
fi

cat > .worker-result.json <<'RESULT'
{"verdict": "pass", "findings": 0, "detail": "implemented"}
RESULT
"""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

# Each orchestrator cycle takes ~10ms (reads task files, polls subprocesses,
# calls decide). Worker subprocesses take ~50-200ms. max_cycles must be high
# enough to cover the wall-clock time of subprocess execution. 500 cycles
# gives a ~5s budget which is more than sufficient.
MAX_CYCLES = 500


@pytest.mark.slow
class TestSingleTaskCompletesE2E:
    """One task, deterministic agent always passes.

    Task goes from not-started -> implementer -> verifier -> complete.
    """

    def test_single_task_completes_e2e(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_repo(repo)

        # Seed the repo with a spec and a task
        _write_spec_file(repo, "example.md", "# Example\nBuild a widget.\n")
        _write_task_file(repo, "task-001", TASK_CONTENT.format(task_id="task-001"))
        _commit_all(repo, "chore: seed spec and task")

        # Create the agent script
        agent_script = _make_agent_script(tmp_path, "pass-agent.sh", PASS_AGENT_BODY)

        # Wire up real adapters
        state = GitStateStore(repo_path=repo)
        runtime = LocalRuntime(
            repo_path=str(repo),
            worktree_base=str(tmp_path / "worktrees"),
            command=f"bash {agent_script}",
        )
        orch = Orchestrator(
            state=state,
            runtime=runtime,
            process=E2E_PIPELINE,
            max_workers=2,
            max_rounds=10,
            poll_interval=0,
        )

        reason = orch.run_loop(max_cycles=MAX_CYCLES)

        assert "all tasks complete" in reason.lower()

        task = state.get_task("task-001")
        assert task.status == TaskStatus.COMPLETE

        # Verify the orchestrator committed state changes to trunk
        log = _git(repo, "log", "--oneline")
        assert "orchestrator" in log.lower()


@pytest.mark.slow
class TestFailedVerificationRetriesE2E:
    """Verifier agent script returns fail on the first call, then pass on the second.

    Uses a counter file in tmp_path to track invocations.
    """

    def test_failed_verification_retries_e2e(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_repo(repo)

        _write_spec_file(repo, "example.md", "# Example\nBuild a widget.\n")
        _write_task_file(repo, "task-001", TASK_CONTENT.format(task_id="task-001"))
        _commit_all(repo, "chore: seed spec and task")

        counter_file = tmp_path / "verifier-counter"

        # Agent script that fails on the first invocation (counter file absent),
        # then passes on all subsequent invocations.
        retry_agent_body = f"""\
#!/bin/bash
set -e
cat > /dev/null

COUNTER_FILE="{counter_file}"

if [ ! -f "$COUNTER_FILE" ]; then
    echo "1" > "$COUNTER_FILE"
    cat > .worker-result.json <<'RESULT'
{{"verdict": "fail", "findings": 1, "detail": "tests failed on first run"}}
RESULT
else
    cat > .worker-result.json <<'RESULT'
{{"verdict": "pass", "findings": 0, "detail": "all good"}}
RESULT
fi
"""

        agent_script = _make_agent_script(tmp_path, "retry-agent.sh", retry_agent_body)

        state = GitStateStore(repo_path=repo)
        runtime = LocalRuntime(
            repo_path=str(repo),
            worktree_base=str(tmp_path / "worktrees"),
            command=f"bash {agent_script}",
        )
        orch = Orchestrator(
            state=state,
            runtime=runtime,
            process=E2E_PIPELINE,
            max_workers=2,
            max_rounds=10,
            poll_interval=0,
        )

        reason = orch.run_loop(max_cycles=MAX_CYCLES)

        assert "all tasks complete" in reason.lower()

        task = state.get_task("task-001")
        assert task.status == TaskStatus.COMPLETE

        # Verify the fail path ran at least once
        assert counter_file.exists()


@pytest.mark.slow
class TestTwoTasksRunInParallelE2E:
    """Two independent tasks, both complete. Verify both worker branches are created."""

    def test_two_tasks_run_in_parallel_e2e(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_repo(repo)

        _write_spec_file(repo, "example.md", "# Example\nBuild widgets.\n")
        _write_task_file(repo, "task-001", TASK_CONTENT.format(task_id="task-001"))
        _write_task_file(repo, "task-002", TASK_CONTENT.format(task_id="task-002"))
        _commit_all(repo, "chore: seed spec and tasks")

        agent_script = _make_agent_script(tmp_path, "pass-agent.sh", PASS_AGENT_BODY)

        state = GitStateStore(repo_path=repo)
        runtime = LocalRuntime(
            repo_path=str(repo),
            worktree_base=str(tmp_path / "worktrees"),
            command=f"bash {agent_script}",
        )
        orch = Orchestrator(
            state=state,
            runtime=runtime,
            process=E2E_PIPELINE,
            max_workers=4,
            max_rounds=10,
            poll_interval=0,
        )

        reason = orch.run_loop(max_cycles=MAX_CYCLES)

        assert "all tasks complete" in reason.lower()

        task1 = state.get_task("task-001")
        task2 = state.get_task("task-002")
        assert task1.status == TaskStatus.COMPLETE
        assert task2.status == TaskStatus.COMPLETE

        # Verify orchestrator committed state changes
        log = _git(repo, "log", "--oneline")
        assert "orchestrator" in log.lower()


@pytest.mark.slow
class TestLocalMergeLandsCodeOnBaseBranch:
    """Full pipeline with merge-pr step, no PRManager (local merge mode).

    Verifies that code committed by the agent on the worker branch is merged
    into the base branch when the pipeline completes.
    """

    def test_local_merge_lands_code_on_base_branch(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_repo(repo)

        _write_spec_file(repo, "example.md", "# Example\nBuild a widget.\n")
        _write_task_file(repo, "task-001", TASK_CONTENT.format(task_id="task-001"))
        _commit_all(repo, "chore: seed spec and task")

        agent_script = _make_agent_script(tmp_path, "commit-agent.sh", COMMIT_AGENT_BODY)

        state = GitStateStore(repo_path=repo)
        runtime = LocalRuntime(
            repo_path=str(repo),
            worktree_base=str(tmp_path / "worktrees"),
            command=f"bash {agent_script}",
        )
        orch = Orchestrator(
            state=state,
            runtime=runtime,
            process=E2E_MERGE_PIPELINE,
            max_workers=2,
            max_rounds=10,
            repo_path=str(repo),
            poll_interval=0,
        )

        reason = orch.run_loop(max_cycles=MAX_CYCLES)

        assert "all tasks complete" in reason.lower()

        task = state.get_task("task-001")
        assert task.status == TaskStatus.COMPLETE

        # Verify the agent's file exists on the base branch
        assert (repo / "feature.txt").exists()
        assert (repo / "feature.txt").read_text().strip() == "hello from agent"


@pytest.mark.slow
class TestPRFlowWithFakePRManager:
    """Full pipeline with FakePRManager wired into the Orchestrator.

    Proves the PR path works end-to-end: implementer -> verifier -> merge-pr
    with real GitStateStore + LocalRuntime + FakePRManager.
    """

    def test_pr_flow_with_fake_pr_manager(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_repo(repo)

        _write_spec_file(repo, "example.md", "# Example\nBuild a widget.\n")
        # Task needs a pr field set so _merge_via_pr is used instead of _merge_local
        task_with_pr = dedent("""\
            ---
            id: task-001
            title: Implement example feature
            spec_ref: specs/example.md
            status: not-started
            phase: null
            deps: []
            round: 0
            branch: null
            pr: https://github.com/test/repo/pull/1
            ---

            ## Spec
            Build the example feature.

            ## Findings
            """)
        _write_task_file(repo, "task-001", task_with_pr)
        _commit_all(repo, "chore: seed spec and task")

        agent_script = _make_agent_script(tmp_path, "pass-agent.sh", PASS_AGENT_BODY)

        pr_manager = FakePRManager(repo="test/repo")
        # Pre-create the PR in the fake so it exists when merge is called
        pr_url = pr_manager.create_draft(
            task_id="task-001",
            branch="worker/task-001",
            title="Implement example feature",
            spec_ref="specs/example.md",
        )

        state = GitStateStore(repo_path=repo)
        runtime = LocalRuntime(
            repo_path=str(repo),
            worktree_base=str(tmp_path / "worktrees"),
            command=f"bash {agent_script}",
        )
        orch = Orchestrator(
            state=state,
            runtime=runtime,
            process=E2E_MERGE_PIPELINE,
            max_workers=2,
            max_rounds=10,
            pr_manager=pr_manager,
            poll_interval=0,
        )

        reason = orch.run_loop(max_cycles=MAX_CYCLES)

        assert "all tasks complete" in reason.lower()

        task = state.get_task("task-001")
        assert task.status == TaskStatus.COMPLETE

        # Verify FakePRManager received the merge call
        assert len(pr_manager.merged) == 1
        assert pr_manager.rebased == [("worker/task-001", "main")]

        # Verify the PR was actually merged in the fake
        assert pr_manager._prs[pr_url].merged


@pytest.mark.slow
class TestGateBlocksUntilLgtm:
    """Pipeline with gate: implementer -> verifier -> gate(human-pr-approval) -> merge-pr.

    Task reaches the gate and stalls. Test adds the lgtm signal to FakePRManager.
    Next cycle clears the gate. Task proceeds to merge and completes.
    """

    def test_gate_blocks_until_lgtm(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_repo(repo)

        _write_spec_file(repo, "example.md", "# Example\nBuild a widget.\n")
        task_with_pr = dedent("""\
            ---
            id: task-001
            title: Implement example feature
            spec_ref: specs/example.md
            status: not-started
            phase: null
            deps: []
            round: 0
            branch: null
            pr: https://github.com/test/repo/pull/1
            ---

            ## Spec
            Build the example feature.

            ## Findings
            """)
        _write_task_file(repo, "task-001", task_with_pr)
        _commit_all(repo, "chore: seed spec and task")

        agent_script = _make_agent_script(tmp_path, "pass-agent.sh", PASS_AGENT_BODY)

        pr_manager = FakePRManager(repo="test/repo")
        pr_url = pr_manager.create_draft(
            task_id="task-001",
            branch="worker/task-001",
            title="Implement example feature",
            spec_ref="specs/example.md",
        )

        state = GitStateStore(repo_path=repo)
        runtime = LocalRuntime(
            repo_path=str(repo),
            worktree_base=str(tmp_path / "worktrees"),
            command=f"bash {agent_script}",
        )
        orch = Orchestrator(
            state=state,
            runtime=runtime,
            process=E2E_GATE_PIPELINE,
            max_workers=2,
            max_rounds=10,
            pr_manager=pr_manager,
            poll_interval=0,
        )

        # Run enough cycles for implementer + verifier to complete, reaching the gate
        for _ in range(MAX_CYCLES):
            result = orch.run_cycle()
            if result is not None:
                break
            task = state.get_task("task-001")
            if task.phase is not None and str(task.phase) == "human-pr-approval":
                break

        # Task should be at the gate
        task = state.get_task("task-001")
        assert task.status == TaskStatus.IN_PROGRESS
        assert str(task.phase) == "human-pr-approval"

        # Simulate human approval: add lgtm label
        pr_manager.add_label(pr_url, "lgtm")

        # Run more cycles — gate should clear, merge should succeed
        reason = orch.run_loop(max_cycles=MAX_CYCLES)

        assert "all tasks complete" in reason.lower()

        task = state.get_task("task-001")
        assert task.status == TaskStatus.COMPLETE

        # Verify the PR was merged
        assert len(pr_manager.merged) == 1
