# hyperloop

A reconciler that keeps code in sync with specs using AI agents. Specs are desired state. Code is actual state. Hyperloop continuously closes the gap.

```
Spec (desired) <-> Code (actual) = Gap
Gap -> Work -> PR -> Gate -> Merge -> Gap closed
```

You don't manage tasks -- you manage specs. Tasks are an internal implementation detail, like Kubernetes pods. Want to add a feature? Update the spec. Want to cancel it? Remove it from the spec.

## Prerequisites

- Python 3.12+
- [kustomize](https://kubectl.docs.kubernetes.io/installation/kustomize/) on PATH
- `git`
- `gh` CLI (for GitHub PR operations)
- An Anthropic API key, or Vertex AI / Bedrock credentials

## Install

```bash
pip install hyperloop
```

## Quickstart

```bash
mkdir my-project && cd my-project && git init && git commit --allow-empty -m init

# Write a spec
cat > specs/auth.md << 'EOF'
# User Authentication
Implement JWT-based auth. POST /auth/login, POST /auth/register, GET /auth/me.
Passwords hashed with bcrypt. JWTs expire after 24h.
EOF

# Initialize hyperloop structure
hyperloop init

# Run the orchestrator
export ANTHROPIC_API_KEY=your-key  # or CLAUDE_CODE_USE_VERTEX=1
hyperloop run

# With GitHub PR support
hyperloop run --repo owner/repo
```

## Reconciliation Cycle

Each cycle has four phases:

1. **COLLECT** -- reap finished workers, run cycle hooks (e.g. process-improver)
2. **INTAKE** -- detect spec gaps and failed tasks, invoke PM agent to propose new work
3. **ADVANCE** -- advance existing tasks through pipeline steps (gates, actions)
4. **SPAWN** -- decide which tasks need workers, compose prompts, spawn agents

The orchestrator halts when no gaps remain. Use `hyperloop watch` for continuous operation.

## Pipeline Primitives

Work moves through a pipeline defined in `process.yaml`. Four primitives:

| Primitive | What it does |
|---|---|
| `agent: X` | Spawn a worker agent with X's prompt template |
| `gate: X` | Block until an external signal (e.g. PR label, CI status) |
| `action: X` | Execute an operation (e.g. merge PR) |
| `loop:` | Wrap steps -- on fail restart from top, on pass continue |

Example pipeline:

```yaml
pipeline:
  - loop:
      - agent: implementer
      - agent: verifier
  - gate: human-pr-approval
  - action: merge-pr
```

## Project Structure

After `hyperloop init`:

```
my-project/
├── .hyperloop.yaml                     # orchestrator config
├── .hyperloop/
│   ├── agents/
│   │   ├── kustomization.yaml          # composition point (base + process component)
│   │   └── process/
│   │       ├── kustomization.yaml      # process-improver writes here
│   │       └── process.yaml            # pipeline + gate/action/hook config
│   ├── state/
│   │   ├── tasks/                      # task metadata (YAML frontmatter)
│   │   └── reviews/                    # per-round review files
│   └── checks/                         # executable check scripts
└── specs/
    └── *.md                            # product specs (your domain)
```

`specs/` is yours -- product specs only. `.hyperloop/` is orchestrator-managed.

## Prompt Composition

Three layers, resolved via `kustomize build`:

| Layer | Source | What it provides |
|---|---|---|
| Base | hyperloop repo `base/` | Core agent prompts |
| Project overlay | gitops repo or in-repo patches | Project-specific `guidelines` |
| Process overlay | `.hyperloop/agents/process/` | Learned rules from process-improver |

At compose time the orchestrator injects: `prompt + guidelines + spec content + findings from prior rounds`.

## Configuration

```yaml
# .hyperloop.yaml

overlay: .hyperloop/agents/
base_branch: main
runtime: local                          # local | ambient

max_workers: 6
poll_interval: 30
max_task_rounds: 50
max_action_attempts: 3

notifications:
  type: github-comment                  # github-comment | null (default: null)
```

## Custom Processes

Override the default pipeline in `.hyperloop/agents/process/process.yaml`:

```yaml
pipeline:
  - loop:
      - agent: implementer
      - agent: verifier
  - gate: human-pr-approval
  - action: merge-pr

gates:
  human-pr-approval:
    type: label                         # label | pr-approval | ci-status | all

actions:
  merge-pr:
    type: pr-merge

hooks:
  after_reap:
    - type: process-improver
```

## Architecture

Hexagonal (ports and adapters). The domain is pure logic with no I/O. Ports define interfaces, adapters implement them. Seven concerns are separated:

| Port | Purpose |
|---|---|
| `SpecSource` | Where to read desired state |
| `StateStore` | Where task/worker state lives |
| `Runtime` | Where agent sessions execute |
| `GatePort` | How gates are evaluated |
| `ActionPort` | How pipeline actions execute |
| `NotificationPort` | How humans are told to act |
| `OrchestratorProbe` | Domain observability |

The default adapter set is git-native (git state store, git spec source, local worktrees for agent isolation), but the architecture is adapter-agnostic.

See `specs/spec.md` for the full specification.

## Development

```bash
uv sync --all-extras
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run pyright
```
