"""Tests for the pipeline executor — class that advances through pipeline steps.

The PipelineExecutor takes a pipeline definition at construction, and given a
current position and worker result, returns the next action to take and the new position.
"""

from hyperloop.domain.model import (
    ActionStep,
    GateStep,
    LoopStep,
    PipelinePosition,
    RoleStep,
    Verdict,
    WorkerResult,
)
from hyperloop.domain.pipeline import (
    PerformAction,
    PipelineComplete,
    PipelineExecutor,
    PipelineFailed,
    SpawnRole,
    WaitForGate,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PASS = WorkerResult(verdict=Verdict.PASS, findings=0, detail="ok")
FAIL = WorkerResult(verdict=Verdict.FAIL, findings=1, detail="failed")


def pos(*indices):
    return PipelinePosition(path=indices)


def role(name):
    return RoleStep(role=name, on_pass=None, on_fail=None)


# ---------------------------------------------------------------------------
# Simple sequence: (implementer, verifier, merge-pr)
# ---------------------------------------------------------------------------


class TestSimpleSequence:
    """Pipeline with no loops: role -> role -> action."""

    pipeline = (role("implementer"), role("verifier"), ActionStep(action="merge-pr"))
    executor = PipelineExecutor(pipeline)

    def test_start_spawns_first_role(self):
        """At step 0 with no result, spawn implementer."""
        action, new_pos = self.executor.next_action(pos(0), result=None)
        assert action == SpawnRole(role="implementer")
        assert new_pos == pos(0)

    def test_pass_advances_to_next_role(self):
        """At step 0 with pass, advance to step 1 and spawn verifier."""
        action, new_pos = self.executor.next_action(pos(0), result=PASS)
        assert action == SpawnRole(role="verifier")
        assert new_pos == pos(1)

    def test_verifier_pass_advances_to_action(self):
        """At step 1 with pass, advance to step 2 and perform merge."""
        action, new_pos = self.executor.next_action(pos(1), result=PASS)
        assert action == PerformAction(action="merge-pr")
        assert new_pos == pos(2)

    def test_action_pass_completes_pipeline(self):
        """At step 2 (action) with pass, pipeline is complete."""
        action, _new_pos = self.executor.next_action(pos(2), result=PASS)
        assert action == PipelineComplete()

    def test_fail_outside_loop_fails_pipeline(self):
        """At step 1 with fail, no enclosing loop, pipeline fails."""
        action, _new_pos = self.executor.next_action(pos(1), result=FAIL)
        assert isinstance(action, PipelineFailed)


# ---------------------------------------------------------------------------
# Loop: (loop((implementer, verifier)), merge-pr)
# ---------------------------------------------------------------------------


class TestLoop:
    """Pipeline with a simple loop wrapping two role steps."""

    pipeline = (
        LoopStep(steps=(role("implementer"), role("verifier"))),
        ActionStep(action="merge-pr"),
    )
    executor = PipelineExecutor(pipeline)

    def test_start_enters_loop_at_first_step(self):
        """At loop start with no result, spawn implementer (inside loop)."""
        action, new_pos = self.executor.next_action(pos(0, 0), result=None)
        assert action == SpawnRole(role="implementer")
        assert new_pos == pos(0, 0)

    def test_implementer_pass_advances_to_verifier(self):
        """Inside loop, implementer pass advances to verifier."""
        action, new_pos = self.executor.next_action(pos(0, 0), result=PASS)
        assert action == SpawnRole(role="verifier")
        assert new_pos == pos(0, 1)

    def test_verifier_pass_exits_loop(self):
        """Inside loop, verifier pass exits loop and advances to merge."""
        action, new_pos = self.executor.next_action(pos(0, 1), result=PASS)
        assert action == PerformAction(action="merge-pr")
        assert new_pos == pos(1)

    def test_verifier_fail_restarts_loop(self):
        """Inside loop, verifier fail restarts loop from implementer."""
        action, new_pos = self.executor.next_action(pos(0, 1), result=FAIL)
        assert action == SpawnRole(role="implementer")
        assert new_pos == pos(0, 0)

    def test_implementer_fail_restarts_loop(self):
        """Inside loop, implementer fail also restarts loop from beginning."""
        action, new_pos = self.executor.next_action(pos(0, 0), result=FAIL)
        assert action == SpawnRole(role="implementer")
        assert new_pos == pos(0, 0)


# ---------------------------------------------------------------------------
# Nested loops:
# (loop((loop((implementer, verifier)), security)), merge-pr)
# ---------------------------------------------------------------------------


class TestNestedLoops:
    """Pipeline with loops nested two levels deep."""

    pipeline = (
        LoopStep(
            steps=(
                LoopStep(steps=(role("implementer"), role("verifier"))),
                role("security"),
            ),
        ),
        ActionStep(action="merge-pr"),
    )
    executor = PipelineExecutor(pipeline)

    def test_start_at_inner_implementer(self):
        action, new_pos = self.executor.next_action(pos(0, 0, 0), result=None)
        assert action == SpawnRole(role="implementer")
        assert new_pos == pos(0, 0, 0)

    def test_inner_implementer_pass_to_verifier(self):
        action, new_pos = self.executor.next_action(pos(0, 0, 0), result=PASS)
        assert action == SpawnRole(role="verifier")
        assert new_pos == pos(0, 0, 1)

    def test_inner_verifier_fail_restarts_inner_loop(self):
        """Verifier fail in inner loop restarts inner loop (back to implementer)."""
        action, new_pos = self.executor.next_action(pos(0, 0, 1), result=FAIL)
        assert action == SpawnRole(role="implementer")
        assert new_pos == pos(0, 0, 0)

    def test_inner_verifier_pass_exits_inner_advances_to_security(self):
        """Verifier pass exits inner loop, advances to security."""
        action, new_pos = self.executor.next_action(pos(0, 0, 1), result=PASS)
        assert action == SpawnRole(role="security")
        assert new_pos == pos(0, 1)

    def test_security_fail_restarts_outer_loop(self):
        """Security fail restarts outer loop (back to inner loop start = implementer)."""
        action, new_pos = self.executor.next_action(pos(0, 1), result=FAIL)
        assert action == SpawnRole(role="implementer")
        assert new_pos == pos(0, 0, 0)

    def test_security_pass_exits_both_loops_to_merge(self):
        """Security pass exits outer loop, advances to merge."""
        action, new_pos = self.executor.next_action(pos(0, 1), result=PASS)
        assert action == PerformAction(action="merge-pr")
        assert new_pos == pos(1)

    def test_merge_pass_completes_pipeline(self):
        action, _new_pos = self.executor.next_action(pos(1), result=PASS)
        assert action == PipelineComplete()


# ---------------------------------------------------------------------------
# Gate: (implementer, gate(human-pr-approval), merge-pr)
# ---------------------------------------------------------------------------


class TestGate:
    """Pipeline with a gate step that blocks until an external signal."""

    pipeline = (
        role("implementer"),
        GateStep(gate="human-pr-approval"),
        ActionStep(action="merge-pr"),
    )
    executor = PipelineExecutor(pipeline)

    def test_implementer_pass_advances_to_gate(self):
        """After implementer passes, advance to gate and return WaitForGate."""
        action, new_pos = self.executor.next_action(pos(0), result=PASS)
        assert action == WaitForGate(gate="human-pr-approval")
        assert new_pos == pos(1)

    def test_at_gate_no_result_returns_wait(self):
        """At gate with no result (not yet signaled), return WaitForGate."""
        action, new_pos = self.executor.next_action(pos(1), result=None)
        assert action == WaitForGate(gate="human-pr-approval")
        assert new_pos == pos(1)

    def test_gate_pass_advances_to_merge(self):
        """Gate with pass (signal received) advances to merge."""
        action, new_pos = self.executor.next_action(pos(1), result=PASS)
        assert action == PerformAction(action="merge-pr")
        assert new_pos == pos(2)


# ---------------------------------------------------------------------------
# on_pass / on_fail overrides
# ---------------------------------------------------------------------------


class TestRoutingOverrides:
    """RoleStep with explicit on_pass/on_fail routing targets."""

    pipeline = (
        RoleStep(role="implementer", on_pass="security", on_fail=None),
        role("verifier"),
        role("security"),
        ActionStep(action="merge-pr"),
    )
    executor = PipelineExecutor(pipeline)

    def test_on_pass_override_jumps_to_named_role(self):
        """Implementer with on_pass='security' skips verifier, goes to security."""
        action, new_pos = self.executor.next_action(pos(0), result=PASS)
        assert action == SpawnRole(role="security")
        assert new_pos == pos(2)

    def test_on_fail_override_jumps_to_named_role(self):
        """RoleStep with on_fail='implementer' jumps back to implementer."""
        pipeline = (
            role("implementer"),
            RoleStep(role="verifier", on_pass=None, on_fail="implementer"),
            ActionStep(action="merge-pr"),
        )
        executor = PipelineExecutor(pipeline)
        action, new_pos = executor.next_action(pos(1), result=FAIL)
        assert action == SpawnRole(role="implementer")
        assert new_pos == pos(0)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_single_action_step(self):
        """Pipeline with only an action step."""
        pipeline = (ActionStep(action="merge-pr"),)
        executor = PipelineExecutor(pipeline)
        action, new_pos = executor.next_action(pos(0), result=None)
        assert action == PerformAction(action="merge-pr")
        assert new_pos == pos(0)

    def test_action_step_no_result_performs_action(self):
        """At an action step with no result, perform the action."""
        pipeline = (ActionStep(action="merge-pr"),)
        executor = PipelineExecutor(pipeline)
        action, _new_pos = executor.next_action(pos(0), result=None)
        assert action == PerformAction(action="merge-pr")

    def test_loop_with_single_role(self):
        """Loop containing a single role restarts on fail."""
        pipeline = (LoopStep(steps=(role("implementer"),)),)
        executor = PipelineExecutor(pipeline)
        action, new_pos = executor.next_action(pos(0, 0), result=FAIL)
        assert action == SpawnRole(role="implementer")
        assert new_pos == pos(0, 0)

    def test_position_into_loop_entry(self):
        """Entering a loop for the first time — position should be inside the loop."""
        pipeline = (LoopStep(steps=(role("implementer"), role("verifier"))),)
        executor = PipelineExecutor(pipeline)
        action, new_pos = executor.next_action(pos(0, 0), result=None)
        assert action == SpawnRole(role="implementer")
        assert new_pos == pos(0, 0)
