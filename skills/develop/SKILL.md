---
name: develop
description: >
  Retrieve a verifiable unit of work, derived from a spec, to implement.
  Use when the user wants to continue the development of the system.
---

Follow the workflow phases in order.

## Steps

### Phase 1 — Retrieve Unit of Work

Spawn a subagent with instructions found verbatim in <repo_root>/workflows/development/next-unit-of-work.workflow.md.

### Phase 2 — Execute the Unit of Work

Read actual code and existing specs in the affected areas. Confirm your understanding without wasting the user's time.

**Before writing any code**, read the Configuration model and identify every configurable value
that intersects with the work. Spec examples use concrete values (e.g. `hyperloop/spec/abc123/task/5`)
to illustrate behavior — those values are often configurable (e.g. `branch_prefix`). Never hardcode
a value that exists in Configuration; accept it as a constructor parameter. Check how peer
components in the same domain receive their configuration and follow the same pattern.

Proceed with test driven development. Tests should share reusable components where possible, 
use fakes instead of mocks, and test real behavior. If the tests pass but the software crashes, 
the tests did not do their job.

Use atomic, conventional commits.

Follow implementation guidelines found in AGENTS.md.

### Phase 4 — Critic Pass

Spawn critics in parallel to review the implementation. Standard critics:
- Data shape
- Security review
- Consistency, code style (ex. NO MAGIC STRINGS), etc.
- Test coverage
- Configuration hardcoding: compare every literal string, prefix, path, or pattern in the new code against the Configuration model. If a value appears in Configuration, the code must accept it as a parameter — not hardcode it. Spec examples are illustrations, not constants.
- Verify actual functionality by running the real binary/entry points from the command line, not just via test harnesses. If the work produces a CLI command, run it. If it produces an API, call it. Tests verify code correctness — this critic verifies that the software actually works when a user runs it.

Plus work-driven critics based on the scope of the unit of work.

### Phase 5–6 — Synthesize and Present

Separate findings into factual errors (fix directly) and design decisions (present to user with 2–3 concrete options each, one at a time).

### Phase 7 — Apply and Verify

Apply all fixes. Run a second critic pass (Phase 8). Stop when only MINORs remain.