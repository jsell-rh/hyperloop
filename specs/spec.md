# hyperloop

A reconciler that keeps code in sync with specs using AI agents. Specs are desired state. Code is actual state. Hyperloop continuously closes the gap.

## Core Concepts

**Hyperloop is a reconciler, not a task runner.** Its job is to make the code match the specs. Tasks are an internal implementation detail — like Kubernetes pods. You don't manage pods, you manage Deployments. You don't manage tasks, you manage specs.

**Hyperloop is a control plane.** It does not run inside any particular repo or environment. It connects to spec sources, state stores, and runtimes through ports. The default adapter set is git-native, but the architecture is agnostic.

**Specs are desired state.** All change requests — from Jira, GitHub Issues, or humans — flow through spec files. Want to add a feature? Update the spec. Want to cancel a feature? Remove it from the spec. Everything flows from specs.

**The reconciliation loop:**

```
Spec (desired) ←→ Code (actual) = Gap
Gap → Work (ephemeral) → PR → Gate → Merge → Gap closed
```

The orchestrator detects gaps between specs and code, creates work to close them, drives that work through a pipeline, and merges the result. If work fails, the gap persists and new work is created. The system converges when there are no gaps.

**Seven concerns, separated:**

| Concern | What it does | Swappable |
|---|---|---|
| Decision | Given the world, what actions to take | No (this is the orchestrator) |
| Specs | Where to read desired state | Yes (`SpecSource` port) |
| State | Where task/worker state lives | Yes (`StateStore` port) |
| Runtime | Where agent sessions execute | Yes (`Runtime` port) |
| Gate | How gates are evaluated | Yes (`GatePort` port) |
| Action | How pipeline actions execute | Yes (`ActionPort` port) |
| Notification | How humans are told to act | Yes (`NotificationPort` port) |

**Ownership rule:** Workers report verdicts. The orchestrator decides status transitions. Workers never write task status. This makes the runtime irrelevant to correctness.

## Reconciliation Model

### Specs are config, code is state

The analogy to Kubernetes is intentional:

| Kubernetes | Hyperloop |
|---|---|
| Deployment YAML | Spec file |
| Running pods | In-flight tasks / workers |
| Desired replicas vs actual | Spec requirements vs implemented code |
| Controller reconciliation loop | Orchestrator cycle |
| Pod failure → controller creates new pod | Task failure → gap persists → new work created |

### Failure is feedback, not terminal

When work fails — a task hits max rounds, a PR is rejected, a merge conflicts repeatedly — the gap between spec and code still exists. The orchestrator doesn't halt. It creates new work to close the gap, potentially with different context (updated guidelines from the process-improver, findings from prior attempts).

A task's `failed` status means "this attempt at closing the gap didn't work." The gap itself is tracked by the existence of the spec requirement and the absence of its implementation.

### Closing a PR is corrective, not destructive

When a human closes a PR (rejects the approach), the orchestrator doesn't treat it as a fatal error. The gap still exists. The system creates new work to close it — with the rejection as context. The human is saying "not THIS approach," not "don't do anything."

**Feedback flow:** When the orchestrator detects a PR is CLOSED, it reads the PR's comments and review comments, then stores them as a review finding:

```yaml
---
task_id: task-027
round: 0
role: human
verdict: fail
---
PR #4 was closed. Human feedback:
"This approach adds a new dependency we don't want.
 Use the existing auth module instead."
```

The gap re-enters intake. The PM creates a new task for the same gap. The next implementer's prompt includes the human's feedback as prior findings — the agent sees why the previous approach was rejected and tries differently.

If the human closed without a comment, the findings record "PR was closed without feedback." The next attempt has less context but the process-improver may have updated guidelines from the pattern.

The only way to stop work on a gap: change the spec. Remove the requirement, or mark it as deferred. The spec is the single control surface.

### Loop prevention

There is no formal "gap counter." The PM agent IS the loop-breaker. It receives the full failure history in its prompt context — reviews from prior attempts, findings, human feedback from closed PRs. After seeing multiple failures for the same spec area, the PM either proposes a different approach or stops proposing work (signaling the gap needs human attention).

Individual tasks are bounded by `max_task_rounds` — a task that exceeds this limit fails. If the PM creates a new task for the same gap, it's a fresh task with fresh rounds, but with all prior failure context. The process-improver also learns from repeated failures and updates guidelines.

## Data Model

### Task

Internal bookkeeping — not a user-facing concept. Persisted via `StateStore`. Written only by the orchestrator.

```yaml
id: task-027
title: Implement Places DB persistent storage
spec_ref: specs/persistence.md@abc123   # spec file @ version identifier
status: not-started                     # not-started | in-progress | complete | failed
phase: null                             # current pipeline step (for crash recovery)
deps: [task-004]
round: 0                                # incremented each time the loop restarts
branch: null
pr: null
```

`spec_ref` pins the spec version this task was scoped to. `failed` means this attempt didn't work — the gap is still open. A failed task does NOT halt the orchestrator.

### spec_ref versioning

```
specs/persistence.md@abc123
```

The version identifier is captured at intake time. The prompt composer reads the spec at that version, not the latest. If the spec changes while tasks are in flight, existing tasks finish against their pinned version. New tasks are created for the new version's gaps.

### Review

Written after each failed round. Preserved as history — informs future attempts at the same gap.

```yaml
task_id: task-027
round: 0
role: verifier
verdict: fail
---
Branch deletes 3 files from main that are out-of-scope for task-027...
```

Reviews are the institutional memory of the project. They must be durable and auditable — queryable across time.

### Worker Result

The only thing the orchestrator reads from a worker:

```python
@dataclass(frozen=True)
class WorkerResult:
    verdict: Verdict        # PASS or FAIL
    detail: str             # free-text summary from the worker
```

### Task Proposal

Value object produced by the PM agent during intake:

```python
@dataclass(frozen=True)
class TaskProposal:
    title: str
    spec_ref: str           # "specs/widget.md@abc123"
    deps: tuple[str, ...]
```

## Pipeline DSL

Users define the pipeline that work moves through in `process.yaml`:

```yaml
pipeline:
  - loop:
      - agent: implementer
      - agent: verifier
  - gate: human-pr-approval
  - action: merge-pr

gates:
  human-pr-approval:
    type: label

actions:
  merge-pr:
    type: pr-merge

hooks:
  after_reap:
    - type: process-improver
```

### Primitives

| Primitive | What happens | Who executes |
|---|---|---|
| `agent: X` | Spawn a worker agent with X's prompt template | Runtime |
| `gate: X` | Block until external signal | GatePort adapter |
| `action: X` | Execute an operation | ActionPort adapter |
| `loop:` | Wrap agent steps — on fail restart from top, on pass continue | Pipeline executor (pure logic) |

The pipeline is a state machine. The orchestrator calls `PipelineExecutor.advance(position, result)` and receives back what the next step is. The pipeline executor is a pure function with no I/O.

Actions can appear anywhere in the pipeline, not just at the end. After SUCCESS, the pipeline advances to whatever comes next.

### Agent definitions

Agent prompts come through the kustomize template system. See `specs/prompt-composition.md`.

```yaml
apiVersion: hyperloop.io/v1
kind: Agent
metadata:
  name: implementer
prompt: |
  You are a worker agent implementing a task...
guidelines: ""
```

## Cycle

The orchestrator runs a fixed reconciliation loop with four phases:

```
while true:
    1. COLLECT   — reap finished workers, run cycle hooks
    2. INTAKE    — detect spec gaps, create work to close them
    3. ADVANCE   — advance existing work through pipeline steps
    4. SPAWN     — decide what to spawn, spawn workers
    persist state
    sync with remote (pull then push — ensures trunk is current before workers branch)
    if no gaps remain → halt
    otherwise → sleep and repeat
```

### COLLECT

Poll every running worker. If done, reap its `WorkerResult`. Build a map of `task_id → WorkerResult`.

If any results were reaped and cycle hooks are configured, call each hook's `after_reap(results)`. This runs BEFORE INTAKE, ADVANCE, and SPAWN — guideline changes from the process-improver are visible to workers spawned in the same cycle.

### INTAKE

Detect gaps and create work to close them. Intake fires when either trigger is present:

- **Spec changes** — specs changed since the last-processed version
- **Task failures** — tasks failed since the last intake run

If neither trigger is present, INTAKE is skipped (no PM invocation).

When triggered, a single PM invocation receives both as context:

1. **Detection (mechanical):** Identify spec changes (via `SpecSource.detect_changes()`) and recently failed tasks (from `StateStore`).
2. **Analysis (agent):** The PM agent reads the spec diffs, failure history, current tasks, and scoped codebase context. It proposes tasks scoped to the gaps — either new work from spec changes or reattempts for failed work with a different approach.
3. **Creation (mechanical):** The orchestrator parses the PM's structured output as `TaskProposal[]` and creates tasks with `spec_ref@version` pinning.

On the first run with no prior version, all specs are treated as new.

Intake is its own phase because it creates new tasks (write). ADVANCE only reads and advances existing tasks.

### PM agent interface

The PM agent uses the same `Runtime` port as any other agent. The contract for its output is runtime-specific:

- **Local runtime:** PM returns structured JSON (via structured output) containing `TaskProposal[]`. The orchestrator parses the JSON.
- **Ambient runtime:** PM writes proposals as annotations. The orchestrator reads them via the ambient API.

The PM's prompt template lives at `base/pm.yaml` and is overridable via kustomize, like any other agent.

### ADVANCE

For each existing task, check its current pipeline position:

- **Has a WorkerResult?** Feed to pipeline executor → returns next step (`SpawnAgent`, `WaitForGate`, `PerformAction`, `PipelineComplete`, `PipelineFailed`). Update phase.
- **At a `gate:` step?** Call `GatePort.check(task, gate_name)`. Cleared → advance. Not cleared → skip. On first entry, call `NotificationPort.gate_blocked()`.
- **At an `action:` step?** Call `ActionPort.execute(task, action_name)`:
  - SUCCESS → advance to next step (or COMPLETE if last)
  - RETRY → stay, try again next cycle
  - ERROR → increment `error_attempts[task]`, loop back after max

### SPAWN

`decide(world)` — pure function examining all tasks, dependencies, and running workers — returns a list of `SpawnWorker` actions. Compose prompts, call `Runtime.spawn()`. Workers run in the background until next COLLECT.

### Halt condition

The orchestrator halts when there are no open gaps: all tasks are terminal (COMPLETE or FAILED with no re-intake pending) and no spec changes are pending.

For continuous operation: `hyperloop watch`. Suppresses halting — sleeps and re-checks for spec changes each cycle.

### Why serial

The reconciliation state is a shared mutable resource. A single writer per cycle eliminates races between state transitions, result merges, intake, and worker spawns.

## Ports

### SpecSource

```python
class SpecSource(Protocol):
    def detect_changes(self, since: str | None) -> list[SpecChange]:
        """Return spec files that changed since the given version marker.
        If since is None (first run), return all specs."""
        ...

    def read(self, spec_ref: str) -> str:
        """Read spec content at a pinned version (e.g. path@sha)."""
        ...

    def current_version(self) -> str:
        """Return the current version marker (for tracking last-processed)."""
        ...
```

The port that connects the reconciler to desired state. The orchestrator calls `detect_changes()` during INTAKE and `read()` during prompt composition.

### StateStore

```python
class StateStore(Protocol):
    def get_world(self) -> World: ...
    def get_task(self, task_id: str) -> Task: ...
    def add_task(self, task: Task) -> None: ...
    def transition_task(self, task_id: str, status: TaskStatus, phase: Phase | None) -> None: ...
    def store_review(self, task_id: str, round: int, role: str, verdict: str, detail: str) -> None: ...
    def get_findings(self, task_id: str) -> str: ...
    def persist(self, message: str) -> None: ...
    def sync(self) -> None: ...
```

The port for durable reconciliation state. State must be:

- **Durable** — survives orchestrator crashes
- **Shared** — synced with remote so workers branch from current trunk
- **Auditable** — review history is queryable across time

### GatePort

```python
class GatePort(Protocol):
    def check(self, task: Task, gate_name: str) -> bool:
        """Return True if the gate is cleared for this task."""
        ...
```

Gates block until an external signal is received. Tasks at a gate do not consume a worker slot.

Adapters:

| Adapter | Signal | Mechanism |
|---|---|---|
| `LabelGate` | `lgtm` label on PR | Checks PR labels. Default. |
| `PRApprovalGate` | GitHub PR approved review | Checks review status. |
| `CIStatusGate` | All required CI checks pass | Checks status rollup. |
| `AllGate` | Multiple conditions (AND) | Clears when ALL child gates clear. |

Gates can be combined — a single gate requiring both label AND CI:

```yaml
gates:
  human-pr-approval:
    type: all
    require:
      - type: label
      - type: ci-status
```

### ActionPort

```python
class ActionOutcome(Enum):
    SUCCESS = "success"
    RETRY = "retry"
    ERROR = "error"

@dataclass(frozen=True)
class ActionResult:
    outcome: ActionOutcome
    detail: str
    pr_url: str | None = None   # if set, orchestrator updates task.pr

class ActionPort(Protocol):
    def execute(self, task: Task, action_name: str) -> ActionResult:
        """Execute an action for a task."""
        ...
```

| Outcome | Meaning | Orchestrator action |
|---|---|---|
| SUCCESS | Action completed | Advance to next pipeline step |
| RETRY | Transient failure | Stay, try next cycle. No counter. |
| ERROR | Needs intervention | Increment `error_attempts[task]`. After max, loop back. |

Adapter boundary:

- **Orchestrator owns:** dependency ordering, attempt tracking, status/phase transitions, applying metadata from `ActionResult`.
- **Adapter owns:** all mechanics. Returns metadata via `ActionResult`. Never reads or writes `StateStore`.

### NotificationPort

```python
class NotificationPort(Protocol):
    def gate_blocked(self, *, task: Task, gate_name: str) -> None:
        """A task is waiting for human action at a gate."""
        ...

    def task_errored(self, *, task: Task, attempts: int, detail: str) -> None:
        """A task hit max errors and needs investigation."""
        ...
```

Notifications fire **once** per state entry, not every cycle. The orchestrator deduplicates.

### CycleHook

```python
class CycleHook(Protocol):
    def after_reap(
        self, *, results: dict[str, WorkerResult], cycle: int
    ) -> None:
        """Called after all workers are reaped, with all results."""
        ...
```

Extension point for cross-cutting concerns needing all cycle results. The process-improver is a `CycleHook` adapter. Config accepts a list of hooks.

### Existing ports

| Port | Purpose |
|---|---|
| `Runtime` | Agent execution. Workers run independently, push results to branches. |
| `PRPort` | PR lifecycle (create, rebase, merge). Used by gate and action adapters. |
| `OrchestratorProbe` | Domain observability (structured events). |

## Traceability

Every artifact traces back to its originating spec:

```
spec
  └── task (spec_ref pinned)
       ├── reviews (round history)
       └── commits (Spec-Ref + Task-Ref trailers)
            └── PR (spec + task labels)
                 └── merged (trailers preserved in squash commit)
```

`git log --grep="Spec-Ref: specs/persistence.md"` returns every commit that implemented any part of that spec.

## Prompt Composition

Three layers, all resolved via kustomize. See `specs/prompt-composition.md`.

| Layer | Source | Field targeted | Who writes it |
|---|---|---|---|
| Base | hyperloop repo `base/` | `prompt` | Framework maintainers |
| Project overlay | gitops repo or in-repo patches | `guidelines`, `prompt` | Project team |
| Process overlay | `.hyperloop/agents/process/` | `guidelines` | Process-improver agent |

At compose time, the orchestrator injects:

- `prompt` + `guidelines` (from kustomize build)
- Task spec content (read from `spec_ref@version` via `SpecSource`)
- Findings from prior rounds (from `StateStore`)
- Traceability refs for commit trailers

## Concurrency

The orchestrator cycle runs serially — one writer, no concurrent state mutations. Workers run independently between cycles. How workers execute is runtime-specific. Up to `max_workers` simultaneously.

## Recovery

The orchestrator can crash and restart without losing progress.

**Required properties of state:** durable (survives crash), consistent (no partial writes). On restart: read persisted state, cancel orphaned workers, resume from recorded phases.

## Configuration

```yaml
# .hyperloop.yaml — infrastructure concerns

overlay: .hyperloop/agents/
base_branch: main
runtime: local                    # local | ambient

max_workers: 6
poll_interval: 30
max_task_rounds: 50
max_action_attempts: 3

notifications:
  type: github-comment            # github-comment | null (default: null)
```

```yaml
# .hyperloop/agents/process/process.yaml — process concerns (via kustomize)
# May come from a remote overlay (level 1/2) and not exist locally (level 3).

pipeline:
  - loop:
      - agent: implementer
      - agent: verifier
  - gate: human-pr-approval
  - action: merge-pr

gates:
  human-pr-approval:
    type: label

actions:
  merge-pr:
    type: pr-merge

hooks:
  after_reap:
    - type: process-improver
```

## Git Adapter Set

The default adapter set connects hyperloop to a git-based workflow. These are implementation details — the reconciler architecture does not require git.

### GitSpecSource

Implements `SpecSource` using the local git repo:

- `detect_changes(since)` → `git diff <since>..HEAD -- specs/`
- `read(spec_ref)` → `git show <sha>:<path>` for versioned refs, or file read for unversioned
- `current_version()` → `git rev-parse HEAD`

The version identifier in `spec_ref@sha` is a git commit SHA.

### GitStateStore

Implements `StateStore` using files in `.hyperloop/state/` committed to the repo:

- Tasks live at `.hyperloop/state/tasks/task-{id}.md` — YAML frontmatter
- Reviews live at `.hyperloop/state/reviews/task-{id}-round-{n}.md` — YAML frontmatter + body
- `persist()` → `git add .hyperloop/state/ && git commit`
- `sync()` → `git pull --rebase origin && git push origin` (best-effort, no-op without a remote)

Sync runs once per cycle after persist, before workers spawn. This ensures workers branch from a trunk that includes the latest task files — without sync, worker PRs would include orchestrator state changes in their diffs.

State files are committed to trunk. This provides full git-history auditability but creates merge conflicts when worker branches carry stale copies. The `PRMergeAction` adapter auto-resolves these: tasks/ take trunk version, reviews/ take branch version.

### AgentSdkRuntime

Implements `Runtime` using the Claude Agent SDK with local git worktrees:

- `spawn()` → creates a git worktree on the task's branch, starts a Claude agent session in it
- Workers are isolated: each has its own worktree, own branch, own working directory
- Worker results are read from review files on the branch after the agent completes

### PRMergeAction

Implements `ActionPort` for `merge-pr` using the `gh` CLI:

- Checks PR state (OPEN/CLOSED/MERGED) before operating
- Recreates PRs if closed or stale-merged
- Rebases the branch onto trunk, auto-resolving `.hyperloop/state/` file conflicts
- Polls GitHub `mergeable` status after rebase (avoids race condition)
- Squash-merges with trailers preserved

Returns `ActionResult` with `pr_url` if the PR was recreated.

### LabelGate

Implements `GatePort` by checking for a `lgtm` label on the task's PR via `gh pr view --json labels`.

### GitHubCommentNotification

Implements `NotificationPort` by posting comments on the task's PR when human action is needed.

### Directory layout (git adapter)

```
target-repo/
├── .hyperloop.yaml              ← infrastructure config
├── .hyperloop/
│   ├── agents/                  ← kustomize composition point
│   │   ├── kustomization.yaml
│   │   └── process/             ← process concerns + process-improver output
│   │       ├── kustomization.yaml
│   │       └── process.yaml     ← pipeline + gate/action/hook config
│   ├── state/                   ← GitStateStore data (committed to trunk)
│   │   ├── tasks/
│   │   │   └── task-*.md
│   │   └── reviews/
│   │       └── task-*-round-*.md
│   └── checks/                  ← executable validations (process-improver writes)
│       └── *.sh
└── specs/
    └── *.md                     ← desired state (source of truth)
```

## Orchestrator Repo Structure

```
hyperloop/
├── specs/                       ← specs for hyperloop itself
├── base/                        ← base agent + process definitions
│   ├── process.yaml
│   ├── implementer.yaml
│   ├── verifier.yaml
│   ├── process-improver.yaml
│   └── pm.yaml
├── src/hyperloop/
│   ├── domain/                  ← pure logic, no I/O
│   │   ├── model.py             ← Task, AgentStep, TaskProposal, WorkerResult
│   │   ├── decide.py            ← pure decision function
│   │   └── pipeline.py          ← pipeline executor
│   ├── ports/                   ← Protocol interfaces
│   │   ├── spec_source.py
│   │   ├── state.py
│   │   ├── runtime.py
│   │   ├── gate.py
│   │   ├── action.py
│   │   ├── notification.py
│   │   ├── hook.py
│   │   ├── pr.py
│   │   └── probe.py
│   ├── adapters/                ← Implementations
│   │   ├── git/                 ← git adapter set
│   │   │   ├── spec_source.py   ← GitSpecSource
│   │   │   ├── state.py         ← GitStateStore
│   │   │   └── runtime.py       ← AgentSdkRuntime
│   │   ├── ambient/             ← ambient adapter set
│   │   │   └── runtime.py       ← AmbientRuntime
│   │   ├── gate/
│   │   │   ├── label.py
│   │   │   ├── pr_approval.py
│   │   │   ├── ci_status.py
│   │   │   └── all.py
│   │   ├── action/
│   │   │   └── pr_merge.py
│   │   ├── notification/
│   │   │   └── github_comment.py
│   │   ├── hook/
│   │   │   └── process_improver.py
│   │   └── probe/
│   │       ├── structlog.py
│   │       ├── matrix.py
│   │       └── otel.py
│   ├── compose.py               ← prompt composition (kustomize + SpecSource)
│   ├── wiring.py                ← config → object graph
│   └── loop.py                  ← 4-phase reconciliation cycle
└── tests/
    └── fakes/
```

## What This Does Not Cover

- **Custom pipeline primitives.** The four primitives (`agent`, `gate`, `loop`, `action`) are sufficient.
- **Plugin discovery.** Adapters are wired explicitly in config.
- **External spec sources.** Jira, GitHub Issues, etc. operate upstream — they update specs, hyperloop watches specs.
- **Multiple processes.** One process per orchestrator run.
- **Conditional pipeline steps.** Conditional logic belongs in agent prompts or gate adapters.
