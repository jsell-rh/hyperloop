---
id: task-006
title: Merge ready PRs in dependency order
spec_ref: specs/spec.md
status: in-progress
phase: implementer
deps: []
round: 0
branch: null
pr: null
---

## Spec

The spec states:

> Merge order: the serial section merges PRs one at a time, rebasing each onto the new HEAD after the previous merge. Merges in task dependency order when possible, falling back to completion order.

The current `Orchestrator._merge_ready_prs()` iterates `all_tasks.values()` in arbitrary dict order, with no respect for the dependency graph. If task A depends on task B and both are ready to merge simultaneously, merging A before B is incorrect: A was built assuming B's changes are on trunk. Merging in the wrong order causes unnecessary rebase conflicts and incorrect merge history.

### What to build

**1. Topological sort helper** (`src/hyperloop/loop.py`):

Add a pure module-level function:

```python
def _dep_order_ids(tasks: dict[str, Task], candidate_ids: list[str]) -> list[str]:
    ...
```

- Takes the full task dict (for dep lookup) and a list of candidate task IDs to order.
- Returns the candidates in topological order: dependencies before dependents.
- Only considers dependencies within the candidate set; tasks outside candidates are ignored (treated as already merged).
- If two candidates have no dependency relationship, preserve input order (callers pre-sort by task ID for determinism).
- On a cycle within candidates (should not occur after recovery validates), fall back to input order for the cyclic group rather than raising.

Kahn's algorithm (BFS topological sort) is recommended.

**2. Apply ordering in `_merge_ready_prs()`** (`src/hyperloop/loop.py`):

Update `_merge_ready_prs()` to:

1. Collect all task IDs at phase `merge-pr` with status `IN_PROGRESS`.
2. Sort them by `task.id` first (for stable determinism), then apply `_dep_order_ids` for dep ordering.
3. Merge them one at a time in that order using the existing `_merge_via_pr` / `_merge_local` logic (unchanged).

**3. Tests** (`tests/test_loop.py`):

TDD: write failing tests first.

- **Helper unit tests**: test `_dep_order_ids` directly:
  - Linear chain: A → B → C (C deps B deps A) → merge order A, B, C
  - Diamond: A and B both dep on C → C first, then A and B in ID order
  - No deps: tasks maintain stable (ID) input order
  - Single task: returns unchanged
  - Candidate not in full tasks dict: graceful (skip unknown deps)

- **Integration test**: create a world where two tasks are at `merge-pr`, one depending on the other. Run `_merge_ready_prs()` via a full cycle. Assert the dependent is merged after the depended-on task. Use `FakePRManager` (from `tests/fakes/pr.py`) to record merge call order.

Use `InMemoryStateStore` and `FakePRManager`; no mocks.

### Constraints

- `_dep_order_ids` must be a pure function (no I/O, no side effects), independently testable.
- Full type hints, no `Any`.
- Follow TDD: failing test first, then implementation.

## Findings
