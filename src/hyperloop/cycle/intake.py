"""INTAKE phase -- detect spec gaps and create work via PM agent.

Intake has a contained side effect (runs the PM agent via runtime.run_serial).
Returns IntakeResult describing what happened so the Orchestrator can apply
spec_ref pinning.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from hyperloop.domain.model import IntakeContext

if TYPE_CHECKING:
    from hyperloop.compose import PromptComposer
    from hyperloop.ports.runtime import Runtime
    from hyperloop.ports.state import StateStore

logger: structlog.stdlib.BoundLogger = structlog.get_logger()


@dataclass(frozen=True)
class IntakeResult:
    """Result of the INTAKE phase."""

    ran: bool
    created_count: int
    tasks_before: set[str]
    success: bool
    duration_s: float
    unprocessed_count: int


def _unprocessed_specs(state: StateStore) -> list[str]:
    """Return spec file paths that have no corresponding task."""
    all_specs = state.list_files("specs/**/*.spec.md")
    world = state.get_world()
    covered_refs = {task.spec_ref.split("@")[0] for task in world.tasks.values()}
    return [s for s in all_specs if s not in covered_refs]


def run_intake(
    state: StateStore,
    runtime: Runtime,
    composer: PromptComposer | None,
    has_failures: bool,
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
        logger.debug("intake: no composer -- skipping")
        return not_ran

    unprocessed = _unprocessed_specs(state)
    if not unprocessed and not has_failures:
        logger.debug("intake: no unprocessed specs or failures -- skipping")
        return not_ran

    logger.info(
        "intake: running PM (unprocessed=%d, failures=%s)",
        len(unprocessed),
        has_failures,
    )

    # Collect failed task IDs when re-triggering on failures
    failed_task_ids: tuple[str, ...] = ()
    if has_failures:
        from hyperloop.domain.model import TaskStatus

        world = state.get_world()
        failed_task_ids = tuple(t.id for t in world.tasks.values() if t.status == TaskStatus.FAILED)

    context = IntakeContext(
        unprocessed_specs=tuple(unprocessed),
        failed_tasks=failed_task_ids,
    )
    composed = composer.compose(role="pm", context=context)
    prompt = composed.text

    world_before = state.get_world()
    tasks_before = set(world_before.tasks.keys())
    task_count_before = len(world_before.tasks)
    intake_start = time.monotonic()
    success = runtime.run_serial("pm", prompt)

    world_after = state.get_world()
    task_count_after = len(world_after.tasks)
    created_count = task_count_after - task_count_before

    return IntakeResult(
        ran=True,
        created_count=created_count,
        tasks_before=tasks_before,
        success=success,
        duration_s=time.monotonic() - intake_start,
        unprocessed_count=len(unprocessed),
    )
