"""ADVANCE phase -- process reaped results and handle gates/actions.

Returns a list of transitions and spawn requests. Does NOT call
state.transition_task, state.store_review, state.set_task_pr, or
state.set_task_branch. Those are Orchestrator responsibilities.

CAN call gate.check(), action.execute(), pr.create_draft(), pr.get_pr_state()
as those are external queries/operations whose results inform the transitions.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from hyperloop.cycle.helpers import (
    BRANCH_PREFIX,
    find_position_for_step,
    phase_for_action,
    phase_for_pipe_action,
)
from hyperloop.domain.model import (
    ActionStep,
    CheckStep,
    GateStep,
    Phase,
    PipelinePosition,
    TaskStatus,
    Verdict,
    WorkerHandle,
    WorkerResult,
)
from hyperloop.domain.pipeline import (
    PipelineComplete,
    PipelineExecutor,
    PipelineFailed,
    SpawnAgent,
)
from hyperloop.ports.action import ActionOutcome

if TYPE_CHECKING:
    from hyperloop.domain.model import Task
    from hyperloop.ports.action import ActionPort
    from hyperloop.ports.check import CheckPort
    from hyperloop.ports.gate import GatePort
    from hyperloop.ports.notification import NotificationPort
    from hyperloop.ports.pr import PRPort
    from hyperloop.ports.probe import OrchestratorProbe
    from hyperloop.ports.state import StateStore

logger: structlog.stdlib.BoundLogger = structlog.get_logger()


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
    to_spawn: list[tuple[str, str, PipelinePosition]]
    halt_reason: str | None
    action_attempts: dict[str, int]
    notified_gates: set[str]
    had_failures: bool


def advance(
    state: StateStore,
    reaped: dict[str, WorkerResult],
    reaped_metadata: dict[str, tuple[WorkerHandle, PipelinePosition, float]],
    executor: PipelineExecutor,
    gate: GatePort | None,
    action: ActionPort | None,
    check: CheckPort | None,
    pr: PRPort | None,
    notification: NotificationPort,
    probe: OrchestratorProbe,
    max_task_rounds: int,
    max_action_attempts: int,
    action_attempts: dict[str, int],
    notified_gates: set[str],
    cycle: int,
) -> AdvanceResult:
    """Advance tasks: process reaped results, then gates/actions.

    Args:
        state: State store for reading task state (not mutating).
        reaped: Reaped worker results: task_id -> WorkerResult.
        reaped_metadata: Reaped worker metadata: task_id -> (handle, pos, spawn_time).
        executor: Pipeline executor for walking the pipeline.
        gate: Gate port for checking gate signals (may be None).
        action: Action port for executing actions (may be None).
        pr: PR port for creating/checking PRs (may be None).
        notification: Notification port for gate-blocked alerts.
        probe: Probe for observability events.
        max_task_rounds: Maximum rounds per task.
        max_action_attempts: Maximum action retry attempts.
        action_attempts: Current action attempt counts (copy -- will be updated).
        notified_gates: Current gate notification set (copy -- will be updated).
        cycle: Current cycle number.

    Returns:
        AdvanceResult with transitions, spawn requests, and updated tracking state.
    """
    transitions: list[TaskTransition] = []
    to_spawn: list[tuple[str, str, PipelinePosition]] = []
    halt_reason: str | None = None
    had_failures = False

    # -- Step 1: Process reaped results through the pipeline --
    for task_id, result in reaped.items():
        worker_info = reaped_metadata.get(task_id)
        if worker_info is None:
            continue

        _handle, position, spawn_time = worker_info
        task = state.get_task(task_id)

        probe.worker_reaped(
            task_id=task_id,
            role=_handle.role,
            verdict=result.verdict.value,
            round=task.round,
            cycle=cycle,
            spec_ref=task.spec_ref,
            detail=result.detail,
            duration_s=time.monotonic() - spawn_time,
        )

        pipe_action, _new_pos = executor.next_action(position, result)

        if isinstance(pipe_action, PipelineComplete):
            transitions.append(
                TaskTransition(task_id=task_id, status=TaskStatus.COMPLETE, phase=None)
            )
            probe.task_completed(
                task_id=task_id,
                spec_ref=task.spec_ref,
                total_rounds=task.round,
                total_cycles=cycle,
                cycle=cycle,
            )

        elif isinstance(pipe_action, PipelineFailed):
            transitions.append(
                TaskTransition(
                    task_id=task_id,
                    status=TaskStatus.FAILED,
                    phase=None,
                    review=ReviewRecord(
                        round=task.round,
                        role=_handle.role,
                        verdict=result.verdict.value,
                        detail=result.detail,
                    ),
                )
            )
            halt_reason = f"task {task_id} pipeline failed: {pipe_action.reason}"
            had_failures = True
            probe.task_failed(
                task_id=task_id,
                spec_ref=task.spec_ref,
                reason=pipe_action.reason,
                round=task.round,
                cycle=cycle,
            )

        elif isinstance(pipe_action, SpawnAgent):
            if result.verdict == Verdict.FAIL:
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

                transitions.append(
                    TaskTransition(
                        task_id=task_id,
                        status=TaskStatus.IN_PROGRESS,
                        phase=Phase(pipe_action.agent),
                        round=new_round,
                        review=ReviewRecord(
                            round=task.round,
                            role=_handle.role,
                            verdict=result.verdict.value,
                            detail=result.detail,
                        ),
                    )
                )
                had_failures = True
                probe.task_looped_back(
                    task_id=task_id,
                    spec_ref=task.spec_ref,
                    round=new_round,
                    cycle=cycle,
                    findings_preview=result.detail[:200],
                )
            else:
                # Advancing forward on PASS -- create draft PR if needed
                pr_url: str | None = None
                if task.pr is None and pr is not None:
                    branch = task.branch or f"{BRANCH_PREFIX}/{task_id}"
                    draft_url = pr.create_draft(
                        task_id,
                        branch,
                        task.title,
                        task.spec_ref,
                        pr_title=task.pr_title,
                        pr_description=task.pr_description,
                    )
                    if draft_url:
                        pr_url = draft_url

                transitions.append(
                    TaskTransition(
                        task_id=task_id,
                        status=TaskStatus.IN_PROGRESS,
                        phase=Phase(pipe_action.agent),
                        pr_url=pr_url,
                    )
                )
                probe.task_advanced(
                    task_id=task_id,
                    spec_ref=task.spec_ref,
                    from_phase=str(task.phase) if task.phase else None,
                    to_phase=pipe_action.agent,
                    from_status=task.status.value,
                    to_status=TaskStatus.IN_PROGRESS.value,
                    round=task.round,
                    cycle=cycle,
                )

        else:
            # WaitForGate, PerformAction -- record phase, don't spawn
            # Ensure PR exists before task reaches gate/action steps
            pr_url_ga: str | None = None
            if task.pr is None and pr is not None:
                branch = task.branch or f"{BRANCH_PREFIX}/{task_id}"
                draft_url = pr.create_draft(
                    task_id,
                    branch,
                    task.title,
                    task.spec_ref,
                    pr_title=task.pr_title,
                    pr_description=task.pr_description,
                )
                if draft_url:
                    pr_url_ga = draft_url

            phase_name = phase_for_action(pipe_action)
            transitions.append(
                TaskTransition(
                    task_id=task_id,
                    status=TaskStatus.IN_PROGRESS,
                    phase=Phase(phase_name) if phase_name else None,
                    pr_url=pr_url_ga,
                )
            )
            probe.task_advanced(
                task_id=task_id,
                spec_ref=task.spec_ref,
                from_phase=str(task.phase) if task.phase else None,
                to_phase=phase_name,
                from_status=task.status.value,
                to_status=TaskStatus.IN_PROGRESS.value,
                round=task.round,
                cycle=cycle,
            )

    # If we found a halt reason during reaped-result processing, return early
    if halt_reason is not None:
        return AdvanceResult(
            transitions=transitions,
            to_spawn=to_spawn,
            halt_reason=halt_reason,
            action_attempts=action_attempts,
            notified_gates=notified_gates,
            had_failures=had_failures,
        )

    # -- Step 2: Advance tasks at gate and action steps --
    all_tasks = state.get_world().tasks

    for task in all_tasks.values():
        if task.status != TaskStatus.IN_PROGRESS:
            continue
        if task.phase is None:
            continue
        # Skip tasks that were just transitioned (they may have been reaped above)
        if any(t.task_id == task.id for t in transitions):
            continue

        pos = find_position_for_step(executor, str(task.phase))
        if pos is None:
            continue

        step = PipelineExecutor.resolve_step(executor.pipeline, pos.path)

        # -- Gate step --
        if isinstance(step, GateStep):
            gate_result = _advance_gate(
                task=task,
                step=step,
                pos=pos,
                executor=executor,
                gate=gate,
                pr=pr,
                notification=notification,
                probe=probe,
                notified_gates=notified_gates,
                cycle=cycle,
            )
            transitions.extend(gate_result.transitions)
            if gate_result.halt_reason is not None:
                halt_reason = gate_result.halt_reason
                break

        # -- Check step --
        elif isinstance(step, CheckStep):
            check_result = _advance_check(
                task=task,
                step=step,
                pos=pos,
                executor=executor,
                check=check,
                probe=probe,
                max_task_rounds=max_task_rounds,
                cycle=cycle,
            )
            transitions.extend(check_result.transitions)
            if check_result.halt_reason is not None:
                halt_reason = check_result.halt_reason
                had_failures = True
                break

        # -- Action step --
        elif isinstance(step, ActionStep):
            action_result = _advance_action(
                task=task,
                step=step,
                pos=pos,
                executor=executor,
                action=action,
                notification=notification,
                probe=probe,
                action_attempts=action_attempts,
                max_action_attempts=max_action_attempts,
                cycle=cycle,
            )
            transitions.extend(action_result.transitions)
            if action_result.halt_reason is not None:
                halt_reason = action_result.halt_reason
                break

    return AdvanceResult(
        transitions=transitions,
        to_spawn=to_spawn,
        halt_reason=halt_reason,
        action_attempts=action_attempts,
        notified_gates=notified_gates,
        had_failures=had_failures,
    )


@dataclass(frozen=True)
class _StepResult:
    """Internal result from processing a single gate or action step."""

    transitions: list[TaskTransition]
    halt_reason: str | None = None


def _advance_gate(
    task: Task,
    step: GateStep,
    pos: PipelinePosition,
    executor: PipelineExecutor,
    gate: GatePort | None,
    pr: PRPort | None,
    notification: NotificationPort,
    probe: OrchestratorProbe,
    notified_gates: set[str],
    cycle: int,
) -> _StepResult:
    """Handle a task at a gate step. Returns transitions."""
    if gate is None:
        logger.debug("gates: no gate adapter -- skipping gate polling")
        return _StepResult(transitions=[])

    # Notification deduplication: notify once per gate entry
    if task.id not in notified_gates:
        notification.gate_blocked(task=task, gate_name=step.gate)
        # Add needs-approval label when task first enters a gate
        if task.pr is not None and pr is not None:
            pr.add_label(task.pr, "hyperloop/needs-approval")
        notified_gates.add(task.id)

    cleared = gate.check(task, step.gate)
    probe.gate_checked(
        task_id=task.id,
        gate=step.gate,
        cleared=cleared,
        cycle=cycle,
    )

    if not cleared:
        return _StepResult(transitions=[])

    # Gate cleared -- remove from notified set and remove needs-approval label
    notified_gates.discard(task.id)
    if task.pr is not None and pr is not None:
        pr.remove_label(task.pr, "hyperloop/needs-approval")

    # Check if the gate check returned True because PR was merged
    if task.pr is not None and pr is not None:
        pr_state_check = pr.get_pr_state(task.pr)
        if pr_state_check is not None and pr_state_check.state == "MERGED":
            probe.merge_attempted(
                task_id=task.id,
                branch=task.branch or f"{BRANCH_PREFIX}/{task.id}",
                spec_ref=task.spec_ref,
                outcome="merged_externally",
                attempt=0,
                cycle=cycle,
            )
            return _StepResult(
                transitions=[
                    TaskTransition(
                        task_id=task.id,
                        status=TaskStatus.COMPLETE,
                        phase=None,
                    )
                ]
            )

    advanced = PipelineExecutor.advance_from(executor.pipeline, pos.path)
    if advanced is not None:
        next_action, _new_pos = advanced
        phase_name = phase_for_pipe_action(next_action)
        return _StepResult(
            transitions=[
                TaskTransition(
                    task_id=task.id,
                    status=TaskStatus.IN_PROGRESS,
                    phase=Phase(phase_name) if phase_name else None,
                )
            ]
        )
    return _StepResult(
        transitions=[
            TaskTransition(
                task_id=task.id,
                status=TaskStatus.COMPLETE,
                phase=None,
            )
        ]
    )


def _advance_action(
    task: Task,
    step: ActionStep,
    pos: PipelinePosition,
    executor: PipelineExecutor,
    action: ActionPort | None,
    notification: NotificationPort,
    probe: OrchestratorProbe,
    action_attempts: dict[str, int],
    max_action_attempts: int,
    cycle: int,
) -> _StepResult:
    """Handle a task at an action step. Returns transitions."""
    if action is None:
        logger.debug(
            "actions: no action adapter -- skipping action %s",
            step.action,
        )
        return _StepResult(transitions=[])

    result = action.execute(task, step.action)

    if result.outcome == ActionOutcome.SUCCESS:
        action_attempts.pop(task.id, None)
        probe.merge_attempted(
            task_id=task.id,
            branch=task.branch or f"{BRANCH_PREFIX}/{task.id}",
            spec_ref=task.spec_ref,
            outcome="merged",
            attempt=0,
            cycle=cycle,
        )

        # Advance past action or complete
        advanced = PipelineExecutor.advance_from(executor.pipeline, pos.path)
        if advanced is not None:
            next_act, _new_pos = advanced
            phase_name = phase_for_pipe_action(next_act)
            return _StepResult(
                transitions=[
                    TaskTransition(
                        task_id=task.id,
                        status=TaskStatus.IN_PROGRESS,
                        phase=Phase(phase_name) if phase_name else None,
                        pr_url=result.pr_url,
                    )
                ]
            )
        return _StepResult(
            transitions=[
                TaskTransition(
                    task_id=task.id,
                    status=TaskStatus.COMPLETE,
                    phase=None,
                    pr_url=result.pr_url,
                )
            ]
        )

    if result.outcome == ActionOutcome.RETRY:
        # Stay at current step, try again next cycle
        transitions: list[TaskTransition] = []
        if result.pr_url is not None:
            transitions.append(
                TaskTransition(
                    task_id=task.id,
                    status=TaskStatus.IN_PROGRESS,
                    phase=Phase(step.action),
                    pr_url=result.pr_url,
                )
            )
        return _StepResult(transitions=transitions)

    # ActionOutcome.ERROR
    attempts = action_attempts.get(task.id, 0) + 1
    action_attempts[task.id] = attempts

    looping_back = attempts >= max_action_attempts
    probe.rebase_conflict(
        task_id=task.id,
        branch=task.branch or f"{BRANCH_PREFIX}/{task.id}",
        attempt=attempts,
        max_attempts=max_action_attempts,
        looping_back=looping_back,
        cycle=cycle,
    )

    if looping_back:
        action_attempts.pop(task.id, None)
        notification.task_errored(
            task=task,
            attempts=attempts,
            detail=result.detail,
        )

        # Detect rebase/conflict errors — these indicate a poisoned branch
        detail_lower = result.detail.lower()
        is_rebase_error = "rebase" in detail_lower or "conflict" in detail_lower

        if is_rebase_error:
            # Branch is poisoned — reset task to start fresh
            detail = (
                f"Branch reset: {max_action_attempts} consecutive rebase/merge failures. "
                f"The branch likely has state files in its commit history that cause "
                f"permanent conflicts. Task reset to not-started for a fresh attempt."
            )
            probe.task_reset(
                task_id=task.id,
                spec_ref=task.spec_ref,
                reason=detail,
                prior_round=task.round,
                cycle=cycle,
            )
            return _StepResult(
                transitions=[
                    TaskTransition(
                        task_id=task.id,
                        status=TaskStatus.NOT_STARTED,
                        phase=None,
                        round=0,
                        review=ReviewRecord(
                            round=task.round,
                            role="orchestrator",
                            verdict="fail",
                            detail=detail,
                        ),
                        reset_branch=True,
                    )
                ]
            )

        # Non-rebase error — loop back to implementer as before
        detail = f"Action error after {max_action_attempts} attempts: {result.detail}"
        return _StepResult(
            transitions=[
                TaskTransition(
                    task_id=task.id,
                    status=TaskStatus.IN_PROGRESS,
                    phase=Phase("implementer"),
                    round=task.round + 1,
                    review=ReviewRecord(
                        round=task.round,
                        role="orchestrator",
                        verdict="fail",
                        detail=detail,
                    ),
                )
            ]
        )

    # Stay at merge-pr, retry next cycle
    return _StepResult(
        transitions=[
            TaskTransition(
                task_id=task.id,
                status=TaskStatus.IN_PROGRESS,
                phase=Phase(step.action),
            )
        ]
    )


def _advance_check(
    task: Task,
    step: CheckStep,
    pos: PipelinePosition,
    executor: PipelineExecutor,
    check: CheckPort | None,
    probe: OrchestratorProbe,
    max_task_rounds: int,
    cycle: int,
) -> _StepResult:
    """Handle a task at a check step. Returns transitions."""
    if check is None:
        # No check adapter — pass through
        advanced = PipelineExecutor.advance_from(executor.pipeline, pos.path)
        if advanced is not None:
            next_action, _new_pos = advanced
            phase_name = phase_for_pipe_action(next_action)
            return _StepResult(
                transitions=[
                    TaskTransition(
                        task_id=task.id,
                        status=TaskStatus.IN_PROGRESS,
                        phase=Phase(phase_name) if phase_name else None,
                    )
                ]
            )
        return _StepResult(
            transitions=[TaskTransition(task_id=task.id, status=TaskStatus.COMPLETE, phase=None)]
        )

    passed = check.evaluate(task, step.check)
    probe.gate_checked(
        task_id=task.id,
        gate=step.check,
        cleared=passed,
        cycle=cycle,
    )

    if passed:
        advanced = PipelineExecutor.advance_from(executor.pipeline, pos.path)
        if advanced is not None:
            next_action, _new_pos = advanced
            phase_name = phase_for_pipe_action(next_action)
            return _StepResult(
                transitions=[
                    TaskTransition(
                        task_id=task.id,
                        status=TaskStatus.IN_PROGRESS,
                        phase=Phase(phase_name) if phase_name else None,
                    )
                ]
            )
        return _StepResult(
            transitions=[TaskTransition(task_id=task.id, status=TaskStatus.COMPLETE, phase=None)]
        )

    # Check failed — feed through pipeline executor to trigger loop restart
    fail_result = WorkerResult(verdict=Verdict.FAIL, detail=f"Check '{step.check}' failed")
    pipe_action, _new_pos = executor.next_action(pos, fail_result)

    if isinstance(pipe_action, SpawnAgent):
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
                    phase=Phase(pipe_action.agent),
                    round=new_round,
                    review=ReviewRecord(
                        round=task.round,
                        role="check",
                        verdict="fail",
                        detail=f"Check '{step.check}' failed — looping back",
                    ),
                )
            ]
        )

    if isinstance(pipe_action, PipelineFailed):
        return _StepResult(
            transitions=[
                TaskTransition(
                    task_id=task.id,
                    status=TaskStatus.FAILED,
                    phase=None,
                    review=ReviewRecord(
                        round=task.round,
                        role="check",
                        verdict="fail",
                        detail=f"Check '{step.check}' failed with no enclosing loop",
                    ),
                )
            ],
            halt_reason=f"task {task.id} check failed: {pipe_action.reason}",
        )

    # Shouldn't reach here, but handle gracefully
    return _StepResult(transitions=[])
