# hyperloop

Walks tasks through composable workflow pipelines using AI agents. You write specs, it creates tasks, implements them, verifies the work, and merges PRs.

## Prerequisites

- Python 3.12+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) (`claude` on PATH)
- `gh` CLI (authenticated, for PR management)
- `git`

## Install

From PyPI (once published):

```bash
pip install hyperloop
```

From source (for development or testing):

```bash
git clone git@github.com:jsell-rh/hyperloop.git
cd hyperloop
uv sync --all-extras
```

## Quickstart

1. Create a repo with a spec:

```bash
mkdir -p my-project/specs
cd my-project
git init && git commit --allow-empty -m "init"
```

2. Write a spec. This is what you want built. Be specific about acceptance criteria:

```markdown
<!-- specs/auth.md -->
# User Authentication

Implement JWT-based authentication for the API.

## Acceptance Criteria

- POST /auth/login accepts email + password, returns JWT
- POST /auth/register creates a new user account
- GET /auth/me returns the current user (requires valid JWT)
- Passwords are hashed with bcrypt, never stored in plaintext
- JWTs expire after 24 hours
```

3. Run:

```bash
# From source:
uv run hyperloop run --repo owner/repo --branch main

# Or if installed:
hyperloop run --repo owner/repo --branch main
```

4. See what it would do without executing:

```bash
hyperloop run --repo owner/repo --dry-run
```

The orchestrator reads your specs, has the PM create tasks in `specs/tasks/`, then walks each task through the default pipeline: implement, verify, merge.

## Configuration

Create `.hyperloop.yaml` in your repo root:

```yaml
target:
  base_branch: main

runtime:
  max_workers: 4

merge:
  auto_merge: true
  strategy: squash
```

Then just run from the repo directory:

```bash
hyperloop run
```

The repo is inferred from your git remote. All settings have sensible defaults.

## Customizing Agent Behavior

Hyperloop ships with base agent definitions (implementer, verifier, etc.) that work out of the box. To customize them for your project, overlay with patches.

### In-repo overlay

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

### Shared overlay via gitops repo

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

## Development

```bash
uv sync --all-extras
uv run pytest                    # run tests (280 tests)
uv run ruff check .              # lint
uv run ruff format --check .     # format check
uv run pyright                   # type check
uv run hyperloop --help          # CLI help
```
