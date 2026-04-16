"""Tests for MatrixProbe — posts probe calls to a Matrix room.

Uses httpx.MockTransport to intercept HTTP requests. No real Matrix server.
No unittest.mock — MockTransport is a real transport adapter implementing
the httpx transport protocol.
"""

from __future__ import annotations

import json

import httpx
import structlog

from hyperloop.adapters.probe.matrix import MatrixProbe


def _configure_structlog_for_tests() -> None:
    """Configure structlog minimally so error logging in MatrixProbe works."""
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(0),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )


_configure_structlog_for_tests()


def _make_probe(
    requests: list[httpx.Request],
    verbose: bool = False,
    error: bool = False,
) -> MatrixProbe:
    """Create a MatrixProbe with a mock transport that captures requests."""

    def handler(request: httpx.Request) -> httpx.Response:
        if error:
            msg = "network error"
            raise httpx.ConnectError(msg)
        requests.append(request)
        return httpx.Response(200, json={"event_id": f"$evt{len(requests)}"})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)

    probe = MatrixProbe(
        homeserver="https://matrix.example.com",
        room_id="!room:example.com",
        access_token="syt_test_token",
        verbose=verbose,
    )
    probe._client = client
    return probe


class TestHighSignalCalls:
    """High-signal probe calls always send an HTTP PUT request."""

    def test_worker_reaped_sends_request(self) -> None:
        requests: list[httpx.Request] = []
        probe = _make_probe(requests)

        probe.worker_reaped(
            task_id="task-001",
            role="verifier",
            verdict="pass",
            round=0,
            cycle=1,
            spec_ref="specs/task-001.md",
            findings_count=0,
            detail="All tests pass",
            duration_s=42.5,
        )

        assert len(requests) == 1
        assert requests[0].method == "PUT"
        body = json.loads(requests[0].content)
        assert body["msgtype"] == "m.text"
        assert "task-001" in body["body"]

    def test_worker_reaped_includes_cost_when_present(self) -> None:
        requests: list[httpx.Request] = []
        probe = _make_probe(requests)

        probe.worker_reaped(
            task_id="task-001",
            role="implementer",
            verdict="pass",
            round=0,
            cycle=1,
            spec_ref="specs/task-001.md",
            findings_count=0,
            detail="All good",
            duration_s=30.0,
            cost_usd=1.23,
            num_turns=5,
            api_duration_ms=25000.0,
        )

        assert len(requests) == 1
        body = json.loads(requests[0].content)["body"]
        assert "$1.23" in body

    def test_worker_reaped_omits_cost_when_none(self) -> None:
        requests: list[httpx.Request] = []
        probe = _make_probe(requests)

        probe.worker_reaped(
            task_id="task-001",
            role="implementer",
            verdict="pass",
            round=0,
            cycle=1,
            spec_ref="specs/task-001.md",
            findings_count=0,
            detail="All good",
            duration_s=30.0,
            cost_usd=None,
        )

        assert len(requests) == 1
        body = json.loads(requests[0].content)["body"]
        assert "$" not in body

    def test_task_completed_sends_request(self) -> None:
        requests: list[httpx.Request] = []
        probe = _make_probe(requests)

        probe.task_completed(
            task_id="task-003",
            spec_ref="specs/task-003.md",
            total_rounds=1,
            total_cycles=3,
            cycle=5,
        )

        assert len(requests) == 1
        assert "task-003" in json.loads(requests[0].content)["body"]

    def test_task_failed_sends_request(self) -> None:
        requests: list[httpx.Request] = []
        probe = _make_probe(requests)

        probe.task_failed(
            task_id="task-001",
            spec_ref="specs/task-001.md",
            reason="max_rounds exceeded",
            round=50,
            cycle=100,
        )

        assert len(requests) == 1
        body = json.loads(requests[0].content)["body"]
        assert "FAILED" in body

    def test_orchestrator_halted_sends_request(self) -> None:
        requests: list[httpx.Request] = []
        probe = _make_probe(requests)

        probe.orchestrator_halted(
            reason="all tasks complete",
            total_cycles=10,
            completed_tasks=5,
            failed_tasks=0,
        )

        assert len(requests) == 1


class TestLowSignalCalls:
    """Low-signal probe calls send NO HTTP request."""

    def test_cycle_started_no_request(self) -> None:
        requests: list[httpx.Request] = []
        probe = _make_probe(requests)

        probe.cycle_started(
            cycle=1,
            active_workers=0,
            not_started=5,
            in_progress=0,
            complete=0,
            failed=0,
        )

        assert len(requests) == 0

    def test_task_advanced_no_request(self) -> None:
        requests: list[httpx.Request] = []
        probe = _make_probe(requests)

        probe.task_advanced(
            task_id="task-001",
            spec_ref="specs/task-001.md",
            from_phase="implementer",
            to_phase="verifier",
            from_status="in_progress",
            to_status="in_progress",
            round=0,
            cycle=1,
        )

        assert len(requests) == 0


class TestVerboseOnlyCalls:
    """Verbose-only calls only send when verbose=True."""

    def test_worker_spawned_not_sent_when_not_verbose(self) -> None:
        requests: list[httpx.Request] = []
        probe = _make_probe(requests, verbose=False)

        probe.worker_spawned(
            task_id="task-001",
            role="implementer",
            branch="hyperloop/task-001",
            round=0,
            cycle=1,
            spec_ref="specs/task-001.md",
        )

        assert len(requests) == 0

    def test_worker_spawned_sent_when_verbose(self) -> None:
        requests: list[httpx.Request] = []
        probe = _make_probe(requests, verbose=True)

        probe.worker_spawned(
            task_id="task-001",
            role="implementer",
            branch="hyperloop/task-001",
            round=0,
            cycle=1,
            spec_ref="specs/task-001.md",
        )

        assert len(requests) == 1

    def test_cycle_completed_not_sent_when_not_verbose(self) -> None:
        requests: list[httpx.Request] = []
        probe = _make_probe(requests, verbose=False)

        probe.cycle_completed(
            cycle=1,
            active_workers=0,
            not_started=0,
            in_progress=0,
            complete=5,
            failed=0,
            spawned_ids=(),
            reaped_ids=(),
            duration_s=1.5,
        )

        assert len(requests) == 0

    def test_cycle_completed_sent_when_verbose(self) -> None:
        requests: list[httpx.Request] = []
        probe = _make_probe(requests, verbose=True)

        probe.cycle_completed(
            cycle=1,
            active_workers=0,
            not_started=0,
            in_progress=0,
            complete=5,
            failed=0,
            spawned_ids=(),
            reaped_ids=(),
            duration_s=1.5,
        )

        assert len(requests) == 1


class TestTaskThreading:
    """Second call for same task_id includes m.relates_to thread relation."""

    def test_first_call_has_no_thread_relation(self) -> None:
        requests: list[httpx.Request] = []
        probe = _make_probe(requests)

        probe.worker_reaped(
            task_id="task-001",
            role="implementer",
            verdict="pass",
            round=0,
            cycle=1,
            spec_ref="specs/task-001.md",
            findings_count=0,
            detail="ok",
            duration_s=10.0,
        )

        body = json.loads(requests[0].content)
        assert "m.relates_to" not in body

    def test_second_call_has_thread_relation(self) -> None:
        requests: list[httpx.Request] = []
        probe = _make_probe(requests)

        # First call — sets the thread root
        probe.worker_reaped(
            task_id="task-001",
            role="implementer",
            verdict="pass",
            round=0,
            cycle=1,
            spec_ref="specs/task-001.md",
            findings_count=0,
            detail="ok",
            duration_s=10.0,
        )

        # Second call — should include m.relates_to
        probe.task_completed(
            task_id="task-001",
            spec_ref="specs/task-001.md",
            total_rounds=1,
            total_cycles=2,
            cycle=2,
        )

        body = json.loads(requests[1].content)
        assert "m.relates_to" in body
        assert body["m.relates_to"]["rel_type"] == "m.thread"
        assert body["m.relates_to"]["event_id"] == "$evt1"


class TestErrorIsolation:
    """HTTP errors are swallowed — MatrixProbe never raises."""

    def test_http_error_swallowed(self) -> None:
        # Re-configure structlog to avoid stale config from other test modules
        _configure_structlog_for_tests()

        requests: list[httpx.Request] = []
        probe = _make_probe(requests, error=True)

        # Should not raise
        probe.worker_reaped(
            task_id="task-001",
            role="verifier",
            verdict="fail",
            round=0,
            cycle=1,
            spec_ref="specs/task-001.md",
            findings_count=1,
            detail="error",
            duration_s=5.0,
        )

        # No request was captured (the transport raises before response)
        assert len(requests) == 0


class TestGateCheckedFiltering:
    """gate_checked with cleared=True sends, cleared=False does not."""

    def test_cleared_true_sends(self) -> None:
        requests: list[httpx.Request] = []
        probe = _make_probe(requests)

        probe.gate_checked(
            task_id="task-001",
            gate="human-pr-approval",
            cleared=True,
            cycle=5,
        )

        assert len(requests) == 1

    def test_cleared_false_does_not_send(self) -> None:
        requests: list[httpx.Request] = []
        probe = _make_probe(requests)

        probe.gate_checked(
            task_id="task-001",
            gate="human-pr-approval",
            cleared=False,
            cycle=5,
        )

        assert len(requests) == 0
