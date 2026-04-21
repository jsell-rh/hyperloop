"""GitSpecSource -- reads spec files from a git repository.

Stub implementation -- not yet wired.  Lives alongside state.py
(GitStateStore), runtime.py (AgentSdkRuntime), and _worktree.py
under adapters/git/.
"""

from __future__ import annotations


class GitSpecSource:
    """Reads spec files from the git working tree."""

    def list_specs(self, pattern: str) -> list[str]:
        """List spec files matching a glob pattern."""
        raise NotImplementedError

    def read_spec(self, path: str) -> str:
        """Read the contents of a spec file."""
        raise NotImplementedError
