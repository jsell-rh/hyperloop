# Hyperloop

Spec-driven reconciliation engine. Specs declare desired state; code is actual state; agents reconcile the two.

## Quick Start

```bash
hyperloop init          # scaffold .hyperloop.yaml and agent overlays
hyperloop run           # start the reconciliation loop
hyperloop get specs     # list specs and their statuses
hyperloop get tasks     # list tasks across all specs
```

## Configuration

All options live in `.hyperloop.yaml` at the repo root. Missing file or missing keys use defaults.

### Convergence

| Option | Default | Description |
|---|---|---|
| `convergence_bound` | 3 | Max verification cycles per spec before Failed |
| `max_task_retries` | 3 | Max retries per task before re-decomposition |
| `max_redecompositions` | 1 | Max re-decompositions per reconciliation attempt |
| `max_integration_retries` | 3 | Max integration submission retries before Failed |
| `max_concurrent_tasks` | 5 | Max tasks dispatched concurrently |

### Cycle

| Option | Default | Description |
|---|---|---|
| `cycle_interval_seconds` | 30 | Seconds between reconciliation cycles |

### Models

| Option | Default | Description |
|---|---|---|
| `implementation_model` | None | Model for implementation agents (runtime default if unset) |
| `verification_model` | None | Model for verification agents (should differ from implementation) |
| `decomposition_model` | None | Model for decomposition agents |

### Git

| Option | Default | Description |
|---|---|---|
| `trunk_branch` | `main` | Trunk branch name |
| `branch_prefix` | `hyperloop/` | Prefix for all managed branches |
| `plan_branch` | `hyperloop/plan` | Branch for plan state persistence |
| `git_author_name` | `hyperloop` | Git author for reconciler commits |
| `git_author_email` | `hyperloop@localhost` | Git email for reconciler commits |

### Paths

| Option | Default | Description |
|---|---|---|
| `specs_directory` | `specs/` | Directory containing spec files |
| `overlay_path` | `.hyperloop/agents` | Kustomize overlay directory for prompt composition |

### Executor

| Option | Default | Description |
|---|---|---|
| `executor_type` | `claude_sdk` | Agent executor backend (`claude_sdk` or `ambient`) |
| `executor_timeout_seconds` | 2700 | Max seconds per agent session |
| `executor_max_retries` | 3 | Max executor-level retries |
| `executor_max_tokens` | 128000 | Max tokens per agent session |
| `repository_url` | None | Required for `ambient` executor |
| `project_name` | None | Required for `ambient` executor |
| `acpctl_path` | `acpctl` | Path to acpctl binary |

### Observability

| Option | Default | Description |
|---|---|---|
| `observer_adapters` | `[]` | Observer adapters to activate (empty = NullProbe) |

### Example

```yaml
convergence_bound: 5
max_concurrent_tasks: 3
cycle_interval_seconds: 60
trunk_branch: develop
verification_model: gemini-pro
observer_adapters:
  - structlog
```
