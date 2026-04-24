"""Contract tests for InMemoryStateStore and InMemoryRuntime fakes.

These tests verify the fakes implement the full port contract correctly.
They are structured so they could also be run against real adapters later.
"""

from __future__ import annotations

from hyperloop.domain.model import (
    Phase,
    Signal,
    SignalStatus,
    StepOutcome,
    StepResult,
    Task,
    TaskStatus,
    Verdict,
    WorkerPollStatus,
    WorkerResult,
)
from tests.fakes.channel import FakeChannelPort
from tests.fakes.runtime import InMemoryRuntime
from tests.fakes.signal import FakeSignalPort
from tests.fakes.state import InMemoryStateStore
from tests.fakes.step_executor import FakeStepExecutor

# ---------------------------------------------------------------------------
# InMemoryStateStore contract tests
# ---------------------------------------------------------------------------


class TestStateStoreGetTask:
    def test_store_and_retrieve_task(self):
        store = InMemoryStateStore()
        task = Task(
            id="task-001",
            title="Implement widget",
            spec_ref="specs/widget.md",
            status=TaskStatus.NOT_STARTED,
            phase=None,
            deps=(),
            round=0,
            branch=None,
            pr=None,
        )
        store.add_task(task)

        retrieved = store.get_task("task-001")
        assert retrieved.id == "task-001"
        assert retrieved.title == "Implement widget"
        assert retrieved.spec_ref == "specs/widget.md"
        assert retrieved.status == TaskStatus.NOT_STARTED
        assert retrieved.phase is None
        assert retrieved.deps == ()
        assert retrieved.round == 0
        assert retrieved.branch is None
        assert retrieved.pr is None

    def test_get_task_raises_on_missing(self):
        store = InMemoryStateStore()
        try:
            store.get_task("nonexistent")
            raise AssertionError("Expected KeyError")
        except KeyError:
            pass


class TestStateStoreTransition:
    def test_transition_updates_status_and_phase(self):
        store = InMemoryStateStore()
        task = Task(
            id="task-001",
            title="Implement widget",
            spec_ref="specs/widget.md",
            status=TaskStatus.NOT_STARTED,
            phase=None,
            deps=(),
            round=0,
            branch=None,
            pr=None,
        )
        store.add_task(task)

        store.transition_task("task-001", TaskStatus.IN_PROGRESS, Phase("implementer"))

        updated = store.get_task("task-001")
        assert updated.status == TaskStatus.IN_PROGRESS
        assert updated.phase == Phase("implementer")

    def test_transition_preserves_other_fields(self):
        store = InMemoryStateStore()
        task = Task(
            id="task-002",
            title="Build API",
            spec_ref="specs/api.md",
            status=TaskStatus.NOT_STARTED,
            phase=None,
            deps=("task-001",),
            round=3,
            branch="hyperloop/task-002",
            pr="https://github.com/org/repo/pull/42",
        )
        store.add_task(task)

        store.transition_task("task-002", TaskStatus.COMPLETED, None)

        updated = store.get_task("task-002")
        assert updated.title == "Build API"
        assert updated.spec_ref == "specs/api.md"
        assert updated.deps == ("task-001",)
        assert updated.round == 3
        assert updated.branch == "hyperloop/task-002"
        assert updated.pr == "https://github.com/org/repo/pull/42"


class TestStateStoreReview:
    def test_store_review_then_get_findings(self):
        store = InMemoryStateStore()
        task = Task(
            id="task-001",
            title="Widget",
            spec_ref="specs/widget.md",
            status=TaskStatus.IN_PROGRESS,
            phase=Phase("verifier"),
            deps=(),
            round=1,
            branch=None,
            pr=None,
        )
        store.add_task(task)

        store.store_review("task-001", 1, "verifier", "fail", "Test X failed: expected 3, got 5")
        findings = store.get_findings("task-001")
        assert "Test X failed: expected 3, got 5" in findings

    def test_get_findings_returns_latest_review(self):
        store = InMemoryStateStore()
        task = Task(
            id="task-001",
            title="Widget",
            spec_ref="specs/widget.md",
            status=TaskStatus.IN_PROGRESS,
            phase=Phase("verifier"),
            deps=(),
            round=2,
            branch=None,
            pr=None,
        )
        store.add_task(task)

        store.store_review("task-001", 1, "verifier", "fail", "Round 1 failed")
        store.store_review("task-001", 2, "verifier", "fail", "Round 2 failed")

        findings = store.get_findings("task-001")
        assert "Round 2 failed" in findings

    def test_get_findings_empty_when_no_reviews(self):
        store = InMemoryStateStore()
        task = Task(
            id="task-001",
            title="Widget",
            spec_ref="specs/widget.md",
            status=TaskStatus.NOT_STARTED,
            phase=None,
            deps=(),
            round=0,
            branch=None,
            pr=None,
        )
        store.add_task(task)

        findings = store.get_findings("task-001")
        assert findings == ""


class TestStateStoreEpoch:
    def test_get_set_roundtrip(self):
        store = InMemoryStateStore()
        store.set_epoch("intake", "abc123")
        assert store.get_epoch("intake") == "abc123"

    def test_get_returns_empty_for_unset_key(self):
        store = InMemoryStateStore()
        assert store.get_epoch("nonexistent") == ""

    def test_set_overwrites_previous_value(self):
        store = InMemoryStateStore()
        store.set_epoch("intake", "v1")
        store.set_epoch("intake", "v2")
        assert store.get_epoch("intake") == "v2"


class TestStateStoreReadFile:
    def test_read_existing_file(self):
        store = InMemoryStateStore()
        store.set_file("specs/prompts/implementer.md", "You are an implementer.")

        content = store.read_file("specs/prompts/implementer.md")
        assert content == "You are an implementer."

    def test_read_missing_file_returns_none(self):
        store = InMemoryStateStore()
        assert store.read_file("nonexistent.md") is None


class TestStateStorePersist:
    def test_persist_records_message(self):
        store = InMemoryStateStore()
        store.persist("feat: update task-001 status")
        assert "feat: update task-001 status" in store.committed_messages


class TestStateStoreGetWorld:
    def test_returns_snapshot_of_all_tasks(self):
        store = InMemoryStateStore()
        task1 = Task(
            id="task-001",
            title="Widget",
            spec_ref="specs/widget.md",
            status=TaskStatus.NOT_STARTED,
            phase=None,
            deps=(),
            round=0,
            branch=None,
            pr=None,
        )
        task2 = Task(
            id="task-002",
            title="API",
            spec_ref="specs/api.md",
            status=TaskStatus.IN_PROGRESS,
            phase=Phase("implementer"),
            deps=("task-001",),
            round=1,
            branch="hyperloop/task-002",
            pr=None,
        )
        store.add_task(task1)
        store.add_task(task2)
        store.set_epoch("intake", "abc")

        world = store.get_world()
        assert len(world.tasks) == 2
        assert "task-001" in world.tasks
        assert "task-002" in world.tasks
        assert world.tasks["task-001"].status == TaskStatus.NOT_STARTED
        assert world.tasks["task-002"].phase == Phase("implementer")
        assert world.epoch == "abc"

    def test_empty_world(self):
        store = InMemoryStateStore()
        world = store.get_world()
        assert len(world.tasks) == 0
        assert world.epoch == ""


# ---------------------------------------------------------------------------
# InMemoryRuntime contract tests
# ---------------------------------------------------------------------------


class TestRuntimeSpawnAndPoll:
    def test_spawn_returns_handle(self):
        runtime = InMemoryRuntime()
        handle = runtime.spawn("task-001", "implementer", "Do the work", "hyperloop/task-001")

        assert handle.task_id == "task-001"
        assert handle.role == "implementer"

    def test_poll_returns_running_by_default(self):
        runtime = InMemoryRuntime()
        handle = runtime.spawn("task-001", "implementer", "Do the work", "hyperloop/task-001")

        assert runtime.poll(handle) == WorkerPollStatus.RUNNING

    def test_poll_returns_configured_status(self):
        runtime = InMemoryRuntime()
        handle = runtime.spawn("task-001", "implementer", "Do the work", "hyperloop/task-001")

        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)
        assert runtime.poll(handle) == WorkerPollStatus.DONE


class TestRuntimeReap:
    def test_full_lifecycle_spawn_poll_reap(self):
        runtime = InMemoryRuntime()
        handle = runtime.spawn("task-001", "implementer", "Do the work", "hyperloop/task-001")

        # Worker is running
        assert runtime.poll(handle) == WorkerPollStatus.RUNNING

        # Worker finishes
        expected_result = WorkerResult(
            verdict=Verdict.PASS,
            detail="All tests pass",
        )
        runtime.set_result("task-001", expected_result)
        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)

        assert runtime.poll(handle) == WorkerPollStatus.DONE

        # Reap the result
        result = runtime.reap(handle)
        assert result.verdict == Verdict.PASS
        assert result.detail == "All tests pass"

    def test_reap_with_failure(self):
        runtime = InMemoryRuntime()
        handle = runtime.spawn("task-001", "verifier", "Verify the work", "hyperloop/task-001")

        result = WorkerResult(
            verdict=Verdict.FAIL,
            detail="3 tests failed",
        )
        runtime.set_result("task-001", result)
        runtime.set_poll_status("task-001", WorkerPollStatus.DONE)

        reaped = runtime.reap(handle)
        assert reaped.verdict == Verdict.FAIL


class TestRuntimeCancel:
    def test_cancel_marks_worker_cancelled(self):
        runtime = InMemoryRuntime()
        handle = runtime.spawn("task-001", "implementer", "Do the work", "hyperloop/task-001")

        runtime.cancel(handle)
        assert runtime.poll(handle) == WorkerPollStatus.FAILED


class TestRuntimeFindOrphan:
    def test_find_orphan_returns_handle_for_active_worker(self):
        runtime = InMemoryRuntime()
        handle = runtime.spawn("task-001", "implementer", "Do the work", "hyperloop/task-001")

        orphan = runtime.find_orphan("task-001", "hyperloop/task-001")
        assert orphan is not None
        assert orphan.task_id == handle.task_id

    def test_find_orphan_returns_none_after_reap(self):
        runtime = InMemoryRuntime()
        handle = runtime.spawn("task-001", "implementer", "Do the work", "hyperloop/task-001")

        result = WorkerResult(verdict=Verdict.PASS, detail="ok")
        runtime.set_result("task-001", result)
        runtime.reap(handle)

        orphan = runtime.find_orphan("task-001", "hyperloop/task-001")
        assert orphan is None

    def test_find_orphan_returns_none_after_cancel(self):
        runtime = InMemoryRuntime()
        handle = runtime.spawn("task-001", "implementer", "Do the work", "hyperloop/task-001")

        runtime.cancel(handle)

        orphan = runtime.find_orphan("task-001", "hyperloop/task-001")
        assert orphan is None

    def test_find_orphan_returns_none_for_unknown_task(self):
        runtime = InMemoryRuntime()
        orphan = runtime.find_orphan("task-999", "hyperloop/task-999")
        assert orphan is None


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _task(task_id: str = "task-001") -> Task:
    return Task(
        id=task_id,
        title="Test",
        spec_ref="specs/test.md",
        status=TaskStatus.IN_PROGRESS,
        phase=None,
        deps=(),
        round=1,
        branch="hyperloop/task-001",
        pr=None,
    )


# ---------------------------------------------------------------------------
# FakeStepExecutor basic tests
# ---------------------------------------------------------------------------


class TestFakeStepExecutor:
    def test_construct_and_execute(self) -> None:
        executor = FakeStepExecutor()
        result = executor.execute(_task(), "merge", {})
        assert result.outcome == StepOutcome.ADVANCE
        assert result.detail == "OK"

    def test_configure_and_retrieve(self) -> None:
        executor = FakeStepExecutor()
        fail_result = StepResult(outcome=StepOutcome.RETRY, detail="fail")
        executor.set_result("task-001", "lint", fail_result)

        result = executor.execute(_task(), "lint", {})
        assert result.outcome == StepOutcome.RETRY

    def test_records_calls(self) -> None:
        executor = FakeStepExecutor()
        executor.execute(_task(), "merge", {"force": True})
        assert len(executor.executed) == 1
        assert executor.executed[0] == ("task-001", "merge", {"force": True})


# ---------------------------------------------------------------------------
# FakeSignalPort basic tests
# ---------------------------------------------------------------------------


class TestFakeSignalPort:
    def test_construct_and_check(self) -> None:
        port = FakeSignalPort()
        signal = port.check(_task(), "review", {})
        assert signal.status == SignalStatus.PENDING

    def test_configure_and_retrieve(self) -> None:
        port = FakeSignalPort()
        port.set_signal("task-001", "review", Signal(status=SignalStatus.APPROVED, message="ok"))

        signal = port.check(_task(), "review", {})
        assert signal.status == SignalStatus.APPROVED

    def test_records_calls(self) -> None:
        port = FakeSignalPort()
        port.check(_task(), "ci", {"verbose": True})
        assert len(port.checked) == 1
        assert port.checked[0] == ("task-001", "ci", {"verbose": True})


# ---------------------------------------------------------------------------
# FakeChannelPort basic tests
# ---------------------------------------------------------------------------


class TestFakeChannelPort:
    def test_construct(self) -> None:
        channel = FakeChannelPort()
        assert channel.gate_blocked_calls == []
        assert channel.task_errored_calls == []
        assert channel.worker_crashed_calls == []

    def test_gate_blocked(self) -> None:
        channel = FakeChannelPort()
        channel.gate_blocked(task=_task(), signal_name="review")
        assert len(channel.gate_blocked_calls) == 1

    def test_task_errored(self) -> None:
        channel = FakeChannelPort()
        channel.task_errored(task=_task(), detail="boom")
        assert channel.task_errored_calls[0] == ("task-001", "boom")

    def test_worker_crashed(self) -> None:
        channel = FakeChannelPort()
        channel.worker_crashed(task=_task(), role="impl", branch="b")
        assert channel.worker_crashed_calls[0] == ("task-001", "impl", "b")
