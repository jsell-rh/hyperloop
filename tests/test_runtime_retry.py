"""Tests for runtime retry with exponential backoff.

Covers:
- agent_retried probe event is recorded
- Delay computation is within expected bounds (jitter +-20%)
- Retry helper correctly retries transient failures and emits probe events
- Timeout errors are NOT retried
"""

from __future__ import annotations

import pytest

from tests.fakes.probe import RecordingProbe


class TestRetryDelayComputation:
    """_compute_retry_delay produces correct base + jitter values."""

    def test_attempt_1_delay_is_near_5s(self) -> None:
        from hyperloop.adapters.retry import compute_retry_delay

        delays = [compute_retry_delay(1) for _ in range(100)]
        for d in delays:
            assert 4.0 <= d <= 6.0, f"attempt 1 delay {d} out of [4.0, 6.0]"

    def test_attempt_2_delay_is_near_10s(self) -> None:
        from hyperloop.adapters.retry import compute_retry_delay

        delays = [compute_retry_delay(2) for _ in range(100)]
        for d in delays:
            assert 8.0 <= d <= 12.0, f"attempt 2 delay {d} out of [8.0, 12.0]"

    def test_attempt_3_delay_is_near_20s(self) -> None:
        from hyperloop.adapters.retry import compute_retry_delay

        delays = [compute_retry_delay(3) for _ in range(100)]
        for d in delays:
            assert 16.0 <= d <= 24.0, f"attempt 3 delay {d} out of [16.0, 24.0]"

    def test_jitter_is_not_constant(self) -> None:
        from hyperloop.adapters.retry import compute_retry_delay

        delays = {compute_retry_delay(1) for _ in range(20)}
        assert len(delays) > 1, "jitter should produce varying delays"


class TestRetryWithProbe:
    """retry_with_backoff calls the operation, retries on failure, emits probe."""

    def test_success_on_first_try_no_retries(self) -> None:
        from hyperloop.adapters.retry import retry_with_backoff

        probe = RecordingProbe()
        call_count = 0

        def op() -> str:
            nonlocal call_count
            call_count += 1
            return "ok"

        result = retry_with_backoff(
            op,
            role="implementer",
            operation="run_serial",
            probe=probe,
            max_attempts=3,
            sleep_fn=lambda _: None,
        )
        assert result == "ok"
        assert call_count == 1
        assert len(probe.of_method("agent_retried")) == 0

    def test_success_after_two_failures(self) -> None:
        from hyperloop.adapters.retry import retry_with_backoff

        probe = RecordingProbe()
        call_count = 0

        def op() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("transient error")
            return "ok"

        result = retry_with_backoff(
            op,
            role="implementer",
            operation="spawn",
            probe=probe,
            max_attempts=3,
            sleep_fn=lambda _: None,
        )
        assert result == "ok"
        assert call_count == 3

        retried_calls = probe.of_method("agent_retried")
        assert len(retried_calls) == 2
        assert retried_calls[0]["attempt"] == 1
        assert retried_calls[0]["max_attempts"] == 3
        assert retried_calls[0]["role"] == "implementer"
        assert retried_calls[0]["operation"] == "spawn"
        assert "transient error" in str(retried_calls[0]["error"])

    def test_all_retries_exhausted_raises(self) -> None:
        from hyperloop.adapters.retry import retry_with_backoff

        probe = RecordingProbe()

        def op() -> str:
            raise RuntimeError("always fails")

        with pytest.raises(RuntimeError, match="always fails"):
            retry_with_backoff(
                op,
                role="verifier",
                operation="run_serial",
                probe=probe,
                max_attempts=3,
                sleep_fn=lambda _: None,
            )

        retried_calls = probe.of_method("agent_retried")
        assert len(retried_calls) == 2  # 2 retries before final attempt raises

    def test_timeout_errors_not_retried(self) -> None:
        from hyperloop.adapters.retry import retry_with_backoff

        probe = RecordingProbe()

        def op() -> str:
            raise TimeoutError("timed out")

        with pytest.raises(TimeoutError, match="timed out"):
            retry_with_backoff(
                op,
                role="implementer",
                operation="run_serial",
                probe=probe,
                max_attempts=3,
                sleep_fn=lambda _: None,
            )

        assert len(probe.of_method("agent_retried")) == 0

    def test_concurrent_futures_timeout_not_retried(self) -> None:
        import concurrent.futures

        from hyperloop.adapters.retry import retry_with_backoff

        probe = RecordingProbe()

        def op() -> str:
            raise concurrent.futures.TimeoutError()

        with pytest.raises(concurrent.futures.TimeoutError):
            retry_with_backoff(
                op,
                role="implementer",
                operation="run_serial",
                probe=probe,
                max_attempts=3,
                sleep_fn=lambda _: None,
            )

        assert len(probe.of_method("agent_retried")) == 0

    def test_probe_receives_delay_value(self) -> None:
        from hyperloop.adapters.retry import retry_with_backoff

        probe = RecordingProbe()
        call_count = 0

        def op() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise RuntimeError("transient")
            return "ok"

        retry_with_backoff(
            op,
            role="pm",
            operation="run_serial",
            probe=probe,
            max_attempts=3,
            sleep_fn=lambda _: None,
        )

        retried = probe.of_method("agent_retried")
        assert len(retried) == 1
        delay_s = retried[0]["delay_s"]
        assert isinstance(delay_s, float)
        assert delay_s > 0


class TestAgentRetriedProbeEvent:
    """The agent_retried probe event is correctly recorded by RecordingProbe."""

    def test_recording_probe_records_agent_retried(self) -> None:
        probe = RecordingProbe()
        probe.agent_retried(
            role="implementer",
            operation="spawn",
            attempt=1,
            max_attempts=3,
            delay_s=5.2,
            error="API 429",
        )

        calls = probe.of_method("agent_retried")
        assert len(calls) == 1
        assert calls[0]["role"] == "implementer"
        assert calls[0]["operation"] == "spawn"
        assert calls[0]["attempt"] == 1
        assert calls[0]["max_attempts"] == 3
        assert calls[0]["delay_s"] == 5.2
        assert calls[0]["error"] == "API 429"


class TestGitStateStoreTimeout:
    """GitStateStore._git has a timeout parameter to prevent hangs."""

    def test_git_method_has_timeout_parameter(self) -> None:
        """The _git method signature accepts a timeout parameter."""
        import inspect

        from hyperloop.adapters.git.state import GitStateStore

        sig = inspect.signature(GitStateStore._git)
        assert "timeout" in sig.parameters
        # Default should be 30.0
        assert sig.parameters["timeout"].default == 30.0
