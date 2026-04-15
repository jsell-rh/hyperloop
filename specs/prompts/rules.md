# Worker Rules

One sentence per rule. Read before starting work. Read again before submitting.

## Result File

- Always write `.worker-result.json` to the repo root before finishing — the orchestrator cannot advance the task without it.
- The result file must contain exactly three fields: `verdict` (`"pass"` or `"fail"`), `findings` (integer count of issues), and `detail` (one-sentence summary).
- Write the result file last, after all code changes are committed, so the file reflects the final state of the work.
- A missing or malformed result file is treated as a task failure regardless of the quality of the code changes.

## TDD

- Write the failing test before writing any implementation code — no exceptions.
- Do not use `unittest.mock`, `MagicMock`, or `patch`; use fakes from `tests/fakes/` instead.

## Code Quality

- Every new function must have full type hints; `Any` is banned.
- Do not set task status in the task file — the orchestrator owns that field.
- Commit each logical change atomically; all tests must pass on every commit.
