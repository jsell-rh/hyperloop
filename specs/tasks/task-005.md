---
id: task-005
title: Implement AmbientStateStore adapter
spec_ref: specs/spec.md
status: not-started
phase: null
deps: [task-004]
round: 0
branch: null
pr: null
---

## Spec

The spec defines two state store implementations:

> Implementations: `GitStateStore` (reads/writes task files, commits to git), `AmbientStateStore` (reads/writes annotations via API).

`GitStateStore` is complete. `AmbientStateStore` does not exist. On the ambient platform, task state lives in platform annotations rather than git-committed YAML files, allowing the orchestrator to manage tasks without requiring git write access to the target repo. This is the natural pairing with `AmbientRuntime` (task-004).

### StateStore Interface (all methods required)

```
get_world()                              → World
get_task(id)                             → Task
transition_task(id, status, phase, round)→ void
store_findings(id, data)                 → void
get_findings(id)                         → str
clear_findings(id)                       → void
set_task_branch(id, branch)              → void     (added in task-002)
set_task_pr(id, pr_url)                  → void
get_epoch(key)                           → str
set_epoch(key, value)                    → void
list_files(pattern)                      → list[str]
read_file(path)                          → str | None
commit(message)                          → void     (may be a no-op on ambient)
```

### Ambient Platform Model

On the ambient platform, task state is represented as annotations on a task resource (or equivalent). The mapping from `Task` fields to annotations follows the `ambient.io/` annotation scheme already used for agent configuration. The exact annotation schema should be derived from the HyperFleet platform documentation.

`list_files` and `read_file` must read spec files from the target repo — on the ambient platform this may be done via the GitHub API (for `list_files("specs/*.md")`) and a file content API, rather than local filesystem access.

`commit` may be a no-op if the ambient platform stores state in annotations rather than git; the method must still exist and be callable.

### What to build

**1. `AmbientStateStore` class** (`src/hyperloop/adapters/ambient_state.py`):

Implement all methods of the `StateStore` protocol using the ambient platform API (see task-004 for platform SDK notes). Key design considerations:

- State durability: task status and phase must survive orchestrator restarts (stored in platform annotations, not in-memory).
- `get_world()` must return all tasks, reconstructed from the ambient platform's annotation store.
- `read_file` / `list_files` should read from the target repo via GitHub API (using the `repo` config value), not from local disk.
- `commit` can record a message as an annotation or be a no-op — callers must not depend on it causing a git commit.

**2. Fake or test double** (`tests/fakes/`):

The existing `InMemoryStateStore` in `tests/fakes/state.py` already serves as the in-memory fake for both `GitStateStore` and `AmbientStateStore`. No new fake is needed unless the ambient-specific contract diverges. If `set_task_branch` (from task-002) is not yet on `InMemoryStateStore`, add it here.

**3. Contract tests** (`tests/test_state_contract.py`):

The existing contract tests run against `InMemoryStateStore` and `GitStateStore`. Add `AmbientStateStore` (backed by a local ambient platform test fixture or integration environment) to the same contract test suite, so all three implementations are validated against identical assertions.

**4. CLI wiring** (`src/hyperloop/cli.py`):

When `cfg.runtime == "ambient"`, construct `AmbientStateStore` alongside `AmbientRuntime`. The ambient state store will need the same platform credentials as the runtime. Coordinate the credential approach with task-004.

**5. Tests** (`tests/test_ambient_state.py` or integrated into contract tests):

TDD. The contract tests are the primary validation. Additionally:
- `get_world()` on an empty platform → returns `World` with empty tasks dict
- `transition_task` persists to the platform; a subsequent `get_task` reflects the new status
- `store_findings` / `get_findings` / `clear_findings` round-trip correctly
- `list_files` returns spec file paths from the target repo

Do not mock the ambient platform SDK in unit tests; use a local test environment or the platform's test mode if available.

## Findings
