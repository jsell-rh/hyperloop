# Agent Prompts Specification

## Purpose

Base agent prompts define the behavioral contract each agent role follows when operating on a team's repository. The prompts are framework defaults shipped in `base/` and composed via the three-layer model defined in the prompt-composition spec. Teams MAY override or extend these via project and process overlays, but the base layer establishes the minimum expected workflow for each role.

Prompts are generic — they contain no project-specific references. Project-specific instructions (coding standards, architectural conventions, preferred test frameworks, file organization rules) belong in the project overlay's guidelines, not in the base prompt.

## Requirements

### Requirement: Decomposer Workflow

The decomposer base prompt SHALL instruct the agent to follow a read-first, dependency-ordered decomposition workflow.

The prompt SHALL address these phases:

| Phase | Concern |
|---|---|
| Read specs | Read each spec provided in the prompt context (injected by the composer at the pinned blob SHA) |
| Read diffs | When a diff is provided (modified specs), use the diff to scope work to only what changed; when no diff is provided (new specs), treat the full spec as new work |
| Read implementation | Read the current codebase to understand what already exists |
| Check for prior failures | When prior events are provided (verification failures, task failures), produce only targeted corrective tasks rather than re-decomposing from scratch |
| Gap analysis | Identify gaps between spec requirements and current implementation |
| Cross-spec dependency awareness | Reference existing tasks from other specs (provided in the prompt context) and declare cross-spec dependencies where appropriate |
| Dependency ordering | Order proposed tasks so that dependencies are respected — no proposed task depends on work from a later proposed task |
| Proposed task formatting | Format each gap as a verifiable unit of work with testing scenarios; do not include implementation details |

#### Scenario: Decomposer reads before decomposing

- GIVEN 3 new specs are provided in the prompt context
- WHEN the decomposer agent runs
- THEN it reads all provided spec content before producing any proposed tasks
- AND it reads the current implementation to identify what already satisfies the specs

#### Scenario: Modified spec scoped by diff

- GIVEN a spec has been modified and a diff from the previous version is provided
- WHEN the decomposer analyzes the spec
- THEN it scopes proposed tasks to only the requirements that changed
- AND it does not re-decompose requirements that are unchanged

#### Scenario: Failure-aware re-decomposition

- GIVEN prior events include a VerificationFailed rationale citing a specific requirement
- WHEN the decomposer re-decomposes the spec
- THEN it produces only targeted corrective proposed tasks addressing the failure
- AND it does not duplicate work that already succeeded

#### Scenario: Proposed tasks are dependency-ordered

- GIVEN spec A defines a model and spec B defines an API that uses the model
- WHEN the decomposer produces proposed tasks
- THEN the model task appears before the API task
- AND the API task declares a dependency on the model task

#### Scenario: Cross-spec dependencies declared

- GIVEN the decomposer receives existing tasks from other specs in the prompt context
- WHEN it produces proposed tasks that depend on work from another spec
- THEN the proposed task declares the cross-spec dependency

#### Scenario: Proposed tasks include testing scenarios

- GIVEN a spec requirement with two scenarios
- WHEN the decomposer creates a proposed task for that requirement
- THEN the proposed task description includes the testing scenarios that must pass

### Requirement: Implementer Workflow

The implementer base prompt SHALL instruct the agent to follow a multi-phase workflow: understand, implement with tests, then self-critique.

The prompt SHALL address these phases:

| Phase | Concern |
|---|---|
| Orientation | Read the spec, the task description, and the surrounding codebase before writing any code |
| Configuration awareness | Identify configurable values that intersect with the work; never hardcode a value that is configurable |
| Implementation with tests | Write tests that verify behavior; ensure tests exercise real behavior rather than implementation details |
| Atomic commits | Each commit represents a coherent, reviewable unit of change |
| Critic pass | Self-review the implementation against specific concerns: data shape, security, code style, test coverage, configuration hardcoding, and real functionality verification |
| Iterative refinement | Fix issues found by the critic pass; repeat until only minor issues remain |

#### Scenario: Implementer reads before writing

- GIVEN a task referencing a spec requirement
- WHEN the implementer agent starts
- THEN it reads the spec content provided in the prompt context
- AND it reads the existing code in the affected area
- AND it does not create any files or commits before completing orientation

#### Scenario: Configuration values are not hardcoded

- GIVEN the project defines a configurable value for a prefix used in branch naming
- WHEN the implementer writes code that uses the prefix
- THEN it accepts the value as a parameter rather than hardcoding a literal string

#### Scenario: Critic pass catches configuration hardcoding

- GIVEN the implementer has completed its implementation
- WHEN the critic pass runs
- THEN it compares every literal string, path, and pattern in the new code against the project's configurable values
- AND it flags any hardcoded value that should be a parameter

#### Scenario: Critic pass verifies real functionality

- GIVEN the implementation produces a CLI command or API endpoint
- WHEN the critic pass runs
- THEN it verifies functionality by running the actual binary or calling the actual endpoint
- AND it does not rely solely on the test harness for verification

### Requirement: Verifier Workflow

The verifier base prompt SHALL instruct the agent to systematically check every spec requirement against the implementation.

The prompt SHALL address these concerns:

| Concern | Description |
|---|---|
| Requirement enumeration | Check every requirement and scenario in the spec, not a sample |
| Evidence-based assessment | Cite specific code locations that satisfy or violate each requirement |
| Test execution | Run the test suite and report results |
| Actionable rationale | When reporting failures, provide specific, actionable rationale that can drive targeted corrective tasks |
| Verdict | Report PASS only if all requirements are met; report FAIL with detailed rationale per unmet requirement |

#### Scenario: Verifier checks every requirement

- GIVEN a spec with 5 requirements and 12 scenarios
- WHEN the verifier runs
- THEN it evaluates all 5 requirements and all 12 scenarios
- AND it does not skip requirements that appear to be satisfied at a glance

#### Scenario: Verifier cites evidence

- GIVEN a spec requirement is satisfied by a specific function in the codebase
- WHEN the verifier evaluates that requirement
- THEN it references the specific file and the behavior it observed

#### Scenario: Verifier runs tests

- GIVEN the workspace contains a test suite
- WHEN the verifier evaluates the implementation
- THEN it runs the tests and includes the results in its assessment

#### Scenario: Failure rationale is actionable

- GIVEN the verifier detects a requirement is not met
- WHEN it reports the failure
- THEN the rationale identifies which specific requirement failed and what is missing
- AND a subsequent decomposer agent could produce a targeted corrective task from the rationale alone

### Requirement: Merge Resolver Workflow

The merge resolver base prompt SHALL instruct the agent to resolve conflicts while preserving the intent of both contributions.

The prompt SHALL address these concerns:

| Concern | Description |
|---|---|
| Intent preservation | Understand the purpose of changes on both sides before resolving |
| Correctness verification | Ensure the merged result builds successfully and tests pass |
| Newer-wins tiebreaker | When contributions are genuinely incompatible, prefer the newer task's intent |

#### Scenario: Both sides preserved

- GIVEN task A adds a function and task B adds a different function in the same file
- WHEN a merge conflict occurs
- THEN the resolver includes both functions in the result

#### Scenario: Merged code passes tests

- GIVEN a merge conflict has been resolved
- WHEN the resolver completes
- THEN the test suite passes on the merged result

### Requirement: Integration Summarizer Workflow

The integration summarizer base prompt SHALL instruct the agent to produce a structured summary suitable for a pull request.

The prompt SHALL address these concerns:

| Concern | Description |
|---|---|
| Audience | Written for human reviewers who have not seen the individual tasks |
| Structure | Produces a PR title and body |
| Scope clarity | Explains what changed and why, without requiring the reader to inspect every file |
| Traceability | References the spec and completed tasks that drove the changes |

#### Scenario: Summary references spec

- GIVEN a verified spec
- WHEN the summarizer produces a PR body
- THEN the body references the spec that drove the changes

#### Scenario: Summary is self-contained

- GIVEN 4 tasks were completed to satisfy the spec
- WHEN the summarizer produces a PR body
- THEN a reviewer can understand the scope and intent without reading the task descriptions individually

### Requirement: Generic Prompts

Base agent prompts SHALL NOT contain project-specific references. Project-specific instructions — coding standards, architectural conventions, preferred test frameworks, file organization rules — belong in the project overlay's guidelines, not in the base prompt.

Testing methodology (TDD vs test-after, mocks vs fakes, specific test frameworks) is a project-level concern. The base prompt instructs agents to write and run tests; the project overlay specifies how.

#### Scenario: Base prompt works on any repository

- GIVEN a team using Hyperloop on a repository in any programming language
- WHEN the base implementer prompt is composed with no project overlay
- THEN the prompt instructs the agent in language-agnostic terms
- AND it does not reference any specific file, framework, or convention

#### Scenario: Project overlay adds specificity

- GIVEN a team adds a guideline specifying their preferred testing approach
- WHEN the implementer prompt is composed
- THEN the base workflow phases are preserved
- AND the project's testing guideline appears in the Guidelines section
