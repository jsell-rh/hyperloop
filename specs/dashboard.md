# Dashboard

A read-only web UI that shows orchestrator state per-repo. Separate process from the orchestrator — different lifecycle, different deployment. The orchestrator writes state, the dashboard reads it.

## Core Design

The dashboard is an observer. It uses `StateStore` and `SpecSource` ports in read-only mode to display the current state of an orchestrated repo. It never writes state, never spawns workers, and never touches `Runtime`, `PRPort`, `ActionPort`, or `NotificationPort`.

**Two processes, one config.** The dashboard reads `.hyperloop.yaml` from the target repo to construct the same `StateStore` and `SpecSource` adapters the orchestrator uses. It sees exactly what the orchestrator sees.

**Can observe any repo.** The dashboard does not need to run in the same environment as the orchestrator. Point it at any repo with `.hyperloop/state/` and it renders the current state.

## Architecture

```
dashboard/
├── server/                     # Python backend (FastAPI)
│   ├── __init__.py
│   ├── app.py                  # FastAPI app + lifespan
│   ├── routes/
│   │   ├── specs.py            # /api/specs endpoints
│   │   ├── tasks.py            # /api/tasks endpoints
│   │   └── health.py           # /api/health
│   └── deps.py                 # StateStore + SpecSource dependency injection
├── app/                        # Nuxt 4 frontend
│   ├── nuxt.config.ts
│   ├── app.vue
│   ├── pages/
│   │   ├── index.vue           # Overview — specs with progress
│   │   ├── specs/[id].vue      # Spec detail — tasks + content
│   │   └── tasks/[id].vue      # Task detail — reviews + pipeline
│   ├── components/
│   │   ├── SpecCard.vue
│   │   ├── TaskRow.vue
│   │   ├── PipelineIndicator.vue
│   │   ├── StatusBadge.vue
│   │   └── ReviewTimeline.vue
│   ├── composables/
│   │   └── useApi.ts           # Typed API client
│   └── types/
│       └── index.ts            # TypeScript types matching backend models
├── package.json
└── pyproject.toml
```

### Backend

Thin Python API server using FastAPI. No business logic — it translates port reads into JSON responses.

The backend constructs `StateStore` and `SpecSource` from the target repo's `.hyperloop.yaml`, identical to how `wiring.py` constructs them for the orchestrator. This means the dashboard sees the same state files, same spec versions, same review history.

### Frontend

Nuxt 4 + shadcn-vue (Tailwind-based component library). Renders orchestrator state as a multi-page dashboard with spec progress, task pipelines, and review history.

### Communication

REST API. The frontend polls the backend at a configurable interval. No WebSocket — polling is sufficient for the ~10s refresh cadence this dashboard targets.

## CLI

```bash
# Start dashboard for the current repo (reads .hyperloop.yaml from cwd)
hyperloop dashboard

# Specify a port
hyperloop dashboard --port 8080

# Observe a remote repo (clones to a temp dir, pulls on each refresh)
hyperloop dashboard --repo owner/repo --port 8080
```

### Launch behavior

`hyperloop dashboard` starts both the Python API server and serves the built Nuxt frontend.

- **Development:** Nuxt dev server proxies `/api/*` requests to the Python backend. Two processes.
- **Production:** Python serves the pre-built Nuxt static files from `dashboard/app/.output/public/` alongside the API routes. Single process.

## Backend API

All endpoints are read-only. The backend calls `state.get_world()` and `spec_source.read()` on each request — the `StateStore` and `SpecSource` implementations handle freshness (for git-backed state, this means reading from disk or pulling from remote).

### `GET /api/health`

```json
{
  "status": "ok",
  "repo": "owner/repo",
  "state_store": "git",
  "spec_source": "git"
}
```

### `GET /api/specs`

List all specs with task progress summary.

```json
[
  {
    "spec_ref": "specs/persistence.md",
    "title": "Persistent Storage",
    "tasks_total": 4,
    "tasks_complete": 2,
    "tasks_in_progress": 1,
    "tasks_failed": 1,
    "tasks_not_started": 0
  }
]
```

Derived from `StateStore.get_world()`. Tasks are grouped by `spec_ref` (stripping the `@version` suffix for grouping). The title is extracted from the first `# heading` of the spec content.

### `GET /api/specs/{spec_ref}`

Spec detail with rendered content and associated tasks.

```json
{
  "spec_ref": "specs/persistence.md",
  "content": "# Persistent Storage\n\nThe system shall...",
  "tasks": [
    {
      "id": "task-027",
      "title": "Implement Places DB persistent storage",
      "status": "in-progress",
      "phase": "implementer",
      "round": 2,
      "branch": "hyperloop/task-027",
      "pr": "https://github.com/owner/repo/pull/42",
      "spec_ref": "specs/persistence.md@abc123"
    }
  ]
}
```

`spec_ref` in the URL is the unversioned spec path (e.g., `specs/persistence.md`). The backend reads the latest version via `SpecSource.read()`. Tasks are all tasks whose `spec_ref` starts with this path.

### `GET /api/tasks`

List all tasks, optionally filtered.

Query parameters:
- `status` — filter by status (`not-started`, `in-progress`, `complete`, `failed`)
- `spec_ref` — filter by spec path prefix

```json
[
  {
    "id": "task-027",
    "title": "Implement Places DB persistent storage",
    "status": "in-progress",
    "phase": "implementer",
    "round": 2,
    "branch": "hyperloop/task-027",
    "pr": "https://github.com/owner/repo/pull/42",
    "spec_ref": "specs/persistence.md@abc123"
  }
]
```

### `GET /api/tasks/{task_id}`

Task detail with full review history.

```json
{
  "id": "task-027",
  "title": "Implement Places DB persistent storage",
  "status": "in-progress",
  "phase": "implementer",
  "round": 2,
  "branch": "hyperloop/task-027",
  "pr": "https://github.com/owner/repo/pull/42",
  "spec_ref": "specs/persistence.md@abc123",
  "deps": ["task-004"],
  "reviews": [
    {
      "round": 0,
      "role": "verifier",
      "verdict": "fail",
      "detail": "Branch deletes 3 files from main that are out-of-scope..."
    },
    {
      "round": 1,
      "role": "verifier",
      "verdict": "fail",
      "detail": "Tests fail: missing null check in widget.py line 42..."
    }
  ]
}
```

Reviews are read via `StateStore.get_findings(task_id)`, parsed from the review file format (YAML frontmatter + body).

### `GET /api/summary`

Aggregate progress across all tasks.

```json
{
  "total": 12,
  "not_started": 3,
  "in_progress": 4,
  "complete": 4,
  "failed": 1,
  "specs_total": 5,
  "specs_complete": 2
}
```

A spec is "complete" when all of its tasks are in terminal states and at least one is `complete`.

## Frontend Views

### Overview page (`/`)

Grid of spec cards. Each card shows:
- Spec title (first `#` heading from the spec file)
- Progress bar (complete / total tasks)
- Status breakdown: counts by status, shown as small colored badges
- Click navigates to spec detail

Cards are sorted: specs with in-progress work first, then not-started, then complete, then all-failed.

### Spec detail page (`/specs/:id`)

Two sections:

**Spec content.** The spec file rendered as markdown with proper typography. Read-only.

**Task list.** Table of all tasks for this spec:

| Column | Content |
|---|---|
| ID | `task-027` |
| Title | Implement Places DB persistent storage |
| Status | Badge: `in-progress` (blue) |
| Phase | Current pipeline step: `implementer` |
| Round | `2` |
| PR | Link to PR (if exists) |

Click a task row to navigate to task detail.

### Task detail page (`/tasks/:id`)

Three sections:

**Task metadata.** Card showing ID, title, status, spec_ref, branch, PR link, dependencies.

**Pipeline position.** Visual representation of the pipeline with the current step highlighted. Shows the full pipeline structure (e.g., `loop[ implementer → verifier ] → gate → merge`) with the active step indicated. Completed steps are marked, upcoming steps are dimmed.

**Review history.** Timeline of all reviews across all rounds. Each entry shows:
- Round number
- Role (implementer, verifier, human)
- Verdict badge (pass/fail)
- Detail text (the review body)

Most recent round at the top. Failed rounds show the verifier's findings. Pass rounds show confirmation.

## UI Components

### StatusBadge

Color-coded badge for task status:

| Status | Color | Label |
|---|---|---|
| `not-started` | Gray | Not Started |
| `in-progress` | Blue | In Progress |
| `complete` | Green | Complete |
| `failed` | Red | Failed |

Uses shadcn-vue `Badge` with variant mapped to status.

### PipelineIndicator

Horizontal step indicator showing the full pipeline. Steps are rendered as connected nodes:

```
[ implementer ] → [ verifier ] → [ gate ] → [ merge ]
       ●                ○             ○          ○
    (active)        (pending)     (pending)  (pending)
```

For loop structures, steps inside the loop are visually grouped with a loop indicator showing the current round.

Uses shadcn-vue `Separator` between steps.

### SpecCard

Card component for the overview grid:
- Title, progress bar, status badges
- Uses shadcn-vue `Card`, `Progress`, `Badge`

### TaskRow

Table row component for the spec detail task list:
- Compact layout with status badge, phase text, round count
- Uses shadcn-vue `Table` row styling

### ReviewTimeline

Vertical timeline of review entries:
- Each entry: round badge, role, verdict badge, detail text
- Expandable detail (collapsed by default if long)
- Uses shadcn-vue `Card`, `Badge`, `Separator`

## TypeScript Types

```typescript
// types/index.ts

interface SpecSummary {
  spec_ref: string
  title: string
  tasks_total: number
  tasks_complete: number
  tasks_in_progress: number
  tasks_failed: number
  tasks_not_started: number
}

interface SpecDetail {
  spec_ref: string
  content: string
  tasks: TaskSummary[]
}

interface TaskSummary {
  id: string
  title: string
  status: "not-started" | "in-progress" | "complete" | "failed"
  phase: string | null
  round: number
  branch: string | null
  pr: string | null
  spec_ref: string
}

interface TaskDetail extends TaskSummary {
  deps: string[]
  reviews: Review[]
}

interface Review {
  round: number
  role: string
  verdict: string
  detail: string
}

interface Summary {
  total: number
  not_started: number
  in_progress: number
  complete: number
  failed: number
  specs_total: number
  specs_complete: number
}
```

## Backend Dependency Injection

```python
# dashboard/server/deps.py

from hyperloop.ports.state import StateStore
from hyperloop.ports.spec_source import SpecSource

_state: StateStore
_spec_source: SpecSource

def init(repo_path: str) -> None:
    """Construct StateStore and SpecSource from repo's .hyperloop.yaml.

    Uses the same wiring logic as the orchestrator (hyperloop.wiring)
    but only constructs the two read-only ports.
    """
    ...

def get_state() -> StateStore:
    return _state

def get_spec_source() -> SpecSource:
    return _spec_source
```

The `init` function reads `.hyperloop.yaml` from the target repo and constructs the appropriate `StateStore` and `SpecSource` adapters. For the git adapter set, this means `GitStateStore` and `GitSpecSource` pointed at the repo.

For `--repo owner/repo` mode: the backend clones the repo to a temp directory and constructs the adapters against the clone. On each `get_world()` call, the `GitStateStore` pulls from remote.

## Refresh Strategy

- Frontend polls `/api/tasks` and `/api/summary` every N seconds (configurable, default 10s)
- Backend calls `state.get_world()` on each request — `StateStore` reads current state from disk
- For git-backed state: `GitStateStore.get_world()` reads `.hyperloop/state/` files from the working tree
- For remote observation (`--repo`): the backend runs `git pull` periodically (on each `get_world()` call or on a background timer) to stay current
- No WebSocket needed — polling matches the orchestrator's own cycle cadence

## Prompt Provenance

The dashboard can display the fully-composed prompt for any task/round, with each section annotated by its source layer. This lets a human see exactly what an agent was told and where each instruction came from.

### Data Model

```python
@dataclass(frozen=True)
class PromptSection:
    source: str      # "base", "project-overlay", "process-overlay", "spec", "findings", "runtime"
    label: str       # "prompt", "guidelines", "spec", "findings", "epilogue"
    content: str

@dataclass(frozen=True)
class ComposedPrompt:
    sections: tuple[PromptSection, ...]
    text: str        # the flattened string passed to the runtime
```

### Source Attribution

| Section | Source | How determined |
|---|---|---|
| `prompt` | `base` or `project-overlay` | From `AgentTemplate`. If the template came from a kustomize patch (overlay), source is `project-overlay`. If from the base resource, source is `base`. |
| `guidelines` | `process-overlay` or `project-overlay` | The `guidelines` field on `AgentTemplate`. Empty in base. If non-empty, it was patched by an overlay. Process-improver writes to the process overlay; project teams write to the project overlay. The `AgentTemplate.annotations` can carry a `source` hint. |
| `spec` | `spec` | Content from `SpecSource.read(spec_ref)`. Source is always `spec`. |
| `findings` | `findings` | From `StateStore.get_findings(task_id)`. Prior round review content. |
| `epilogue` | `runtime` | Runtime-specific instructions (e.g., "push your branch when done"). |

### Compose Changes

`PromptComposer.compose()` currently returns `str`. It should return `ComposedPrompt` — a structured object with the section list and the flattened text. The flattened `text` field is what gets passed to the runtime (backwards compatible). The sections are stored for observability.

The `prompt_composed` probe event should include the sections (or the orchestrator should store them for dashboard retrieval).

### Storage

The orchestrator stores the composed prompt sections for each spawn in `StateStore`. Suggested path: `.hyperloop/state/prompts/task-{id}-round-{n}-{role}.json`. This is write-once, read-many — the dashboard reads it, the orchestrator writes it after each spawn.

### API Endpoint

`GET /api/tasks/{task_id}/prompts`

Returns all composed prompts for a task across rounds/roles:

```json
[
  {
    "round": 0,
    "role": "implementer",
    "sections": [
      {
        "source": "base",
        "label": "prompt",
        "content": "You are a worker agent implementing a task..."
      },
      {
        "source": "process-overlay",
        "label": "guidelines",
        "content": "- Do not delete files your task did not create.\n- Run checks before submitting."
      },
      {
        "source": "spec",
        "label": "spec",
        "content": "# Persistent Storage\n\nThe system shall..."
      },
      {
        "source": "findings",
        "label": "findings",
        "content": ""
      }
    ]
  },
  {
    "round": 1,
    "role": "implementer",
    "sections": [
      {
        "source": "base",
        "label": "prompt",
        "content": "You are a worker agent implementing a task..."
      },
      {
        "source": "process-overlay",
        "label": "guidelines",
        "content": "- Do not delete files your task did not create.\n- Run checks before submitting.\n- Always run the full test suite before writing your verdict."
      },
      {
        "source": "spec",
        "label": "spec",
        "content": "# Persistent Storage\n\nThe system shall..."
      },
      {
        "source": "findings",
        "label": "findings",
        "content": "Tests fail: missing null check in widget.py line 42..."
      }
    ]
  }
]
```

### Frontend

The task detail page includes a "Prompt" tab. Each prompt entry (per round/role) is rendered as collapsible panels — one panel per section. The panel header shows the source label as a colored badge:

| Source | Color |
|---|---|
| `base` | Gray |
| `project-overlay` | Purple |
| `process-overlay` | Amber |
| `spec` | Blue |
| `findings` | Orange |
| `runtime` | Slate |

Content is rendered as monospace text (not markdown — it's a prompt, not documentation).

## Navigation

Persistent top navigation bar in `app.vue`. Four sections:

| Nav Item | Route | Purpose |
|---|---|---|
| Overview | `/` | Spec cards + summary + dependency graph |
| Activity | `/activity` | Cycle-by-cycle reconciliation log (requires `dashboard.enabled`) |
| Process | `/process` | Pipeline definition, gates, actions, hooks |
| Agents | `/agents` | Per-role prompt composition with layer breakdown |

Tasks are accessed contextually from specs, activity, or the dependency graph — not as a top-level nav item.

## Dependency Graph

The overview page includes a dependency DAG visualization showing all tasks as nodes and their dependency relationships as edges.

### Layout

Below the spec cards grid, a full-width card titled "Dependency Graph". The graph uses automatic DAG layout (topological ordering, left-to-right flow). Each node shows:

- Task ID
- Short title (truncated to ~30 chars)
- Status badge (colored: gray/blue/green/red)
- Current phase (small text below title)

Edges are directional arrows from dependency to dependent. Edge color reflects blocking status: green if the dep is complete, red if the dep is failed, gray if not-started, blue if in-progress.

### Critical Path

The longest chain of non-complete tasks is highlighted with thicker edges and a subtle background. This is the bottleneck — the chain that determines when the project finishes. Computed via longest-path algorithm on the DAG (only considering non-terminal tasks).

### Interaction

- Click a node to navigate to `/tasks/{id}`
- Hover a node to highlight its dependency chain (ancestors and descendants)
- Zoom/pan for large graphs (> 20 nodes)

### API

`GET /api/tasks/graph`

Returns the full task list with deps, optimized for graph rendering:

```json
{
  "nodes": [
    { "id": "task-001", "title": "Value objects", "status": "complete", "phase": null, "spec_ref": "specs/domain-model.md" },
    { "id": "task-002", "title": "Domain events", "status": "in-progress", "phase": "verifier", "spec_ref": "specs/domain-model.md" }
  ],
  "edges": [
    { "from": "task-001", "to": "task-002" }
  ],
  "critical_path": ["task-003", "task-007", "task-012"]
}
```

### Component

`DependencyGraph.vue` — uses a lightweight DAG layout library (e.g., `dagre` via `@dagrejs/dagre` or `elkjs`). Renders as SVG within the card. Falls back to a flat table if the library isn't available.

## Process View (`/process`)

Pipeline definition, gate/action/hook configuration, and process-improver learnings — all in one reference page.

### Sections

1. **Pipeline Flowchart** — horizontal structural diagram showing the pipeline with loop grouping. Agent nodes blue-tinted, gate nodes amber, action nodes green. Raw YAML collapsible below.
2. **Gates** — table of gate configs (name, type, configuration)
3. **Actions** — table of action configs
4. **Hooks** — table of hooks with descriptions
5. **Process Learning** — current state of the process overlay (what the process-improver has learned: which agents have guidelines, what the guidelines say)
6. **Source Provenance** — where the config comes from (file paths, kustomize refs)

### API

`GET /api/process`

```json
{
  "pipeline_steps": [
    { "type": "loop", "children": [
      { "type": "agent", "name": "implementer" },
      { "type": "agent", "name": "verifier" }
    ]},
    { "type": "gate", "name": "pr-require-label" },
    { "type": "action", "name": "merge-pr" }
  ],
  "pipeline_raw": "- loop:\n    - agent: implementer\n    ...",
  "gates": { "pr-require-label": { "type": "label" } },
  "actions": { "merge-pr": { "type": "pr-merge" } },
  "hooks": { "after_reap": [{ "type": "process-improver" }] },
  "process_learning": {
    "patched_agents": ["implementer", "verifier"],
    "guidelines": { "implementer": "- Do not delete files...", "verifier": "- Run full test suite..." },
    "check_scripts": ["no-unscoped-deletions.sh"]
  },
  "source_file": ".hyperloop/agents/process/process.yaml",
  "base_ref": "github.com/org/hyperloop//base?ref=main"
}
```

## Agents View (`/agents`)

Per-role prompt composition showing the three-layer breakdown.

### Layout

Left sidebar listing agent roles (with amber dot indicator for roles that have process overlay patches). Main area shows the selected role's prompt broken into layers.

### Layers

Three collapsible panels per agent:

1. **Base** (gray) — the `prompt` field from the base definition
2. **Project Overlay** (purple) — any prompt/guidelines patches from the project overlay
3. **Process Overlay** (amber) — guidelines written by the process-improver, with last-modified timestamp

Below the layers: a "Composed Preview" showing the final merged prompt template (without per-task spec/findings injection).

### Check Scripts

A fourth panel showing executable check scripts from `.hyperloop/checks/` with their content.

### API

`GET /api/agents`

```json
[
  {
    "name": "implementer",
    "prompt": "You are a worker agent...",
    "guidelines": "- Do not delete files...",
    "has_process_patches": true,
    "process_overlay_file": ".hyperloop/agents/process/implementer-overlay.yaml"
  }
]
```

`GET /api/agents/checks`

```json
[
  { "name": "no-unscoped-deletions.sh", "path": ".hyperloop/checks/no-unscoped-deletions.sh", "content": "#!/bin/bash\n..." }
]
```

## Activity View (`/activity`)

Cycle-by-cycle reconciliation log. Requires `dashboard.enabled: true` in `.hyperloop.yaml`.

### Opt-in Data Collection

When `dashboard.enabled` is true, the orchestrator wires a `FileProbe` adapter that writes one JSON line per probe event to `~/.cache/hyperloop/{repo-hash}/events.jsonl`. The file is capped at `dashboard.events_limit` events (default 1000). When the dashboard is not enabled, no FileProbe is wired and there is no I/O overhead.

If the Activity page is loaded without event data, it shows: "Enable `dashboard: { enabled: true }` in .hyperloop.yaml to see cycle activity."

### Sections

1. **Status Strip** — current cycle number, active workers, task breakdown, orchestrator status (running/halted/stale)
2. **Worker Timeline** — horizontal bars for active and recently completed workers, with duration and verdict
3. **Cycle Log** — reverse-chronological cards, each showing the four phases (COLLECT, INTAKE, ADVANCE, SPAWN) with event details

### API

`GET /api/activity?since_cycle=N&limit=20`

### FileProbe Configuration

```yaml
# .hyperloop.yaml
dashboard:
  enabled: true
  events_limit: 1000
```

## Design Principles

- **Clean, enterprise.** No visual clutter, no decorative elements. Information density without noise.
- **shadcn-vue components.** Card, Badge, Table, Tabs, Progress, Separator. No custom CSS beyond Tailwind utilities.
- **Responsive.** Works on desktop and tablet. Not optimized for mobile — this is a monitoring dashboard.
- **Fast loads.** Nuxt SSR for initial paint. Client-side polling for updates. No full page reloads on navigation.
- **Dark mode.** Supported via Tailwind's dark mode classes. Follows system preference.

## What This Does Not Cover

- **Write operations.** The dashboard is read-only. No task creation, no status changes, no PR actions.
- **Authentication.** The dashboard is a local dev tool. Auth is out of scope for v1.
- **Multi-repo views.** One dashboard instance observes one repo. Run multiple instances for multiple repos.
- **Historical trends.** The dashboard shows current state, not time-series data. Git history provides the audit trail.
- **WebSocket/SSE push.** Polling is sufficient. If latency requirements change, SSE can be added to the backend without frontend changes (the composable abstracts the transport).
