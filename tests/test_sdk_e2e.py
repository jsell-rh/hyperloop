"""SDK end-to-end tests -- requires Agent SDK + API credentials.

Skipped when ANTHROPIC_API_KEY is not set or CLAUDE_CODE_USE_VERTEX is not set.
Run manually: uv run pytest tests/test_sdk_e2e.py -v
"""

from __future__ import annotations

import os
import subprocess
import time
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from hyperloop.adapters.git.runtime import AgentSdkRuntime
from hyperloop.domain.model import Verdict

if TYPE_CHECKING:
    from pathlib import Path

skip_no_credentials = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("CLAUDE_CODE_USE_VERTEX"),
    reason="No API credentials -- set ANTHROPIC_API_KEY or CLAUDE_CODE_USE_VERTEX=1",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TASK_CONTENT = dedent("""\
    ---
    id: task-001
    title: Write hello file
    spec_ref: specs/hello.md
    status: not-started
    phase: null
    deps: []
    round: 0
    branch: null
    pr: null
    ---
    """)


def _init_repo(path: Path) -> None:
    """Create a git repo with an initial empty commit."""
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
    subprocess.run(
        ["git", "-C", str(path), "commit", "--no-verify", "--allow-empty", "-m", "init"],
        check=True,
        capture_output=True,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@skip_no_credentials
@pytest.mark.slow
class TestSdkAgentWritesReviewFile:
    """Validates the SDK runtime integration end-to-end."""

    def test_agent_completes_with_non_error_verdict(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)

        # Write a simple spec
        specs_dir = repo / "specs"
        specs_dir.mkdir()
        (specs_dir / "hello.md").write_text("# Hello\nWrite 'hello' to hello.txt.")

        # Write a task file
        tasks_dir = repo / ".hyperloop" / "state" / "tasks"
        tasks_dir.mkdir(parents=True)
        (tasks_dir / "task-001.md").write_text(TASK_CONTENT)

        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "--no-verify", "-m", "initial setup"],
            check=True,
            capture_output=True,
        )

        # Create the branch for the worker
        branch = "hyperloop/task-001"
        subprocess.run(
            ["git", "-C", str(repo), "checkout", "-b", branch],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "checkout", "-"],
            check=True,
            capture_output=True,
        )

        runtime = AgentSdkRuntime(repo_path=str(repo))

        prompt = (
            "Write 'hello' to hello.txt in the current directory. "
            "Then write your review file to "
            ".hyperloop/state/reviews/task-001-round-0.md "
            "with YAML frontmatter containing verdict: pass, "
            "and a body saying 'Done'."
        )

        handle = runtime.spawn("task-001", "implementer", prompt=prompt, branch=branch)

        # Poll with timeout
        timeout = 120
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            status = runtime.poll(handle)
            if status != "running":
                break
            time.sleep(2)

        status = runtime.poll(handle)
        assert status in ("done", "failed"), f"Agent timed out after {timeout}s"

        result = runtime.reap(handle)
        assert result.verdict != Verdict.FAIL, f"Agent failed: {result.detail}"
