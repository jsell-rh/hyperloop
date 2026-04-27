"""INTAKE phase -- detect spec gaps and create work via PM agent.

Intake has a contained side effect (runs the PM agent via runtime.run_serial).
Returns IntakeResult describing what happened so the Orchestrator can apply
spec_ref pinning.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from hyperloop.domain.model import IntakeContext, SpecChangeType, SpecIntakeEntry

if TYPE_CHECKING:
    from pathlib import Path

    from hyperloop.compose import PromptComposer
    from hyperloop.ports.probe import OrchestratorProbe
    from hyperloop.ports.runtime import Runtime
    from hyperloop.ports.spec_source import SpecSource
    from hyperloop.ports.state import StateStore


@dataclass(frozen=True)
class IntakeResult:
    """Result of the INTAKE phase."""

    ran: bool
    created_count: int
    tasks_before: set[str]
    success: bool
    duration_s: float
    unprocessed_count: int
    unprocessed_specs: tuple[str, ...] = ()


def _detect_spec_entries(
    state: StateStore, spec_source: SpecSource | None = None
) -> list[SpecIntakeEntry]:
    """Return specs that need PM attention, with change context for modified ones."""
    all_specs = state.list_files("specs/**/*.spec.md")
    world = state.get_world()

    pinned_versions: dict[str, str] = {}
    covered: set[str] = set()
    for task in world.tasks.values():
        if "@" in task.spec_ref:
            path, sha = task.spec_ref.rsplit("@", 1)
            covered.add(path)
            existing = pinned_versions.get(path)
            if existing is None:
                pinned_versions[path] = sha
        else:
            covered.add(task.spec_ref)

    result: list[SpecIntakeEntry] = []
    for spec in all_specs:
        if spec not in covered:
            result.append(SpecIntakeEntry(path=spec, change_type=SpecChangeType.NEW))
        elif (
            spec_source is not None
            and spec in pinned_versions
            and spec_source.has_changed(spec, pinned_versions[spec])
        ):
            diff = spec_source.get_diff(spec, pinned_versions[spec])
            result.append(
                SpecIntakeEntry(path=spec, change_type=SpecChangeType.MODIFIED, diff=diff)
            )

    return result


def run_intake(
    state: StateStore,
    runtime: Runtime,
    composer: PromptComposer | None,
    has_failures: bool,
    spec_source: SpecSource | None = None,
    probe: OrchestratorProbe | None = None,
    cycle: int = 0,
) -> IntakeResult:
    """Run PM intake if there are unprocessed specs or task failures.

    This function has a contained side effect: it calls ``runtime.run_serial``
    to run the PM agent. It returns an IntakeResult so the Orchestrator can
    apply spec_ref pinning and emit probe events.

    Args:
        state: State store for reading specs and tasks.
        runtime: Runtime for running the PM agent serially.
        composer: Prompt composer (None = skip intake).
        has_failures: Whether any task has failed since last intake.

    Returns:
        IntakeResult describing what happened.
    """
    not_ran = IntakeResult(
        ran=False,
        created_count=0,
        tasks_before=set(),
        success=True,
        duration_s=0.0,
        unprocessed_count=0,
    )

    if composer is None:
        return not_ran

    entries = _detect_spec_entries(state, spec_source)
    if not entries and not has_failures:
        return not_ran

    spec_paths = tuple(e.path for e in entries)

    # Collect failed task IDs and their detail when re-triggering on failures
    failed_task_ids: tuple[str, ...] = ()
    failure_details: tuple[str, ...] = ()
    if has_failures:
        from hyperloop.domain.model import TaskStatus

        world = state.get_world()
        failed_tasks_list = [t for t in world.tasks.values() if t.status == TaskStatus.FAILED]
        failed_task_ids = tuple(t.id for t in failed_tasks_list)
        details: list[str] = []
        for task in failed_tasks_list:
            findings = state.get_findings(task.id)
            if findings:
                details.append(f"Task {task.id}: {findings}")
            else:
                details.append(f"Task {task.id}: (no detail available)")
        failure_details = tuple(details)

    context = IntakeContext(
        unprocessed_specs=spec_paths,
        spec_entries=tuple(entries),
        failed_tasks=failed_task_ids,
        failure_details=failure_details,
    )
    composed = composer.compose(role="pm", context=context)
    prompt = composed.text
    if probe is not None:
        probe.prompt_composed(
            task_id="pm-intake",
            role="pm",
            prompt_text=prompt,
            sections=composed.sections,
            round=0,
            cycle=cycle,
        )

    world_before = state.get_world()
    tasks_before = set(world_before.tasks.keys())
    task_count_before = len(world_before.tasks)
    intake_start = time.monotonic()
    success = runtime.run_serial("pm", prompt)

    _ingest_working_tree_tasks(state)

    world_after = state.get_world()
    task_count_after = len(world_after.tasks)
    created_count = task_count_after - task_count_before

    return IntakeResult(
        ran=True,
        created_count=created_count,
        tasks_before=tasks_before,
        success=success,
        duration_s=time.monotonic() - intake_start,
        unprocessed_count=len(entries),
        unprocessed_specs=spec_paths,
    )


@dataclass(frozen=True)
class IngestResult:
    """Result of working-tree task ingestion."""

    added_count: int
    failed: tuple[Path, ...]


def _ingest_working_tree_tasks(state: StateStore) -> IngestResult:
    """Scan the working tree for task files the PM wrote and ingest them via the port.

    Delegates to ``state.ingest_external_tasks()`` which knows how to parse
    task .md files. Only successfully ingested files are deleted, and only
    after ``persist()`` succeeds. Files that fail to parse remain on disk
    for operator inspection and are reported in ``IngestResult.failed``.

    Returns:
        IngestResult with counts and paths of files that failed to parse.
    """
    from pathlib import Path

    empty = IngestResult(added_count=0, failed=())

    repo_path: Path | None = getattr(state, "_repo", None)
    if repo_path is None:
        return empty

    tasks_dir = Path(repo_path) / ".hyperloop" / "state" / "tasks"
    if not tasks_dir.is_dir():
        return empty

    # Collect all candidate files before ingestion
    world = state.get_world()
    existing_ids = set(world.tasks.keys())
    candidate_files = [f for f in sorted(tasks_dir.glob("*.md")) if f.stem not in existing_ids]

    ingested = state.ingest_external_tasks(tasks_dir)
    ingested_set = set(ingested)

    # Identify files that were candidates but not ingested (parse failures)
    failed_files = tuple(f for f in candidate_files if f.stem not in ingested_set)

    if ingested:
        state.persist("ingest tasks from PM")

        # Only delete successfully ingested files after persist succeeds
        for task_id in ingested:
            task_file = tasks_dir / f"{task_id}.md"
            if task_file.exists():
                task_file.unlink()

    return IngestResult(added_count=len(ingested), failed=failed_files)
