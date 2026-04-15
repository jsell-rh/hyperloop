---
id: task-002
title: Persist task branch to task file via set_task_branch
spec_ref: specs/spec.md
status: in-progress
phase: implementer
deps: []
round: 1
branch: null
pr: null
---

## Spec

The spec defines `branch: null` in the task data model as a field "set by orchestrator before first spawn". The orchestrator uses the branch name when spawning workers and looking for orphaned workers on crash recovery. Currently the branch name is derived on-the-fly as `task.branch or f"worker/{task_id}"` wherever it is needed, but the computed name is never persisted back to the task file. This means:

- The task file's `branch` field stays `null` permanently.
- On recovery the orchestrator recomputes the branch name from the fallback, which is consistent but leaves the task file's branch field inconsistent with the spec.
- `set_task_pr` already exists as a precedent for this pattern; `set_task_branch` follows the same design.

### What to build

**1. StateStore protocol** (`src/hyperloop/ports/state.py`):

Add the method:

```python
def set_task_branch(self, task_id: str, branch: str) -> None:
    """Set the branch name on a task (called once, before first spawn)."""
    ...
```

**2. GitStateStore** (`src/hyperloop/adapters/git_state.py`):

Implement `set_task_branch` following the exact pattern of `set_task_pr`:

```python
def set_task_branch(self, task_id: str, branch: str) -> None:
    fm, body = self._read_task_file(task_id)
    fm["branch"] = branch
    self._write_task_file(task_id, fm, body)
```

**3. InMemoryStateStore** (`tests/fakes/state.py`):

Add the matching implementation so the fake satisfies the protocol:

```python
def set_task_branch(self, task_id: str, branch: str) -> None:
    old = self._tasks[task_id]
    self._tasks[task_id] = Task(
        id=old.id, title=old.title, spec_ref=old.spec_ref,
        status=old.status, phase=old.phase, deps=old.deps,
        round=old.round, branch=branch, pr=old.pr,
    )
```

**4. Orchestrator loop** (`src/hyperloop/loop.py`):

In `run_cycle`, when computing the branch for a task that does not yet have one (i.e. `task.branch is None`), persist it before calling `runtime.spawn`:

```python
branch = task.branch or f"worker/{task_id}"
if task.branch is None:
    self._state.set_task_branch(task_id, branch)
```

This call should happen inside the spawn loop (`for task_id, role, position in to_spawn`), right before `self._runtime.spawn(...)`.

**5. Tests**:

TDD: write failing tests first.

- `tests/test_git_state.py`: `set_task_branch` writes the branch field to the task file frontmatter; a subsequent `get_task` returns the branch.
- `tests/test_fakes.py` or `tests/test_state_contract.py`: same assertion on `InMemoryStateStore` (contract test).
- `tests/test_loop.py`: after a cycle that spawns a new task, the task's `branch` field is set in the state store.

Do not use mocks; use `InMemoryStateStore` and `FakeRuntime` as appropriate.

## Findings
Worker result file not found