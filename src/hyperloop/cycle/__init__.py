"""Cycle phases -- pure decision modules for the orchestrator loop.

Each phase takes state, returns results. The Orchestrator applies those
results to ports (state store, runtime, etc.).
"""

from hyperloop.cycle.advance import AdvanceResult, ReviewRecord, TaskTransition, advance
from hyperloop.cycle.collect import CollectResult, collect
from hyperloop.cycle.helpers import (
    BRANCH_PREFIX,
    build_world,
    extract_roles_from_phases,
    extract_step_names,
)
from hyperloop.cycle.intake import IntakeResult, run_intake
from hyperloop.cycle.spawn import SpawnPlan, SpawnResult, plan_spawns

__all__ = [
    "BRANCH_PREFIX",
    "AdvanceResult",
    "CollectResult",
    "IntakeResult",
    "ReviewRecord",
    "SpawnPlan",
    "SpawnResult",
    "TaskTransition",
    "advance",
    "build_world",
    "collect",
    "extract_roles_from_phases",
    "extract_step_names",
    "plan_spawns",
    "run_intake",
]
