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
status: not-started    # not-started | in-progress | complete
deps: [task-004]
round: 0
branch: null
pr: null
---

## Spec
(what to build)

## Findings
(appended by orchestrator after each failed round)
```

Status is deliberately minimal. The task is either not started, being worked on, or done. The *phase within the pipeline* is tracked by the orchestrator, not in the task file.

### Worker Result

Written by the worker on its branch (local) or via annotations (ambient). The only thing the orchestrator reads from the worker.

```json
{
  "verdict": "pass",
  "findings": 0,
  "detail": "All tests pass, check scripts pass"
}
```

### Workflow

Defines the pipeline a task moves through. Ships with a default; projects overlay it.

```yaml
kind: Workflow
name: default

pipeline:
  - loop:
      - role: implementer
      - role: verifier
  - action: merge-pr
```

Four primitives:

| Primitive | Behavior |
|---|---|
| `role: X` | Spawn agent with role X. Fail propagates to enclosing loop. |
| `gate: X` | Block until external signal (e.g. human PR approval). |
| `loop` | Wrap steps. On fail, retry from top. On pass, continue. |
| `action: X` | Terminal operation (merge-pr, mark-pr-ready). |

### Agent Definition

Follows the ambient platform resource model. Base definitions ship with the orchestrator. Projects overlay with personas and project-specific rules.

```yaml
kind: Agent
name: implementer
prompt: |
  You are a worker agent. Read ambient.io/persona for identity.
  Read ambient.io/task-spec for your assignment.
  Do the work. Push to your branch.
  Write .worker-result.json with your verdict.
  You do NOT set task status.

annotations:
  ambient.io/persona: ""
  ambient.io/task-spec: ""
  ambient.io/process-overlay: ""
  ambient.io/findings: ""
```

## Prompt Composition

Three layers, composed at spawn time:

| Layer | Source | What it provides | Who writes it |
|---|---|---|---|
| Base | Orchestrator repo `base/` | Protocol (how to behave) | Orchestrator maintainers |
| Project overlay | Project gitops repo `overlays/{project}/` | Persona (who you are) | Project team |
| Process overlay | Target repo `specs/prompts/` | Learned rules (what to watch for) | Process-improver agent |

Composition uses kustomize: `kustomize build overlays/{project}/` merges base + project overlay. The orchestrator then injects process overlay + task context at spawn time.

## PR Lifecycle

PRs are the integration mechanism between workers and trunk.

1. Worker pushes commits to its branch.
2. Orchestrator creates a **draft PR** when the first review phase begins.
3. On review pass, orchestrator marks the PR **ready**.
4. If `auto_merge: true`, orchestrator squash-merges and deletes the branch.
5. If `auto_merge: false`, PR waits for human merge.

The PR accumulates the full history across rounds (every attempt, every fix).

## State Store Interface

```
getWorld()                → tasks, workers, epoch
transitionTask(id, to)    → update status, commit
storeFindings(id, data)   → append findings to task file
getEpoch(key)             → content fingerprint for skip logic
setEpoch(key, value)      → record last-run marker
readFile(path)            → read from trunk
commit(message)           → persist state changes
```

Implementations: `GitStateStore` (reads/writes task files, commits to git), `AmbientStateStore` (reads/writes annotations via API).

## Runtime Interface

```
spawn(task, role, prompt, context)  → WorkerHandle
poll(handle)                        → running | done | failed
reap(handle)                        → WorkerResult
cancel(handle)                      → void
```

Implementations: `LocalRuntime` (git worktrees + tmux + claude CLI), `AmbientRuntime` (ambient platform API — create agent, start session, poll annotations).

## Orchestrator Loop

```
resolve templates (once at startup)

while true:
    reap finished workers
    for each result:
        advance pipeline (next step or retry loop)
        if process-improver needed: run on trunk

    decide what to spawn
        gate: skip if world unchanged since last run
        priority: in-progress > not-started with deps satisfied
        limit: max_parallel workers

    spawn workers
        compose prompt: template + process overlay + task context
        hand to runtime

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
├── spec.md              ← this file
├── base/                ← base agent + workflow definitions
│   ├── workflow.yaml
│   ├── implementer.yaml
│   ├── verifier.yaml
│   └── process-improver.yaml
├── src/                 ← orchestrator code
│   ├── loop.py          ← main loop
│   ├── decide.py        ← pure decision function
│   ├── compose.py       ← prompt composition
│   ├── state/
│   │   ├── interface.py
│   │   └── git.py
│   └── runtime/
│       ├── interface.py
│       ├── local.py
│       └── ambient.py
└── tests/
    └── test_decide.py   ← decision function is pure, fully testable
```

### Target repo (prescribed structure)

```
target-repo/
└── specs/
    ├── tasks/           ← task files (orchestrator writes status)
    ├── reviews/         ← review artifacts (verifier writes)
    └── prompts/         ← process overlays (process-improver writes)
```

### Project gitops repo (optional, for overlay)

```
project-gitops/
└── overlays/{project}/
    ├── kustomization.yaml
    ├── workflow-patch.yaml
    ├── implementer-patch.yaml
    └── verifier-patch.yaml
```
