# Prompt Composition: Kustomize All The Way Down

## Problem

Agent prompts are composed from three layers, but only layers 1 and 2 use kustomize. Layer 3 (process overlays) is a freeform file read at spawn time — inconsistent format, not mechanically injected, and creates merge conflicts when the process-improver modifies trunk while tasks are in flight.

## Design

All three layers use kustomize resources with a consistent schema. A new `guidelines` field on Agent resources provides the additive surface — the process-improver targets `guidelines`, leaving `prompt` untouched by convention.

### Agent Schema

```yaml
apiVersion: hyperloop.io/v1
kind: Agent
metadata:
  name: implementer
prompt: |
  You are a worker agent...
guidelines: ""
```

`prompt` is the core agent identity (protocol, behavior). `guidelines` is project-specific and process-learned rules. At compose time: `prompt + guidelines + spec + findings`.

### Three Layers

| Layer | Source | Field targeted | Who writes it |
|---|---|---|---|
| Base | hyperloop repo `base/` | `prompt` | Orchestrator maintainers |
| Project overlay | gitops repo or in-repo patches | `guidelines`, `prompt` (can override) | Project team |
| Process overlay | `.hyperloop/agents/process/` | `guidelines` | Process-improver agent |

All three resolve in a single `kustomize build`.

## Directory Structure

```
target-repo/
├── .hyperloop.yaml
├── .hyperloop/
│   ├── agents/
│   │   ├── kustomization.yaml         # composition point
│   │   └── process/                   # kustomize Component
│   │       ├── kustomization.yaml     # kind: Component, patches list
│   │       ├── implementer-overlay.yaml
│   │       └── verifier-overlay.yaml
│   ├── state/
│   │   ├── tasks/
│   │   │   └── task-*.md
│   │   └── reviews/
│   │       └── task-{id}-round-{n}.md
│   └── checks/
│       └── *.sh
├── specs/
│   └── *.spec.md                     # product specs only

~/.cache/hyperloop/
└── {repo-hash}/
    └── matrix-state.json              # credentials cache, per-repo
```

`specs/` is the user's domain — product specs, nothing else. `.hyperloop/` is 100% tracked orchestrator content — agent config, state, checks. No gitignore carve-outs. Ephemeral caches (Matrix credentials) live in `$XDG_CACHE_HOME/hyperloop/` (or `~/.cache/hyperloop/`), keyed by repo path hash.

## `hyperloop init`

Scaffolds the required structure. Eliminates cold-start problems — the orchestrator always has a valid kustomization to build, and the process-improver has a Component to write patches into.

```
hyperloop init [--base-ref github.com/org/hyperloop//base?ref=main]
               [--overlay github.com/org/gitops//overlays/api?ref=main]
```

### Without `--overlay` (level 1)

```yaml
# .hyperloop/agents/kustomization.yaml
resources:
  - github.com/org/hyperloop//base?ref=main

components:
  - process
```

```yaml
# .hyperloop/agents/process/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1alpha1
kind: Component
```

```yaml
# .hyperloop.yaml (created if absent)
overlay: .hyperloop/agents/
```

### With `--overlay` (level 2+)

```yaml
# .hyperloop/agents/kustomization.yaml
resources:
  - github.com/org/hyperfleet-gitops//overlays/api?ref=main

components:
  - process
```

The gitops overlay references the base internally. Chain: base -> gitops overlay -> local process component.

### Idempotent

Running `init` again does not overwrite existing files — only creates missing ones.

### Validation

After scaffolding, runs `kustomize build .hyperloop/agents/` to verify resolution. Fails fast if kustomize is missing or remote ref is unreachable.

## Concrete Examples

### Level 1: Base only

After `hyperloop init`:

```
hyperfleet-api/
├── .hyperloop.yaml                    # overlay: .hyperloop/agents/
├── .hyperloop/
│   ├── agents/
│   │   ├── kustomization.yaml        # resources: [base], components: [process]
│   │   └── process/
│   │       └── kustomization.yaml    # empty Component
│   └── state/
│       └── tasks/
└── specs/
    └── api-endpoints.spec.md
```

`kustomize build .hyperloop/agents/` resolves base prompts. Empty guidelines. Empty process component contributes nothing.

### Levels 1+2: Base + project overlay

After `hyperloop init --overlay github.com/org/hyperfleet-gitops//overlays/api?ref=main`:

```
hyperfleet-api/
├── .hyperloop.yaml                    # overlay: .hyperloop/agents/
├── .hyperloop/
│   ├── agents/
│   │   ├── kustomization.yaml        # resources: [gitops overlay], components: [process]
│   │   └── process/
│   │       └── kustomization.yaml    # empty Component
│   └── state/
│       └── tasks/
└── specs/
    └── api-endpoints.spec.md
```

The gitops overlay might patch `process.yaml` with a custom loop, 
or overwrite an agent prompts. One `kustomize build` resolves layers 1+2.

### Levels 1+2+3: Base + project overlay + process overlay

After the orchestrator runs and the process-improver learns from verifier failures:

```
hyperfleet-api/
├── .hyperloop.yaml
├── .hyperloop/
│   ├── agents/
│   │   ├── kustomization.yaml
│   │   └── process/
│   │       ├── kustomization.yaml            # Component with patches
│   │       ├── implementer-overlay.yaml
│   │       └── verifier-overlay.yaml
│   ├── state/
│   │   ├── tasks/
│   │   │   ├── task-001.md
│   │   │   └── task-002.md
│   │   └── reviews/
│   │       ├── task-001-round-0.md
│   │       └── task-001-round-1.md
│   └── checks/
│       └── no-unscoped-deletions.sh
└── specs/
    └── api-endpoints.spec.md
```

```yaml
# .hyperloop/agents/process/kustomization.yaml (maintained by process-improver)
apiVersion: kustomize.config.k8s.io/v1alpha1
kind: Component

patches:
  - path: implementer-overlay.yaml
    target: { kind: Agent, name: implementer }
  - path: verifier-overlay.yaml
    target: { kind: Agent, name: verifier }
```

```yaml
# .hyperloop/agents/process/implementer-overlay.yaml
apiVersion: hyperloop.io/v1
kind: Agent
metadata:
  name: implementer
guidelines: |
  - Do not delete files your task did not create.
  - Run .hyperloop/checks/no-unscoped-deletions.sh before submitting.
```

One `kustomize build` resolves all three layers. Guidelines from the gitops overlay and process overlay are merged by kustomize's strategic merge.

## Compose Flow

1. **Startup**: `kustomize build .hyperloop/agents/` -> `AgentTemplate` objects with `prompt` + `guidelines`.
2. **After process-improver runs**: re-run `kustomize build` (~54ms local, no network). Update templates.
3. **At compose time**: `prompt + guidelines + spec + findings`.

The `_read_overlay()` method is removed. All overlay resolution happens through kustomize.

## Mechanical Guarantee

The process-improver runs in serial section step 3. Workers spawn in step 9. If the process-improver modifies overlay files and commits, the orchestrator re-runs `kustomize build` before step 9. Any agent spawned after a process improvement **will** see the updated guidelines. This is guaranteed by loop ordering, not by polling or caching.

## Review Findings

Findings from failed rounds are stored as separate files, not inlined in task files.

### File format

```
.hyperloop/state/reviews/task-027-round-0.md
```

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

### Flow

1. Verifier fails, reports findings in `WorkerResult`.
2. Orchestrator writes `.hyperloop/state/reviews/task-{id}-round-{n}.md` on trunk.
3. On next spawn, orchestrator reads the latest review file and injects findings into the worker's prompt.
4. On task completion, review files are preserved (historical record, not cleared).
5. Process-improver reads all review files from the current cycle to identify patterns.

### Benefits over inlined findings

- **Task files stay clean** — just frontmatter metadata, no growing body.
- **Review history preserved** — each round is a separate file, not overwritten.
- **Process-improver analysis** — can scan all reviews across tasks to find systemic patterns.

### Task file format (simplified)

With findings extracted, task files become pure metadata:

```yaml
---
id: task-027
title: Implement Places DB persistent storage
spec_ref: specs/persistence.md
status: in-progress
phase: verifier
deps: [task-004]
round: 1
branch: worker/task-027
pr: null
---
```

No body sections. The `## Spec` content is read from `spec_ref` at compose time. The `## Findings` content is read from review files.

## Credentials Cache

Matrix bot credentials and other ephemeral caches live outside the repo:

```
$XDG_CACHE_HOME/hyperloop/   (or ~/.cache/hyperloop/)
└── {repo-path-hash}/
    └── matrix-state.json
```

Keyed by a hash of the repo's absolute path. This keeps `.hyperloop/` in the repo 100% tracked — no gitignore carve-outs needed. `hyperloop init` does not need to touch `.gitignore` for cache files.
