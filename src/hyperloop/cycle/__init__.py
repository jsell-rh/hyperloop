"""Cycle phases -- pure decision modules for the orchestrator loop.

Each phase takes state, returns results. The Orchestrator applies those
results to ports (state store, runtime, etc.).
"""

from hyperloop.cycle.advance import AdvanceResult, ReviewRecord, TaskTransition, advance
from hyperloop.cycle.collect import CollectResult, collect
from hyperloop.cycle.helpers import (
    BRANCH_PREFIX,
    build_world,
    collect_roles,
    collect_steps_of_type,
    find_position_for_role,
    find_position_for_step,
    phase_for_action,
    phase_for_pipe_action,
    position_from_phase,
)
from hyperloop.cycle.intake import IntakeResult, run_intake
from hyperloop.cycle.spawn import SpawnPlan, plan_spawns

__all__ = [
    "BRANCH_PREFIX",
    "AdvanceResult",
    "CollectResult",
    "IntakeResult",
    "ReviewRecord",
    "SpawnPlan",
    "TaskTransition",
    "advance",
    "build_world",
    "collect",
    "collect_roles",
    "collect_steps_of_type",
    "find_position_for_role",
    "find_position_for_step",
    "phase_for_action",
    "phase_for_pipe_action",
    "plan_spawns",
    "position_from_phase",
    "run_intake",
]
