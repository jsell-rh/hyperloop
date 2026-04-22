"""Tests for OtelProbe — OpenTelemetry trace and metric export.

Uses in-memory exporters from the OTel SDK so no collector is needed.
Skipped entirely if opentelemetry is not installed (optional dependency).
"""

from __future__ import annotations

import pytest

otel = pytest.importorskip("opentelemetry")

from opentelemetry.sdk.metrics import MeterProvider  # noqa: E402
from opentelemetry.sdk.metrics.export import InMemoryMetricReader  # noqa: E402
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)
from opentelemetry.trace import StatusCode  # noqa: E402

from hyperloop.adapters.probe.otel import OtelProbe  # noqa: E402


def _make_probe() -> tuple[OtelProbe, InMemorySpanExporter, InMemoryMetricReader]:
    """Create an OtelProbe wired to in-memory exporters for testing."""
    span_exporter = InMemorySpanExporter()
    tp = TracerProvider()
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    tp.add_span_processor(SimpleSpanProcessor(span_exporter))

    metric_reader = InMemoryMetricReader()
    mp = MeterProvider(metric_readers=[metric_reader])

    probe = OtelProbe(
        service_name="test-hyperloop",
        endpoint="http://localhost:4317",
        tracer_provider=tp,
        meter_provider=mp,
    )
    return probe, span_exporter, metric_reader


class TestWorkerLifecycleCreatesSpan:
    """worker_spawned + worker_reaped creates a span with correct attributes."""

    def test_creates_span_with_attributes(self) -> None:
        probe, exporter, _reader = _make_probe()

        probe.worker_spawned(
            task_id="task-001",
            role="implementer",
            branch="hl/task-001",
            round=1,
            cycle=3,
            spec_ref="specs/task-001.md",
        )
        probe.worker_reaped(
            task_id="task-001",
            role="implementer",
            verdict="pass",
            round=1,
            cycle=3,
            spec_ref="specs/task-001.md",
            detail="All tests pass",
            duration_s=42.5,
        )

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.name == "hyperloop.worker"
        attrs = dict(span.attributes or {})
        assert attrs["hyperloop.task_id"] == "task-001"
        assert attrs["hyperloop.role"] == "implementer"
        assert attrs["hyperloop.branch"] == "hl/task-001"
        assert attrs["hyperloop.round"] == 1
        assert attrs["hyperloop.verdict"] == "pass"
        assert attrs["hyperloop.duration_s"] == 42.5

    def test_fail_verdict_sets_error_status(self) -> None:
        probe, exporter, _reader = _make_probe()

        probe.worker_spawned(
            task_id="task-002",
            role="verifier",
            branch="hl/task-002",
            round=2,
            cycle=5,
            spec_ref="specs/task-002.md",
        )
        probe.worker_reaped(
            task_id="task-002",
            role="verifier",
            verdict="fail",
            round=2,
            cycle=5,
            spec_ref="specs/task-002.md",
            detail="Tests failed",
            duration_s=55.0,
        )

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].status.status_code == StatusCode.ERROR

    def test_pass_verdict_does_not_set_error_status(self) -> None:
        probe, exporter, _reader = _make_probe()

        probe.worker_spawned(
            task_id="task-003",
            role="implementer",
            branch="hl/task-003",
            round=1,
            cycle=1,
            spec_ref="specs/task-003.md",
        )
        probe.worker_reaped(
            task_id="task-003",
            role="implementer",
            verdict="pass",
            round=1,
            cycle=1,
            spec_ref="specs/task-003.md",
            detail="ok",
            duration_s=10.0,
        )

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].status.status_code != StatusCode.ERROR


class TestWorkerMessageAddsEvent:
    """worker_message adds span events to the active worker span."""

    def test_message_appears_as_span_event(self) -> None:
        probe, exporter, _reader = _make_probe()

        probe.worker_spawned(
            task_id="task-001",
            role="implementer",
            branch="hl/task-001",
            round=1,
            cycle=1,
            spec_ref="specs/task-001.md",
        )
        probe.worker_message(
            task_id="task-001",
            role="implementer",
            message_type="text",
            content="I will implement the feature now",
        )
        probe.worker_reaped(
            task_id="task-001",
            role="implementer",
            verdict="pass",
            round=1,
            cycle=1,
            spec_ref="specs/task-001.md",
            detail="ok",
            duration_s=20.0,
        )

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        events = spans[0].events
        assert len(events) == 1
        assert events[0].name == "text"
        event_attrs = dict(events[0].attributes or {})
        assert event_attrs["hyperloop.content"] == "I will implement the feature now"

    def test_long_content_truncated_to_200_chars(self) -> None:
        probe, exporter, _reader = _make_probe()

        probe.worker_spawned(
            task_id="task-001",
            role="implementer",
            branch="hl/task-001",
            round=1,
            cycle=1,
            spec_ref="specs/task-001.md",
        )
        long_content = "x" * 500
        probe.worker_message(
            task_id="task-001",
            role="implementer",
            message_type="tool_use",
            content=long_content,
        )
        probe.worker_reaped(
            task_id="task-001",
            role="implementer",
            verdict="pass",
            round=1,
            cycle=1,
            spec_ref="specs/task-001.md",
            detail="ok",
            duration_s=5.0,
        )

        spans = exporter.get_finished_spans()
        events = spans[0].events
        event_attrs = dict(events[0].attributes or {})
        assert len(str(event_attrs["hyperloop.content"])) == 200


class TestCycleCreatesSpan:
    """cycle_started + cycle_completed creates a span."""

    def test_creates_cycle_span(self) -> None:
        probe, exporter, _reader = _make_probe()

        probe.cycle_started(
            cycle=7,
            active_workers=3,
            not_started=2,
            in_progress=3,
            complete=1,
            failed=0,
        )
        probe.cycle_completed(
            cycle=7,
            active_workers=2,
            not_started=1,
            in_progress=2,
            complete=2,
            failed=0,
            spawned_ids=("task-001",),
            reaped_ids=("task-002",),
            duration_s=15.3,
        )

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.name == "hyperloop.cycle"
        attrs = dict(span.attributes or {})
        assert attrs["hyperloop.cycle"] == 7
        assert attrs["hyperloop.duration_s"] == 15.3


class TestMetricsRecorded:
    """Metrics are recorded correctly on probe events."""

    def test_worker_duration_histogram_recorded(self) -> None:
        probe, _exporter, reader = _make_probe()

        probe.worker_spawned(
            task_id="task-001",
            role="implementer",
            branch="hl/task-001",
            round=1,
            cycle=1,
            spec_ref="specs/task-001.md",
        )
        probe.worker_reaped(
            task_id="task-001",
            role="implementer",
            verdict="pass",
            round=1,
            cycle=1,
            spec_ref="specs/task-001.md",
            detail="ok",
            duration_s=42.5,
        )

        metrics_data = reader.get_metrics_data()
        assert metrics_data is not None
        metric_names: set[str] = set()
        for resource_metrics in metrics_data.resource_metrics:
            for scope_metrics in resource_metrics.scope_metrics:
                for metric in scope_metrics.metrics:
                    metric_names.add(metric.name)

        assert "hyperloop.worker.duration_s" in metric_names

    def test_tasks_completed_counter_incremented(self) -> None:
        probe, _exporter, reader = _make_probe()

        probe.task_completed(
            task_id="task-001",
            spec_ref="specs/task-001.md",
            total_rounds=3,
            total_cycles=5,
            cycle=5,
        )

        metrics_data = reader.get_metrics_data()
        assert metrics_data is not None
        metric_names: set[str] = set()
        for resource_metrics in metrics_data.resource_metrics:
            for scope_metrics in resource_metrics.scope_metrics:
                for metric in scope_metrics.metrics:
                    metric_names.add(metric.name)

        assert "hyperloop.tasks.completed" in metric_names

    def test_tasks_failed_counter_incremented(self) -> None:
        probe, _exporter, reader = _make_probe()

        probe.task_failed(
            task_id="task-001",
            spec_ref="specs/task-001.md",
            reason="max_rounds exceeded",
            round=50,
            cycle=100,
        )

        metrics_data = reader.get_metrics_data()
        assert metrics_data is not None
        metric_names: set[str] = set()
        for resource_metrics in metrics_data.resource_metrics:
            for scope_metrics in resource_metrics.scope_metrics:
                for metric in scope_metrics.metrics:
                    metric_names.add(metric.name)

        assert "hyperloop.tasks.failed" in metric_names

    def test_cycle_duration_histogram_recorded(self) -> None:
        probe, _exporter, reader = _make_probe()

        probe.cycle_started(
            cycle=1,
            active_workers=0,
            not_started=0,
            in_progress=0,
            complete=0,
            failed=0,
        )
        probe.cycle_completed(
            cycle=1,
            active_workers=0,
            not_started=0,
            in_progress=0,
            complete=1,
            failed=0,
            spawned_ids=(),
            reaped_ids=(),
            duration_s=9.8,
        )

        metrics_data = reader.get_metrics_data()
        assert metrics_data is not None
        metric_names: set[str] = set()
        for resource_metrics in metrics_data.resource_metrics:
            for scope_metrics in resource_metrics.scope_metrics:
                for metric in scope_metrics.metrics:
                    metric_names.add(metric.name)

        assert "hyperloop.cycle.duration_s" in metric_names


class TestProbeDoesNotRaise:
    """Probe methods must not raise even with unexpected inputs."""

    def test_worker_reaped_without_prior_spawn(self) -> None:
        """Reaping a task_id that was never spawned should not raise."""
        probe, _exporter, _reader = _make_probe()

        # No exception expected
        probe.worker_reaped(
            task_id="nonexistent",
            role="verifier",
            verdict="fail",
            round=1,
            cycle=1,
            spec_ref="specs/x.md",
            detail="",
            duration_s=1.0,
        )

    def test_worker_message_without_active_span(self) -> None:
        """Sending a message for a task with no active span should not raise."""
        probe, _exporter, _reader = _make_probe()

        probe.worker_message(
            task_id="nonexistent",
            role="implementer",
            message_type="text",
            content="hello",
        )

    def test_cycle_completed_without_start(self) -> None:
        """Completing a cycle that was never started should not raise."""
        probe, _exporter, _reader = _make_probe()

        probe.cycle_completed(
            cycle=99,
            active_workers=0,
            not_started=0,
            in_progress=0,
            complete=0,
            failed=0,
            spawned_ids=(),
            reaped_ids=(),
            duration_s=0.0,
        )

    def test_orchestrator_halted_without_start(self) -> None:
        """Halting without a prior start should not raise."""
        probe, _exporter, _reader = _make_probe()

        probe.orchestrator_halted(
            reason="test",
            total_cycles=0,
            completed_tasks=0,
            failed_tasks=0,
        )

    def test_all_noop_methods_accept_kwargs(self) -> None:
        """No-op methods (gate_checked, merge_attempted, etc.) accept kwargs."""
        probe, _exporter, _reader = _make_probe()

        probe.task_advanced(task_id="t", from_phase="a", to_phase="b")
        probe.gate_checked(task_id="t", gate="g", cleared=True, cycle=1)
        probe.merge_attempted(task_id="t", branch="b", spec_ref="s", outcome="merged")
        probe.rebase_conflict(task_id="t", branch="b", attempt=1, max_attempts=3)
        probe.recovery_started(in_progress_tasks=0)
        probe.orphan_found(task_id="t", branch="b")
        probe.prompt_composed(task_id="t", role="r", prompt_text="p", sections=(), round=1, cycle=1)


class TestOrchestratorRunSpan:
    """orchestrator_started/halted creates and ends a run span."""

    def test_run_span_created_and_ended(self) -> None:
        probe, exporter, _reader = _make_probe()

        probe.orchestrator_started(
            task_count=5,
            max_workers=3,
            max_task_rounds=50,
        )
        probe.orchestrator_halted(
            reason="all tasks complete",
            total_cycles=10,
            completed_tasks=5,
            failed_tasks=0,
        )

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.name == "hyperloop.run"
        attrs = dict(span.attributes or {})
        assert attrs["hyperloop.task_count"] == 5
        assert attrs["hyperloop.halt_reason"] == "all tasks complete"
        assert attrs["hyperloop.completed_tasks"] == 5


class TestSerialAgentEvents:
    """intake_ran and process_improver_ran add events to cycle span."""

    def test_intake_ran_adds_event_to_cycle_span(self) -> None:
        probe, exporter, _reader = _make_probe()

        probe.cycle_started(
            cycle=1,
            active_workers=0,
            not_started=5,
            in_progress=0,
            complete=0,
            failed=0,
        )
        probe.intake_ran(
            unprocessed_specs=3,
            created_tasks=2,
            success=True,
            cycle=1,
            duration_s=5.5,
        )
        probe.cycle_completed(
            cycle=1,
            active_workers=0,
            not_started=3,
            in_progress=2,
            complete=0,
            failed=0,
            spawned_ids=("task-001", "task-002"),
            reaped_ids=(),
            duration_s=10.0,
        )

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        events = spans[0].events
        assert any(e.name == "intake_ran" for e in events)

    def test_process_improver_ran_adds_event_to_cycle_span(self) -> None:
        probe, exporter, _reader = _make_probe()

        probe.cycle_started(
            cycle=2,
            active_workers=0,
            not_started=0,
            in_progress=0,
            complete=3,
            failed=1,
        )
        probe.process_improver_ran(
            failed_task_ids=("task-004",),
            success=True,
            cycle=2,
            duration_s=3.2,
        )
        probe.cycle_completed(
            cycle=2,
            active_workers=0,
            not_started=0,
            in_progress=0,
            complete=3,
            failed=1,
            spawned_ids=(),
            reaped_ids=(),
            duration_s=8.0,
        )

        spans = exporter.get_finished_spans()
        events = spans[0].events
        assert any(e.name == "process_improver_ran" for e in events)


class TestTaskLifecycleEvents:
    """task_completed/failed/looped_back add events to run span."""

    def test_task_completed_adds_event_to_run_span(self) -> None:
        probe, exporter, _reader = _make_probe()

        probe.orchestrator_started(task_count=1, max_workers=1, max_task_rounds=10)
        probe.task_completed(
            task_id="task-001",
            spec_ref="specs/task-001.md",
            total_rounds=2,
            total_cycles=3,
            cycle=3,
        )
        probe.orchestrator_halted(
            reason="all tasks complete",
            total_cycles=3,
            completed_tasks=1,
            failed_tasks=0,
        )

        spans = exporter.get_finished_spans()
        run_span = next(s for s in spans if s.name == "hyperloop.run")
        assert any(e.name == "task_completed" for e in run_span.events)

    def test_task_failed_adds_event_to_run_span(self) -> None:
        probe, exporter, _reader = _make_probe()

        probe.orchestrator_started(task_count=1, max_workers=1, max_task_rounds=10)
        probe.task_failed(
            task_id="task-001",
            spec_ref="specs/task-001.md",
            reason="max_rounds exceeded",
            round=10,
            cycle=20,
        )
        probe.orchestrator_halted(
            reason="all tasks complete",
            total_cycles=20,
            completed_tasks=0,
            failed_tasks=1,
        )

        spans = exporter.get_finished_spans()
        run_span = next(s for s in spans if s.name == "hyperloop.run")
        assert any(e.name == "task_failed" for e in run_span.events)

    def test_task_looped_back_adds_event_to_run_span(self) -> None:
        probe, exporter, _reader = _make_probe()

        probe.orchestrator_started(task_count=1, max_workers=1, max_task_rounds=10)
        probe.task_looped_back(
            task_id="task-001",
            spec_ref="specs/task-001.md",
            round=2,
            cycle=4,
            findings_preview="test failures",
        )
        probe.orchestrator_halted(
            reason="all tasks complete",
            total_cycles=10,
            completed_tasks=1,
            failed_tasks=0,
        )

        spans = exporter.get_finished_spans()
        run_span = next(s for s in spans if s.name == "hyperloop.run")
        assert any(e.name == "task_looped_back" for e in run_span.events)
