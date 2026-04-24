# State Management Specification

## Purpose

The system persists orchestrator state (tasks, reviews, summaries, epochs) durably on a dedicated git branch, separate from application code on main. This keeps the main branch clean for code-only commits. Garbage collection prunes terminal state after a retention period, writing summaries to preserve historical context.

## Requirements

### Requirement: State Branch Isolation

Orchestrator state SHALL be persisted on a dedicated orphan branch (`hyperloop/state`), not on the main branch. Code commits on main and state commits on the state branch MUST NOT interfere with each other.

#### Scenario: State commits don't pollute main

- GIVEN the orchestrator persists state every cycle
- WHEN a developer views the main branch history
- THEN no state commits appear
- AND only merged code PRs are visible

#### Scenario: State branch is an orphan branch

- GIVEN the state branch needs to be created
- WHEN the orchestrator initializes it
- THEN it creates an orphan branch (no shared history with main)
- AND this prevents any accidental merge between state and code

### Requirement: State Branch Bootstrap

On first run, the orchestrator SHALL create the state branch and initialize the directory structure.

#### Scenario: First-run bootstrap

- GIVEN no `hyperloop/state` branch exists locally or on the remote
- WHEN the orchestrator starts for the first time
- THEN it creates an orphan branch named `hyperloop/state`
- AND creates the directory structure: `.hyperloop/state/tasks/`, `.hyperloop/state/reviews/`, `.hyperloop/state/summaries/`
- AND commits the empty structure
- AND pushes the branch to the remote

#### Scenario: Remote branch exists but not local

- GIVEN the `hyperloop/state` branch exists on the remote but not locally
- WHEN the orchestrator starts
- THEN it fetches and checks out the remote state branch
- AND continues from the persisted state

### Requirement: State Branch Read/Write Protocol

The orchestrator SHALL use `git show` to read state files from the state branch without checking it out. Writes SHALL use a temporary worktree or index manipulation to commit to the state branch without leaving main.

#### Scenario: Reading state without checkout

- GIVEN the orchestrator is on the main branch
- WHEN it needs to read task files
- THEN it uses `git show hyperloop/state:.hyperloop/state/tasks/task-001.md`
- AND the main branch working tree is unaffected

#### Scenario: Writing state without checkout

- GIVEN the orchestrator needs to persist state changes
- WHEN it commits to the state branch
- THEN it uses a temporary index or worktree to stage and commit changes to `hyperloop/state`
- AND the main branch working tree and index are unaffected

#### Scenario: Workers do not access state directly

- GIVEN a worker runs on a task branch (off main)
- WHEN the worker needs context (spec, findings, previous feedback)
- THEN that context is provided in the worker's prompt at spawn time
- AND the worker has no need to read the state branch

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
- AND the main branch is not modified

#### Scenario: Sync pulls then pushes

- GIVEN the state branch may have diverged from remote
- WHEN sync is called
- THEN it fetches `origin/hyperloop/state`
- AND rebases local state branch onto the fetched ref
- AND pushes the state branch to origin

### Requirement: Sync Conflict Resolution

On rebase conflicts during sync, the system SHALL apply a deterministic resolution strategy.

#### Scenario: Task file conflict

- GIVEN two orchestrator restarts wrote different task statuses
- WHEN a rebase conflict occurs on a task file
- THEN the remote version (origin) wins
- AND the local version is discarded
- AND this is safe because the orchestrator is single-instance (remote is the prior self)

#### Scenario: Review file conflict

- GIVEN a review file conflicts during rebase
- WHEN the conflict is detected
- THEN the local version wins (review was just written by this instance)

#### Scenario: Summary file conflict

- GIVEN a summary file conflicts during rebase
- WHEN the conflict is detected
- THEN the local version wins (summary was just written by GC)

### Requirement: State File Isolation from Code Branches

Worker task branches and merged PRs MUST NOT contain state files. State files exist only on the state branch.

#### Scenario: PR merge doesn't carry state

- GIVEN a PR for task-001 is squash-merged to main
- WHEN the merge completes
- THEN no `.hyperloop/state/` files are present on main
- AND the state branch is the sole location for state files

#### Scenario: Worker branches don't contain state

- GIVEN a worker runs on branch `task-001-impl`
- WHEN the worker commits code
- THEN no `.hyperloop/state/` files are committed to the task branch
- AND the verdict file (`.hyperloop/worker-result.yaml`) is the only hyperloop file on task branches

### Requirement: Garbage Collection Lifecycle

Terminal tasks (status "completed" or "failed") SHALL be pruned after a configurable retention period. Pruning writes a summary before deleting task and review files.

#### Scenario: Retention period check

- GIVEN task-001 reached "completed" 45 days ago
- WHEN the retention period is 30 days
- THEN task-001 is eligible for pruning

#### Scenario: Pruning sequence

- GIVEN task-001 is eligible for pruning
- WHEN GC runs
- THEN a summary record is written (or updated) for the task's spec
- AND the task file is deleted
- AND the task's review files are deleted
- AND the full detail remains in git history of the state branch

#### Scenario: Active tasks never pruned

- GIVEN task-002 has status "in-progress"
- WHEN GC runs
- THEN task-002 is not affected regardless of age

### Requirement: Crash Recovery from State

On restart, the orchestrator SHALL reconstruct its operational state entirely from the persisted state branch.

#### Scenario: Restart reads state

- GIVEN the orchestrator crashed
- WHEN it restarts
- THEN it reads all task files from the state branch (via `git show`)
- AND reconstructs the world snapshot
- AND resumes from each task's persisted phase

### Requirement: GC Configuration

Garbage collection behavior SHALL be configurable.

#### Scenario: Configuration options

- GIVEN the configuration file
- WHEN GC settings are specified
- THEN the following options are honored: retention_days (default 30), summarize (default true), run_every_cycles (default 100)
