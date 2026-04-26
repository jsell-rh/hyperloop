"""Tests for PM intake and process-improver serial agents.

Tests the detection logic (which specs need tasks, which findings to collect)
and the wiring (that serial agents are invoked with correct prompts).
Uses InMemoryStateStore and InMemoryRuntime. No mocks.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from hyperloop.adapters.hook.process_improver import ProcessImproverHook
from hyperloop.adapters.probe import NullProbe
from hyperloop.compose import PromptComposer, load_templates_from_dir
from hyperloop.domain.model import (
    Phase,
    PhaseStep,
    Process,
    Task,
    TaskStatus,
    Verdict,
    WorkerPollStatus,
    WorkerResult,
)
from hyperloop.loop import Orchestrator
from tests.fakes.runtime import InMemoryRuntime
from tests.fakes.spec_source import FakeSpecSource
from tests.fakes.state import InMemoryStateStore

if TYPE_CHECKING:
    from hyperloop.ports.hook import CycleHook

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PASS_RESULT = WorkerResult(verdict=Verdict.PASS, detail="All tests pass")
FAIL_RESULT = WorkerResult(verdict=Verdict.FAIL, detail="Tests failed: missing null check")
FAIL_CRASH_RESULT = WorkerResult(verdict=Verdict.FAIL, detail="Agent crashed")

DEFAULT_PROCESS = Process(
    name="default",
    phases={
        "implement": PhaseStep(run="agent implementer", on_pass="verify", on_fail="implement"),
        "verify": PhaseStep(run="agent verifier", on_pass="done", on_fail="implement"),
    },
)

BASE_DIR = Path(__file__).parent.parent / "base"


def _task(
    task_id: str = "task-001",
    status: TaskStatus = TaskStatus.NOT_STARTED,
    spec_ref: str = "specs/widget.spec.md",
    deps: tuple[str, ...] = (),
    phase: Phase | None = None,
    round: int = 0,
) -> Task:
    return Task(
        id=task_id,
        title=f"Task {task_id}",
        spec_ref=spec_ref,
        status=status,
        phase=phase,
        deps=deps,
        round=round,
        branch=None,
        pr=None,
    )


def _make_orchestrator(
    state: InMemoryStateStore,
    runtime: InMemoryRuntime,
    composer: PromptComposer | None = None,
    max_task_rounds: int = 50,
    spec_source: FakeSpecSource | None = None,
) -> Orchestrator:
    probe = NullProbe()
    hooks: list[CycleHook] = []
    if composer is not None:
        hooks.append(ProcessImproverHook(runtime, composer, probe))
    return Orchestrator(
        state=state,
        runtime=runtime,
        process=DEFAULT_PROCESS,
        max_workers=6,
        max_task_rounds=max_task_rounds,
        hooks=hooks,
        composer=composer,
        spec_source=spec_source,
        poll_interval=0,
        probe=probe,
    )


# ---------------------------------------------------------------------------
# Unprocessed specs detection
# ---------------------------------------------------------------------------


class TestUnprocessedSpecs:
    """_unprocessed_specs returns specs that have no corresponding task."""

    def test_spec_with_no_task_is_unprocessed(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.set_file("specs/widget.spec.md", "Widget spec content")

        orch = _make_orchestrator(state, runtime)
        unprocessed = orch._unprocessed_specs()

        assert unprocessed == ["specs/widget.spec.md"]

    def test_spec_with_matching_task_is_not_unprocessed(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.set_file("specs/widget.spec.md", "Widget spec content")
        state.add_task(_task(spec_ref="specs/widget.spec.md"))

        orch = _make_orchestrator(state, runtime)
        unprocessed = orch._unprocessed_specs()

        assert unprocessed == []

    def test_multiple_specs_mixed_coverage(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.set_file("specs/widget.spec.md", "Widget spec")
        state.set_file("specs/api.spec.md", "API spec")
        state.set_file("specs/auth.spec.md", "Auth spec")
        state.add_task(_task(task_id="task-001", spec_ref="specs/widget.spec.md"))

        orch = _make_orchestrator(state, runtime)
        unprocessed = orch._unprocessed_specs()

        assert unprocessed == ["specs/api.spec.md", "specs/auth.spec.md"]

    def test_no_specs_returns_empty(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()

        orch = _make_orchestrator(state, runtime)
        unprocessed = orch._unprocessed_specs()

        assert unprocessed == []

    def test_nested_spec_files_are_found(self) -> None:
        """Spec files in subdirectories (specs/iam/*.spec.md) are detected."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.set_file("specs/widget.spec.md", "Widget spec")
        state.set_file("specs/iam/tenants.spec.md", "Tenants spec")
        state.set_file("specs/tasks/task-001.md", "Not a spec file")

        orch = _make_orchestrator(state, runtime)
        unprocessed = orch._unprocessed_specs()

        assert unprocessed == ["specs/iam/tenants.spec.md", "specs/widget.spec.md"]


# ---------------------------------------------------------------------------
# Collect cycle findings
# ---------------------------------------------------------------------------


class TestCollectCycleFindings:
    """_collect_cycle_findings aggregates failure details from reaped results."""

    def test_collects_fail_verdict(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        orch = _make_orchestrator(state, runtime)

        results: dict[str, WorkerResult] = {
            "task-001": FAIL_RESULT,
        }
        text = orch._collect_cycle_findings(results)

        assert "task-001" in text
        assert "missing null check" in text

    def test_ignores_pass_verdict(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        orch = _make_orchestrator(state, runtime)

        results: dict[str, WorkerResult] = {
            "task-001": PASS_RESULT,
        }
        text = orch._collect_cycle_findings(results)

        assert text == ""

    def test_collects_multiple_failures(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        orch = _make_orchestrator(state, runtime)

        results: dict[str, WorkerResult] = {
            "task-001": FAIL_RESULT,
            "task-002": FAIL_CRASH_RESULT,
            "task-003": PASS_RESULT,
        }
        text = orch._collect_cycle_findings(results)

        assert "task-001" in text
        assert "task-002" in text
        assert "task-003" not in text

    def test_empty_results_returns_empty_string(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        orch = _make_orchestrator(state, runtime)

        text = orch._collect_cycle_findings({})

        assert text == ""


# ---------------------------------------------------------------------------
# PM Intake wiring
# ---------------------------------------------------------------------------


class TestPMIntake:
    """PM intake runs when unprocessed specs exist and composer is configured."""

    def test_intake_runs_pm_when_unprocessed_specs_exist(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.set_file("specs/widget.spec.md", "Widget spec content")

        composer = PromptComposer(templates=load_templates_from_dir(BASE_DIR), state=state)
        orch = _make_orchestrator(state, runtime, composer=composer)

        orch.run_cycle()

        pm_runs = [r for r in runtime.serial_runs if r.role == "pm"]
        assert len(pm_runs) == 1
        assert "specs/widget.spec.md" in pm_runs[0].prompt

    def test_intake_skips_when_all_specs_covered(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.set_file("specs/widget.spec.md", "Widget spec content")
        state.add_task(_task(spec_ref="specs/widget.spec.md"))

        composer = PromptComposer(templates=load_templates_from_dir(BASE_DIR), state=state)
        orch = _make_orchestrator(state, runtime, composer=composer)

        orch.run_cycle()

        pm_runs = [r for r in runtime.serial_runs if r.role == "pm"]
        assert len(pm_runs) == 0

    def test_intake_skips_when_no_composer(self) -> None:
        """Without a composer, intake is a no-op."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.set_file("specs/widget.spec.md", "Widget spec content")

        orch = _make_orchestrator(state, runtime, composer=None)

        orch.run_cycle()

        assert len(runtime.serial_runs) == 0

    def test_intake_lists_all_unprocessed_specs_in_prompt(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.set_file("specs/api.spec.md", "API spec")
        state.set_file("specs/auth.spec.md", "Auth spec")
        state.set_file("specs/widget.spec.md", "Widget spec")
        state.add_task(_task(spec_ref="specs/widget.spec.md"))

        composer = PromptComposer(templates=load_templates_from_dir(BASE_DIR), state=state)
        orch = _make_orchestrator(state, runtime, composer=composer)

        orch.run_cycle()

        pm_runs = [r for r in runtime.serial_runs if r.role == "pm"]
        assert len(pm_runs) == 1
        prompt = pm_runs[0].prompt
        assert "specs/api.spec.md" in prompt
        assert "specs/auth.spec.md" in prompt
        assert "specs/widget.spec.md" not in prompt  # already covered

    def test_intake_retriggers_on_task_failure(self) -> None:
        """Intake fires when a task fails, even if all specs are covered."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.set_file("specs/widget.spec.md", "Widget spec content")
        state.add_task(_task(spec_ref="specs/widget.spec.md"))

        composer = PromptComposer(templates=load_templates_from_dir(BASE_DIR), state=state)
        orch = _make_orchestrator(state, runtime, composer=composer, max_task_rounds=50)

        # Cycle 1: spawn implementer (no intake -- all specs covered)
        orch.run_cycle()
        pm_runs_before = [r for r in runtime.serial_runs if r.role == "pm"]
        assert len(pm_runs_before) == 0

        # Implementer passes -> verifier
        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)
        runtime.set_result("task-001", PASS_RESULT)
        orch.run_cycle()

        # Verifier fails -> should set failure flag
        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)
        runtime.set_result("task-001", FAIL_RESULT)
        orch.run_cycle()

        # Intake should have run because of the failure
        pm_runs_after = [r for r in runtime.serial_runs if r.role == "pm"]
        assert len(pm_runs_after) == 1

    def test_intake_failure_flag_resets_after_intake(self) -> None:
        """The failure flag is reset after intake runs, preventing duplicate runs."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.set_file("specs/widget.spec.md", "Widget spec content")
        state.add_task(_task(spec_ref="specs/widget.spec.md"))

        composer = PromptComposer(templates=load_templates_from_dir(BASE_DIR), state=state)
        orch = _make_orchestrator(state, runtime, composer=composer, max_task_rounds=50)

        # Cycle 1: spawn implementer
        orch.run_cycle()

        # Implementer passes -> verifier
        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)
        runtime.set_result("task-001", PASS_RESULT)
        orch.run_cycle()

        # Verifier fails -> triggers intake
        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)
        runtime.set_result("task-001", FAIL_RESULT)
        orch.run_cycle()

        pm_runs_after_fail = [r for r in runtime.serial_runs if r.role == "pm"]
        assert len(pm_runs_after_fail) == 1

        # Reset runtime so the re-spawned implementer is still "running"
        runtime.set_poll_status("task-001", WorkerPollStatus.RUNNING)

        # Next cycle: no new failures, no unprocessed specs -> intake should NOT run again
        orch.run_cycle()
        pm_runs_next = [r for r in runtime.serial_runs if r.role == "pm"]
        assert len(pm_runs_next) == 1  # still 1, not 2


# ---------------------------------------------------------------------------
# SHA pinning
# ---------------------------------------------------------------------------


class TestSpecRefPinning:
    """After intake, new tasks get spec_ref pinned to the current SHA."""

    def test_new_tasks_get_sha_pinned_spec_ref(self) -> None:
        """Tasks created by the PM agent have @sha appended to spec_ref."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.set_file("specs/widget.spec.md", "Widget spec content")

        spec_source = FakeSpecSource()
        spec_source.set_version("abc123")

        composer = PromptComposer(templates=load_templates_from_dir(BASE_DIR), state=state)

        def create_task_during_intake(prompt: str) -> bool:
            state.add_task(_task(task_id="task-new", spec_ref="specs/widget.spec.md"))
            return True

        runtime.set_serial_callback("pm", create_task_during_intake)
        orch = _make_orchestrator(state, runtime, composer=composer, spec_source=spec_source)

        orch.run_cycle()

        task = state.get_task("task-new")
        assert task.spec_ref == "specs/widget.spec.md@abc123"

    def test_existing_tasks_not_re_pinned(self) -> None:
        """Tasks that existed before intake are not modified."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.set_file("specs/new.spec.md", "New spec")
        state.add_task(_task(task_id="task-old", spec_ref="specs/old.md@oldsha"))

        spec_source = FakeSpecSource()
        spec_source.set_version("newsha")

        composer = PromptComposer(templates=load_templates_from_dir(BASE_DIR), state=state)
        orch = _make_orchestrator(state, runtime, composer=composer, spec_source=spec_source)

        orch.run_cycle()

        task = state.get_task("task-old")
        assert task.spec_ref == "specs/old.md@oldsha"

    def test_already_pinned_tasks_not_double_pinned(self) -> None:
        """If PM writes spec_ref with @sha already, don't append again."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.set_file("specs/widget.spec.md", "Widget spec")

        spec_source = FakeSpecSource()
        spec_source.set_version("abc123")

        composer = PromptComposer(templates=load_templates_from_dir(BASE_DIR), state=state)

        def create_pinned_task(prompt: str) -> bool:
            state.add_task(
                _task(task_id="task-pre-pinned", spec_ref="specs/widget.spec.md@already")
            )
            return True

        runtime.set_serial_callback("pm", create_pinned_task)
        orch = _make_orchestrator(state, runtime, composer=composer, spec_source=spec_source)

        orch.run_cycle()

        task = state.get_task("task-pre-pinned")
        assert task.spec_ref == "specs/widget.spec.md@already"

    def test_no_pinning_without_spec_source(self) -> None:
        """Without a spec_source, spec_ref stays bare (no crash)."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.set_file("specs/widget.spec.md", "Widget spec")

        composer = PromptComposer(templates=load_templates_from_dir(BASE_DIR), state=state)

        def create_task(prompt: str) -> bool:
            state.add_task(_task(task_id="task-bare", spec_ref="specs/widget.spec.md"))
            return True

        runtime.set_serial_callback("pm", create_task)
        orch = _make_orchestrator(state, runtime, composer=composer)

        orch.run_cycle()

        task = state.get_task("task-bare")
        assert task.spec_ref == "specs/widget.spec.md"

    def test_unprocessed_specs_recognizes_pinned_refs(self) -> None:
        """A task with spec_ref 'specs/widget.spec.md@sha' covers 'specs/widget.spec.md'."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.set_file("specs/widget.spec.md", "Widget spec")
        state.add_task(_task(spec_ref="specs/widget.spec.md@abc123"))

        orch = _make_orchestrator(state, runtime)
        unprocessed = orch._unprocessed_specs()

        assert unprocessed == []


# ---------------------------------------------------------------------------
# Process-improver wiring
# ---------------------------------------------------------------------------


class TestProcessImprover:
    """Process-improver runs when there are failures this cycle."""

    def test_process_improver_runs_on_failure(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task())
        state.set_file("specs/widget.spec.md", "Widget spec")

        composer = PromptComposer(templates=load_templates_from_dir(BASE_DIR), state=state)
        orch = _make_orchestrator(state, runtime, composer=composer, max_task_rounds=50)

        # Cycle 1: spawn implementer
        orch.run_cycle()

        # Implementer passes -> verifier
        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)
        runtime.set_result("task-001", PASS_RESULT)
        orch.run_cycle()

        # Verifier fails -> should trigger process-improver
        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)
        runtime.set_result("task-001", FAIL_RESULT)
        orch.run_cycle()

        pi_runs = [r for r in runtime.serial_runs if r.role == "process-improver"]
        assert len(pi_runs) == 1
        assert "missing null check" in pi_runs[0].prompt

    def test_process_improver_skips_on_all_pass(self) -> None:
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task())
        state.set_file("specs/widget.spec.md", "Widget spec")

        composer = PromptComposer(templates=load_templates_from_dir(BASE_DIR), state=state)
        orch = _make_orchestrator(state, runtime, composer=composer)

        # Cycle 1: spawn implementer
        orch.run_cycle()

        # Implementer passes -> verifier
        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)
        runtime.set_result("task-001", PASS_RESULT)
        orch.run_cycle()

        # Verifier passes -> no process-improver
        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)
        runtime.set_result("task-001", PASS_RESULT)
        orch.run_cycle()

        pi_runs = [r for r in runtime.serial_runs if r.role == "process-improver"]
        assert len(pi_runs) == 0

    def test_process_improver_skips_when_no_composer(self) -> None:
        """Without a composer, process-improver is a no-op."""
        state = InMemoryStateStore()
        runtime = InMemoryRuntime()
        state.add_task(_task())

        orch = _make_orchestrator(state, runtime, composer=None)

        # Cycle 1: spawn implementer
        orch.run_cycle()

        # Implementer passes -> verifier
        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)
        runtime.set_result("task-001", PASS_RESULT)
        orch.run_cycle()

        # Verifier fails -> should not crash without composer
        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)
        runtime.set_result("task-001", FAIL_RESULT)
        orch.run_cycle()


# ---------------------------------------------------------------------------
# InMemoryRuntime.run_serial contract
# ---------------------------------------------------------------------------


class TestInMemoryRuntimeSerial:
    """InMemoryRuntime.run_serial records invocations and supports callbacks."""

    def test_records_runs(self) -> None:
        runtime = InMemoryRuntime()
        runtime.run_serial("pm", "prompt text")

        assert len(runtime.serial_runs) == 1
        assert runtime.serial_runs[0].role == "pm"
        assert runtime.serial_runs[0].prompt == "prompt text"

    def test_default_success(self) -> None:
        runtime = InMemoryRuntime()
        assert runtime.run_serial("pm", "prompt") is True

    def test_configurable_failure(self) -> None:
        runtime = InMemoryRuntime()
        runtime.set_serial_default_success(False)
        assert runtime.run_serial("pm", "prompt") is False

    def test_callback_for_role(self) -> None:
        runtime = InMemoryRuntime()
        callback_called_with: list[str] = []

        def callback(prompt: str) -> bool:
            callback_called_with.append(prompt)
            return True

        runtime.set_serial_callback("pm", callback)
        runtime.run_serial("pm", "my prompt")

        assert callback_called_with == ["my prompt"]


# ---------------------------------------------------------------------------
# StateStore.list_files contract
# ---------------------------------------------------------------------------


class TestInMemoryListFiles:
    """InMemoryStateStore.list_files matches glob patterns against stored files."""

    def test_matches_top_level_specs(self) -> None:
        state = InMemoryStateStore()
        state.set_file("specs/widget.spec.md", "content")
        state.set_file("specs/api.spec.md", "content")

        result = state.list_files("specs/*.md")
        assert result == ["specs/api.spec.md", "specs/widget.spec.md"]

    def test_does_not_match_subdirectory_files(self) -> None:
        state = InMemoryStateStore()
        state.set_file("specs/widget.spec.md", "content")
        state.set_file("specs/tasks/task-001.md", "content")

        result = state.list_files("specs/*.md")
        assert result == ["specs/widget.spec.md"]

    def test_empty_store_returns_empty_list(self) -> None:
        state = InMemoryStateStore()
        assert state.list_files("specs/*.md") == []
