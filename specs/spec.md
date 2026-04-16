# hyperloop

An orchestrator that turns a backlog of tasks into completed, merged work using AI agents.

## Core Concepts

**The orchestrator has one job:** walk each task through a process pipeline until it reaches a terminal action (e.g. merge). It does not implement, review, or fix code. It spawns agents that do, reads their verdicts, and advances the pipeline.

**Three concerns, separated:**

| Concern | What it does | Swappable |
|---|---|---|
| Decision | Given the world, what actions to take | No (this is the orchestrator) |
| State | Where task/worker state lives | Yes (git, ambient annotations, etc.) |
| Runtime | Where agent sessions execute | Yes (local CLI, ambient platform, etc.) |

**Ownership rule:** Workers report verdicts. The orchestrator decides status transitions. Workers never write task status. This makes the runtime irrelevant to correctness.

## Data Model

### Task

Lives in the target repo at `.hyperloop/state/tasks/task-{id}.md`. Written only by the orchestrator on trunk. Pure metadata — no body content.

```yaml
---
id: task-027
title: Implement Places DB persistent storage
spec_ref: specs/persistence.md    # traceable link to the originating spec
status: not-started               # not-started | in-progress | complete | failed
phase: null                       # current pipeline step (for crash recovery)
deps: [task-004]
round: 0                          # incremented each time the loop restarts
branch: null                      # set by orchestrator before first spawn
pr: null                          # set by orchestrator when draft PR created
---
```

Status is deliberately minimal: not started, being worked on, done, or failed. `phase` tracks where the task is in the pipeline so the orchestrator can resume after a crash. `spec_ref` traces this task back to the spec that originated it. `failed` is a terminal state — the task hit `max_task_rounds` without completing. The orchestrator halts when any task enters `failed`.

### Review

Lives at `.hyperloop/state/reviews/task-{id}-round-{n}.md`. Written by the orchestrator after each failed round. Preserved as historical record (never cleared).

```yaml
---
task_id: task-027
round: 0
role: verifier
verdict: fail
findings: 3
---
Branch deletes 3 files from main that are out-of-scope for task-027...
```

Separating reviews from tasks keeps task files as pure metadata and preserves the full review history across rounds. The process-improver reads review files to identify systemic patterns.

### Worker Result

Written by the worker on its branch (local) or via annotations (ambient). The only thing the orchestrator reads from a worker.

```json
{
  "verdict": "pass",
  "findings": 0,
  "detail": "All tests pass, check scripts pass"
}
```

### Process

Defines the pipelines work moves through. Ships with a default; projects overlay it.

```yaml
kind: Process
name: default

intake:
  - role: pm

pipeline:
  - loop:
      - role: implementer
      - role: verifier
  - action: merge-pr
```

Two pipelines in one process:

- **intake** runs at project level, serially on trunk. Creates tasks from specs (or Jira, or whatever the intake role does). Runs periodically or on-demand, not per-task.
- **pipeline** runs per-task. Workers run in parallel on branches. Processes each task through implementation, review, and merge.

Both use the same primitives.

### Pipeline Primitives

Four primitives:

| Primitive | Behavior |
|---|---|
| `role: X` | Spawn agent with role X. Fail propagates to enclosing loop. |
| `gate: X` | Block until external signal (e.g. human PR approval). |
| `loop` | Wrap steps. On fail, retry from top. On pass, continue. |
| `action: X` | Terminal operation (merge-pr, mark-pr-ready). |

Convention: `on_pass` = next step in list. `on_fail` = restart enclosing loop. These can be explicitly overridden per-step for non-standard routing.

### Gates

Gates block a task's pipeline until an external signal is received. The orchestrator polls for the signal each cycle. Tasks at a gate do not consume a worker slot.

The gate interface is transparent to the signal source, but v1 supports only **PR labels**:

| Gate | Signal | Mechanism |
|---|---|---|
| `human-pr-approval` | `lgtm` label on the task's PR | Orchestrator checks `gh pr view --json labels` each cycle |

When the orchestrator sees the `lgtm` label, the gate clears and the task advances to the next pipeline step. The label is then removed to prevent re-triggering.

Future signal sources (webhooks, CI status, ambient annotations) can be added behind the same interface without changing the process yaml.

### Agent Definition

Follows the ambient platform resource model. Base definitions live in the hyperloop repo, referenced by git URL. Projects overlay with personas and project-specific rules via kustomize patches in a gitops repo.

```yaml
kind: Agent
name: implementer
prompt: |
  You are a worker agent implementing a task.
  Task spec is in the Spec section. Feedback in Findings.
  Project rules in Guidelines. Do the work. Push to your branch.
  Write .worker-result.json with your verdict.
  You do NOT set task status.
guidelines: ""
```

## Traceability

Every artifact traces back to its originating spec through an unbroken chain:

```
spec (specs/*.md)
  └── task (.hyperloop/state/tasks/task-{id}.md)   spec_ref: specs/persistence.md
       ├── reviews (.hyperloop/state/reviews/)     task_id + round + findings
       └── commits (on worker branch)              Spec-Ref: specs/persistence.md
            │                                      Task-Ref: task-027
            └── PR                                 labels: spec/persistence, task/task-027
                 └── merged to trunk               trailers preserved in squash commit
```

### Commit Trailers

Every commit produced by a worker must include git trailers linking back to the spec and task:

```
feat: implement Places DB schema and migration

Spec-Ref: specs/persistence.md
Task-Ref: task-027
```

The orchestrator injects `spec_ref` and `task_id` into the worker's prompt context. The worker's agent definition instructs it to include these as trailers in every commit. The base implementer prompt includes:

```
Include these trailers in every commit message:
  Spec-Ref: {spec_ref}
  Task-Ref: {task_id}
```

### PR Labels

The orchestrator adds labels to the draft PR for traceability:

- `spec/{spec_name}` — derived from `spec_ref` (e.g. `spec/persistence`)
- `task/{task_id}` — the task ID (e.g. `task/task-027`)

### Squash Merge

When using `strategy: squash`, the squash commit message preserves the trailers:

```
feat: implement Places DB persistent storage (#42)

Spec-Ref: specs/persistence.md
Task-Ref: task-027
```

This means `git log --grep="Spec-Ref: specs/persistence.md"` returns every commit that implemented any part of that spec.

## Prompt Composition

Three layers, all resolved via kustomize. See `specs/prompt-composition.md` for full design.

| Layer | Source | Field targeted | Who writes it |
|---|---|---|---|
| Base | hyperloop repo `base/` | `prompt` | Orchestrator maintainers |
| Project overlay | gitops repo or in-repo patches | `guidelines`, `prompt` (can override) | Project team |
| Process overlay | `.hyperloop/agents/process/` | `guidelines` | Process-improver agent |

Agent resources have two text fields: `prompt` (core identity) and `guidelines` (additive rules). All three layers resolve in a single `kustomize build .hyperloop/agents/`. The process overlay is a kustomize Component that patches `guidelines` — additive by convention, replaceable by capability.

At compose time, the orchestrator takes the resolved template and injects:

- `prompt` + `guidelines` (from kustomize build)
- Task spec content (read from `spec_ref`)
- Findings from prior rounds (read from review files)
- Traceability refs (`spec_ref`, `task_id`) for commit trailers

The worker never needs to read the task file — everything it needs arrives in its prompt.

When the process-improver modifies overlay files mid-run, the orchestrator re-runs `kustomize build` before spawning new workers. This is a mechanical guarantee: any agent spawned after a process improvement will see the updated guidelines.

## Concurrency Model

Each orchestrator cycle has a single serial section where all trunk mutations and decisions happen, followed by workers running independently on branches between cycles.

### Serial Section

The orchestrator does all its work sequentially in one pass. No concurrent trunk writers.

1. **Reap** — collect results from finished workers.
2. **Store findings** — append to task files on trunk for all failed tasks.
3. **Process-improver** — runs once, serially, on trunk. Reads ALL findings from the current cycle. Writes `guidelines` overlays to `.hyperloop/agents/process/` and check scripts to `.hyperloop/checks/`. One agent, one pass, consolidated.
4. **Intake** — PM runs on trunk if new specs exist. Creates task files. Rejects dependency cycles.
5. **Merge PRs** — squash-merge any ready PRs. Rebase, resolve conflicts, merge one at a time (see Merge Conflict Handling).
6. **Decide** — determine which tasks to spawn. Create branches from the now-stable HEAD. Compose prompts.
7. **Update state** — transition task statuses and phases on trunk. Commit all state changes.
8. **Spawn** — hand workers to the runtime. From this point, workers run independently on their own branches.

After spawning, the orchestrator sleeps until the next poll interval. Workers push to their own branches — no trunk writes until the next serial section.

### Why Serial

Trunk is a shared mutable resource. Giving it a single writer eliminates:

- Multiple process-improvers clobbering each other's commits.
- Orchestrator commits racing with PR merges.
- Intake creating tasks while findings are being written.
- Workers spawning from a moving HEAD.
- Task phase updates racing with trunk mutations.

Process-improver is NOT a pipeline step — it's an orchestrator-internal serial operation. It runs between reap and spawn, sees all findings from the current cycle at once, and makes a single consolidated improvement pass. It writes `guidelines` overlays to `.hyperloop/agents/process/` and check scripts to `.hyperloop/checks/`. What it improves is defined by its agent definition, which projects can overlay.

## Branch Lifecycle

1. Orchestrator creates the branch (`worker/task-{id}`) from trunk HEAD during the serial section (after merging, before spawning).
2. Worker receives the branch name and pushes commits to it.
3. On subsequent rounds (loop retry), the same branch is reused with accumulated commits.
4. Orchestrator creates a draft PR from the branch when the first verifier step begins.
5. On completion, the PR is merged during the serial section.
6. After merge, the branch is deleted.

For local runtime: orchestrator creates a git worktree on the branch. For ambient runtime: orchestrator creates the branch via git/API, passes the branch name to the agent at spawn time.

## PR Lifecycle

PRs are the integration mechanism between workers and trunk.

1. Worker pushes commits to its branch (with `Spec-Ref` and `Task-Ref` trailers).
2. Orchestrator creates a **draft PR** before the first review step, with spec/task labels.
3. The PR accumulates commits across rounds (every attempt, every fix).
4. On review pass, orchestrator marks the PR **ready**.
5. If `auto_merge: true`, orchestrator squash-merges during the serial section and deletes the branch.
6. If `auto_merge: false`, PR waits for human merge.

### Merge Conflict Handling

When multiple tasks run in parallel, their PRs can conflict. Task A merges, trunk moves, Task B's branch now conflicts.

The orchestrator handles this during the serial section:

1. **Rebase** — orchestrator rebases the branch onto current trunk HEAD.
2. **Clean rebase** — proceed with merge.
3. **Conflict** — orchestrator aborts the rebase, marks the task `needs-rebase`, and defers it. During the spawn step, a **rebase-resolver** agent is spawned for the task:
   - Rebase-resolver is a lightweight, orchestrator-internal agent. Not a pipeline step.
   - It receives: the branch, the conflicting files, and what changed on trunk.
   - Its job is narrow: resolve conflict markers, run tests, push. Not a full implementation round.
   - It runs on the task's branch (not trunk), so it's safe to run in parallel with other workers.
   - Next cycle's serial section re-attempts the rebase + merge.
4. **Repeated conflicts** — if a task has been deferred for `max_rebase_attempts` (default: 3) consecutive cycles, the orchestrator treats it as a pipeline failure and sends the task back through the loop with conflict details as findings.

Merge order: the serial section merges PRs one at a time, rebasing each onto the new HEAD after the previous merge. Merges in task dependency order when possible, falling back to completion order.

## Findings Flow

Findings serve two purposes: persistent audit trail and worker context.

1. Verifier fails and reports findings in its `WorkerResult`.
2. Orchestrator writes findings to `.hyperloop/state/reviews/task-{id}-round-{n}.md` on trunk during the serial section.
3. On next spawn, orchestrator reads the latest review file and injects findings into the worker's prompt context.
4. Worker receives findings as prompt content — it never reads the task or review files.
5. On task completion, review files are preserved as historical record (not cleared).
6. Process-improver reads all review files from the current cycle to identify systemic patterns.

The review file is the ledger. Prompt injection is the delivery.

## Recovery

The orchestrator can crash and restart without losing progress.

**What is persisted (survives crash):**
- Task status and phase — in `.hyperloop/state/tasks/` on trunk
- Branch with accumulated commits — in git
- Draft PR with labels — on GitHub
- Review findings — in `.hyperloop/state/reviews/` on trunk
- Traceability (spec_ref, trailers, labels) — in git + GitHub

**What is ephemeral (lost on crash, reconstructed):**
- Worker handles (process IDs, agent IDs)

**Recovery procedure:**

1. Read `.hyperloop/state/tasks/*.md` from trunk → know all task statuses and phases.
2. List open draft PRs with orchestrator labels → find in-flight work.
3. **Check for orphaned workers** — before spawning, verify no worker is already active for a task:
   - Local runtime: check if worktree/process exists for the branch.
   - Ambient runtime: check if an agent with this task's label already exists.
   - If an orphaned worker is found: cancel it via the runtime before re-spawning.
4. For each task with `status: in-progress`:
   a. Has a `phase` set? → resume from that phase (after clearing orphans).
   b. Has a branch with commits but no PR? → re-spawn on same branch.
   c. Has an open draft PR? → re-run current phase (verifier, etc.).
   d. No branch? → start fresh.
5. Resume normal loop.

## State Store Interface

```
getWorld()                → tasks, workers, epoch
getTask(id)               → single task with status, phase, spec_ref
transitionTask(id, status, phase) → update status + phase
storeReview(id, round, review) → write review file to .hyperloop/state/reviews/
getFindings(id)           → read latest review findings for prompt injection
getEpoch(key)             → content fingerprint for skip logic
setEpoch(key, value)      → record last-run marker
readFile(path)            → read from trunk
commit(message)           → persist state changes
```

Implementations: `GitStateStore` (reads/writes files in `.hyperloop/state/`, commits to git), `AmbientStateStore` (reads/writes annotations via API).

## Runtime Interface

```
spawn(task, role, prompt, branch)  → WorkerHandle
poll(handle)                       → running | done | failed
reap(handle)                       → WorkerResult
cancel(handle)                     → void
findOrphan(task, branch)           → WorkerHandle | null  (for crash recovery)
```

Implementations: `LocalRuntime` (git worktrees + CLI), `AmbientRuntime` (ambient platform API — create agent, start session, poll annotations).

## Orchestrator Loop

```
startup:
    read .hyperloop.yaml from target repo
    kustomize build .hyperloop/agents/ → resolved templates
    recovery (if resuming):
        read task files → reconstruct in-flight state
        match open PRs to tasks → recover phase
        check for orphaned workers → cancel before re-spawning
        validate dependency graph → reject cycles

while true:
    ┌── serial (all orchestrator work) ───────────────────────┐
    │                                                         │
    │  1. reap finished workers                               │
    │     for each result:                                    │
    │         if pass: advance to next pipeline step          │
    │         if fail: store findings on trunk                │
    │         if task.round >= max_task_rounds: → failed      │
    │                                                         │
    │  2. if any task failed → halt (needs human attention)   │
    │                                                         │
    │  3. if any failures this cycle:                         │
    │         run process-improver ONCE on trunk              │
    │         (reads all findings, writes guidelines/checks)  │
    │         re-run kustomize build to pick up changes       │
    │                                                         │
    │  4. run intake if configured + new specs exist          │
    │         (creates task files, rejects dep cycles)        │
    │                                                         │
    │  5. poll gates                                          │
    │         for tasks at a gate: check PR labels            │
    │         if lgtm label found: clear gate, advance task   │
    │                                                         │
    │  6. merge ready PRs (one at a time, dep order):         │
    │         rebase branch onto HEAD                         │
    │         if clean: squash-merge, preserve trailers       │
    │         if conflict: mark needs-rebase, defer           │
    │         if deferred > max_rebase_attempts:              │
    │             store as findings, loop task back            │
    │                                                         │
    │  7. decide what to spawn                                │
    │         priority: in-progress > not-started w/ deps met │
    │         include: needs-rebase tasks (rebase-resolver)   │
    │         limit: max_workers                              │
    │         create branches from stable HEAD                │
    │         compose prompts (template + guidelines + context)│
    │         inject spec_ref + task_id for trailers          │
    │                                                         │
    │  8. update state                                        │
    │         transition task statuses + phases on trunk      │
    │         commit all state changes                        │
    │                                                         │
    │  9. spawn workers (hand to runtime)                     │
    │                                                         │
    └─────────────────────────────────────────────────────────┘

    check convergence
        all tasks complete + no active workers → halt

    sleep(poll_interval)
    (workers run independently on branches between cycles)
```

## Configuration

The target repo contains a `.hyperloop.yaml` file:

```yaml
# Points to a kustomization directory — kustomize build resolves base + overlay
overlay: git@gitlab.cee.redhat.com:hyperfleet/gitops//overlays/api

target:
  repo: owner/repo
  base_branch: main
  specs_dir: specs

runtime:
  default: local         # local | ambient
  max_workers: 6

merge:
  auto_merge: true
  strategy: squash
  delete_branch: true

poll_interval: 30
max_task_rounds: 50
max_cycles: 200
max_rebase_attempts: 3
```

### Adoption Levels

All levels require `hyperloop init` first. See `specs/prompt-composition.md`.

**Level 1 — base only:**

```bash
hyperloop init
hyperloop run
```

`hyperloop init` scaffolds `.hyperloop/agents/` pointing at the base. Base prompts, default process. Process-improver can start learning immediately.

**Level 2 — project overlay via gitops:**

```bash
hyperloop init --overlay github.com/org/hyperfleet-gitops//overlays/api?ref=main
hyperloop run
```

`.hyperloop/agents/kustomization.yaml` references the gitops overlay (which references the base internally). Persona, custom pipeline, project-specific guidelines — all resolved by kustomize.

## Directory Structure

### Orchestrator repo (this repo)

```
hyperloop/
├── specs/
│   └── spec.md              ← this file
├── base/                    ← base agent + process definitions
│   ├── process.yaml           referenced by gitops repos via kustomize remote resource
│   ├── implementer.yaml       (github.com/org/hyperloop//base?ref=v1.2.0)
│   ├── verifier.yaml
│   ├── process-improver.yaml
│   ├── rebase-resolver.yaml
│   └── pm.yaml
├── src/                     ← orchestrator engine (installed via pip/uvx)
│   ├── loop.py              ← main loop (serial section) + recovery
│   ├── decide.py            ← pure decision function
│   ├── compose.py           ← spawn-time injection (layer 3 + task context)
│   ├── pipeline.py          ← pipeline executor (recursive, handles loops)
│   ├── state/
│   │   ├── interface.py
│   │   └── git.py
│   └── runtime/
│       ├── interface.py
│       ├── local.py
│       └── ambient.py
└── tests/
    ├── test_decide.py       ← decision function is pure, fully testable
    └── test_pipeline.py     ← pipeline execution against mock runtime
```

The `base/` directory is not bundled into the pip package. It lives in the repo and is referenced by gitops repos via kustomize remote resources. This decouples prompt evolution from tool releases.

### Target repo (prescribed structure)

Created by `hyperloop init`. See `specs/prompt-composition.md` for full details.

```
target-repo/
├── .hyperloop.yaml          ← orchestrator config
├── .hyperloop/
│   ├── agents/              ← kustomize composition point (all 3 layers resolve here)
│   │   ├── kustomization.yaml
│   │   └── process/         ← kustomize Component (process-improver writes here)
│   │       └── kustomization.yaml
│   ├── state/
│   │   ├── tasks/           ← task metadata (orchestrator writes on trunk)
│   │   │   └── task-*.md
│   │   └── reviews/         ← review findings (orchestrator writes on trunk)
│   │       └── task-{id}-round-{n}.md
│   └── checks/              ← executable validations (process-improver writes on trunk)
│       └── *.sh
└── specs/
    └── *.md                 ← product specs only (human-written, referenced by spec_ref)
```

### Project gitops repo (level 3 adoption)

```
project-gitops/
└── overlays/{project}/
    ├── kustomization.yaml            ← references hyperloop//base as remote resource
    ├── process-patch.yaml            ← replaces pipeline list
    ├── implementer-patch.yaml        ← injects persona
    ├── verifier-patch.yaml
    └── process-improver-patch.yaml
```
