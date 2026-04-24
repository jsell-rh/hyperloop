# State Management Specification

## Purpose

The system persists orchestrator state (tasks, reviews, summaries, epochs) durably and separately from application code. State lives on a dedicated branch to keep the main branch clean. Garbage collection prunes terminal state after a retention period, writing summaries to preserve historical context.

## Requirements

### Requirement: State Branch Isolation

Orchestrator state SHALL be persisted on a dedicated branch (e.g., `hyperloop/state`), not on the main branch. Code commits on main and state commits on the state branch MUST NOT interfere with each other.

#### Scenario: State commits don't pollute main

- GIVEN the orchestrator persists state every cycle
- WHEN a developer views the main branch history
- THEN no state commits appear
- AND only merged code PRs are visible

#### Scenario: State branch is operational

- GIVEN the state branch exists
- WHEN the orchestrator syncs
- THEN it pulls and pushes the state branch
- AND the main branch is unaffected

#### Scenario: State branch created on first run

- GIVEN no state branch exists
- WHEN the orchestrator starts for the first time
- THEN it creates the state branch
- AND initializes the state directory structure

### Requirement: Task File Format

Tasks SHALL be persisted as individual files with YAML frontmatter containing all task fields.

#### Scenario: Task file structure

- GIVEN task-001 exists
- WHEN it is persisted
- THEN a file is written at `.hyperloop/state/tasks/task-001.md`
- AND the file contains YAML frontmatter with: id, title, spec_ref, status, phase, deps, round, branch, pr

#### Scenario: Task file update

- GIVEN task-001 transitions from phase "implement" to "verify"
- WHEN the state is persisted
- THEN the task file is updated with the new phase
- AND other fields remain unchanged

### Requirement: Review File Format

Review findings SHALL be persisted as individual files per task per round, separate from task files.

#### Scenario: Review file structure

- GIVEN task-001 fails at round 2 with detail "missing error handling"
- WHEN the review is stored
- THEN a file is written at `.hyperloop/state/reviews/task-001-round-2.md`
- AND it contains YAML frontmatter (task_id, round, role, verdict) and the detail as body text

#### Scenario: Multiple rounds preserved

- GIVEN task-001 has failed 3 times
- WHEN get_findings is called
- THEN it returns the most recent round's detail
- AND all three review files exist for historical queries

### Requirement: Summary File Format

Summary records SHALL be written when garbage collection prunes terminal tasks. Summaries preserve historical context without the full task and review files.

#### Scenario: Summary structure

- GIVEN GC prunes tasks for spec "auth.md@abc123"
- WHEN the summary is written
- THEN a file exists at `.hyperloop/state/summaries/auth.md.yaml`
- AND it contains: spec (path), spec_ref (with SHA), total_tasks, completed, failed, failure_themes, last_audit, last_audit_result

#### Scenario: Summary accumulates across versions

- GIVEN spec "auth.md" has been through two versions (@abc123 and @def456)
- WHEN both versions' tasks are pruned
- THEN the summary contains entries for both versions
- AND the PM can see the full history when creating tasks for a third version

### Requirement: Persist and Sync

State changes SHALL be persisted via atomic commits to the state branch and synced with the remote.

#### Scenario: Persist commits to state branch

- GIVEN pending state changes (task transitions, new reviews)
- WHEN persist is called
- THEN all changes are committed atomically to the state branch
- AND the commit message describes the changes

#### Scenario: Sync pulls then pushes

- GIVEN the state branch may have diverged from remote
- WHEN sync is called
- THEN it pulls from remote with rebase
- AND pushes to remote
- AND conflicts in state files are resolved deterministically

### Requirement: Garbage Collection Lifecycle

Terminal tasks (status "synced" or "failed") SHALL be pruned after a configurable retention period. Pruning writes a summary before deleting task and review files.

#### Scenario: Retention period check

- GIVEN task-001 reached "synced" 45 days ago
- WHEN the retention period is 30 days
- THEN task-001 is eligible for pruning

#### Scenario: Pruning sequence

- GIVEN task-001 is eligible for pruning
- WHEN GC runs
- THEN a summary record is written (or updated) for the task's spec
- AND the task file is deleted
- AND the task's review files are deleted
- AND the full detail remains in git history

#### Scenario: Active tasks never pruned

- GIVEN task-002 has status "in-progress"
- WHEN GC runs
- THEN task-002 is not affected regardless of age

### Requirement: Crash Recovery from State

On restart, the orchestrator SHALL reconstruct its operational state entirely from the persisted state branch.

#### Scenario: Restart reads state

- GIVEN the orchestrator crashed
- WHEN it restarts
- THEN it reads all task files from the state branch
- AND reconstructs the world snapshot
- AND resumes from each task's persisted phase

### Requirement: GC Configuration

Garbage collection behavior SHALL be configurable.

#### Scenario: Configuration options

- GIVEN the configuration file
- WHEN GC settings are specified
- THEN the following options are honored: retention_days (default 30), summarize (default true), run_every_cycles (default 100)
