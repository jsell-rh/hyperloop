"""Tests for review file parsing from worktrees."""

from __future__ import annotations

from typing import TYPE_CHECKING

from hyperloop.adapters.runtime.agent_sdk import _read_review_from_worktree
from hyperloop.domain.model import Verdict

if TYPE_CHECKING:
    from pathlib import Path


class TestReadReviewFromWorktree:
    """_read_review_from_worktree parses worker-written review files."""

    def test_parses_valid_review_file(self, tmp_path: Path) -> None:
        reviews_dir = tmp_path / ".hyperloop" / "state" / "reviews"
        reviews_dir.mkdir(parents=True)
        (reviews_dir / "task-001-round-0.md").write_text(
            "---\ntask_id: task-001\nround: 0\nrole: verifier\n"
            "verdict: fail\nfindings: 3\n---\nThree issues found.\n"
        )

        result = _read_review_from_worktree(str(tmp_path), "task-001")

        assert result is not None
        assert result.verdict == Verdict.FAIL
        assert result.findings == 3
        assert result.detail == "Three issues found."

    def test_takes_latest_round(self, tmp_path: Path) -> None:
        reviews_dir = tmp_path / ".hyperloop" / "state" / "reviews"
        reviews_dir.mkdir(parents=True)
        (reviews_dir / "task-001-round-0.md").write_text(
            "---\ntask_id: task-001\nround: 0\nrole: verifier\n"
            "verdict: fail\nfindings: 2\n---\nOld findings.\n"
        )
        (reviews_dir / "task-001-round-1.md").write_text(
            "---\ntask_id: task-001\nround: 1\nrole: verifier\n"
            "verdict: pass\nfindings: 0\n---\nAll good now.\n"
        )

        result = _read_review_from_worktree(str(tmp_path), "task-001")

        assert result is not None
        assert result.verdict == Verdict.PASS
        assert result.detail == "All good now."

    def test_returns_none_when_no_review_files(self, tmp_path: Path) -> None:
        result = _read_review_from_worktree(str(tmp_path), "task-001")
        assert result is None

    def test_returns_none_on_missing_frontmatter(self, tmp_path: Path) -> None:
        reviews_dir = tmp_path / ".hyperloop" / "state" / "reviews"
        reviews_dir.mkdir(parents=True)
        (reviews_dir / "task-001-round-0.md").write_text("No frontmatter here.\n")

        result = _read_review_from_worktree(str(tmp_path), "task-001")
        assert result is None

    def test_returns_none_on_malformed_yaml(self, tmp_path: Path) -> None:
        reviews_dir = tmp_path / ".hyperloop" / "state" / "reviews"
        reviews_dir.mkdir(parents=True)
        (reviews_dir / "task-001-round-0.md").write_text("---\n: broken yaml {{{\n---\nBody.\n")

        result = _read_review_from_worktree(str(tmp_path), "task-001")
        assert result is None

    def test_ignores_other_task_reviews(self, tmp_path: Path) -> None:
        reviews_dir = tmp_path / ".hyperloop" / "state" / "reviews"
        reviews_dir.mkdir(parents=True)
        (reviews_dir / "task-002-round-0.md").write_text(
            "---\ntask_id: task-002\nround: 0\nrole: verifier\n"
            "verdict: pass\nfindings: 0\n---\nWrong task.\n"
        )

        result = _read_review_from_worktree(str(tmp_path), "task-001")
        assert result is None
