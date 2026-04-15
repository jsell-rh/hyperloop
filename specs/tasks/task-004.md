---
id: task-004
title: Implement AmbientRuntime adapter
spec_ref: specs/spec.md
status: in-progress
phase: implementer
deps: []
round: 1
branch: null
pr: null
---

## Spec

The spec describes two runtime implementations:

> Implementations: `LocalRuntime` (git worktrees + CLI), `AmbientRuntime` (ambient platform API — create agent, start session, poll annotations).

`LocalRuntime` is complete. `AmbientRuntime` (`src/hyperloop/adapters/ambient.py`) does not exist. The ambient platform is the target execution environment for agents running outside a local machine — agents are created as platform resources, given annotations that configure their identity and task context, and their results are read back via annotations.

The spec's directory structure lists `src/hyperloop/adapters/ambient.py` as a required file. The `config.py` already includes `runtime: "local" | "ambient"` as a configuration field; the CLI must be updated to wire up `AmbientRuntime` when `runtime == "ambient"`.

### Runtime Interface (required methods)

All five methods of the `Runtime` protocol must be implemented:

```
spawn(task_id, role, prompt, branch)  → WorkerHandle
poll(handle)                          → "running" | "done" | "failed"
reap(handle)                          → WorkerResult
cancel(handle)                        → void
find_orphan(task_id, branch)          → WorkerHandle | None
```

### Ambient Platform Model

Agents on the ambient platform are resources with attached annotations. The orchestrator's agent YAML definitions (`base/implementer.yaml`, etc.) list the annotation keys that each agent reads:

```yaml
annotations:
  ambient.io/persona: ""
  ambient.io/task-spec: ""
  ambient.io/process-overlay: ""
  ambient.io/findings: ""
```

At spawn time the orchestrator injects the composed prompt content by setting these annotations on the agent resource before starting its session. The `WorkerHandle.session_id` field (currently `None` in `LocalRuntime`) is used by `AmbientRuntime` to track the session.

### What to build

**1. `AmbientRuntime` class** (`src/hyperloop/adapters/ambient.py`):

The class must implement the `Runtime` protocol. The exact ambient platform SDK/API should be determined from the HyperFleet platform documentation or SDK available in the project environment. The implementation must:

- `spawn`: Create or locate an agent resource of the given role, set the appropriate annotations (injecting the composed prompt as `ambient.io/task-spec` or equivalent), start a session, and return a `WorkerHandle` with `session_id` populated.
- `poll`: Query the session's status annotation or API endpoint; map to `"running"`, `"done"`, or `"failed"`.
- `reap`: Read the `.worker-result.json` equivalent from the session's result annotation (or equivalent artifact store). Parse into `WorkerResult`. Clean up the session resource.
- `cancel`: Terminate the session via the platform API.
- `find_orphan`: Search for an existing agent session with a label or annotation matching `task/{task_id}`. Return a `WorkerHandle` if found, `None` otherwise.

**2. FakeAmbientRuntime** (`tests/fakes/runtime.py` or a new file):

A complete in-memory fake implementing the `Runtime` protocol. It must:
- Track spawned sessions in a dict
- Expose a test helper to set a session's result (so tests can simulate worker completion)
- Pass the same contract tests as `LocalRuntime` (or a subset appropriate for in-memory)

The existing `FakeRuntime` in `tests/fakes/runtime.py` may serve this role if it already satisfies the contract; otherwise extend it or add a separate `FakeAmbientRuntime`.

**3. CLI wiring** (`src/hyperloop/cli.py`):

When `cfg.runtime == "ambient"`, construct `AmbientRuntime` instead of `LocalRuntime` and pass it to the `Orchestrator`. The ambient runtime will likely require additional config (cluster URL, credentials). Determine the right approach from the platform SDK.

**4. Tests** (`tests/test_local_runtime.py` or a new `tests/test_ambient_runtime.py`):

TDD. The fake runtime must be tested via the same contract tests that cover `LocalRuntime`. At minimum:
- `spawn` returns a `WorkerHandle` with a non-None `session_id`
- `poll` returns `"running"` immediately after spawn
- Simulating completion → `poll` returns `"done"` → `reap` returns the correct `WorkerResult`
- `cancel` removes the session
- `find_orphan` returns a handle for a known session and `None` for unknown

Do not mock the ambient platform SDK in unit tests; use the fake instead.

## Findings
Worker result file not found