"""ADVANCE phase -- process reaped results and handle action/signal steps.

Uses flat phase map and task_processor domain functions.
Returns a list of transitions. Does NOT call state.transition_task,
state.store_review, or state.set_task_pr. Those are Orchestrator responsibilities.

CAN call step_executor.execute(), signal_port.check() as those are external
queries whose results inform the transitions.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from hyperloop.cycle.helpers import BRANCH_PREFIX
from hyperloop.domain.model import (
    Phase,
    StepOutcome,
    TaskStatus,
    WorkerHandle,
    WorkerResult,
)
from hyperloop.domain.task_processor import (
    determine_step_type,
    extract_role,
    is_terminal,
    process_result,
)

if TYPE_CHECKING:
    from hyperloop.domain.model import PhaseMap, Task
    from hyperloop.ports.channel import ChannelPort
    from hyperloop.ports.pr import PRPort
    from hyperloop.ports.probe import OrchestratorProbe
    from hyperloop.ports.signal import SignalPort
    from hyperloop.ports.state import StateStore
    from hyperloop.ports.step_executor import StepExecutor


@dataclass(frozen=True)
class ReviewRecord:
    """A review to be stored by the Orchestrator."""

    round: int
    role: str
    verdict: str
    detail: str


@dataclass(frozen=True)
class TaskTransition:
    """A state transition to be applied by the Orchestrator."""

    task_id: str
    status: TaskStatus
    phase: Phase | None
    round: int | None = None
    review: ReviewRecord | None = None
    pr_url: str | None = None
    reset_branch: bool = False


@dataclass(frozen=True)
class AdvanceResult:
    """Result of the ADVANCE phase."""

    transitions: list[TaskTransition]
    halt_reason: str | None
    had_failures: bool


def advance(
    state: StateStore,
    reaped: dict[str, WorkerResult],
    reaped_metadata: dict[str, tuple[WorkerHandle, float]],
    phases: PhaseMap,
    step_executor: StepExecutor | None,
    signal_port: SignalPort | None,
    channel: ChannelPort | None,
    pr: PRPort | None,
    probe: OrchestratorProbe,
    max_task_rounds: int,
    cycle: int,
    running_tasks: frozenset[str] = frozenset(),
) -> AdvanceResult:
    """Advance tasks: process reaped results, then handle action/signal steps.

    Args:
        state: State store for reading task state (not mutating).
        reaped: Reaped worker results: task_id -> WorkerResult.
        reaped_metadata: Reaped worker metadata: task_id -> (handle, spawn_time).
        phases: Flat phase map from the process.
        step_executor: StepExecutor port (may be None).
        signal_port: SignalPort (may be None).
        channel: ChannelPort for notifications (may be None).
        pr: PR port for creating drafts (may be None).
        probe: Probe for observability events.
        max_task_rounds: Maximum rounds per task.
        cycle: Current cycle number.
        running_tasks: Set of task IDs with active workers.

    Returns:
        AdvanceResult with transitions and halt reason.
    """
    transitions: list[TaskTransition] = []
    halt_reason: str | None = None
    had_failures = False

    # -- Step 1: Process reaped agent results through the phase map --
    for task_id, result in reaped.items():
        worker_info = reaped_metadata.get(task_id)
        if worker_info is None:
            continue

        handle, spawn_time = worker_info
        task = state.get_task(task_id)

        probe.worker_reaped(
            task_id=task_id,
            role=handle.role,
            verdict=result.verdict.value,
            round=task.round,
            cycle=cycle,
            spec_ref=task.spec_ref,
            detail=result.detail,
            duration_s=time.monotonic() - spawn_time,
        )

        if task.phase is None or task.phase not in phases:
            continue

        phase_step = phases[task.phase]
        outcome, next_phase = process_result(phase_step, result, task.phase)

        if is_terminal(next_phase):
            transitions.append(
                TaskTransition(
                    task_id=task_id,
                    status=TaskStatus.COMPLETED,
                    phase=None,
                )
            )
            probe.task_completed(
                task_id=task_id,
                spec_ref=task.spec_ref,
                total_rounds=task.round,
                total_cycles=cycle,
                cycle=cycle,
            )
            continue

        if outcome == StepOutcome.RETRY:
            new_round = task.round + 1
            if new_round >= max_task_rounds:
                transitions.append(
                    TaskTransition(
                        task_id=task_id,
                        status=TaskStatus.FAILED,
                        phase=None,
                        round=new_round,
                    )
                )
                halt_reason = f"task {task_id} exceeded max_task_rounds ({max_task_rounds})"
                had_failures = True
                probe.task_failed(
                    task_id=task_id,
                    spec_ref=task.spec_ref,
                    reason=f"exceeded max_task_rounds ({max_task_rounds})",
                    round=new_round,
                    cycle=cycle,
                )
                continue

            # Create draft PR on advancing past first agent phase
            pr_url = _maybe_create_pr(task, pr)

            transitions.append(
                TaskTransition(
                    task_id=task_id,
                    status=TaskStatus.IN_PROGRESS,
                    phase=Phase(next_phase),
                    round=new_round,
                    review=ReviewRecord(
                        round=task.round,
                        role=handle.role,
                        verdict=result.verdict.value,
                        detail=result.detail,
                    ),
                    pr_url=pr_url,
                )
            )
            had_failures = True
            probe.task_retried(
                task_id=task_id,
                spec_ref=task.spec_ref,
                round=new_round,
                cycle=cycle,
                findings_preview=result.detail[:200],
            )
        else:
            # ADVANCE
            pr_url = _maybe_create_pr(task, pr)
            transitions.append(
                TaskTransition(
                    task_id=task_id,
                    status=TaskStatus.IN_PROGRESS,
                    phase=Phase(next_phase),
                    pr_url=pr_url,
                )
            )
            probe.task_advanced(
                task_id=task_id,
                spec_ref=task.spec_ref,
                from_phase=str(task.phase) if task.phase else None,
                to_phase=next_phase,
                from_status=task.status.value,
                to_status=TaskStatus.IN_PROGRESS.value,
                round=task.round,
                cycle=cycle,
            )

    # If we found a halt reason during reaped-result processing, return early
    if halt_reason is not None:
        return AdvanceResult(
            transitions=transitions,
            halt_reason=halt_reason,
            had_failures=had_failures,
        )

    # -- Step 2: Handle tasks at action/signal/check steps --
    all_tasks = state.get_world().tasks

    for task in all_tasks.values():
        if task.status != TaskStatus.IN_PROGRESS:
            continue
        if task.phase is None:
            continue
        # Skip tasks that were just transitioned
        if any(t.task_id == task.id for t in transitions):
            continue
        # Skip tasks with active workers
        if task.id in running_tasks:
            continue

        if task.phase not in phases:
            continue

        phase_step = phases[task.phase]
        step_type = determine_step_type(phase_step)

        if step_type == "agent":
            # Agent steps are handled by SPAWN, not ADVANCE
            continue

        if step_type in ("action", "check"):
            t = _advance_action(
                task=task,
                phase_step=phase_step,
                step_executor=step_executor,
                pr=pr,
                probe=probe,
                max_task_rounds=max_task_rounds,
                cycle=cycle,
            )
            transitions.extend(t.transitions)
            if t.halt_reason is not None:
                halt_reason = t.halt_reason
                had_failures = True
                break

        elif step_type == "signal":
            t = _advance_signal(
                task=task,
                phase_step=phase_step,
                signal_port=signal_port,
                channel=channel,
                probe=probe,
                max_task_rounds=max_task_rounds,
                cycle=cycle,
            )
            transitions.extend(t.transitions)
            if t.halt_reason is not None:
                halt_reason = t.halt_reason
                had_failures = True
                break

    return AdvanceResult(
        transitions=transitions,
        halt_reason=halt_reason,
        had_failures=had_failures,
    )


@dataclass(frozen=True)
class _StepResult:
    """Internal result from processing a single step."""

    transitions: list[TaskTransition]
    halt_reason: str | None = None


def _advance_action(
    task: Task,
    phase_step: object,
    step_executor: StepExecutor | None,
    pr: PRPort | None,
    probe: OrchestratorProbe,
    max_task_rounds: int,
    cycle: int,
) -> _StepResult:
    """Handle a task at an action/check step."""
    from hyperloop.domain.model import PhaseStep

    assert isinstance(phase_step, PhaseStep)

    if step_executor is None:
        return _StepResult(transitions=[])

    step_name = extract_role(phase_step)
    result = step_executor.execute(task, step_name, phase_step.args)

    probe.step_executed(
        task_id=task.id,
        step_name=step_name,
        outcome=result.outcome.value,
        detail=result.detail,
        cycle=cycle,
    )

    outcome, next_phase = process_result(phase_step, result, str(task.phase))

    if is_terminal(next_phase):
        return _StepResult(
            transitions=[
                TaskTransition(
                    task_id=task.id,
                    status=TaskStatus.COMPLETED,
                    phase=None,
                    pr_url=result.pr_url,
                )
            ]
        )

    if outcome == StepOutcome.RETRY:
        new_round = task.round + 1
        if new_round >= max_task_rounds:
            return _StepResult(
                transitions=[
                    TaskTransition(
                        task_id=task.id,
                        status=TaskStatus.FAILED,
                        phase=None,
                        round=new_round,
                    )
                ],
                halt_reason=f"task {task.id} exceeded max_task_rounds ({max_task_rounds})",
            )
        return _StepResult(
            transitions=[
                TaskTransition(
                    task_id=task.id,
                    status=TaskStatus.IN_PROGRESS,
                    phase=Phase(next_phase),
                    round=new_round,
                    review=ReviewRecord(
                        round=task.round,
                        role="step:" + step_name,
                        verdict="fail",
                        detail=result.detail,
                    ),
                    pr_url=result.pr_url,
                )
            ]
        )

    if outcome == StepOutcome.WAIT:
        # Stay at current phase
        return _StepResult(transitions=[])

    # ADVANCE
    return _StepResult(
        transitions=[
            TaskTransition(
                task_id=task.id,
                status=TaskStatus.IN_PROGRESS,
                phase=Phase(next_phase),
                pr_url=result.pr_url,
            )
        ]
    )


def _advance_signal(
    task: Task,
    phase_step: object,
    signal_port: SignalPort | None,
    channel: ChannelPort | None,
    probe: OrchestratorProbe,
    max_task_rounds: int,
    cycle: int,
) -> _StepResult:
    """Handle a task at a signal step."""
    from hyperloop.domain.model import PhaseStep

    assert isinstance(phase_step, PhaseStep)

    if signal_port is None:
        return _StepResult(transitions=[])

    signal_name = extract_role(phase_step)
    signal = signal_port.check(task, signal_name, phase_step.args)

    probe.signal_checked(
        task_id=task.id,
        signal_name=signal_name,
        status=signal.status.value,
        message=signal.message,
        cycle=cycle,
    )

    outcome, next_phase = process_result(phase_step, signal, str(task.phase))

    if outcome == StepOutcome.WAIT:
        return _StepResult(transitions=[])

    if is_terminal(next_phase):
        return _StepResult(
            transitions=[
                TaskTransition(
                    task_id=task.id,
                    status=TaskStatus.COMPLETED,
                    phase=None,
                )
            ]
        )

    if outcome == StepOutcome.RETRY:
        new_round = task.round + 1
        if new_round >= max_task_rounds:
            return _StepResult(
                transitions=[
                    TaskTransition(
                        task_id=task.id,
                        status=TaskStatus.FAILED,
                        phase=None,
                        round=new_round,
                    )
                ],
                halt_reason=f"task {task.id} exceeded max_task_rounds ({max_task_rounds})",
            )
        return _StepResult(
            transitions=[
                TaskTransition(
                    task_id=task.id,
                    status=TaskStatus.IN_PROGRESS,
                    phase=Phase(next_phase),
                    round=new_round,
                    review=ReviewRecord(
                        round=task.round,
                        role="signal:" + signal_name,
                        verdict="rejected",
                        detail=signal.message,
                    ),
                )
            ]
        )

    # ADVANCE
    return _StepResult(
        transitions=[
            TaskTransition(
                task_id=task.id,
                status=TaskStatus.IN_PROGRESS,
                phase=Phase(next_phase),
            )
        ]
    )


def _maybe_create_pr(task: Task, pr: PRPort | None) -> str | None:
    """Create a draft PR if the task doesn't have one and pr port is available."""
    if task.pr is not None or pr is None:
        return None
    branch = task.branch or f"{BRANCH_PREFIX}/{task.id}"
    draft_url = pr.create_draft(
        task.id,
        branch,
        task.title,
        task.spec_ref,
        pr_title=task.pr_title,
        pr_description=task.pr_description,
    )
    return draft_url if draft_url else None
