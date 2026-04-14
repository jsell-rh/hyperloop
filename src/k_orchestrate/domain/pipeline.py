"""Pipeline executor — walks a task through pipeline steps.

Given the current pipeline position and a worker result, returns the next action
to take and the new position. No I/O, no side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

from k_orchestrate.domain.model import (
    ActionStep,
    GateStep,
    LoopStep,
    PipelinePosition,
    PipelineStep,
    RoleStep,
    Verdict,
    WorkerResult,
)

# ---------------------------------------------------------------------------
# Pipeline actions (output of next_action)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SpawnRole:
    """Spawn a worker with the given role."""

    role: str


@dataclass(frozen=True)
class WaitForGate:
    """Block until the named gate's external signal is received."""

    gate: str


@dataclass(frozen=True)
class PerformAction:
    """Execute a terminal action (merge-pr, mark-pr-ready, etc.)."""

    action: str


@dataclass(frozen=True)
class PipelineComplete:
    """The pipeline has been fully traversed — no more steps."""


@dataclass(frozen=True)
class PipelineFailed:
    """The pipeline cannot continue (fail with no enclosing loop)."""

    reason: str


PipelineAction = SpawnRole | WaitForGate | PerformAction | PipelineComplete | PipelineFailed
"""Union of all pipeline action types."""


# ---------------------------------------------------------------------------
# Pipeline executor class
# ---------------------------------------------------------------------------


class PipelineExecutor:
    """Walks a task through a pipeline, returning the next action at each step."""

    def __init__(self, pipeline: tuple[PipelineStep, ...]) -> None:
        self._pipeline = pipeline

    def next_action(
        self, position: PipelinePosition, result: WorkerResult | None
    ) -> tuple[PipelineAction, PipelinePosition]:
        """Determine the next pipeline action given the current position and result.

        Pure method. No I/O. No side effects.

        Args:
            position: Current position in the pipeline (path of indices).
            result: The result from the current step's worker, or None if just arriving.

        Returns:
            A tuple of (action to take, new position).
        """
        step = self._resolve_step(self._pipeline, position.path)

        # --- No result: we're arriving at this step for the first time ---
        if result is None:
            return self._action_for_step(step), position

        # --- Result received: decide what to do next ---
        is_pass = result.verdict == Verdict.PASS

        # Handle on_pass/on_fail overrides on RoleStep
        if isinstance(step, RoleStep):
            override = step.on_pass if is_pass else step.on_fail
            if override is not None:
                # Find the named step in the current step list (same nesting level)
                parent_steps: Sequence[PipelineStep] = self._pipeline
                prefix: tuple[int, ...] = ()
                if len(position.path) > 1:
                    # Walk to the parent's step list
                    for idx in position.path[:-1]:
                        s = parent_steps[idx]
                        if isinstance(s, LoopStep):
                            parent_steps = s.steps
                            prefix = (*prefix, idx)
                        else:
                            break

                target_idx = self._find_step_by_role(parent_steps, override)
                if target_idx is not None:
                    return self._descend_to_leaf(parent_steps, prefix, target_idx)

        if is_pass:
            # Advance to next step
            advanced = self._advance_from(self._pipeline, position.path)
            if advanced is not None:
                return advanced
            # Past the end of the pipeline
            return PipelineComplete(), position

        # Fail: restart enclosing loop
        restarted = self._restart_loop(self._pipeline, position.path)
        if restarted is not None:
            return restarted

        # No enclosing loop — pipeline fails
        reason = f"fail at step {list(position.path)} with no enclosing loop"
        return PipelineFailed(reason=reason), position

    def initial_position(self) -> PipelinePosition:
        """Return the position of the first leaf step in the pipeline."""
        path: list[int] = [0]
        step: PipelineStep = self._pipeline[0]
        while isinstance(step, LoopStep):
            path.append(0)
            step = step.steps[0]
        return PipelinePosition(path=tuple(path))

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _resolve_step(
        steps: Sequence[PipelineStep],
        path: tuple[int, ...],
    ) -> PipelineStep:
        """Walk the path to find the step at the given position."""
        step = steps[path[0]]
        for idx in path[1:]:
            if not isinstance(step, LoopStep):
                msg = f"Expected LoopStep at path prefix, got {type(step).__name__}"
                raise ValueError(msg)
            step = step.steps[idx]
        return step

    @staticmethod
    def _find_step_by_role(
        steps: Sequence[PipelineStep],
        target_role: str,
    ) -> int | None:
        """Find the index of a step matching the target role name at the top level."""
        for i, step in enumerate(steps):
            if isinstance(step, RoleStep) and step.role == target_role:
                return i
        return None

    @staticmethod
    def _action_for_step(step: PipelineStep) -> PipelineAction:
        """Return the immediate action for arriving at a step (no result yet)."""
        if isinstance(step, RoleStep):
            return SpawnRole(role=step.role)
        if isinstance(step, GateStep):
            return WaitForGate(gate=step.gate)
        if isinstance(step, ActionStep):
            return PerformAction(action=step.action)
        # LoopStep — should not be called directly; caller descends into it.
        msg = f"Cannot produce action for {type(step).__name__}"
        raise ValueError(msg)

    @staticmethod
    def _descend_to_leaf(
        steps: Sequence[PipelineStep],
        prefix: tuple[int, ...],
        index: int,
    ) -> tuple[PipelineAction, PipelinePosition]:
        """Descend from a step index, entering nested LoopSteps until we reach a leaf step.

        Returns the action for the leaf step and its full position path.
        """
        step = steps[index]
        current_path = (*prefix, index)

        while isinstance(step, LoopStep):
            # Enter the loop at its first child
            current_path = (*current_path, 0)
            step = step.steps[0]

        return PipelineExecutor._action_for_step(step), PipelinePosition(path=current_path)

    @staticmethod
    def _descend_to_leaf_from_loop(
        loop: LoopStep,
        loop_path: tuple[int, ...],
    ) -> tuple[PipelineAction, PipelinePosition]:
        """Descend from a LoopStep to its first leaf step."""
        step: PipelineStep = loop.steps[0]
        current_path = (*loop_path, 0)

        while isinstance(step, LoopStep):
            current_path = (*current_path, 0)
            step = step.steps[0]

        return PipelineExecutor._action_for_step(step), PipelinePosition(path=current_path)

    @classmethod
    def _advance_from(
        cls,
        pipeline: Sequence[PipelineStep],
        path: tuple[int, ...],
    ) -> tuple[PipelineAction, PipelinePosition] | None:
        """Try to advance to the next sibling step at the given nesting level.

        If we're at the end of the current step list, returns None (caller must
        handle exiting to the parent level).
        """
        if len(path) == 1:
            # Top level
            next_idx = path[0] + 1
            if next_idx >= len(pipeline):
                return None
            return cls._descend_to_leaf(pipeline, (), next_idx)

        # Inside a nested structure — find the parent LoopStep
        parent_path = path[:-1]
        current_idx = path[-1]

        # Walk to the parent step
        parent_steps: Sequence[PipelineStep] = pipeline
        for idx in parent_path[:-1]:
            s = parent_steps[idx]
            if not isinstance(s, LoopStep):
                msg = f"Expected LoopStep, got {type(s).__name__}"
                raise ValueError(msg)
            parent_steps = s.steps

        parent_step = parent_steps[parent_path[-1]]
        if not isinstance(parent_step, LoopStep):
            msg = f"Expected LoopStep, got {type(parent_step).__name__}"
            raise ValueError(msg)

        next_idx = current_idx + 1
        if next_idx < len(parent_step.steps):
            # There's a next sibling within this loop
            return cls._descend_to_leaf(parent_step.steps, parent_path, next_idx)

        # End of this loop's steps — exit the loop and advance at the parent level
        return cls._advance_from(pipeline, parent_path)

    @classmethod
    def _restart_loop(
        cls,
        pipeline: Sequence[PipelineStep],
        path: tuple[int, ...],
    ) -> tuple[PipelineAction, PipelinePosition] | None:
        """Find the nearest enclosing LoopStep and restart it.

        Returns None if there is no enclosing loop (fail at top level).
        """
        # Walk up the path to find a LoopStep
        for depth in range(len(path) - 1, 0, -1):
            candidate_path = path[:depth]
            step: PipelineStep
            steps: Sequence[PipelineStep] = pipeline
            step = steps[candidate_path[0]]
            for idx in candidate_path[1:]:
                if not isinstance(step, LoopStep):
                    break
                step = step.steps[idx]
            else:
                # We successfully walked the path — check if it points to a LoopStep
                if isinstance(step, LoopStep):
                    return cls._descend_to_leaf_from_loop(step, candidate_path)

        # Also check if the top-level step itself is a LoopStep
        if len(path) > 1:
            top_step = pipeline[path[0]]
            if isinstance(top_step, LoopStep):
                return cls._descend_to_leaf_from_loop(top_step, (path[0],))

        return None
