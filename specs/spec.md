# k-orchestrate

An orchestrator that turns a backlog of tasks into completed, merged work using AI agents.

## Core Concepts

**The orchestrator has one job:** walk each task through a workflow pipeline until it reaches a terminal action (e.g. merge). It does not implement, review, or fix code. It spawns agents that do, reads their verdicts, and advances the pipeline.

**Three concerns, separated:**

| Concern | What it does | Swappable |
|---|---|---|
| Decision | Given the world, what actions to take | No (this is the orchestrator) |
| State | Where task/worker state lives | Yes (git, ambient annotations, etc.) |
| Runtime | Where agent sessions execute | Yes (local CLI, ambient platform, etc.) |

**Ownership rule:** Workers report verdicts. The orchestrator decides status transitions. Workers never write task status. This makes the runtime irrelevant to correctness.

## Data Model

### Task

Lives in the target repo at `specs/tasks/task-{id}.md`. Written only by the orchestrator on trunk.

```yaml
---
id: task-027
title: Implement Places DB persistent storage
spec_ref: specs/persistence.md    # traceable link to the originating spec
status: not-started               # not-started | in-progress | complete
phase: null                       # current pipeline step (for crash recovery)
deps: [task-004]
round: 0                          # incremented each time the loop restarts
branch: null                      # set by orchestrator before first spawn
pr: null                          # set by orchestrator when draft PR created
---

## Spec
(what to build — written by PM or human)

## Findings
(appended by orchestrator after each failed round, cleared on completion)
```

Status is deliberately minimal: not started, being worked on, or done. `phase` tracks where the task is in the pipeline so the orchestrator can resume after a crash. `spec_ref` traces this task back to the spec that originated it.

### Worker Result

Written by the worker on its branch (local) or via annotations (ambient). The only thing the orchestrator reads from a worker.

```json
{
  "verdict": "pass",
  "findings": 0,
  "detail": "All tests pass, check scripts pass"
}
```

### Workflow

Defines the pipelines work moves through. Ships with a default; projects overlay it.

```yaml
kind: Workflow
name: default

intake:
  - role: pm
    input: specs

pipeline:
  - loop:
      - role: implementer
      - role: verifier
  - action: merge-pr
```

Two pipelines in one workflow:

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

### Agent Definition

Follows the ambient platform resource model. Base definitions ship with the orchestrator. Projects overlay with personas and project-specific rules.

```yaml
kind: Agent
name: implementer
prompt: |
  You are a worker agent. Read ambient.io/persona for identity.
  Read ambient.io/task-spec for your assignment.
  Read ambient.io/findings for prior review feedback.
  Do the work. Push to your branch.
  Write .worker-result.json with your verdict.
  You do NOT set task status.

annotations:
  ambient.io/persona: ""
  ambient.io/task-spec: ""
  ambient.io/process-overlay: ""
  ambient.io/findings: ""
```

## Traceability

Every artifact traces back to its originating spec through an unbroken chain:

```
spec (specs/*.md)
  └── task (specs/tasks/task-{id}.md)     spec_ref: specs/persistence.md
       └── commits (on worker branch)     Spec-Ref: specs/persistence.md
            │                             Task-Ref: task-027
            └── PR                        labels: spec/persistence, task/task-027
                 └── merged to trunk      trailers preserved in squash commit
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

Three layers, composed at spawn time:

| Layer | Source | What it provides | Who writes it |
|---|---|---|---|
| Base | Orchestrator repo `base/` | Protocol (how to behave) | Orchestrator maintainers |
| Project overlay | Project gitops repo `overlays/{project}/` | Persona (who you are) | Project team |
| Process overlay | Target repo `specs/prompts/` | Learned rules (what to watch for) | Process-improver agent |

Composition uses kustomize: `kustomize build overlays/{project}/` merges base + project overlay into resolved templates (done once at startup, re-resolved when gitops changes). The orchestrator injects process overlay + task context at spawn time.

Task context (spec + findings + traceability refs) is injected per-spawn. Findings are read from the task file on trunk, not from the worker's branch. The worker never needs to read the task file — everything it needs arrives in its prompt.

## Concurrency Model

The orchestrator loop has two phases per cycle: a serial phase and a parallel phase. This eliminates races on trunk.

### Serial Phase (trunk writes)

All trunk mutations happen here, sequentially. No workers are running against trunk during this phase.

1. **Reap** — collect results from finished workers.
2. **Store findings** — append to task files on trunk for all failed tasks.
3. **Process-improver** — runs once, serially, on trunk. Reads ALL findings from the current cycle. Improves prompts/checklists/check-scripts in `specs/prompts/`. One agent, one pass, consolidated.
4. **Intake** — PM runs on trunk if new specs exist. Creates task files.
5. **Merge PRs** — squash-merge any ready PRs. Trunk HEAD advances.
6. **Transition tasks** — update status/phase fields in task files.
7. **Commit** — single commit for all orchestrator state changes.

After this phase, trunk HEAD is stable and known.

### Parallel Phase (branch writes only)

Workers run in parallel, each on its own branch. No trunk writes happen during this phase.

1. **Create branches** — from the now-stable trunk HEAD.
2. **Compose prompts** — read templates + process overlay + task context from trunk.
3. **Spawn workers** — hand to runtime. Workers push to their own branches only.
4. **Poll** — wait for workers to complete (or until next cycle).

### Why This Split

Trunk is a shared mutable resource. The serial phase gives it a single writer. The parallel phase never touches it. This eliminates:

- Multiple process-improvers clobbering each other's commits.
- Orchestrator commits racing with PR merges.
- Intake creating tasks while findings are being written.
- Workers spawning from a moving HEAD.

Process-improver is NOT a pipeline step — it's an orchestrator-internal serial operation. It runs between reap and spawn, sees all findings from the current cycle at once, and makes a single consolidated improvement pass. What it improves is defined by its agent definition, which projects can overlay.

## Branch Lifecycle

1. Orchestrator creates the branch (`worker/task-{id}`) from trunk HEAD during the parallel phase.
2. Worker receives the branch name and pushes commits to it.
3. On subsequent rounds (loop retry), the same branch is reused with accumulated commits.
4. Orchestrator creates a draft PR from the branch when the first verifier step begins.
5. On completion, the PR is merged during the serial phase.
6. After merge, the branch is deleted.

For local runtime: orchestrator creates a git worktree on the branch. For ambient runtime: orchestrator creates the branch via git/API, passes the branch name to the agent at spawn time.

## PR Lifecycle

PRs are the integration mechanism between workers and trunk.

1. Worker pushes commits to its branch (with `Spec-Ref` and `Task-Ref` trailers).
2. Orchestrator creates a **draft PR** before the first review step, with spec/task labels.
3. The PR accumulates commits across rounds (every attempt, every fix).
4. On review pass, orchestrator marks the PR **ready**.
5. If `auto_merge: true`, orchestrator squash-merges during the serial phase and deletes the branch.
6. If `auto_merge: false`, PR waits for human merge.

## Findings Flow

Findings serve two purposes: persistent audit trail and worker context.

1. Verifier fails and reports findings in its `WorkerResult`.
2. Orchestrator appends findings to the task file's `## Findings` section on trunk during the serial phase.
3. On next spawn, orchestrator reads findings from the task file and injects them into the worker's prompt context.
4. Worker receives findings as prompt content — it never reads the task file or rebases to get them.
5. On task completion, findings section is cleared.

The task file is the ledger. Prompt injection is the delivery.

## Recovery

The orchestrator can crash and restart without losing progress.

**What is persisted (survives crash):**
- Task status and phase — in task file on trunk
- Branch with accumulated commits — in git
- Draft PR with labels — on GitHub
- Findings — in task file on trunk
- Traceability (spec_ref, trailers, labels) — in git + GitHub

**What is ephemeral (lost on crash, reconstructed):**
- Worker handles (process IDs, agent IDs)

**Recovery procedure:**

1. Read `specs/tasks/*.md` from trunk → know all task statuses and phases.
2. List open draft PRs with orchestrator labels → find in-flight work.
3. For each task with `status: in-progress`:
   a. Has a `phase` set? → resume from that phase.
   b. Has a branch with commits but no PR? → worker died mid-work, re-spawn on same branch.
   c. Has an open draft PR? → re-run current phase (verifier, etc.).
   d. No branch? → start fresh.
4. Resume normal loop.

## State Store Interface

```
getWorld()                → tasks, workers, epoch
getTask(id)               → single task with status, phase, spec_ref, findings
transitionTask(id, status, phase) → update status + phase, commit
storeFindings(id, data)   → append findings to task file on trunk
clearFindings(id)         → clear findings section on completion
getEpoch(key)             → content fingerprint for skip logic
setEpoch(key, value)      → record last-run marker
readFile(path)            → read from trunk
commit(message)           → persist state changes
```

Implementations: `GitStateStore` (reads/writes task files, commits to git), `AmbientStateStore` (reads/writes annotations via API).

## Runtime Interface

```
spawn(task, role, prompt, branch)  → WorkerHandle
poll(handle)                       → running | done | failed
reap(handle)                       → WorkerResult
cancel(handle)                     → void
```

Implementations: `LocalRuntime` (git worktrees + CLI), `AmbientRuntime` (ambient platform API — create agent, start session, poll annotations).

## Orchestrator Loop

```
resolve templates (once at startup, re-resolve on gitops change)

recovery:
    read task files → reconstruct in-flight state
    match open PRs to tasks → recover phase

while true:
    ┌── serial phase (trunk writes) ──────────────────────────┐
    │                                                         │
    │  reap finished workers                                  │
    │  for each result:                                       │
    │      if pass: advance to next pipeline step             │
    │      if fail: store findings on trunk                   │
    │                                                         │
    │  if any failures this cycle:                            │
    │      run process-improver ONCE on trunk                 │
    │      (reads all findings, improves prompts)             │
    │                                                         │
    │  run intake if configured + new specs exist             │
    │      (creates task files on trunk)                      │
    │                                                         │
    │  merge any ready PRs (squash, preserve trailers)        │
    │  transition task statuses + phases                      │
    │  commit all state changes                               │
    │                                                         │
    └─────────────────────────────────────────────────────────┘
    trunk HEAD is now stable

    ┌── parallel phase (branch writes only) ──────────────────┐
    │                                                         │
    │  decide what to spawn                                   │
    │      priority: in-progress > not-started with deps met  │
    │      limit: max_parallel workers                        │
    │                                                         │
    │  for each task to spawn:                                │
    │      create branch from HEAD if needed                  │
    │      compose prompt (template + overlay + context)      │
    │      inject spec_ref + task_id for commit trailers      │
    │      spawn via runtime                                  │
    │      update task phase                                  │
    │                                                         │
    └─────────────────────────────────────────────────────────┘

    check convergence
        all tasks complete + no active workers → halt

    sleep(poll_interval)
```

## Configuration

```yaml
target:
  repo: owner/repo
  base_branch: dev
  specs_dir: specs

runtime:
  default: local         # local | ambient
  max_workers: 6

merge:
  auto_merge: true
  strategy: squash
  delete_branch: true

poll_interval: 30
max_rounds: 50
```

## Directory Structure

### Orchestrator repo (this repo)

```
k-orchestrate/
├── specs/
│   └── spec.md          ← this file
├── base/                ← base agent + workflow definitions
│   ├── workflow.yaml
│   ├── implementer.yaml
│   ├── verifier.yaml
│   ├── process-improver.yaml
│   └── pm.yaml
├── src/                 ← orchestrator code
│   ├── loop.py          ← main loop (serial/parallel phases) + recovery
│   ├── decide.py        ← pure decision function
│   ├── compose.py       ← prompt composition (kustomize + injection)
│   ├── pipeline.py      ← pipeline executor (recursive, handles loops)
│   ├── state/
│   │   ├── interface.py
│   │   └── git.py
│   └── runtime/
│       ├── interface.py
│       ├── local.py
│       └── ambient.py
└── tests/
    ├── test_decide.py   ← decision function is pure, fully testable
    └── test_pipeline.py ← pipeline execution against mock runtime
```

### Target repo (prescribed structure)

```
target-repo/
└── specs/
    ├── *.md             ← product specs (human-written, referenced by spec_ref)
    ├── tasks/           ← task files (orchestrator writes status + findings)
    ├── reviews/         ← review artifacts (verifier writes on branch)
    └── prompts/         ← process overlays (process-improver writes on trunk)
```

### Project gitops repo (optional, for overlay)

```
project-gitops/
└── overlays/{project}/
    ├── kustomization.yaml
    ├── workflow-patch.yaml         ← replaces pipeline list
    ├── implementer-patch.yaml      ← injects persona
    ├── verifier-patch.yaml
    └── process-improver-patch.yaml
```
