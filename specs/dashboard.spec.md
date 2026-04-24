# Dashboard Specification

## Purpose

The dashboard is a web interface for observing orchestrator state and issuing control commands. It reads state from the StateStore and events from the file observer. It provides real-time visibility into spec coverage, task progress, pipeline position, and review history. Control operations allow humans to restart tasks, retire tasks, and force-clear gates without touching git directly.

## Requirements

### Requirement: Read-Only Observation

The dashboard SHALL provide read-only views of all orchestrator state without requiring access to the running orchestrator process.

#### Scenario: Observe any repo

- GIVEN a repository with `.hyperloop/state/` on its state branch
- WHEN the dashboard is pointed at that repo
- THEN it renders the current state of all specs and tasks

#### Scenario: Independent of orchestrator

- GIVEN the orchestrator is not running
- WHEN the dashboard is started
- THEN it displays the last-persisted state
- AND indicates that no orchestrator is active

### Requirement: Spec Overview

The dashboard SHALL display all specs with their coverage status and task progress.

#### Scenario: Spec card display

- GIVEN 5 specs with varying task progress
- WHEN the overview page loads
- THEN each spec is shown as a card with: title, progress bar, task status breakdown (not-started, in-progress, synced, failed)
- AND specs are sorted: in-progress first, then not-started, then synced, then all-failed

#### Scenario: Spec detail

- GIVEN spec "auth.md" has 3 tasks
- WHEN the user navigates to the spec detail view
- THEN the spec content is rendered as markdown
- AND all tasks for this spec are listed with their current phase and status

### Requirement: Task Detail

The dashboard SHALL display full task detail including pipeline position, review history, and prompt provenance.

#### Scenario: Task metadata

- GIVEN task-001 is at phase "verify", round 2
- WHEN the user views the task detail
- THEN they see: id, title, spec_ref, status, phase, round, branch, PR link, dependencies

#### Scenario: Pipeline position visual

- GIVEN a phase map with 6 phases
- WHEN the user views a task at phase "verify"
- THEN a visual indicator shows "verify" as the current step in the sequence

#### Scenario: Review history

- GIVEN task-001 has review findings from rounds 0 and 1
- WHEN the user views the task detail
- THEN both reviews are shown in chronological order with: round, role, verdict, and detail text

#### Scenario: Prompt provenance

- GIVEN task-001's last prompt was composed from base + project overlay + spec + findings
- WHEN the user views the prompt detail
- THEN each section is displayed with its source layer annotated

### Requirement: Control Operations

The dashboard SHALL support control operations that write to the state store. Control operations use optimistic concurrency: the dashboard reads the task version before writing, and the write fails if the version has changed (orchestrator wrote in between). On failure, the user retries.

#### Scenario: Restart a task

- GIVEN task-001 is at phase "verify", stuck
- WHEN the user issues a "restart" command
- THEN task-001's phase is set to the first phase in the phase map
- AND round is incremented
- AND the task processor picks it up next cycle

#### Scenario: Concurrent write conflict

- GIVEN the dashboard reads task-001 at version V
- WHEN the orchestrator updates task-001 before the dashboard writes
- THEN the dashboard write fails with a version conflict
- AND the user is notified to retry

#### Scenario: Retire a task

- GIVEN task-001 is no longer needed
- WHEN the user issues a "retire" command
- THEN task-001's status is set to "failed" with reason "retired by user"
- AND any active worker for the task is cancelled

#### Scenario: Force-clear a gate

- GIVEN task-001 is waiting at a signal step
- WHEN the user issues a "force-clear" command
- THEN the task advances past the signal step to the on_pass phase
- AND the action is logged as a manual override

### Requirement: Activity Feed

The dashboard SHALL display a chronological feed of orchestrator events when the file probe adapter is enabled. The activity feed reads from the local events file and is available only when the dashboard runs on the same machine as the orchestrator. Remote observability is handled by the telemetry adapter (e.g., OpenTelemetry) pushing to a collector.

#### Scenario: Event display

- GIVEN the file observer is writing events
- WHEN the activity page loads
- THEN events are shown in reverse chronological order
- AND each event shows: timestamp, event name, and key data (task_id, verdict, etc.)

#### Scenario: Filtering

- GIVEN 100 events in the feed
- WHEN the user filters by task_id
- THEN only events for that task are shown

### Requirement: Process View

The dashboard SHALL display the current phase map and agent configuration.

#### Scenario: Phase map display

- GIVEN a process with 6 phases
- WHEN the process view loads
- THEN the phase map is displayed as a flowchart showing phase names, step types, and transitions (on_pass, on_fail, on_wait)

#### Scenario: Agent prompt display

- GIVEN 4 agent roles with three-layer prompts
- WHEN the agents view loads
- THEN each role shows its composed prompt with layer breakdown (base, project overlay, process overlay)

### Requirement: Dependency Graph

The dashboard SHALL display task dependency relationships.

#### Scenario: DAG visualization

- GIVEN tasks with dependency relationships
- WHEN the overview page loads
- THEN a directed acyclic graph shows tasks as nodes and dependencies as edges
- AND node color indicates task status

### Requirement: Refresh Strategy

The dashboard SHALL poll for state updates at a configurable interval.

#### Scenario: Periodic refresh

- GIVEN a refresh interval of 10 seconds
- WHEN the dashboard is open
- THEN it re-fetches task state every 10 seconds
- AND updates the UI without full page reload

### Requirement: Dashboard CLI

The dashboard SHALL be launchable via CLI.

#### Scenario: Start dashboard

- GIVEN a repository with hyperloop state
- WHEN `hyperloop dashboard` is run
- THEN a web server starts on the default port
- AND the dashboard is accessible in a browser

#### Scenario: Custom port

- GIVEN the default port is in use
- WHEN `hyperloop dashboard --port 9090` is run
- THEN the server starts on port 9090
