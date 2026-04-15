# hyperloop

Walks tasks through composable workflow pipelines using AI agents. You write specs, it creates tasks, implements them, verifies the work, and merges PRs.

## Install

```bash
pip install hyperloop
# or
uvx hyperloop
```

Requires: `kustomize` CLI (for overlay resolution), `gh` CLI (for PR management), `git`.

## Quickstart

1. Add specs to your repo:

```
your-repo/
└── specs/
    └── auth-api.md       # what you want built
```

2. Run:

```bash
cd your-repo
hyperloop --repo owner/repo --branch main
```

The orchestrator reads your specs, creates tasks, and starts running agents through the pipeline: implement, verify, merge.

## Configuration

Create `.hyperloop.yaml` in your repo root for persistent config:

```yaml
target:
  base_branch: main

runtime:
  default: local
  max_workers: 4

merge:
  auto_merge: true
  strategy: squash
```

## Customizing Agent Behavior

hyperloop ships with base agent definitions (implementer, verifier, etc.) that work out of the box. To customize them for your project, you overlay with patches.

### Level 1: In-repo overlay

For single-repo projects. Agent patches live in the repo itself:

```yaml
# .hyperloop.yaml
overlay: .hyperloop/agents/
```

```
your-repo/
├── .hyperloop.yaml
├── .hyperloop/
│   └── agents/
│       ├── implementer-patch.yaml
│       └── workflow-patch.yaml
└── specs/
```

An implementer patch injects your project's persona:

```yaml
# .hyperloop/agents/implementer-patch.yaml
kind: Agent
name: implementer
annotations:
  ambient.io/persona: |
    You work on a Go API service.
    Build: make build. Test: make test. Lint: make lint.
    Follow Clean Architecture. Use dependency injection.
```

### Level 2: Shared overlay via gitops repo

For teams with multiple repos sharing agent definitions. The overlay lives in a central gitops repo and references the hyperloop base as a kustomize remote resource:

```yaml
# .hyperloop.yaml
overlay: git@github.com:your-org/agent-gitops//overlays/api
```

```yaml
# your-org/agent-gitops/overlays/api/kustomization.yaml
resources:
  - github.com/org/hyperloop//base?ref=v1.0.0

patches:
  - path: implementer-patch.yaml
    target:
      kind: Agent
      name: implementer
  - path: workflow-patch.yaml
    target:
      kind: Workflow
      name: default
```

This pins the base version and lets you upgrade across all repos by bumping the ref.

## Custom Workflows

The default pipeline is: implement, verify, merge. Override it by patching the workflow:

```yaml
# workflow-patch.yaml
kind: Workflow
name: default

pipeline:
  - loop:
      - loop:
          - role: implementer
          - role: verifier
      - role: security-reviewer
  - gate: human-pr-approval
  - action: merge-pr
```

Four primitives:

| Primitive | What it does |
|---|---|
| `role: X` | Spawn an agent. Fail restarts the enclosing loop. |
| `gate: X` | Block until external signal (v1: `lgtm` label on PR). |
| `loop` | Wrap steps. Retry from top on failure. |
| `action: X` | Terminal operation (`merge-pr`, `mark-pr-ready`). |

Loops nest. Inner loops retry independently of outer loops.

## What it creates in your repo

The orchestrator writes to `specs/` in your repo:

```
specs/
├── tasks/       # task files with status, findings, spec references
├── reviews/     # review artifacts from verifier (on branches)
└── prompts/     # process improvements (learned over time)
```

All task state is tracked in git. Every commit includes `Spec-Ref` and `Task-Ref` trailers for traceability. PRs are created as drafts and labeled by spec and task.

## Configuration Reference

```yaml
# .hyperloop.yaml

overlay: .hyperloop/agents/    # local path or git URL to kustomization dir

target:
  repo: owner/repo                 # GitHub repo (default: inferred from git remote)
  base_branch: main                # trunk branch
  specs_dir: specs                 # where specs live

runtime:
  default: local                   # local (v1) | ambient (planned)
  max_workers: 6                   # max parallel task workers

merge:
  auto_merge: true                 # squash-merge on review pass
  strategy: squash                 # squash | merge
  delete_branch: true              # delete worker branch after merge

poll_interval: 30                  # seconds between orchestrator cycles
max_rounds: 50                     # max retry rounds per task before failure
max_rebase_attempts: 3             # max rebase retries before full loop retry
```
