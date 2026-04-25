"""Retry helpers for transient runtime failures.

Provides exponential backoff with jitter for agent operations.
Timeout errors are never retried (they have their own semantics).
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import random
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from hyperloop.ports.probe import OrchestratorProbe


def compute_retry_delay(attempt: int) -> float:
    """Compute retry delay with exponential backoff and +-20% jitter.

    attempt is 1-indexed: attempt 1 -> ~5s, attempt 2 -> ~10s, attempt 3 -> ~20s.
    """
    base = 5.0 * (2 ** (attempt - 1))
    jitter = base * 0.2 * (2 * random.random() - 1)
    return base + jitter


def retry_with_backoff[T](
    fn: Callable[[], T],
    *,
    role: str,
    operation: str = "",
    probe: OrchestratorProbe | None = None,
    max_attempts: int = 3,
    sleep_fn: Callable[[float], None] | None = None,
) -> T:
    """Execute an operation with retry on transient failures.

    Timeout errors (TimeoutError, concurrent.futures.TimeoutError) are never
    retried -- they have their own timeout semantics.

    Args:
        fn: Callable that performs the work. Raises on failure.
        role: Agent role name (for probe context).
        operation: Name of the operation (e.g. "run_serial", "spawn").
        probe: Optional probe for emitting agent_retried events.
        max_attempts: Maximum number of attempts (including the first).
        sleep_fn: Sleep function (injectable for testing). Defaults to time.sleep.

    Returns:
        The return value from a successful fn() call.

    Raises:
        The last exception if all attempts are exhausted, or TimeoutError
        immediately on timeout.
    """
    do_sleep = sleep_fn if sleep_fn is not None else time.sleep
    last_exc: BaseException | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except (TimeoutError, concurrent.futures.TimeoutError):
            raise
        except Exception as exc:
            last_exc = exc
            if attempt < max_attempts:
                delay = compute_retry_delay(attempt)
                if probe is not None:
                    with contextlib.suppress(Exception):
                        probe.agent_retried(
                            role=role,
                            operation=operation,
                            attempt=attempt,
                            max_attempts=max_attempts,
                            delay_s=delay,
                            error=str(exc),
                        )
                do_sleep(delay)

    assert last_exc is not None
    raise last_exc
