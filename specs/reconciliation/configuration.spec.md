# Configuration Specification

## Purpose

Defines all configurable values for the reconciliation engine, their defaults, validation rules, and how configuration is loaded. Every value referenced as "configurable" across the reconciliation specs is cataloged here. Configuration is loaded once at startup and is immutable for the lifetime of the reconciler instance, except for prompt overlays which support hot-reload.

## Requirements

### Requirement: Configuration Values

The system SHALL support the following configuration values:

**Convergence:**

| Name | Type | Default | Description |
|---|---|---|---|
| convergence_bound | int | 3 | Max verification cycles per spec per blob SHA before transitioning to Failed. Must be >= 1 |
| max_task_retries | int | 3 | Max retry count per task before triggering re-decomposition. Must be >= 0 |
| max_redecompositions | int | 1 | Max times a spec can be re-decomposed per reconciliation attempt. Must be >= 0 |
| max_concurrent_tasks | int | 5 | Max number of tasks dispatched concurrently. Must be >= 1 |

#### Scenario: Convergence bound applied

- GIVEN convergence_bound is set to 2
- WHEN a spec has cycled through Verifying → OutOfSync twice
- THEN the third verification failure transitions the spec to Failed

#### Scenario: Task retry limit applied

- GIVEN max_task_retries is set to 3
- WHEN a task has failed and been retried 3 times
- THEN the task's retries are exhausted and re-decomposition is triggered

#### Scenario: Concurrent task limit applied

- GIVEN max_concurrent_tasks is set to 3
- WHEN 5 tasks are unblocked and eligible for dispatch
- THEN only 3 are dispatched this cycle
- AND the remaining 2 are dispatched in subsequent cycles

#### Scenario: Defaults used when not configured

- GIVEN no explicit convergence_bound is set
- WHEN the reconciler starts
- THEN convergence_bound defaults to 3

#### Scenario: Verification uses different model

- GIVEN implementation_model is set to "claude-sonnet" and verification_model is set to "gemini-pro"
- WHEN a verification agent is launched
- THEN the AgentRuntime adapter uses "gemini-pro" for the verification agent
- AND implementation agents use "claude-sonnet"

**Cycle:**

| Name | Type | Default | Description |
|---|---|---|---|
| cycle_interval_seconds | int | 30 | Sleep duration between reconciliation cycles. Must be >= 1 |

**Model Selection:**

| Name | Type | Default | Description |
|---|---|---|---|
| implementation_model | str | None | Model identifier for implementation agents. When None, the runtime default is used |
| verification_model | str | None | Model identifier for verification agents. SHOULD differ from implementation_model per no-self-grading principle |
| decomposition_model | str | None | Model identifier for decomposition agents. When None, the runtime default is used |

#### Scenario: Cycle interval controls loop timing

- GIVEN cycle_interval_seconds is set to 60
- WHEN a reconciliation cycle completes
- THEN the reconciler waits 60 seconds before starting the next cycle

**Integration:**

| Name | Type | Default | Description |
|---|---|---|---|
| integration_strategy | enum | "pr" | How verified work is integrated to trunk. One of: "pr" (open PR, wait for human merge), "pr_automerge" (open PR with automerge, poll until merged), "direct" (merge locally and push). |
| max_integration_retries | int | 3 | Max retry count for integration failures before transitioning to Failed. Must be >= 1 |
| integration_timeout_seconds | int | 86400 | Max time a spec may remain in PendingIntegration before the integration is treated as failed. Must be >= 60. Default is 24 hours |

#### Scenario: PR strategy (default)

- GIVEN integration_strategy is set to "pr"
- WHEN a spec passes verification
- THEN a pull request is opened from the delivery branch to trunk
- AND the spec remains in PendingIntegration until a human merges the PR

#### Scenario: PR automerge strategy

- GIVEN integration_strategy is set to "pr_automerge"
- WHEN a spec passes verification
- THEN a pull request is opened with automerge enabled
- AND the spec remains in PendingIntegration until the PR is automatically merged

#### Scenario: Direct merge strategy

- GIVEN integration_strategy is set to "direct"
- WHEN a spec passes verification
- THEN the delivery branch is merged to trunk locally and pushed
- AND the spec transitions through PendingIntegration to Synced within the same cycle

#### Scenario: Invalid strategy rejected

- GIVEN integration_strategy is set to "webhook"
- WHEN the reconciler attempts to start
- THEN it fails with a validation error listing the valid strategies

**Paths:**

| Name | Type | Default | Description |
|---|---|---|---|
| specs_directory | str | "specs/" | Directory containing spec files, relative to repository root |
| overlay_path | str | ".hyperloop/agents" | Path to kustomize overlay directory for prompt composition. Must exist at startup |

**Observability:**

| Name | Type | Default | Description |
|---|---|---|---|
| observer_adapters | list of str | [] | Observer adapter identifiers to activate. Empty list uses NullProbe |

#### Scenario: Custom specs directory

- GIVEN specs_directory is set to "doc/specs/"
- WHEN the SpecSource adapter scans for specs
- THEN it looks in "doc/specs/" instead of the default "specs/"

**Git Adapter:**

| Name | Type | Default | Description |
|---|---|---|---|
| plan_branch | str | "hyperloop/plan" | Git branch for plan persistence |
| trunk_branch | str | "main" | Name of the trunk branch |
| branch_prefix | str | "hyperloop/" | Prefix for all reconciler-managed branches |

#### Scenario: Custom trunk branch

- GIVEN trunk_branch is set to "develop"
- WHEN the reconciler syncs with upstream
- THEN it pulls from "develop" instead of "main"

#### Scenario: Branch prefix applied

- GIVEN branch_prefix is set to "hyperloop/"
- WHEN a spec delivery branch is created for blob SHA abc123
- THEN the branch name is "hyperloop/spec/abc123"

### Requirement: Validation

The system SHALL validate all configuration values at startup. Invalid configuration SHALL prevent the reconciler from starting.

#### Scenario: Negative convergence bound rejected

- GIVEN convergence_bound is set to 0
- WHEN the reconciler attempts to start
- THEN it fails with a validation error indicating convergence_bound must be a positive integer

#### Scenario: Negative retry limit rejected

- GIVEN max_task_retries is set to -1
- WHEN the reconciler attempts to start
- THEN it fails with a validation error

#### Scenario: Missing specs directory rejected

- GIVEN specs_directory is set to a path that does not exist
- WHEN the reconciler attempts to start
- THEN it fails with a validation error indicating the directory was not found

#### Scenario: Missing overlay path rejected

- GIVEN overlay_path is set to a path that does not exist
- WHEN the reconciler attempts to start
- THEN it fails with a validation error indicating the overlay directory was not found
- AND the error message suggests running `hyperloop init` to scaffold the default configuration

#### Scenario: Valid configuration accepted

- GIVEN all configuration values are within valid ranges
- WHEN the reconciler starts
- THEN it starts successfully and logs the active configuration via the reconciler_started probe

### Requirement: Immutable After Startup

Configuration SHALL be immutable after the reconciler starts. Changing configuration requires a restart, except for prompt overlays which support hot-reload as specified in prompt-composition.spec.md.

#### Scenario: Configuration does not change mid-run

- GIVEN the reconciler is running with convergence_bound of 3
- WHEN the configuration source is modified externally
- THEN the running reconciler continues using convergence_bound of 3
- AND the change takes effect only on the next restart

#### Scenario: Overlay hot-reload is the exception

- GIVEN the reconciler is running
- WHEN prompt overlay files change in the overlay_path directory
- THEN the prompt composer rebuilds as specified in prompt-composition.spec.md
- AND no reconciler restart is required

### Requirement: Configuration Source

The system SHALL load configuration from a YAML file in the repository. The configuration file path is the only value that MAY be provided via environment variable or command-line argument.

#### Scenario: Configuration loaded from file

- GIVEN a configuration file exists at the expected path
- WHEN the reconciler starts
- THEN it reads and validates all configuration values from the file

#### Scenario: Missing configuration file uses defaults

- GIVEN no configuration file exists
- WHEN the reconciler starts
- THEN all values use their defaults
- AND the reconciler starts successfully
