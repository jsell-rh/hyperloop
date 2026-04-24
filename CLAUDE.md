# hyperloop

A spec-to-code reconciler. Specs declare desired behavior. Code is actual behavior. Hyperloop detects gaps and dispatches AI agents to close them.

## Quick Start

```bash
uv sync
uv run pytest                    # run tests
uv run ruff check .              # lint
uv run ruff format --check .     # format check
```

## Architecture

Hexagonal (ports & adapters). Domain logic has zero I/O dependencies.

```
src/hyperloop/
├── domain/              ← pure logic, no I/O, no framework imports
│   ├── model.py         ← Task, WorkerResult, Process, Pipeline
│   ├── decide.py        ← decide(world) → Action[] (pure function)
│   └── pipeline.py      ← pipeline executor (recursive, handles loops)
├── ports/               ← interfaces only (Protocol classes)
│   ├── state.py         ← StateStore protocol
│   └── runtime.py       ← Runtime protocol
├── adapters/            ← implementations of ports
│   ├── runtime/
│   │   ├── agent_sdk.py ← AgentSdkRuntime (Claude Agent SDK + worktrees)
│   │   └── _worktree.py ← shared git worktree helpers
│   ├── state/
│   │   └── git.py       ← GitStateStore
│   └── probe/           ← NullProbe, MultiProbe, StructlogProbe, MatrixProbe
├── compose.py           ← prompt composition (kustomize build)
└── loop.py              ← main loop, wires ports to domain
```

The dependency rule: domain/ imports nothing from ports/ or adapters/. Ports/ imports from domain/ (for types). Adapters/ imports from ports/ and domain/. Loop imports everything.

## Development Practices

### TDD — strict, no exceptions

Write the failing test first, then implement. Red → green → refactor. Every behavior starts as a test. If you can't write a test for it, reconsider the design.

### No mocks — use fakes

Do NOT use `unittest.mock`, `MagicMock`, `patch`, or any mocking library. Instead:

- **Fakes**: complete in-memory implementations of port interfaces. They implement the full contract, not just the methods one test needs. Fakes are first-class code — tested, reusable, and shipped alongside the port they implement.
- **Real objects**: use the actual domain objects. The domain is pure — no I/O, no reason to replace it.
- **Layered testing**: small tests exercise domain logic with fakes. Integration tests exercise adapters against real systems. Overlap between layers is a feature, not redundancy.

Why: mocks couple tests to implementation details. A mock-heavy test says "this function calls that function with these args" — it tests the wiring, not the behavior. When you refactor, mock tests break even if behavior is preserved. Fakes test the contract.

Reference: https://www.alechenninger.com/2020/11/the-secret-world-of-testing-without.html

### Fakes live next to their ports

```
ports/
├── state.py          ← StateStore protocol
└── runtime.py        ← Runtime protocol
tests/
├── fakes/
│   ├── state.py      ← InMemoryStateStore (full implementation, tested)
│   └── runtime.py    ← InMemoryRuntime (full implementation, tested)
├── test_decide.py
├── test_pipeline.py
└── test_loop.py
```

Every fake must pass the same contract tests as its real adapter. If `InMemoryStateStore` diverges from `GitStateStore` behavior, the contract tests catch it.

### Type hints — full coverage, no Any

Every function signature, every variable where the type isn't obvious. Use `Protocol` for interfaces. Use dataclasses or named tuples for value objects. `Any` is banned — if you reach for it, the model is wrong.

### DDD — domain drives the design

The domain model (`domain/`) is the heart. It contains:
- **Value objects**: `TaskStatus`, `Phase`, `Verdict`, `WorkerResult`
- **Entities**: `Task`, `Process`
- **Pure functions**: `decide()`, `run_pipeline()`

These have no dependencies on frameworks, I/O, or infrastructure. They are tested directly, without fakes, because they are pure.

Ports define what the domain needs from the outside world. Adapters fulfill those needs. The domain never knows which adapter is in use.

## Tooling

- **Package manager**: `uv` (not pip, not poetry)
- **Linting + formatting**: `ruff` (configured in pyproject.toml)
- **Testing**: `pytest`
- **Pre-commit**: installed and configured for ruff lint, ruff format, and pytest
- **Type checking**: `pyright` (strict mode)

## Commit Conventions

- Conventional commits: `feat:`, `fix:`, `refactor:`, `test:`, `chore:`, `docs:`
- One logical change per commit
- Atomic commits — each commit should pass all tests

## Specs

The spec index lives at [`specs/index.spec.md`](specs/index.spec.md). It is the table of contents for all spec files. If code and spec disagree, align the code to the spec.

Key specs:
- **[Architecture](specs/architecture.spec.md)** — system identity, two-subsystem design, data model, ports
- **[Reconciler](specs/reconciler.spec.md)** — drift detection, PM intake, audit, GC
- **[Task Processor](specs/task-processor.spec.md)** — phase map, step execution, deterministic workflow
- **[Ports](specs/ports.spec.md)** — contracts for all seven port interfaces
- **[NFR](specs/nfr.spec.md)** — fakes over mocks, contract tests, scenario test coverage
