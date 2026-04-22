"""OtelProbe — exports orchestrator probe events as OpenTelemetry traces and metrics.

Maps probe lifecycle events to spans (traces) and counters/histograms (metrics),
exported via OTLP gRPC to a collector such as Grafana Alloy or the OTel Collector.

All methods swallow exceptions so probe failures never propagate to the
orchestrator loop.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from opentelemetry.metrics import Counter as MetricCounter
    from opentelemetry.metrics import Histogram, Meter, UpDownCounter
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.trace import Span, Tracer

_log = logging.getLogger(__name__)


class OtelProbe:
    """Exports probe events as OpenTelemetry spans and metrics.

    Constructor accepts an optional ``tracer_provider`` and ``meter_provider``
    for testing (in-memory exporters). When omitted, production providers are
    created that export via OTLP gRPC to the given ``endpoint``.
    """

    def __init__(
        self,
        service_name: str = "hyperloop",
        endpoint: str = "http://localhost:4317",
        *,
        tracer_provider: TracerProvider | None = None,
        meter_provider: MeterProvider | None = None,
    ) -> None:
        from opentelemetry.sdk.metrics import MeterProvider as SdkMeterProvider
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider as SdkTracerProvider

        resource = Resource.create({"service.name": service_name})

        # -- Traces --
        if tracer_provider is not None:
            self._tracer_provider: TracerProvider = tracer_provider
        else:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            tp = SdkTracerProvider(resource=resource)
            tp.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
            self._tracer_provider = tp

        self._tracer: Tracer = self._tracer_provider.get_tracer("hyperloop")

        # -- Metrics --
        if meter_provider is not None:
            self._meter_provider: MeterProvider = meter_provider
        else:
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                OTLPMetricExporter,
            )
            from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

            reader = PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=endpoint))
            self._meter_provider = SdkMeterProvider(resource=resource, metric_readers=[reader])

        meter: Meter = self._meter_provider.get_meter("hyperloop")

        self._workers_active: UpDownCounter = meter.create_up_down_counter(
            "hyperloop.workers.active",
            description="Number of currently active workers",
        )
        self._tasks_completed: MetricCounter = meter.create_counter(
            "hyperloop.tasks.completed",
            description="Total tasks completed",
        )
        self._tasks_failed: MetricCounter = meter.create_counter(
            "hyperloop.tasks.failed",
            description="Total tasks failed",
        )
        self._worker_duration: Histogram = meter.create_histogram(
            "hyperloop.worker.duration_s",
            description="Worker execution duration in seconds",
            unit="s",
        )
        self._cycle_duration: Histogram = meter.create_histogram(
            "hyperloop.cycle.duration_s",
            description="Cycle duration in seconds",
            unit="s",
        )

        # Span tracking
        self._run_span: Span | None = None
        self._current_cycle_span: Span | None = None
        self._worker_spans: dict[str, Span] = {}

    # ------------------------------------------------------------------
    # Orchestrator lifecycle
    # ------------------------------------------------------------------

    def orchestrator_started(
        self,
        *,
        task_count: int,
        max_workers: int,
        max_task_rounds: int,
        **_kw: object,
    ) -> None:
        try:
            self._run_span = self._tracer.start_span(
                "hyperloop.run",
                attributes={
                    "hyperloop.task_count": task_count,
                    "hyperloop.max_workers": max_workers,
                    "hyperloop.max_task_rounds": max_task_rounds,
                },
            )
        except Exception:
            _log.exception("otel: orchestrator_started failed")

    def orchestrator_halted(
        self,
        *,
        reason: str,
        total_cycles: int,
        completed_tasks: int,
        failed_tasks: int,
        **_kw: object,
    ) -> None:
        try:
            if self._run_span is not None:
                self._run_span.set_attributes(
                    {
                        "hyperloop.halt_reason": reason,
                        "hyperloop.total_cycles": total_cycles,
                        "hyperloop.completed_tasks": completed_tasks,
                        "hyperloop.failed_tasks": failed_tasks,
                    }
                )
                self._run_span.end()
                self._run_span = None
        except Exception:
            _log.exception("otel: orchestrator_halted failed")

    # ------------------------------------------------------------------
    # Cycle
    # ------------------------------------------------------------------

    def cycle_started(
        self,
        *,
        cycle: int,
        **_kw: object,
    ) -> None:
        try:
            self._current_cycle_span = self._tracer.start_span(
                "hyperloop.cycle",
                attributes={"hyperloop.cycle": cycle},
            )
        except Exception:
            _log.exception("otel: cycle_started failed")

    def cycle_completed(
        self,
        *,
        cycle: int,
        active_workers: int,
        spawned_ids: tuple[str, ...],
        reaped_ids: tuple[str, ...],
        duration_s: float,
        **_kw: object,
    ) -> None:
        try:
            self._cycle_duration.record(duration_s)
            if self._current_cycle_span is not None:
                self._current_cycle_span.set_attributes(
                    {
                        "hyperloop.cycle": cycle,
                        "hyperloop.active_workers": active_workers,
                        "hyperloop.spawned_ids": list(spawned_ids),
                        "hyperloop.reaped_ids": list(reaped_ids),
                        "hyperloop.duration_s": duration_s,
                    }
                )
                self._current_cycle_span.end()
                self._current_cycle_span = None
        except Exception:
            _log.exception("otel: cycle_completed failed")

    # ------------------------------------------------------------------
    # Workers
    # ------------------------------------------------------------------

    def worker_spawned(
        self,
        *,
        task_id: str,
        role: str,
        branch: str,
        round: int,
        cycle: int,
        spec_ref: str,
        **_kw: object,
    ) -> None:
        try:
            span = self._tracer.start_span(
                "hyperloop.worker",
                attributes={
                    "hyperloop.task_id": task_id,
                    "hyperloop.role": role,
                    "hyperloop.branch": branch,
                    "hyperloop.round": round,
                    "hyperloop.cycle": cycle,
                    "hyperloop.spec_ref": spec_ref,
                },
            )
            self._worker_spans[task_id] = span
            self._workers_active.add(1)
        except Exception:
            _log.exception("otel: worker_spawned failed")

    def worker_reaped(
        self,
        *,
        task_id: str,
        role: str,
        verdict: str,
        round: int,
        cycle: int,
        spec_ref: str,
        detail: str,
        duration_s: float,
        **_kw: object,
    ) -> None:
        try:
            from opentelemetry.trace import StatusCode

            span = self._worker_spans.pop(task_id, None)
            if span is not None:
                attrs: dict[str, str | int | float] = {
                    "hyperloop.verdict": verdict,
                    "hyperloop.duration_s": duration_s,
                }
                span.set_attributes(attrs)
                if verdict != "pass":
                    span.set_status(StatusCode.ERROR, f"verdict={verdict}")
                span.end()

            self._workers_active.add(-1)
            self._worker_duration.record(duration_s)
        except Exception:
            _log.exception("otel: worker_reaped failed")

    def worker_message(
        self,
        *,
        task_id: str,
        role: str,
        message_type: str,
        content: str,
        **_kw: object,
    ) -> None:
        try:
            span = self._worker_spans.get(task_id)
            if span is not None:
                span.add_event(
                    message_type,
                    attributes={"hyperloop.content": content[:200]},
                )
        except Exception:
            _log.exception("otel: worker_message failed")

    # ------------------------------------------------------------------
    # Task lifecycle
    # ------------------------------------------------------------------

    def task_advanced(self, **_kw: object) -> None:
        pass

    def task_looped_back(
        self,
        *,
        task_id: str,
        **_kw: object,
    ) -> None:
        try:
            if self._run_span is not None:
                self._run_span.add_event(
                    "task_looped_back",
                    attributes={"hyperloop.task_id": task_id},
                )
        except Exception:
            _log.exception("otel: task_looped_back failed")

    def task_completed(
        self,
        *,
        task_id: str,
        **_kw: object,
    ) -> None:
        try:
            self._tasks_completed.add(1)
            if self._run_span is not None:
                self._run_span.add_event(
                    "task_completed",
                    attributes={"hyperloop.task_id": task_id},
                )
        except Exception:
            _log.exception("otel: task_completed failed")

    def task_failed(
        self,
        *,
        task_id: str,
        **_kw: object,
    ) -> None:
        try:
            self._tasks_failed.add(1)
            if self._run_span is not None:
                self._run_span.add_event(
                    "task_failed",
                    attributes={"hyperloop.task_id": task_id},
                )
        except Exception:
            _log.exception("otel: task_failed failed")

    def task_reset(
        self,
        *,
        task_id: str,
        **_kw: object,
    ) -> None:
        try:
            if self._run_span is not None:
                self._run_span.add_event(
                    "task_reset",
                    attributes={"hyperloop.task_id": task_id},
                )
        except Exception:
            _log.exception("otel: task_reset failed")

    # ------------------------------------------------------------------
    # Pipeline: gates, merges, conflicts
    # ------------------------------------------------------------------

    def gate_checked(self, **_kw: object) -> None:
        pass

    def merge_attempted(self, **_kw: object) -> None:
        pass

    def rebase_conflict(self, **_kw: object) -> None:
        pass

    # ------------------------------------------------------------------
    # Serial agents
    # ------------------------------------------------------------------

    def intake_ran(
        self,
        *,
        cycle: int,
        duration_s: float,
        **_kw: object,
    ) -> None:
        try:
            if self._current_cycle_span is not None:
                self._current_cycle_span.add_event(
                    "intake_ran",
                    attributes={
                        "hyperloop.cycle": cycle,
                        "hyperloop.duration_s": duration_s,
                    },
                )
        except Exception:
            _log.exception("otel: intake_ran failed")

    def process_improver_ran(
        self,
        *,
        cycle: int,
        duration_s: float,
        **_kw: object,
    ) -> None:
        try:
            if self._current_cycle_span is not None:
                self._current_cycle_span.add_event(
                    "process_improver_ran",
                    attributes={
                        "hyperloop.cycle": cycle,
                        "hyperloop.duration_s": duration_s,
                    },
                )
        except Exception:
            _log.exception("otel: process_improver_ran failed")

    # ------------------------------------------------------------------
    # Recovery
    # ------------------------------------------------------------------

    def recovery_started(self, **_kw: object) -> None:
        pass

    def orphan_found(self, **_kw: object) -> None:
        pass

    # ------------------------------------------------------------------
    # Prompt composition
    # ------------------------------------------------------------------

    def prompt_composed(self, **_kw: object) -> None:
        pass

    def pr_created(self, **_kw: object) -> None:
        pass

    def pr_label_changed(self, **_kw: object) -> None:
        pass

    def pr_marked_ready(self, **_kw: object) -> None:
        pass

    def branch_pushed(self, **_kw: object) -> None:
        pass

    def state_synced(self, **_kw: object) -> None:
        pass
