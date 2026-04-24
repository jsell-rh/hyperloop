"""Task processor — pure domain logic for flat phase map execution.

Determines step types, extracts roles, processes results into outcomes,
and manages phase transitions. All functions are pure with no I/O.
"""

from __future__ import annotations

from hyperloop.domain.model import (
    PhaseMap,
    PhaseStep,
    Signal,
    SignalStatus,
    StepOutcome,
    StepResult,
    Task,
    Verdict,
    WorkerResult,
)

_VALID_STEP_TYPES = frozenset({"agent", "action", "signal", "check"})
_TERMINAL_PHASE = "done"


def determine_step_type(phase: PhaseStep) -> str:
    """Parse phase.run to determine step type.

    Raises ValueError for unrecognized step types.
    """
    step_type = phase.run.split()[0]
    if step_type not in _VALID_STEP_TYPES:
        msg = f"unknown step type '{step_type}' in run string '{phase.run}'"
        raise ValueError(msg)
    return step_type


def extract_role(phase: PhaseStep) -> str:
    """Extract the role/name from phase.run (second token)."""
    return phase.run.split()[1]


def process_result(
    phase: PhaseStep,
    result: WorkerResult | StepResult | Signal | None,
    current_phase: str,
) -> tuple[StepOutcome, str]:
    """Given a phase and result, determine the outcome and next phase.

    None result (worker crash) defaults to RETRY.
    """
    if result is None:
        return StepOutcome.RETRY, phase.on_fail

    if isinstance(result, WorkerResult):
        if result.verdict == Verdict.PASS:
            return StepOutcome.ADVANCE, phase.on_pass
        return StepOutcome.RETRY, phase.on_fail

    if isinstance(result, StepResult):
        return result.outcome, _target_for_outcome(phase, result.outcome, current_phase)

    if isinstance(result, Signal):
        if result.status == SignalStatus.APPROVED:
            return StepOutcome.ADVANCE, phase.on_pass
        if result.status == SignalStatus.REJECTED:
            return StepOutcome.RETRY, phase.on_fail
        # PENDING
        return StepOutcome.WAIT, phase.on_wait if phase.on_wait is not None else current_phase

    msg = f"unexpected result type: {type(result)}"
    raise TypeError(msg)


def _target_for_outcome(phase: PhaseStep, outcome: StepOutcome, current_phase: str) -> str:
    """Map a StepOutcome to the appropriate phase target."""
    if outcome == StepOutcome.ADVANCE:
        return phase.on_pass
    if outcome == StepOutcome.RETRY:
        return phase.on_fail
    # WAIT
    return phase.on_wait if phase.on_wait is not None else current_phase


def should_increment_round(outcome: StepOutcome) -> bool:
    """RETRY increments round; ADVANCE and WAIT do not."""
    return outcome == StepOutcome.RETRY


def is_terminal(next_phase: str) -> bool:
    """Returns True if next_phase is the terminal sentinel."""
    return next_phase == _TERMINAL_PHASE


def check_max_rounds(task: Task, max_rounds: int) -> bool:
    """Returns True if task has reached or exceeded max_rounds."""
    return task.round >= max_rounds


def first_phase(phases: PhaseMap) -> str:
    """Returns the name of the first phase in the map.

    Raises ValueError if the phase map is empty.
    """
    if not phases:
        msg = "cannot determine first phase from empty phase map"
        raise ValueError(msg)
    return next(iter(phases))
