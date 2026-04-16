# Ambient Runtime

The Ambient Code Platform runtime adapter. Runs workers as remote Ambient sessions instead of local worktrees. Same Runtime port, same orchestrator loop, different execution substrate.

## Why

Local runtime (AgentSdkRuntime) runs agents in-process on worktrees. This works for single-machine orchestration but doesn't scale to managed infrastructure, team-shared compute, or environments where the orchestrator host shouldn't run agent workloads.

Ambient provides managed agent sessions with git repo access, credential isolation, and a session lifecycle API. The orchestrator becomes a control plane that dispatches work to Ambient sessions and collects results — no local worktrees, no local agent SDK dependency.

## Model: Sessions Only

The adapter uses Ambient sessions directly — no Ambient agents, no inbox. Each `spawn()` creates a session via `acpctl create session` with:

- `--prompt` — the full composed prompt (template + guidelines + spec + findings + epilogue)
- `--repo-url` — so the agent gets the repo cloned into its workspace
- `--name` — `hyperloop-{task_id}-{role}` for identification and orphan detection

This is simpler than the agent+inbox model and provides everything we need:
- The prompt composer already produces the complete prompt
- `create session --repo-url` gives the agent repo access
- Session naming convention enables orphan detection

### Session Lifecycle

Sessions auto-start after creation (the operator sets phase Pending→Running). No separate `start` command needed.

Observed phase transitions:
```
(empty) → Running → Stopping → Stopped
```

Turn completion is detected via AG-UI Server-Sent Events, not session phase (sessions stay `Running` after completing their turn).

## Runtime Port Mapping

### `spawn(task_id, role, prompt, branch) → WorkerHandle`

1. Create session: `acpctl create session --name hyperloop-{task_id}-{role} --prompt <full_prompt> --repo-url <url> -o json`
2. Record session ID and branch in internal dicts.
3. Start a background thread to stream AG-UI events (`acpctl session events <session-id>`).
4. Return a `WorkerHandle` with `session_id` = Ambient session ID.

### `poll(handle) → running | done | failed`

Reads from an internal completion dict, populated by background SSE threads.

Each spawned session has a background thread streaming `session events <session-id>`. When the thread receives a `RUN_FINISHED` AG-UI event, it records the session as `done`.

### `reap(handle) → WorkerResult`

After `poll()` returns `"done"`:

1. **Fetch the worker branch**: `git fetch origin {branch}` with exponential backoff (1s, 2s, 4s, 8s, 16s — 5 attempts).
2. **Read review file** from the fetched ref: `git show origin/{branch}:.hyperloop/state/reviews/{task_id}-round-*.md`.
3. **Stop the session**: `acpctl stop <session-id>`.
4. **Clean up** internal tracking state.

### `cancel(handle) → void`

Stop session + clean up.

### `find_orphan(task_id, branch) → WorkerHandle | null`

List all sessions: `acpctl get sessions --project-id <project> -o json`. Find any Running session whose name starts with `hyperloop-{task_id}-`. If found, return a WorkerHandle and start an SSE thread for it.

### `push_branch(branch) → void`

`git push -u origin {branch}`. Required — Ambient agents access the repo via the remote.

### `worker_epilogue() → str`

Returns "Push your branch when your work is complete."

### `run_serial(role, prompt) → bool`

1. Create session with the full prompt and repo_url.
2. Stream SSE in the **foreground** (blocking) until `RUN_FINISHED` or timeout (600s).
3. Fetch trunk: `git fetch origin main` with backoff.
4. Fast-forward local trunk: `git merge --ff-only origin/main`.
5. Stop the session.
6. Return `True` on success, `False` on timeout or error.

## Project Lifecycle

At startup, `ensure_project()` creates the Ambient project if it doesn't exist. The project is a container for sessions — no agents or other resources are created.

## Repo Access

Repos are attached per-session via `--repo-url` on `acpctl create session`. The Ambient operator clones the repo into the session workspace. Git credentials come from the user's Ambient integrations (GitHub App or PAT configured on the Integrations page).

## SSE Retry

The session may not be ready for SSE streaming immediately after creation. Both background and foreground SSE streams retry with exponential backoff (1s, 2s, 4s, 8s, 16s). Failed connection attempts log stderr from `acpctl` for diagnostics.

## Shutdown Cleanup

An `atexit` hook stops all running sessions when the orchestrator exits — whether cleanly, via exception, or SIGTERM/SIGINT. SIGKILL is unhandleable; `find_orphan` covers that case on next startup.

## Configuration

```yaml
runtime: ambient

ambient:
  project_id: my-project
  repo_url: https://github.com/owner/repo
  acpctl: acpctl              # path to acpctl binary
```

When `runtime: ambient`, the CLI constructs `AmbientRuntime`. The `repo_url` is passed to every session so agents get the repo cloned.

Ambient credentials (API auth) are handled by `acpctl login`. Git credentials for the repo are configured via Ambient's Integrations page (GitHub App or PAT).

## Guidelines Mapping

There is no separate guidelines field on Ambient sessions. The adapter relies on the prompt composer which already concatenates `prompt + guidelines + spec + findings + epilogue` into a single prompt. This complete prompt is passed directly to `create session --prompt`.

## Schema

Our kustomize resources keep `metadata.name` (required by kustomize). The Ambient adapter doesn't sync agents — it only creates sessions — so there's no schema translation needed.

## Error Handling

| Failure | Behavior |
|---|---|
| `acpctl` not on PATH | Fail at startup with clear message |
| Project creation fails | Fail at startup |
| Session creation fails | `spawn()` raises, orchestrator marks task FAILED |
| SSE stream disconnects | Retry with backoff; if exhausted, marks session `failed` |
| Branch not fetchable after RUN_FINISHED | `reap()` returns `Verdict.ERROR` after max retries |
| Session stop fails | Log warning, continue (best-effort cleanup) |

## What This Does NOT Change

- The Runtime port interface — same `Runtime` protocol.
- The orchestrator loop — same serial section, same decide/spawn/poll/reap cycle.
- The domain model — `WorkerHandle`, `WorkerResult`, `Verdict` unchanged.
- The prompt composition model — kustomize still resolves all three layers.
- The review file protocol — workers still write `.hyperloop/state/reviews/` files on their branch.
- The state store — still `GitStateStore` on trunk.
