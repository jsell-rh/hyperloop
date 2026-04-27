"""Tests for the hyperloop baseline command.

Uses real git repos (following test_dashboard.py patterns) for integration
tests that need file_version(), and InMemoryStateStore where appropriate.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import yaml

from hyperloop.commands.baseline import baseline_specs

if TYPE_CHECKING:
    from pathlib import Path


def _init_git_repo(path: Path) -> None:
    """Initialize a git repo with an initial commit."""
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
    (path / ".gitkeep").write_text("")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "--no-verify", "-m", "init"],
        check=True,
        capture_output=True,
    )


def _write_spec(repo: Path, spec_path: str, content: str) -> None:
    """Write a spec file into the repo working tree."""
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


def _get_blob_sha(repo: Path, file_path: str) -> str:
    """Get the blob SHA of a file at HEAD."""
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", f"HEAD:{file_path}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _make_repo_with_specs(tmp_path: Path, spec_names: list[str]) -> Path:
    """Create a temp repo with the given spec files."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    for name in spec_names:
        _write_spec(repo, f"specs/{name}", f"# {name}\n\nSpec content for {name}.\n")

    _commit_all(repo)
    return repo


class TestFirstBaseline:
    """First baseline on a project with specs creates summaries."""

    def test_summaries_created_count_matches(self, tmp_path: Path) -> None:
        repo = _make_repo_with_specs(tmp_path, ["auth.spec.md", "api.spec.md", "storage.spec.md"])

        result = baseline_specs(repo, spec_glob=None, dry_run=False)

        assert result.new == 3
        assert result.updated == 0
        assert result.skipped == 0
        assert result.failed == 0
        assert len(result.actions) == 3
        assert all(a.action == "new" for a in result.actions)

    def test_summaries_persisted_to_state_branch(self, tmp_path: Path) -> None:
        repo = _make_repo_with_specs(tmp_path, ["auth.spec.md"])

        baseline_specs(repo, spec_glob=None, dry_run=False)

        # Verify summary is readable via GitStateStore
        from hyperloop.adapters.git.state import GitStateStore

        state = GitStateStore(repo)
        summaries = state.list_summaries()
        assert "specs/auth.spec.md" in summaries

        parsed = yaml.safe_load(summaries["specs/auth.spec.md"])
        expected_sha = _get_blob_sha(repo, "specs/auth.spec.md")
        assert parsed["spec_ref"] == f"specs/auth.spec.md@{expected_sha}"
        assert parsed["total_tasks"] == 0
        assert parsed["completed"] == 0

    def test_plain_md_specs_also_discovered(self, tmp_path: Path) -> None:
        """specs/**/*.md pattern picks up files without .spec. in name."""
        repo = _make_repo_with_specs(tmp_path, ["auth.md"])

        result = baseline_specs(repo, spec_glob=None, dry_run=False)

        assert result.new == 1
        assert result.actions[0].spec_path == "specs/auth.md"


class TestDryRun:
    """Dry run reports actions but writes nothing."""

    def test_no_summaries_written(self, tmp_path: Path) -> None:
        repo = _make_repo_with_specs(tmp_path, ["auth.spec.md", "api.spec.md"])

        result = baseline_specs(repo, spec_glob=None, dry_run=True)

        assert result.new == 2
        assert result.updated == 0
        assert result.skipped == 0

        # Verify nothing was persisted
        from hyperloop.adapters.git.state import GitStateStore

        state = GitStateStore(repo)
        summaries = state.list_summaries()
        assert len(summaries) == 0

    def test_correct_actions_reported(self, tmp_path: Path) -> None:
        repo = _make_repo_with_specs(tmp_path, ["widget.spec.md"])

        result = baseline_specs(repo, spec_glob=None, dry_run=True)

        assert len(result.actions) == 1
        action = result.actions[0]
        assert action.spec_path == "specs/widget.spec.md"
        assert action.action == "new"
        assert action.sha != ""


class TestIdempotentRerun:
    """Running baseline twice with no changes skips everything."""

    def test_all_skipped_no_new_commit(self, tmp_path: Path) -> None:
        repo = _make_repo_with_specs(tmp_path, ["auth.spec.md", "api.spec.md"])

        # First run
        first = baseline_specs(repo, spec_glob=None, dry_run=False)
        assert first.new == 2

        # Get state branch commit count
        commit_count_before = subprocess.run(
            ["git", "-C", str(repo), "rev-list", "--count", "hyperloop/state"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

        # Second run — should skip everything
        second = baseline_specs(repo, spec_glob=None, dry_run=False)
        assert second.new == 0
        assert second.updated == 0
        assert second.skipped == 2
        assert second.failed == 0
        assert all(a.action == "skipped" for a in second.actions)

        # Verify no new commit was made on state branch
        commit_count_after = subprocess.run(
            ["git", "-C", str(repo), "rev-list", "--count", "hyperloop/state"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert commit_count_before == commit_count_after


class TestSpecModifiedBetweenRuns:
    """Modified spec between baseline runs produces an 'updated' action."""

    def test_updated_summary_with_new_sha(self, tmp_path: Path) -> None:
        repo = _make_repo_with_specs(tmp_path, ["feature.spec.md"])

        # First baseline
        first = baseline_specs(repo, spec_glob=None, dry_run=False)
        assert first.new == 1
        old_sha = first.actions[0].sha

        # Modify the spec file
        _write_spec(repo, "specs/feature.spec.md", "# Feature v2\n\nUpdated content.\n")
        _commit_all(repo, "modify feature spec")

        # Second baseline
        second = baseline_specs(repo, spec_glob=None, dry_run=False)
        assert second.new == 0
        assert second.updated == 1
        assert second.skipped == 0
        assert second.actions[0].action == "updated"
        assert second.actions[0].sha != old_sha

        # Verify persisted summary has new SHA
        from hyperloop.adapters.git.state import GitStateStore

        state = GitStateStore(repo)
        summaries = state.list_summaries()
        parsed = yaml.safe_load(summaries["specs/feature.spec.md"])
        new_sha = _get_blob_sha(repo, "specs/feature.spec.md")
        assert parsed["spec_ref"] == f"specs/feature.spec.md@{new_sha}"


class TestNestedSpecPathRoundTrip:
    """Nested spec paths round-trip correctly through store -> list -> get."""

    def test_nested_spec_path_survives_store_list_roundtrip(self, tmp_path: Path) -> None:
        repo = _make_repo_with_specs(tmp_path, ["placeholder.spec.md"])

        from hyperloop.adapters.git.state import GitStateStore

        state = GitStateStore(repo)
        yaml_content = yaml.dump(
            {
                "spec_path": "specs/core/auth.spec.md",
                "spec_ref": "specs/core/auth.spec.md@abc123",
                "total_tasks": 0,
                "completed": 0,
                "failed": 0,
                "failure_themes": [],
                "last_audit": None,
                "last_audit_result": None,
            }
        )
        state.store_summary("specs/core/auth.spec.md", yaml_content)
        state.persist("test")

        summaries = state.list_summaries()
        assert "specs/core/auth.spec.md" in summaries

    def test_deeply_nested_spec_path_roundtrips(self, tmp_path: Path) -> None:
        repo = _make_repo_with_specs(tmp_path, ["placeholder.spec.md"])

        from hyperloop.adapters.git.state import GitStateStore

        state = GitStateStore(repo)
        yaml_content = yaml.dump(
            {
                "spec_path": "specs/a/b/c/deep.spec.md",
                "spec_ref": "specs/a/b/c/deep.spec.md@sha1",
                "total_tasks": 0,
                "completed": 0,
                "failed": 0,
                "failure_themes": [],
                "last_audit": None,
                "last_audit_result": None,
            }
        )
        state.store_summary("specs/a/b/c/deep.spec.md", yaml_content)
        state.persist("test")

        summaries = state.list_summaries()
        assert "specs/a/b/c/deep.spec.md" in summaries

        # Also verify get_summary works
        retrieved = state.get_summary("specs/a/b/c/deep.spec.md")
        assert retrieved is not None
        parsed = yaml.safe_load(retrieved)
        assert parsed["spec_ref"] == "specs/a/b/c/deep.spec.md@sha1"

    def test_nested_baseline_roundtrips(self, tmp_path: Path) -> None:
        """Baseline on nested specs creates summaries that list_summaries finds."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        _write_spec(repo, "specs/core/system-purpose.spec.md", "# System Purpose\n")
        _write_spec(repo, "specs/core/auth.spec.md", "# Auth\n")
        _commit_all(repo)

        baseline_specs(repo, spec_glob=None, dry_run=False)

        from hyperloop.adapters.git.state import GitStateStore

        state = GitStateStore(repo)
        summaries = state.list_summaries()
        assert "specs/core/system-purpose.spec.md" in summaries
        assert "specs/core/auth.spec.md" in summaries


class TestGlobFilter:
    """Glob filter only baselines matching specs."""

    def test_only_matching_specs_baselined(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        _write_spec(repo, "specs/iam/auth.spec.md", "# IAM Auth\n")
        _write_spec(repo, "specs/iam/roles.spec.md", "# IAM Roles\n")
        _write_spec(repo, "specs/api/rest.spec.md", "# API REST\n")
        _commit_all(repo)

        result = baseline_specs(repo, spec_glob="specs/iam/*", dry_run=False)

        assert result.new == 2
        assert result.skipped == 0
        spec_paths = {a.spec_path for a in result.actions}
        assert spec_paths == {"specs/iam/auth.spec.md", "specs/iam/roles.spec.md"}


class TestNoSpecsFound:
    """No specs found produces graceful empty result."""

    def test_graceful_exit_no_error(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        result = baseline_specs(repo, spec_glob=None, dry_run=False)

        assert result.new == 0
        assert result.updated == 0
        assert result.skipped == 0
        assert result.failed == 0
        assert result.actions == []


class TestReconcilerIntegration:
    """After baseline, detect_coverage_gaps returns no gaps for baselined specs."""

    def test_no_coverage_gaps_after_baseline(self, tmp_path: Path) -> None:
        repo = _make_repo_with_specs(tmp_path, ["auth.spec.md", "api.spec.md"])

        baseline_specs(repo, spec_glob=None, dry_run=False)

        # Load summaries and check coverage
        from hyperloop.adapters.git.state import GitStateStore
        from hyperloop.domain.reconciler import Summary, detect_coverage_gaps

        state = GitStateStore(repo)
        raw_summaries = state.list_summaries()
        summaries: dict[str, Summary] = {}
        for spec_path, content in raw_summaries.items():
            parsed = yaml.safe_load(content)
            summaries[spec_path] = Summary(
                spec_path=parsed["spec_path"],
                spec_ref=parsed["spec_ref"],
                total_tasks=parsed["total_tasks"],
                completed=parsed["completed"],
                failed=parsed["failed"],
                failure_themes=parsed.get("failure_themes", []),
                last_audit=parsed.get("last_audit"),
                last_audit_result=parsed.get("last_audit_result"),
            )

        spec_paths = ["specs/auth.spec.md", "specs/api.spec.md"]

        gaps = detect_coverage_gaps({}, spec_paths, summaries)
        assert gaps == []


class TestFreshnessDriftAfterBaseline:
    """After baseline + spec edit, detect_freshness_drift detects the change."""

    def test_freshness_drift_detected(self, tmp_path: Path) -> None:
        repo = _make_repo_with_specs(tmp_path, ["auth.spec.md"])

        baseline_specs(repo, spec_glob=None, dry_run=False)

        # Modify the spec
        _write_spec(repo, "specs/auth.spec.md", "# Auth v2\n\nChanged.\n")
        _commit_all(repo, "modify auth spec")

        # Load the summary (still has old SHA from baseline)
        from hyperloop.adapters.git.state import GitStateStore
        from hyperloop.domain.reconciler import Summary, detect_freshness_drift

        state = GitStateStore(repo)
        raw_summaries = state.list_summaries()
        summaries: dict[str, Summary] = {}
        for spec_path, content in raw_summaries.items():
            parsed = yaml.safe_load(content)
            summaries[spec_path] = Summary(
                spec_path=parsed["spec_path"],
                spec_ref=parsed["spec_ref"],
                total_tasks=parsed["total_tasks"],
                completed=parsed["completed"],
                failed=parsed["failed"],
                failure_themes=parsed.get("failure_themes", []),
                last_audit=parsed.get("last_audit"),
                last_audit_result=parsed.get("last_audit_result"),
            )

        # Get current spec version
        from hyperloop.adapters.git.spec_source import GitSpecSource

        spec_source = GitSpecSource(repo)
        current_sha = spec_source.file_version("specs/auth.spec.md")

        spec_versions = {"specs/auth.spec.md": current_sha}

        drifts = detect_freshness_drift({}, spec_versions, summaries)
        assert len(drifts) == 1
        assert drifts[0].spec_path == "specs/auth.spec.md"
