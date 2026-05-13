# Hyperloop

Spec-driven reconciliation engine. Specs declare desired state; code is actual state; agents reconcile the two.

> **Note:** This project _builds_ a spec-to-code reconciler — but we are also _building that reconciler from specs_. These instructions govern how to build the reconciler (development process). They are distinct from the design decisions within `specs/` and the reconciler's own runtime behavior.

## Working With Me

- **Never assume — verify.** Check the code, search the web, or ask the user. Do not guess at behavior, API surfaces, or library capabilities.
- **Specs are the source of truth.** If asked to implement something not covered by a spec, confirm with the user whether the spec should be updated first. Update the spec, then implement.
- **Challenge directions that seem wrong.** Push back respectfully when something looks incorrect, contradictory, or likely to cause problems. Don't agree just to be agreeable.

## Architecture

- **Domain-Driven Design / Hexagonal Architecture.** Organize files by domain, not by port/adapter/layer.
- **One file per type.** Nested directories denote domains and subcomponents. Within each domain, `models/`, `ports/`, `adapters/`, etc. are directories. Each file contains a single type (one model, one port, one adapter). No multi-type files.
- **Correctness over backwards compatibility.** Never take shortcuts or make decisions to preserve backwards compatibility. Provide correct implementations only.
- **Simplicity is a virtue.** Remove dead code. But simplicity must not supersede correctness or break prescribed architecture/existing patterns.

## Observability

- **Domain-Oriented Observability only.** No direct logging calls (no `logger.info`, `logger.debug`, etc.).
- **Domain probes** are the sole observability mechanism. Probes express domain-meaningful events, not infrastructure concerns.
- **Structlog** is the probe implementation backend.

## Testing

- **Fakes, not mocks.** All test doubles must be behavioral fakes that provide real guarantees about correctness. No `unittest.mock`, no `MagicMock`, no `patch`.
- Tests must verify behavior, not implementation details.

### Running Tests

```bash
uv run pytest              # full suite (parallel via pytest-xdist)
uv run pytest -x           # stop on first failure
uv run pytest tests/reconciliation/adapters/test_claude_sdk_executor.py  # single file
uv run pytest -k "test_cancel"  # by name pattern
```


## Development Workflow

- Invoke the `/develop` skill. This will provide you with a verifiable unit of work tied to a spec that you are to complete.

## Python Standards

- **Type hints everywhere.** No `Any`. Every function signature, variable where the type is not obvious, and return type must be annotated.
- **Pydantic** for all data objects. **Pydantic Settings** for configuration.
- **Enums over magic strings.** Always. No bare string comparisons for state, status, type, or category. Use `StrEnum`, not `(str, Enum)`.
- **`uv`** for package management. Use `uv add` etc., NEVER adding packages by hand. Pin all dependencies.

## Specs

- Specs live in `specs/` and define desired state using RFC 2119 language (`SHALL`, `MUST`, `SHOULD`, `MAY`).
- Specs describe observable behavior, not implementation. See `specs/index.spec.md` for format.
