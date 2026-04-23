# Configuration Reference

All configuration lives in `.hyperloop.yaml` at the repo root. Configuration is loaded from three sources in order of precedence:

1. **CLI arguments** (highest)
2. **`.hyperloop.yaml`** (project-level)
3. **Environment variables** (specific options)
4. **Defaults** (lowest)

## Full Example

```yaml
# .hyperloop.yaml

repo: owner/repo
overlay: .hyperloop/agents/
base_branch: main
runtime: local

max_workers: 6
poll_interval: 30
max_task_rounds: 50
max_cycles: 200
max_action_attempts: 3

merge:
  auto_merge: true
  strategy: squash
  delete_branch: true

notifications:
  type: github-comment

observability:
  log_format: console
  log_level: info
  matrix:
    homeserver: https://matrix.example.com
    room_id: "!abc123:matrix.example.com"
    token_env: MATRIX_ACCESS_TOKEN
    registration_token_env: MATRIX_REGISTRATION_TOKEN
    verbose: false
    invite_user: "@admin:matrix.example.com"
  otel:
    endpoint: http://localhost:4317
    service_name: hyperloop

dashboard:
  enabled: false
  events_limit: 1000

ambient:
  project_id: my-project
  acpctl: acpctl
  repo_url: https://github.com/my-org/my-project
```

## Core Options

| Key | Type | Default | CLI flag | Description |
|---|---|---|---|---|
| `repo` | `str` | inferred from git remote | `--repo` | GitHub repository (`owner/repo`) |
| `base_branch` | `str` | `main` | `--branch` | Base branch for PRs and rebasing |
| `overlay` | `str` | `.hyperloop/agents/` | -- | Kustomize overlay directory for agent definitions |
| `base_ref` | `str` | see env vars | -- | Kustomize remote base reference |
| `runtime` | `str` | `local` | -- | Runtime type: `local` (worktrees + Agent SDK) or `ambient` (Ambient Code Platform) |
| `max_workers` | `int` | `6` | `--max-workers` | Max parallel agent workers |
| `poll_interval` | `int` | `30` | -- | Seconds between orchestrator cycles |
| `max_task_rounds` | `int` | `50` | -- | Max implement-verify loops per task before failure |
| `max_cycles` | `int` | `200` | -- | Max orchestrator cycles before halt |
| `max_action_attempts` | `int` | `3` | -- | Action retry attempts before looping back |

## Merge Options

Controls PR merge behavior. Nested under `merge:`.

| Key | Type | Default | Description |
|---|---|---|---|
| `auto_merge` | `bool` | `true` | Auto-merge approved PRs |
| `strategy` | `str` | `squash` | Merge strategy: `squash`, `merge`, or `rebase` |
| `delete_branch` | `bool` | `true` | Delete branch after merge |

## Notifications

Nested under `notifications:`.

| Key | Type | Default | Description |
|---|---|---|---|
| `type` | `str` | `null` | `null` (disabled) or `github-comment` (PR comments for gate/action blockers) |

## Observability

Nested under `observability:`.

| Key | Type | Default | Description |
|---|---|---|---|
| `log_format` | `str` | `console` | `console` (human-readable) or `json` (structured) |
| `log_level` | `str` | `info` | `debug`, `info`, `warning`, or `error` |

### Matrix Notifications

Optional. Posts real-time status updates to a Matrix room. Nested under `observability.matrix:`.

| Key | Type | Default | Description |
|---|---|---|---|
| `homeserver` | `str` | required | Matrix homeserver URL |
| `room_id` | `str` | required | Target room ID (`!abc123:example.com`) |
| `token_env` | `str` | required | Env var name holding the Matrix access token |
| `registration_token_env` | `str` | -- | Env var name for auto-registration token |
| `verbose` | `bool` | `false` | Send verbose-level events |
| `invite_user` | `str` | -- | User ID to auto-invite to created rooms |

### OpenTelemetry

Optional. Exports metrics, traces, and logs via OTLP. Nested under `observability.otel:`.

| Key | Type | Default | Description |
|---|---|---|---|
| `endpoint` | `str` | required | OTLP gRPC collector endpoint |
| `service_name` | `str` | `hyperloop` | Service name for resource attributes |

## Dashboard

Optional activity dashboard. Nested under `dashboard:`.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | `bool` | `false` | Enable dashboard event streaming |
| `events_limit` | `int` | `1000` | Max retained events |

## Ambient Runtime

Required when `runtime: ambient`. Nested under `ambient:`.

| Key | Type | Default | Description |
|---|---|---|---|
| `project_id` | `str` | required | Ambient Code Platform project ID |
| `acpctl` | `str` | `acpctl` | Path to `acpctl` CLI |
| `repo_url` | `str` | required | Git repository URL |

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `HYPERLOOP_BASE_REF` | `github.com/jsell-rh/hyperloop//base?ref=main` | Kustomize base reference override |
| `ANTHROPIC_API_KEY` | -- | Anthropic API key (for local runtime) |
| `CLAUDE_CODE_USE_VERTEX` | -- | Set to `1` to use Vertex AI |
| `XDG_CACHE_HOME` | `~/.cache` | Base cache directory (Matrix credentials, dashboard) |

Matrix token env vars are configured dynamically via `matrix.token_env` and `matrix.registration_token_env`.

## CLI Commands

### `hyperloop run`

Run the orchestrator.

```bash
hyperloop run [--path .] [--repo owner/repo] [--branch main] [--config .hyperloop.yaml] [--max-workers 6] [--dry-run]
```

| Flag | Description |
|---|---|
| `--path` | Path to target repository (default: current directory) |
| `--repo` | GitHub repo (`owner/repo`), overrides YAML |
| `--branch` | Base branch, overrides YAML |
| `--config`, `-c` | Config file path, relative to `--path` |
| `--max-workers` | Max parallel workers, overrides YAML |
| `--dry-run` | Show resolved config and exit |

### `hyperloop init`

Scaffold the `.hyperloop/` structure in a repo.

```bash
hyperloop init [--path .] [--base-ref REF] [--overlay REF]
```

| Flag | Description |
|---|---|
| `--path` | Path to target repository |
| `--base-ref` | Kustomize remote base ref |
| `--overlay` | Kustomize remote overlay ref (replaces base with overlay that already includes it) |

### `hyperloop dashboard`

Start the activity dashboard.

```bash
hyperloop dashboard [--path .] [--port 8787]
```

| Flag | Description |
|---|---|
| `--path` | Path to target repository |
| `--port` | Dashboard server port (default: 8787) |

## Process Definition

The process definition (`process.yaml`) defines the pipeline that tasks move through. It lives at `.hyperloop/agents/process/process.yaml`.

```yaml
apiVersion: hyperloop.io/v1
kind: Process
metadata:
  name: default

pipeline:
  - loop:
      - agent: implementer
      - agent: verifier
  - action: mark-pr-ready
  - gate: pr-require-label
  - action: post-pr-comment
    args:
      body: "@coderabbit recheck"
  - check: pr-feedback-addressed
    args:
      require_reviewers: ["coderabbitai"]
      feedback_from: ["coderabbitai"]
  - action: merge-pr

gates:
  pr-require-label:
    type: label

hooks:
  after_reap:
    - type: process-improver
```

### Pipeline Primitives

| Primitive | What it does | Who executes |
|---|---|---|
| `agent: X` | Spawn a worker agent with X's prompt template | Runtime |
| `gate: X` | Block until external signal | GatePort adapter |
| `action: X` | Execute an operation with optional `args:` | ActionPort adapter |
| `check: X` | Mechanical pass/fail with optional `args:` | CheckPort adapter |
| `loop:` | Wrap steps -- on fail restart, on pass continue | Pipeline executor |

### Step Arguments

`action:` and `check:` steps accept an optional `args:` map passed to the adapter:

```yaml
- action: post-pr-comment
  args:
    body: "@coderabbit recheck"
```

### Framework-Shipped Actions

| Action | What it does | Args |
|---|---|---|
| `merge-pr` | Rebase, wait for mergeable, squash-merge | -- |
| `mark-pr-ready` | Mark a draft PR as ready for review | -- |
| `post-pr-comment` | Post a comment on the task's PR | `body: str` (required) |

### Framework-Shipped Checks

| Check | What it does | Args |
|---|---|---|
| `pr-feedback-addressed` | Pass when latest push >= latest comment | `require_reviewers: list[str]` (fail until all posted); `feedback_from: list[str]` (only these authors count as feedback) |

### Gate Types

| Type | Signal | Config key |
|---|---|---|
| `label` | PR label present (default: `lgtm`) | `gates.<name>.type: label` |
| `pr-approval` | GitHub PR review approved | `gates.<name>.type: pr-approval` |
| `ci-status` | All required CI checks pass | `gates.<name>.type: ci-status` |
| `all` | Multiple conditions (AND) | `gates.<name>.type: all` with `require:` list |

Gates are pure queries with no side effects. PR lifecycle actions (marking ready, posting comments) are separate `action:` steps.
