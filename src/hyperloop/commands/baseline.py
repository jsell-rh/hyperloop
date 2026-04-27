"""Baseline command — pre-seed Summary records for brownfield projects.

Discovers all spec files in a repository, computes each spec's current blob
SHA via git, and creates Summary records so hyperloop treats existing code as
"already implemented" at the pinned version.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import TYPE_CHECKING, cast

import yaml

from hyperloop.adapters.git.spec_source import GitSpecSource
from hyperloop.adapters.git.state import GitStateStore

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class BaselineAction:
    """Record of what happened for a single spec during baseline."""

    spec_path: str
    sha: str
    action: str  # "new", "updated", "skipped", "failed"


@dataclass(frozen=True)
class BaselineResult:
    """Aggregate result of a baseline run."""

    new: int
    updated: int
    skipped: int
    failed: int
    actions: list[BaselineAction] = field(default_factory=lambda: [])


def _parse_summary_ref(yaml_content: str) -> str | None:
    """Extract the SHA from a summary's spec_ref field."""
    parsed: object = yaml.safe_load(yaml_content)
    if not isinstance(parsed, dict):
        return None
    d = cast("dict[str, object]", parsed)
    spec_ref = str(d.get("spec_ref", ""))
    if "@" in spec_ref:
        return spec_ref.rsplit("@", 1)[1]
    return None


def _build_summary_yaml(spec_path: str, blob_sha: str) -> str:
    """Build the YAML content for a baseline summary record."""
    data: dict[str, str | int | list[str] | None] = {
        "spec_path": spec_path,
        "spec_ref": f"{spec_path}@{blob_sha}",
        "total_tasks": 0,
        "completed": 0,
        "failed": 0,
        "failure_themes": [],
        "last_audit": None,
        "last_audit_result": None,
    }
    return yaml.dump(data, default_flow_style=False, sort_keys=False)


def baseline_specs(
    repo_path: Path,
    spec_glob: str | None,
    dry_run: bool,
) -> BaselineResult:
    """Discover specs, compute blob SHAs, and create/update Summary records.

    Args:
        repo_path: Path to the git repository.
        spec_glob: Optional glob to filter spec files.
        dry_run: If True, report actions without writing state.

    Returns:
        BaselineResult with counts and per-spec action details.
    """
    state = GitStateStore(repo_path)
    spec_source = GitSpecSource(repo_path)

    # Discover specs using both patterns (matching orchestrator's _run_drift_detection)
    spec_files = state.list_files("specs/**/*.spec.md")
    spec_files_alt = state.list_files("specs/**/*.md")
    all_specs = sorted(set(spec_files) | set(spec_files_alt))

    # Apply optional glob filter
    if spec_glob is not None:
        all_specs = [s for s in all_specs if fnmatch(s, spec_glob)]

    if not all_specs:
        return BaselineResult(new=0, updated=0, skipped=0, failed=0, actions=[])

    # Load existing summaries
    existing_summaries = state.list_summaries()

    actions: list[BaselineAction] = []
    new_count = 0
    updated_count = 0
    skipped_count = 0
    failed_count = 0

    for spec_path in all_specs:
        blob_sha = spec_source.file_version(spec_path)
        if not blob_sha:
            actions.append(BaselineAction(spec_path=spec_path, sha="", action="failed"))
            failed_count += 1
            continue

        existing_yaml = existing_summaries.get(spec_path)
        if existing_yaml is not None:
            existing_sha = _parse_summary_ref(existing_yaml)
            if existing_sha == blob_sha:
                actions.append(BaselineAction(spec_path=spec_path, sha=blob_sha, action="skipped"))
                skipped_count += 1
                continue
            # SHA differs — update
            action = "updated"
            updated_count += 1
        else:
            action = "new"
            new_count += 1

        if not dry_run:
            summary_yaml = _build_summary_yaml(spec_path, blob_sha)
            state.store_summary(spec_path, summary_yaml)

        actions.append(BaselineAction(spec_path=spec_path, sha=blob_sha, action=action))

    # Persist if any changes were made
    if not dry_run and (new_count > 0 or updated_count > 0):
        state.persist(
            f"chore: baseline {new_count + updated_count + skipped_count} specs "
            f"({new_count} new, {updated_count} updated)"
        )

    return BaselineResult(
        new=new_count,
        updated=updated_count,
        skipped=skipped_count,
        failed=failed_count,
        actions=actions,
    )
