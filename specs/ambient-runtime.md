# Ambient Runtime

The Ambient Code Platform runtime adapter. Runs workers as remote Ambient sessions instead of local worktrees. Same Runtime port, same orchestrator loop, different execution substrate.

## Why

Local runtime (AgentSdkRuntime) runs agents in-process on worktrees. This works for single-machine orchestration but doesn't scale to managed infrastructure, team-shared compute, or environments where the orchestrator host shouldn't run agent workloads.

Ambient provides managed agent sessions with git repo access, credential isolation, and a session lifecycle API. The orchestrator becomes a control plane that dispatches work to Ambient sessions and collects results — no local worktrees, no local agent SDK dependency.

## Ambient Concepts

The orchestrator interacts with three Ambient resources:

| Resource | Maps to | Lifecycle |
|---|---|---|
| **Agent** | Role (implementer, verifier, etc.) | Created at startup, persists across tasks |
| **Session** | One worker run (one task + role + round) | Created per spawn, stopped after reap |
| **Inbox Message** | Per-task context (spec + findings + epilogue) | Sent before session start, drained into start context |

Agents are persistent — one per role in the project. Sessions are ephemeral — one per spawn. The agent's standing instructions carry the role identity (prompt + guidelines). Per-task context (spec, findings, epilogue) goes via inbox.

### Agent Resource

```yaml
# Created by the adapter at startup
kind: Agent
name: hyperloop-implementer
prompt: |
  You are a worker agent implementing a task...
  (base prompt + guidelines, concatenated by adapter)
labels:
  hyperloop.io/managed: "true"
  hyperloop.io/role: implementer
annotations:
  hyperloop.io/task-id: ""
  hyperloop.io/branch: ""
```

The `prompt` field carries the kustomize-resolved template prompt + guidelines (concatenated). Labels identify hyperloop-managed agents. Annotations carry per-task state updated by the adapter at spawn time.

Labels, annotations, and inbox are runtime state managed by the adapter — they do not appear in the committed kustomize Agent resources. The committed schema stays: `kind`, `name`, `prompt`, `guidelines`.

### Session Lifecycle

Ambient sessions are persistent — they stay `Running` after the agent completes its turn. There is no `Succeeded` or `Completed` phase. The session waits for more messages.

Observed phase transitions:
```
(empty) → Running → Stopping → Stopped
```

Turn completion must be detected via AG-UI Server-Sent Events, not session phase.

### Start Context

When a session starts, Ambient assembles an initial user message from:

```
# Agent Start: {name}
## Workspace Context        ← project.prompt (project-wide, all agents)
## Standing Instructions    ← agent.prompt (per-role)
## Peer Agents              ← auto-generated list
## Inbox Messages           ← drained from inbox (per-task instructions)
```

This maps to our composition model:
- **Standing Instructions** = kustomize-resolved `prompt` + `guidelines` (set via `agent update`)
- **Inbox Messages** = spec + findings + epilogue (sent per-spawn)

## Runtime Port Mapping

### `spawn(task_id, role, prompt, branch) → WorkerHandle`

1. Update agent annotations: `hyperloop.io/task-id: {task_id}`, `hyperloop.io/branch: {branch}`.
2. Send inbox message with per-task context (spec content, findings from prior rounds, epilogue).
3. Start a session via `acpctl start <agent-id> --project-id <project>`.
4. Start a background thread to stream AG-UI events (`acpctl session events <session-id>`).
5. Return a `WorkerHandle` with `agent_id` = Ambient agent ID, `session_id` = Ambient session ID.

The standing instructions (`agent.prompt` = prompt + guidelines) are updated at startup and after the process-improver runs. Per-spawn context (spec, findings, epilogue) goes via inbox.

### `poll(handle) → running | done | failed`

The adapter maintains an internal dict of session completion state, updated by background SSE threads.

Each spawned session has a background thread streaming `session events <session-id>`. When the thread receives a `RUN_FINISHED` AG-UI event, it records the session as `done` in the shared state dict.

`poll()` reads from this dict:
- Session ID not in dict or no RUN_FINISHED yet → `"running"`
- RUN_FINISHED received → `"done"`
- SSE stream error or session phase is `Stopped`/`Failed` → `"failed"`

This avoids polling. The SSE stream is the authoritative signal for turn completion.

### `reap(handle) → WorkerResult`

After `poll()` returns `"done"`:

1. **Fetch the worker branch**: `git fetch origin {branch}` with exponential backoff.
   - The agent pushes its branch as part of its work. There may be a delay between the AG-UI `RUN_FINISHED` event and the push being fetchable from the remote.
   - Backoff schedule: 1s, 2s, 4s, 8s, 16s (5 attempts, ~31s max wait).
   - If all attempts fail, return `WorkerResult(verdict=ERROR, detail="branch not fetchable after push")`.

2. **Read review file** from the fetched ref: `git show origin/{branch}:.hyperloop/state/reviews/{task_id}-round-*.md`.
   - Same parsing as `_read_review_from_worktree`, but reads from a remote ref instead of a local path.
   - Falls back to `WorkerResult(verdict=PASS, findings=0)` if no review file found (same as AgentSdkRuntime fallback).

3. **Stop the session**: `acpctl stop <session-id>`.

4. **Clean up background SSE thread** for this session.

### `cancel(handle) → void`

1. Stop the session: `acpctl stop <session-id>`.
2. Clean up the background SSE thread.
3. Clean up annotations on the agent (clear `hyperloop.io/task-id`, `hyperloop.io/branch`).

### `find_orphan(task_id, branch) → WorkerHandle | null`

1. Get the agent for this role: `acpctl agent get <name> --project-id <project>`.
2. Check `current_session_id` on the agent. If present and the session phase is `Running`:
   - Check annotations: does `hyperloop.io/task-id` match?
   - If yes, return a `WorkerHandle` for this orphaned session.
3. Otherwise return `None`.

Note: `acpctl agent sessions` is broken (CLI bug: sends project ID as agent ID in the API path — `ambient-api-server-7`). Use `current_session_id` on the agent object instead.

### `push_branch(branch) → void`

Push the branch to remote: `git push -u origin {branch}`.

Required for Ambient — agents access the repo via the remote, not local worktrees. Called by the orchestrator before `spawn()`.

### `worker_epilogue() → str`

Returns instructions for the agent to push its branch:

```
Push your branch when your work is complete:
  git push origin {branch}
```

The `{branch}` placeholder is replaced at compose time with the actual branch name.

### `run_serial(role, prompt) → bool`

Serial agents (PM intake, process-improver) block the orchestrator loop:

1. Send inbox message with the serial agent's context (spec list for PM, findings for process-improver).
2. Start a session: `acpctl start <agent-id> --project-id <project>`.
3. Stream SSE events in the **foreground** (blocking) until `RUN_FINISHED`.
4. Fetch trunk: `git fetch origin main` (or configured base branch) with exponential backoff.
5. Fast-forward local trunk: `git merge --ff-only origin/main`.
6. Stop the session.
7. Return `True` on success, `False` on timeout or error.

The serial agent commits and pushes directly to the base branch. The orchestrator pulls those changes before continuing the cycle. Timeout: 600s (same as AgentSdkRuntime).

## Agent Lifecycle

### Startup

At orchestrator startup, after `kustomize build` resolves templates:

1. For each resolved `AgentTemplate`:
   - Concatenate `prompt` + `guidelines` into a single prompt string.
   - Create or update the Ambient agent via `acpctl agent update <name> --project-id <project> --prompt <concatenated> --labels '{"hyperloop.io/managed":"true","hyperloop.io/role":"<role>"}'`.
2. Set the project prompt if project-wide context is configured (optional).

This is idempotent — `agent update` creates if absent, patches if present.

### After process-improver

When `composer.rebuild()` re-resolves templates with updated guidelines:

1. For each template whose `prompt + guidelines` changed:
   - Update the Ambient agent's prompt: `acpctl agent update <name> --prompt <new-concatenated>`.

Agents spawned after this point will see the updated standing instructions.

### Shutdown

Best-effort cleanup:
- Stop all running sessions managed by this orchestrator run.
- Do NOT delete agents — they persist for the next run (crash recovery depends on this).

## Guidelines Mapping

There is no dedicated `guidelines` field on Ambient agents. The adapter concatenates `prompt + "\n\n## Guidelines\n" + guidelines` into the agent's `prompt` field.

This is the adapter's responsibility, not a schema change. The committed kustomize resources keep `guidelines` as a separate field. The `PromptComposer` continues to resolve them separately. Only the Ambient adapter merges them when syncing to the platform.

## Schema Alignment

Agent resource schema aligns with Ambient's format:

| Field | Our schema | Ambient schema | Action |
|---|---|---|---|
| `name` | `metadata.name` | top-level `name` | Move to top level |
| `kind` | `kind: Agent` | `kind: Agent` | Already matches |
| `apiVersion` | `hyperloop.io/v1` | (ignored) | Keep for our tooling |
| `prompt` | `prompt` | `prompt` | Already matches |
| `guidelines` | `guidelines` | (none) | Keep in our schema; adapter folds into `prompt` |
| `labels` | (none) | `labels` | Runtime state, NOT in schema |
| `annotations` | (none) | `annotations` | Runtime state, NOT in schema |
| `inbox` | (none) | `inbox` | Runtime state, NOT in schema |

The `metadata.name` → top-level `name` change applies to all resources (Agent, Process). The `_extract_name` helper in `compose.py` already supports both forms.

## Configuration

`.hyperloop.yaml` gains an `ambient` section:

```yaml
runtime: ambient              # local | ambient

ambient:
  project_id: my-project       # Ambient project name
  acpctl: acpctl               # path to acpctl binary (default: acpctl)
```

When `runtime: ambient`, the CLI constructs `AmbientRuntime` instead of `AgentSdkRuntime`. The `project_id` maps to the Ambient project where agents and sessions live.

Ambient credentials (API auth) are handled by `acpctl login` / `acpctl config` — the orchestrator does not manage Ambient auth. Git credentials for the remote repo are handled by Ambient's credential system (`acpctl credential create`).

## Concurrency and Threading

Each spawned session has a dedicated background thread for SSE streaming. The main orchestrator loop is single-threaded and never blocks on SSE.

```
Main thread:         spawn → poll → reap → spawn → ...
                       │       ↑       ↑
Background threads:    │       │       │
  session-A SSE ───────┘   reads   reads
  session-B SSE ──────────┘       │
  session-C SSE ──────────────────┘
```

Thread safety: the shared completion-state dict uses a threading lock. Background threads write (`session_id → done/failed`), the main thread reads via `poll()`.

For serial agents, there is no background thread — the main thread streams SSE directly (blocking) since the orchestrator loop must wait for the serial agent to complete.

## Error Handling

| Failure | Behavior |
|---|---|
| `acpctl` not on PATH | Fail at startup with clear message |
| Agent create/update fails | Fail at startup |
| Session start fails | `spawn()` raises, orchestrator marks task FAILED (existing handler) |
| SSE stream disconnects | Background thread retries with backoff; if unrecoverable, marks session `failed` |
| Branch not fetchable after RUN_FINISHED | `reap()` returns `Verdict.ERROR` after max retries |
| Session stop fails | Log warning, continue (best-effort cleanup) |
| `acpctl agent sessions` broken | Use `current_session_id` on agent object (documented workaround) |

## CLI Interaction

The adapter shells out to `acpctl` rather than calling an HTTP API directly. Reasons:

1. `acpctl` handles auth, TLS, and token refresh.
2. `acpctl` supports kustomize natively (`apply -k`), matching our composition model.
3. No additional Python dependency (no Ambient SDK to install).
4. `acpctl` output is JSON-parseable with `-o json`.

If a Python SDK becomes available, the adapter can switch to direct API calls without changing the port interface.

## File Map

```
src/hyperloop/
├── adapters/
│   └── runtime/
│       ├── agent_sdk.py       ← AgentSdkRuntime (local, unchanged)
│       ├── ambient.py         ← AmbientRuntime (NEW)
│       └── _worktree.py       ← shared git helpers (unchanged)
├── config.py                  ← gains AmbientConfig, runtime field
├── cli.py                     ← gains runtime selection logic
└── ...

tests/
├── fakes/
│   └── runtime.py             ← InMemoryRuntime (unchanged, tests both)
├── test_ambient_runtime.py    ← AmbientRuntime unit tests (NEW)
└── ...
```

## Testing

### Unit tests (`test_ambient_runtime.py`)

The adapter shells out to `acpctl`. Tests use a fake `acpctl` — a shell script or Python wrapper that:
- Records commands it receives (for assertion).
- Returns canned JSON responses.
- Simulates SSE event streams via stdout.

This follows the "no mocks" principle: the fake is a real executable that implements the `acpctl` contract, not a patched subprocess.

Test cases:
- `spawn` sends inbox, starts session, returns handle with session ID.
- `poll` returns `"running"` before RUN_FINISHED, `"done"` after.
- `reap` fetches branch, reads review file, stops session.
- `cancel` stops session, cleans up thread.
- `find_orphan` reads `current_session_id` from agent, checks phase.
- `run_serial` blocks until RUN_FINISHED, fetches trunk.
- Agent prompt sync at startup concatenates prompt + guidelines.
- Agent prompt re-sync after `rebuild()` updates only changed agents.

### Integration tests

Manual, require Ambient access:
- Create agents, start sessions, verify inbox drain, verify SSE completion.
- Run the full orchestrator loop against Ambient with a simple task.
- Crash recovery: kill orchestrator mid-run, restart, verify orphan detection.

## Dependencies

The Ambient adapter requires:
- `acpctl` binary on PATH (installed separately).
- Git remote configured with push access (for `push_branch`).
- Ambient project with credentials for the target repo.

No new Python dependencies. The adapter uses `subprocess` for `acpctl` and `threading` for SSE streams — both stdlib.

## What This Does NOT Change

- The Runtime port interface — `AmbientRuntime` implements the same `Runtime` protocol.
- The orchestrator loop — same serial section, same decide/spawn/poll/reap cycle.
- The domain model — `WorkerHandle`, `WorkerResult`, `Verdict` unchanged.
- The prompt composition model — kustomize still resolves all three layers.
- The review file protocol — workers still write `.hyperloop/state/reviews/` files on their branch.
- The state store — still `GitStateStore` on trunk. Ambient doesn't replace state, only execution.
