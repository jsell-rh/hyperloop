# hyperloop

Walks tasks through composable process pipelines using AI agents. You write specs, it creates tasks, implements them, verifies the work, and merges the results.

## Prerequisites

- Python 3.12+
- [kustomize](https://kubectl.docs.kubernetes.io/installation/kustomize/) (`kustomize` on PATH)
- `git`
- `gh` CLI (optional, for GitHub PR operations)
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

## How It Works

Agents run via the [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/overview.md) — in-process, with full tool access (file I/O, git, shell). Each parallel worker gets its own git worktree for branch isolation. Serial agents (PM intake, process-improver) run on trunk.

The SDK handles tool execution, context management, and clean exit. No subprocess polling or result-file conventions.

## Project Structure

After `hyperloop init`:

```
my-project/
├── .hyperloop.yaml                     # orchestrator config
├── .hyperloop/
│   ├── agents/
│   │   ├── kustomization.yaml          # composition point (base + process component)
│   │   └── process/
│   │       └── kustomization.yaml      # empty Component (process-improver writes here)
│   ├── state/
│   │   ├── tasks/                      # task metadata (YAML frontmatter)
│   │   └── reviews/                    # per-round review files
│   └── checks/                         # executable check scripts
└── specs/
    └── *.spec.md                       # product specs (your domain)
```

`specs/` is yours — product specs only. `.hyperloop/` is orchestrator-managed.

## Prompt Composition

Three layers, all resolved via a single `kustomize build`:

| Layer | Source | What it provides |
|---|---|---|
| Base | hyperloop repo `base/` | Core agent prompts |
| Project overlay | gitops repo or in-repo patches | Project-specific `guidelines`, persona |
| Process overlay | `.hyperloop/agents/process/` | Learned rules from process-improver |

Agent resources have a `guidelines` field — additive by convention. At compose time: `prompt + guidelines + spec + findings`.

## Configuration

```yaml
# .hyperloop.yaml

overlay: .hyperloop/agents/             # path to kustomization dir
base_ref: github.com/org/hyperloop//base?ref=v1  # remote base for `hyperloop init`

target:
  repo: owner/repo                      # GitHub repo (omit for local-only)
  base_branch: main

runtime:
  max_workers: 6

merge:
  auto_merge: true
  strategy: squash
  delete_branch: true

poll_interval: 30
max_task_rounds: 50
max_cycles: 200
max_rebase_attempts: 3

observability:
  log_format: console                   # console | json
  log_level: info

  matrix:                               # optional
    homeserver: https://matrix.example.com
    registration_token_env: MATRIX_REG_TOKEN
    verbose: false
```

## Custom Processes

Override the default pipeline (implement → verify → merge):

```yaml
# process-patch.yaml
kind: Process
name: default
pipeline:
  - loop:
      - role: implementer
      - role: verifier
  - gate: human-pr-approval
  - action: merge-pr
```

Four primitives: `role` (spawn agent), `gate` (wait for signal), `loop` (retry on failure), `action` (terminal op). Loops nest.

## Development

```bash
uv sync --all-extras
uv run pytest
uv run ruff check . && ruff format --check .
uv run pyright
```
