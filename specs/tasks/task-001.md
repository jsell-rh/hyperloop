---
id: task-001
title: Load Process definition from kustomize output
spec_ref: specs/spec.md
status: in-progress
phase: implementer
deps: []
round: 0
branch: null
pr: null
---

## Spec

The orchestrator resolves its agent definitions by running `kustomize build <overlay-path>` at startup. The same kustomize output also contains a `kind: Process` document that specifies the `intake` and `pipeline` steps for the project. Currently, `compose.py`'s `_parse_multi_doc()` ignores `kind: Process` documents, and the CLI hardcodes the default process as a Python literal (`LoopStep`, `RoleStep`, `ActionStep`). The hardcoded default matches the base `process.yaml`, but projects that overlay the process via kustomize patches will not have their overrides respected.

### What to build

**1. Process YAML parsing** (`src/hyperloop/compose.py`):

Add a `parse_process(raw: str) -> Process | None` function that:
- Accepts multi-document YAML string (the output of `kustomize build`)
- Finds the document where `kind == "Process"` (there will be at most one)
- Converts the `intake` list and `pipeline` list into `Process` domain objects using the four pipeline primitives: `role:`, `gate:`, `loop:`, `action:`
- Handles nested loops (a `loop:` entry whose value is a list may contain another `loop:` entry)
- Returns `None` if no Process document is found
- Raises `ValueError` with a descriptive message for unrecognised primitive keys

The base `process.yaml` uses this format:

```yaml
apiVersion: hyperloop.io/v1
kind: Process
metadata:
  name: default

intake:
  - role: pm

pipeline:
  - loop:
      - role: implementer
      - role: verifier
  - action: merge-pr
```

YAML list entries are maps with a single key:
- `{role: X}` → `RoleStep(role=X, on_pass=None, on_fail=None)`. If `on_pass` or `on_fail` keys are present, populate them.
- `{gate: X}` → `GateStep(gate=X)`
- `{loop: [...]}` → `LoopStep(steps=(...))` where the value is a nested list parsed recursively
- `{action: X}` → `ActionStep(action=X)`

**2. Expose Process from `PromptComposer.from_kustomize`** (`src/hyperloop/compose.py`):

`from_kustomize` currently returns only a `PromptComposer`. Add a companion classmethod or standalone function so callers can also get the parsed `Process`:

```python
@classmethod
def load_from_kustomize(
    cls,
    overlay: str | None,
    state: StateStore,
    base_ref: str = HYPERLOOP_BASE_REF,
) -> tuple[PromptComposer, Process | None]:
    raw_yaml = _kustomize_build(overlay, base_ref=base_ref)
    templates = _parse_multi_doc(raw_yaml)
    process = parse_process(raw_yaml)
    return cls(templates, state), process
```

`from_kustomize` should remain for backwards compatibility (it can call `load_from_kustomize` and discard the process, or be updated — callers in the CLI must be updated).

**3. CLI update** (`src/hyperloop/cli.py`):

Update the `run` command:
- Call `load_from_kustomize` (or equivalent) instead of the old `from_kustomize` + hardcoded process
- If a `Process` was found in the kustomize output, use it; otherwise fall back to the current hardcoded default
- The fallback default process must remain identical to the current one so existing behaviour is preserved

**4. Tests** (`tests/test_compose.py`):

TDD: write failing tests first, then implement. Tests must cover:
- `parse_process` on the base `process.yaml` content → produces correct `Process` with nested `LoopStep`
- `parse_process` with an overridden pipeline (e.g., no loop, just implementer → action)
- `parse_process` on YAML with no `kind: Process` doc → returns `None`
- `parse_process` with an unknown primitive key → raises `ValueError`
- `load_from_kustomize` returns `(PromptComposer, Process)` when Process doc present
- `load_from_kustomize` returns `(PromptComposer, None)` when no Process doc

Do not use mocks. Use `load_templates_from_dir` and the real `base/` directory YAML files where possible. For kustomize build tests, use the multi-doc YAML directly (do not invoke kustomize in unit tests).

## Findings
