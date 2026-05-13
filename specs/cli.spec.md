# CLI Specification

## Purpose

Provides a kubectl-style command-line interface for inspecting reconciliation state stored in the Plan. The CLI reads from the PlanStore (plan.json on the git plan branch) and presents SpecPlans, Tasks, and Events in a human-readable format. The `run` subcommand starts the reconciler and streams live domain probe events.

## Requirements

### Requirement: Get Resources

The CLI SHALL support listing resources with `hyperloop get <resource>`.

#### Scenario: Get specs

- GIVEN a Plan with 3 SpecPlans
- WHEN `hyperloop get specs` is run
- THEN it displays a table:
  ```
  PATH                  BLOB SHA   STATUS       TASKS   AGE
  specs/auth.spec.md    abc123     Reconciling  3/5     2h
  specs/users.spec.md   def456     Synced       4/4     1d
  specs/rbac.spec.md    ghi789     Failed       0/2     30m
  ```
- AND superseded SpecPlans are hidden by default

#### Scenario: Get specs shows superseded with flag

- GIVEN a Plan with superseded SpecPlans
- WHEN `hyperloop get specs --all` is run
- THEN superseded SpecPlans are included with a Superseded status indicator

#### Scenario: Get tasks

- GIVEN a Plan with tasks across multiple specs
- WHEN `hyperloop get tasks` is run
- THEN it displays a table:
  ```
  ID   NAME                  SPEC                  STATUS      RETRIES   AGE
  1    Create schema          specs/auth.spec.md    Complete    0         2h
  2    Implement repository   specs/auth.spec.md    Complete    1         1h
  3    Add API endpoint       specs/auth.spec.md    InProgress  0         30m
  4    Add validation         specs/users.spec.md   Backlog     0         2h
  5    Write migrations       specs/users.spec.md   Failed      3         45m
  ```

#### Scenario: Get tasks filtered by spec

- GIVEN tasks across multiple specs
- WHEN `hyperloop get tasks --spec specs/auth.spec.md` is run
- THEN only tasks belonging to specs/auth.spec.md are displayed

#### Scenario: Get events

- GIVEN a Plan with events on SpecPlans and Tasks
- WHEN `hyperloop get events` is run
- THEN it displays all events across all resources in reverse chronological order:
  ```
  LAST SEEN   TYPE      REASON               OBJECT                        MESSAGE
  5m ago      Normal    VerificationPassed    spec/specs/auth.spec.md       Implementation matches spec
  10m ago     Warning   TaskFailed            task/5                        TypeError in auth handler
  1h ago      Warning   VerificationFailed    spec/specs/rbac.spec.md       Missing error handling for...
  ```

### Requirement: Describe Resources

The CLI SHALL support detailed views with `hyperloop describe <resource> <identifier>`. Describe output SHALL include an Events section formatted like `kubectl describe`, showing events attached to the resource.

#### Scenario: Describe spec

- GIVEN a SpecPlan for specs/auth.spec.md at SHA abc123
- WHEN `hyperloop describe spec specs/auth.spec.md` is run
- THEN it displays:
  ```
  Name:           specs/auth.spec.md
  Blob SHA:       abc123
  Status:         Reconciling
  Superseded:     false
  Attempts:       1
  Redecomposed:   false
  Tasks:          3 Complete, 1 InProgress, 1 Failed (5 total)

  Tasks:
    ID   NAME                  STATUS      RETRIES
    1    Create schema          Complete    0
    2    Implement repository   Complete    1
    3    Add API endpoint       InProgress  0
    4    Add validation         Backlog     0
    5    Write migrations       Failed      3

  Events:
    Type     Reason               Count   First Seen   Last Seen   Message
    ----     ------               -----   ----------   ---------   -------
    Normal   VerificationPassed   1       2h ago       2h ago      Implementation matches spec
    Warning  VerificationFailed   2       3h ago       2h ago      Missing timeout handling in...
  ```

#### Scenario: Describe task

- GIVEN task 5 with multiple failure events
- WHEN `hyperloop describe task 5` is run
- THEN it displays:
  ```
  ID:             5
  Name:           Write migrations
  Spec:           specs/users.spec.md
  Blob SHA:       def456
  Status:         Failed
  Dependencies:   [4]

  Events:
    Type     Reason         Count   First Seen   Last Seen   Message
    ----     ------         -----   ----------   ---------   -------
    Warning  TaskFailed     3       45m ago      10m ago     TypeError: 'NoneType' has...
  ```

#### Scenario: Describe nonexistent resource

- GIVEN no task with ID 99 exists
- WHEN `hyperloop describe task 99` is run
- THEN it exits with an error message: "task 99 not found"

### Requirement: Init Subcommand

The `hyperloop init` subcommand SHALL scaffold the default Hyperloop configuration in the current repository.

#### Scenario: Init creates overlay directory

- GIVEN no `.hyperloop/agents/` directory exists
- WHEN `hyperloop init` is run
- THEN `.hyperloop/agents/kustomization.yaml` is created referencing the base templates
- AND the reconciler can be started with `hyperloop run` using default configuration

#### Scenario: Init is idempotent

- GIVEN `.hyperloop/agents/kustomization.yaml` already exists
- WHEN `hyperloop init` is run
- THEN the existing configuration is not overwritten
- AND the command exits successfully

#### Scenario: Init in non-git directory

- GIVEN the current directory is not a git repository
- WHEN `hyperloop init` is run
- THEN it fails with an error indicating a git repository is required

### Requirement: Run Subcommand

The `hyperloop run` subcommand SHALL start the reconciler and stream live domain probe events to the console.

#### Scenario: Run streams probe events

- GIVEN a valid configuration
- WHEN `hyperloop run` is run
- THEN the reconciler starts
- AND domain probe events are streamed to stdout as structured log lines
- AND the process runs until interrupted (Ctrl+C) or the reconciler halts

#### Scenario: Run with configuration file

- GIVEN a configuration file at `.hyperloop.yaml`
- WHEN `hyperloop run --config .hyperloop.yaml` is run
- THEN configuration is loaded from the specified file

#### Scenario: Run without configuration file

- GIVEN no `.hyperloop.yaml` exists but `.hyperloop/agents/` has been initialized
- WHEN `hyperloop run` is run
- THEN all configuration values use their defaults
- AND the reconciler starts successfully

### Requirement: Read-Only State Access

All `get` and `describe` commands SHALL be read-only. They read from the PlanStore without modifying state. They do not require a running reconciler.

#### Scenario: CLI works without running reconciler

- GIVEN a Plan exists on the hyperloop/plan branch
- WHEN `hyperloop get specs` is run
- THEN it reads the plan and displays results
- AND no reconciler process needs to be running

#### Scenario: CLI does not modify state

- GIVEN the CLI reads the Plan
- WHEN any `get` or `describe` command completes
- THEN no commits are created on the plan branch
- AND no branches are created or deleted

### Requirement: Event Formatting

Events SHALL be formatted consistently across all describe commands using a tabular layout with columns: Type, Reason, Count, First Seen, Last Seen, Message. Timestamps SHALL be displayed as relative durations (e.g., "5m ago", "2h ago", "3d ago").

#### Scenario: Event with aggregated count

- GIVEN a TaskFailed event with count 3, first_timestamp 45m ago, last_timestamp 10m ago
- WHEN displayed in a describe command
- THEN it shows count 3, First Seen "45m ago", Last Seen "10m ago"

#### Scenario: Long messages are truncated

- GIVEN an event with a message longer than the terminal width
- WHEN displayed
- THEN the message is truncated with "..." to fit the available width

### Requirement: Output Formats

The CLI SHALL support structured output for programmatic consumption.

#### Scenario: JSON output

- GIVEN any `get` or `describe` command
- WHEN the `--output json` flag is provided
- THEN the output is formatted as JSON matching the Plan data model

#### Scenario: Default is human-readable tables

- GIVEN any `get` or `describe` command
- WHEN no `--output` flag is provided
- THEN the output is formatted as human-readable tables
