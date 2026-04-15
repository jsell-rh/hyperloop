---
id: task-003
title: Validate dependency graph for cycles during recovery
spec_ref: specs/spec.md
status: in-progress
phase: implementer
deps: []
round: 0
branch: null
pr: null
---

## Spec

The spec's startup/recovery procedure includes:

> `validate dependency graph → reject cycles`

The `domain/deps.py` module already implements `detect_cycles(tasks)` as a pure function. The `Orchestrator.recover()` method reads all tasks from the state store but does not call `detect_cycles`. If a PM agent writes a cycle into the task graph, the orchestrator will silently loop forever or behave incorrectly rather than halting with a clear error.

### What to build

**1. Wire `detect_cycles` into `recover()`** (`src/hyperloop/loop.py`):

After reading the world in `recover()`, call `detect_cycles` and raise an error if any cycles are found:

```python
from hyperloop.domain.deps import detect_cycles

def recover(self) -> None:
    world = self._state.get_world()

    cycles = detect_cycles(world.tasks)
    if cycles:
        formatted = "; ".join(" -> ".join(c) for c in cycles)
        raise RuntimeError(f"Dependency cycle(s) detected in task graph: {formatted}")

    for task in world.tasks.values():
        ...  # existing orphan-cancellation logic unchanged
```

The error should be raised before any orphan-cancellation or re-spawn logic runs, so the operator sees the cycle immediately on startup without side effects.

**2. Tests** (`tests/test_loop.py`):

TDD: write the failing test first.

- Given an `InMemoryStateStore` seeded with two tasks that depend on each other (A deps B, B deps A), calling `orchestrator.recover()` raises `RuntimeError` containing both task IDs.
- Given tasks with no cycles, `recover()` completes without raising.

Use `InMemoryStateStore` and `FakeRuntime`; no mocks.

## Findings
