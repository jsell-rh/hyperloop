# Dashboard Specification

## Purpose

The dashboard is a web interface for observing orchestrator state and issuing control commands. It serves two observation loops: the **outer loop** (reconciler — "are my specs being implemented?") and the **inner loop** (task processor — "what's happening right now?"). It reads state from the StateStore and events from the FileProbe JSONL log. Control operations allow humans to restart tasks, retire tasks, and force-clear gates without touching git directly.

## Requirements

### Requirement: Independent Observation

The dashboard SHALL provide read-only views of all orchestrator state without requiring access to the running orchestrator process. It reads from persisted state and event logs only.

#### Scenario: Observe any repo

- GIVEN a repository with `.hyperloop/state/` on its state branch
- WHEN the dashboard is pointed at that repo
- THEN it renders the current state of all specs and tasks

#### Scenario: Independent of orchestrator

- GIVEN the orchestrator is not running
- WHEN the dashboard is started
- THEN it displays the last-persisted state
- AND the system status indicator shows "Stale" after the staleness threshold

#### Scenario: Polling refresh

- GIVEN a refresh interval of 10 seconds
- WHEN the dashboard is open
- THEN it re-fetches state every 10 seconds
- AND updates the UI without full page reload

---

### Requirement: Sync Status Model

Every spec SHALL have a three-state sync status derived from reconciler state. This is the primary abstraction for the outer loop.

| Status | Color | Icon | Meaning |
|---|---|---|---|
| Synced | Green | Checkmark | All tasks completed, auditor confirmed alignment |
| Drifted | Blue/Amber | Refresh | Spec changed since tasks were pinned (freshness drift), or auditor found misalignment, or no tasks exist yet |
| Syncing | Blue | Gear | Tasks exist and are in progress toward alignment |

#### Scenario: Spec shows Synced

- GIVEN all tasks for spec "auth.md@abc123" have status "completed"
- AND the convergence record shows "aligned" at SHA abc123
- WHEN the overview page loads
- THEN "auth.md" shows sync status "Synced" with green checkmark icon

#### Scenario: Spec shows Drifted — freshness

- GIVEN spec "auth.md" has tasks pinned to SHA abc123
- AND the current spec SHA is def456
- WHEN the overview page loads
- THEN "auth.md" shows sync status "Drifted" with refresh icon
- AND the drift reason indicates "freshness drift"

#### Scenario: Spec shows Drifted — coverage gap

- GIVEN spec "persistence.md" exists but has no tasks
- WHEN the overview page loads
- THEN "persistence.md" shows sync status "Drifted" with circle icon
- AND the drift reason indicates "coverage gap"

#### Scenario: Spec shows Drifted — alignment gap

- GIVEN all tasks for spec "auth.md@abc123" completed
- AND the auditor found misalignment
- WHEN the overview page loads
- THEN "auth.md" shows sync status "Drifted" with warning icon
- AND the drift reason indicates "alignment gap"

#### Scenario: Spec shows Syncing

- GIVEN spec "auth.md" has 3 tasks, 1 completed, 2 in-progress
- WHEN the overview page loads
- THEN "auth.md" shows sync status "Syncing" with gear icon

---

### Requirement: Spec Lifecycle Stages

Each spec SHALL be classifiable into a lifecycle stage that tracks its progression from initial creation to convergence. The stage is derived, not stored.

| Stage | Condition | Color |
|---|---|---|
| Written | Spec exists, no tasks | Amber |
| Coverage Gap | Spec in PM intake queue | Amber |
| In Progress | Tasks exist and are active | Blue |
| Pending Audit | All tasks completed, awaiting auditor | Blue |
| Converged | Auditor confirmed alignment | Green |
| Freshness Drift | Spec SHA changed after convergence, re-work needed | Blue/Amber |
| Alignment Gap | Auditor found misalignment, PM re-intake needed | Orange |
| Failed/Stuck | All active tasks failing repeatedly | Red |
| Baselined | Pre-hyperloop spec with convergence record, no active work | Gray |

#### Scenario: Stage transition on task completion

- GIVEN spec "auth.md" is at stage "In Progress"
- WHEN all tasks for the spec reach "completed" status
- THEN the stage transitions to "Pending Audit"

#### Scenario: Stage transition on convergence

- GIVEN spec "auth.md" is at stage "Pending Audit"
- WHEN the auditor reports "aligned"
- THEN the stage transitions to "Converged"

#### Scenario: Stage transition on freshness drift

- GIVEN spec "auth.md" is at stage "Converged"
- WHEN the spec file SHA changes
- THEN the stage transitions to "Freshness Drift"

---

### Requirement: Convergence Rate

The dashboard SHALL display a convergence rate as the primary metric: "N / M specs aligned" where N is the count of specs at stage "Converged" or "Baselined" and M is the total spec count.

#### Scenario: Convergence progress display

- GIVEN 12 total specs, 7 converged, 2 baselined, 3 in progress
- WHEN the overview page loads
- THEN the convergence gauge shows "9 / 12 specs aligned"
- AND a progress bar shows 75% fill

#### Scenario: Full convergence

- GIVEN all 12 specs are converged
- WHEN the overview page loads
- THEN the convergence gauge shows "12 / 12 specs aligned"
- AND the system status indicates "fully converged"

---

### Requirement: Overview Page (/)

The overview page SHALL provide a 2-second glance at system health: convergence gauge, summary cards, and spec groups sorted by drift status.

#### Scenario: Summary cards

- GIVEN the orchestrator is running with active work
- WHEN the overview page loads
- THEN 5 summary cards are displayed:
  1. **System Status**: Running/Halted/Stale with last event timestamp
  2. **Convergence Progress**: N/M specs aligned with progress bar
  3. **Task Completion**: complete/in-progress/failed counts
  4. **Active Work**: worker count, current roles, stale worker detection
  5. **Health Checks**: state sync status, PM status, auditor availability

#### Scenario: Spec groups sorted by drift status

- GIVEN specs in various stages
- WHEN the overview page loads
- THEN specs are grouped by directory
- AND within each group, specs are sorted: drifted first, then syncing, then synced

#### Scenario: Spec card display

- GIVEN a spec "auth.md" with 5 tasks
- WHEN the overview page loads
- THEN the spec card shows:
  - Title (from first markdown heading)
  - Sync status icon and color
  - Lifecycle stage badge
  - Progress bar showing task status breakdown (complete/failed/in-progress/not-started)
  - Task count: "3/5 tasks complete"

#### Scenario: Domain sidebar with progress

- GIVEN specs organized in subdirectories (e.g., specs/auth/, specs/billing/)
- WHEN the overview page loads
- THEN a sidebar shows directory names with aggregated progress bars
- AND clicking a directory scrolls to that group

#### Scenario: Dependency graph (collapsible)

- GIVEN tasks with dependency relationships
- WHEN the overview page loads
- THEN a collapsible dependency graph section shows tasks as nodes and dependencies as edges
- AND node color indicates task status
- AND the collapsed state shows active/blocked counts

---

### Requirement: Activity Page (/activity)

The activity page SHALL show the inner loop: cycle-by-cycle reconciler log, live workers panel, auditor Gantt chart, and phase transitions.

#### Scenario: Status banner

- GIVEN the orchestrator is running
- WHEN the activity page loads
- THEN a status banner shows: status dot (green/red/yellow), cycle number, worker count, and last event relative timestamp

#### Scenario: Warnings panel

- GIVEN a task has 3+ consecutive fail verdicts
- WHEN the activity page loads
- THEN a red warning card appears: "Failure loop: task-001 — 4 consecutive failures"

#### Scenario: Long-running worker warning

- GIVEN a worker has been running 3x longer than the average worker duration
- WHEN the activity page loads
- THEN an amber warning card appears indicating the worker may be stuck

#### Scenario: Idle warning

- GIVEN no events for 10+ minutes despite in-progress tasks
- WHEN the activity page loads
- THEN an amber warning card appears: "Prolonged idle — no events in 15m despite 3 in-progress tasks"

#### Scenario: In-flight task cards

- GIVEN 3 tasks are in-progress, 2 have active workers
- WHEN the activity page loads
- THEN each in-flight task shows:
  - Task ID and title
  - Phase flow strip showing current position in the phase map
  - Per-phase duration timings
  - Round badge (amber at round 2, red at round 3+)
  - Current worker role, live elapsed timer, and pulse dot
  - Worker heartbeat indicator (tool name, message count, last activity)

#### Scenario: Phase flow strip with retry arcs

- GIVEN task-001 is at phase "verify" after a retry from "implement"
- WHEN the activity page shows the task card
- THEN the phase flow strip shows all phases as horizontal segments
- AND completed phases are green, current phase is blue (pulsing), pending phases are gray
- AND a failed phase shows red with "(fail)" annotation

#### Scenario: Worker heartbeat animation

- GIVEN a worker sent a tool_use message 3 seconds ago
- WHEN the activity page shows the task card
- THEN the pulse dot is blue with ping animation
- AND the heartbeat detail shows the tool name and "3s ago"

#### Scenario: Worker heartbeat stale

- GIVEN a worker's last message was 65 seconds ago
- WHEN the activity page shows the task card
- THEN the pulse dot turns amber
- AND the active phase bar tints amber

#### Scenario: Reconcile detail per cycle

- GIVEN cycle #42 had drift detection, 2 audits, and GC activity
- WHEN the raw cycle log is expanded
- THEN the cycle card shows:
  - Drift count
  - Audit results with Gantt chart (parallel execution timeline)
  - GC pruned count
  - Reconcile duration

#### Scenario: Auditor Gantt chart

- GIVEN 3 specs were audited in parallel during cycle #42
- WHEN the cycle card renders
- THEN a Gantt chart shows horizontal bars per spec
  - Bar position indicates start time relative to cycle start
  - Bar width indicates duration
  - Bar color indicates result (green for aligned, amber for misaligned)
  - Hover tooltip shows spec_ref, result, and duration
  - Summary line: "3 specs audited in 45s (max parallelism: 2)"

#### Scenario: Event stream

- GIVEN 50 events in the log
- WHEN the activity page loads
- THEN events are shown in reverse chronological order
- AND each event shows: timestamp, cycle number, event type, task_id, and detail text
- AND event types include: worker_spawned, worker_reaped, task_advanced, intake_ran, process_improver_ran

#### Scenario: Raw cycle log with compression

- GIVEN 20 cycles, 15 of which had no meaningful events
- WHEN the raw cycle log is expanded
- THEN consecutive empty cycles are compressed into a single row: "Cycles #5-#19: idle (2m 30s)"
- AND non-empty cycles show as individual CycleCards with phase breakdowns (collect, intake, advance, spawn)

#### Scenario: Activity not enabled

- GIVEN the FileProbe is not configured
- WHEN the activity page loads
- THEN a message instructs the user to enable `dashboard: { enabled: true }` in `.hyperloop.yaml`

---

### Requirement: Spec Detail Page (/specs/:ref)

The spec detail page SHALL show spec content alongside an intelligence panel with drift status, audit history, task list, event timeline, and spec diff on freshness drift.

#### Scenario: Spec content rendering

- GIVEN spec "auth.md" contains markdown
- WHEN the spec detail page loads
- THEN the spec content is rendered as formatted HTML in the main panel
- AND the spec_ref is shown in the page title and breadcrumb

#### Scenario: Task sidebar

- GIVEN spec "auth.md" has 3 tasks
- WHEN the spec detail page loads
- THEN a sidebar lists all tasks with: id, title, status badge, and current phase
- AND each task links to its detail page

#### Scenario: No tasks empty state

- GIVEN spec "new-feature.md" has no tasks
- WHEN the spec detail page loads
- THEN the task sidebar shows: "No tasks yet — no tasks have been created for this spec"

#### Scenario: Drift panel

- GIVEN spec "auth.md" has freshness drift (SHA abc123 to def456)
- WHEN the spec detail page loads
- THEN a drift panel shows:
  - Drift type: "freshness"
  - Old SHA and new SHA
  - Link to view the spec diff

#### Scenario: Spec diff view on freshness drift

- GIVEN spec "auth.md" drifted from SHA abc123 to def456
- WHEN the user opens the spec diff
- THEN a side-by-side diff view shows old content vs new content
- AND additions are highlighted green, removals highlighted red

#### Scenario: Audit history

- GIVEN spec "auth.md" has been audited twice: once misaligned, then aligned
- WHEN the spec detail page loads
- THEN the audit history panel shows both results in chronological order with cycle number, result, and duration

#### Scenario: Event timeline

- GIVEN spec "auth.md" has had 8 probe events (drift_detected, intake_ran, worker_spawned, worker_reaped, task_advanced, audit_ran, convergence_marked)
- WHEN the spec detail page loads
- THEN a vertical timeline shows all events for this spec in chronological order

---

### Requirement: Task Detail Page (/tasks/:id)

The task detail page SHALL show the full task journey: metadata, phase journey with timeline, review findings, live worker stream, prompt viewer, and dependency tree.

#### Scenario: Task metadata

- GIVEN task-001 is at phase "verify", round 2
- WHEN the task detail page loads
- THEN the metadata card shows: id, title, status badge, phase, round, spec_ref (linked), branch, PR URL

#### Scenario: PR description

- GIVEN task-001 has a PR with title and description
- WHEN the task detail page loads
- THEN the PR description card shows the title and body text

#### Scenario: Pipeline position

- GIVEN a phase map with 5 phases
- WHEN the task detail page loads
- THEN a pipeline indicator shows all phases as a horizontal sequence
- AND the current phase is highlighted with the task's position

#### Scenario: Phase journey timeline

- GIVEN task-001 has progressed through implement (pass), verify (fail, retry), implement (pass), verify (pass)
- WHEN the task detail page loads
- THEN a round-by-round timeline shows each phase execution with verdict, duration, and retry bounce-back arcs

#### Scenario: Review findings

- GIVEN task-001 has review findings from rounds 0 and 1
- WHEN the user navigates to the reviews tab
- THEN reviews are shown in reverse chronological order
- AND each review shows: round, role, verdict badge, and detail text

#### Scenario: Latest review inline

- GIVEN task-001 has a latest review
- WHEN the overview tab loads
- THEN a preview of the latest review is shown inline (first 3 lines)
- AND a "Show full review" link switches to the reviews tab

#### Scenario: Prompt viewer

- GIVEN task-001's prompt was composed from base + project overlay + spec + findings
- WHEN the user navigates to the prompt tab
- THEN each prompt section is displayed with:
  - Source layer label (e.g., "base", "project-overlay", "spec", "findings")
  - Section label
  - Content (collapsible)
- AND prompts are shown for each agent role that has processed this task

#### Scenario: Prompt viewer for all agent roles

- GIVEN the dashboard has prompt composition data
- WHEN the user views the prompt tab on any task
- THEN the prompt viewer shows composed prompts for ALL agent roles that processed this task (implementer, verifier, spec-reviewer, etc.)
- AND each role's prompt shows the same section-by-section breakdown

#### Scenario: Dependency tree

- GIVEN task-001 depends on task-000 (completed) and task-002 (in-progress)
- WHEN the task detail page loads
- THEN a dependency tree shows: task-000 (green, completed) and task-002 (blue, in-progress)
- AND each dependency is a link to its detail page

---

### Requirement: Process Page (/process)

The process page SHALL display the phase map visualization, agent configuration, and agent performance roster.

#### Scenario: Phase map flowchart

- GIVEN a process with 5 phases: implement, verify, spec-review, mark-ready, merge
- WHEN the process page loads
- THEN a flowchart shows phases as connected nodes
- AND each node shows: phase name, step type (agent/action/signal)
- AND transitions show on_pass, on_fail, and on_wait paths
- AND backward transitions (retry loops) are visually distinct

#### Scenario: Raw YAML toggle

- GIVEN the process has a raw YAML definition
- WHEN the user clicks "Show raw YAML"
- THEN the full YAML is displayed in a monospace code block

#### Scenario: Gates, actions, hooks

- GIVEN the process has 2 gates, 1 action, and 1 hook
- WHEN the process page loads
- THEN each is shown in its own table section with name and configuration

#### Scenario: Process learning

- GIVEN the process-improver has updated guidelines for the implementer
- WHEN the process page loads
- THEN the process learning section shows: agent name and learned guidelines text

#### Scenario: Agent roster with success rates

- GIVEN 4 agent roles have processed tasks
- WHEN the process page loads
- THEN an agent roster table shows per role:
  - Success rate (pass verdicts / total verdicts)
  - Average duration
  - Total executions
  - Common failure patterns (top reasons from fail verdicts)

---

### Requirement: Control Operations

The dashboard SHALL support control operations that write to the state store. Control operations use optimistic concurrency: the dashboard reads the task round before writing, and the write fails if the round has changed (orchestrator wrote in between).

#### Scenario: Restart a task

- GIVEN task-001 is at phase "verify", stuck
- WHEN the user clicks "Restart"
- THEN task-001's phase is reset to the first phase in the phase map
- AND round is incremented
- AND the task processor picks it up next cycle

#### Scenario: Concurrent write conflict

- GIVEN the dashboard reads task-001 at round R
- WHEN the orchestrator updates task-001 before the dashboard writes
- THEN the dashboard POST returns 409 Conflict
- AND the user sees: "Task was modified by the orchestrator. Please refresh and try again."

#### Scenario: Retire a task

- GIVEN task-001 is no longer needed
- WHEN the user clicks "Retire"
- THEN task-001's status is set to "failed" with reason "retired by user"
- AND any active worker for the task is cancelled

#### Scenario: Force-clear a gate

- GIVEN task-001 is waiting at a signal step
- WHEN the user clicks "Force Clear"
- THEN the task advances past the signal step to the on_pass phase
- AND the action is logged as a manual override
- AND force-clear is only shown when the task has an active phase (is in-progress)

---

### Requirement: Live Worker Streaming

The dashboard SHALL display real-time worker activity for running workers, showing tool calls and message flow.

#### Scenario: Worker heartbeat polling

- GIVEN a worker is running for task-001
- WHEN the activity page is open
- THEN the dashboard polls `/api/activity/worker-heartbeats` every 3 seconds
- AND displays: last tool name, message count, seconds since last message

#### Scenario: Pulse dot color mapping

- GIVEN a worker's last message was N seconds ago
- WHEN the heartbeat is rendered
- THEN the pulse dot color reflects recency:
  - < 10s: blue with ping animation (active)
  - 10-59s: blue without ping (thinking)
  - 60-119s: amber (possibly stale)
  - 120s+: red (likely stuck)

#### Scenario: Tool call indicator

- GIVEN a worker just called tool "bash"
- WHEN the heartbeat renders
- THEN a monospace label shows "bash" with message count and "3s ago"

---

### Requirement: Prompt Viewer

The dashboard SHALL provide a prompt viewer that shows the full composed prompt for ANY agent role with section-by-section provenance.

#### Scenario: Task prompt viewer

- GIVEN task-001 was processed by an implementer
- WHEN the user opens the prompt tab
- THEN the viewer shows each section of the composed prompt:
  - Label: "System Prompt", "Spec Content", "Review Findings", "Process Guidelines"
  - Source: "base", "project-overlay", "process-overlay", "dynamic"
  - Content: the actual text (collapsible for long sections)

#### Scenario: Agent prompt viewer on process page

- GIVEN 4 agent roles are configured
- WHEN the user views the agents page
- THEN each role shows its composed prompt with layer breakdown:
  - Base prompt
  - Project overlay (if present)
  - Process overlay / learned guidelines (if present)

#### Scenario: Prompt data from FileProbe events

- GIVEN the FileProbe writes `prompt_composed` events to JSONL
- WHEN the prompt tab is opened for a task
- THEN prompt data is reconstructed from the most recent `prompt_composed` event for that task

---

### Requirement: Empty States

The dashboard SHALL handle edge cases with helpful empty states.

#### Scenario: No specs

- GIVEN the repository has no spec files
- WHEN the overview page loads
- THEN a centered message shows: "Waiting for specs — when the orchestrator starts processing, your specs and tasks will show up right here."

#### Scenario: All converged

- GIVEN all specs are at stage "Converged"
- WHEN the overview page loads
- THEN the convergence gauge shows 100%
- AND the system status card indicates full convergence

#### Scenario: Just started

- GIVEN the orchestrator just started and has processed 0 cycles
- WHEN the activity page loads
- THEN the status shows "running" with cycle #0
- AND the event stream is empty with a message: "No events recorded yet."

#### Scenario: Orchestrator crashed

- GIVEN the last event is `orchestrator_halted` with reason "PM agent unreachable"
- WHEN the activity page loads
- THEN the status banner shows a red dot with "Halted"
- AND the halted reason is displayed

#### Scenario: API unreachable

- GIVEN the dashboard API server is down
- WHEN any page loads
- THEN an error banner shows: "Unable to reach the Hyperloop API. Retrying..."
- AND the banner persists until the API responds

---

### Requirement: Deep-Linkable URLs

Every view state SHALL be addressable by URL, enabling sharing and bookmarking.

#### Scenario: Spec detail deep link

- GIVEN spec "specs/auth.md"
- WHEN the URL `/specs/specs/auth.md` is opened
- THEN the spec detail page loads for "specs/auth.md"

#### Scenario: Task detail deep link

- GIVEN task "task-001"
- WHEN the URL `/tasks/task-001` is opened
- THEN the task detail page loads for task-001

#### Scenario: Task detail tab deep link

- GIVEN task "task-001"
- WHEN the URL `/tasks/task-001?tab=reviews` is opened
- THEN the task detail page loads with the reviews tab active

#### Scenario: Page title reflects state

- GIVEN 2 tasks are in-progress and 1 is failed
- WHEN the overview page is open
- THEN the browser tab title shows "Hyperloop - 1 failed"
- AND when all tasks pass, the title shows "Hyperloop Dashboard"

---

### Requirement: Keyboard Navigation

The dashboard SHALL support keyboard shortcuts for efficient navigation.

#### Scenario: Vim-style vertical navigation

- GIVEN the overview page is active with spec cards
- WHEN the user presses J
- THEN focus moves to the next spec card
- AND K moves to the previous spec card

#### Scenario: Go-to shortcuts

- WHEN the user presses G then H
- THEN the browser navigates to the overview page (/)
- AND G then A navigates to the activity page (/activity)
- AND G then P navigates to the process page (/process)

#### Scenario: Numbered tab switching

- GIVEN the task detail page is active with 3 tabs (overview, reviews, prompt)
- WHEN the user presses 1, 2, or 3
- THEN the corresponding tab is activated

---

### Requirement: Accessibility

The dashboard SHALL be usable with assistive technology and meet color-independence requirements.

#### Scenario: Color paired with icon

- GIVEN a spec with sync status "Synced"
- WHEN it renders
- THEN the green color is paired with a checkmark icon
- AND a screen reader can identify the status from the icon alt text alone

#### Scenario: Status badge text

- GIVEN a task with status "in-progress"
- WHEN a StatusBadge renders
- THEN the badge contains text ("in-progress") in addition to color
- AND the text is readable by screen readers

#### Scenario: Interactive elements have labels

- GIVEN a control button (Restart, Retire, Force Clear)
- WHEN a screen reader encounters it
- THEN the button has an accessible label describing the action

---

### Requirement: Visual Design

The dashboard SHALL follow a consistent visual language.

#### Scenario: Typography and spacing

- GIVEN any dashboard page
- WHEN it renders
- THEN text uses a clean sans-serif font (Inter or system equivalent)
- AND spacing follows a 4px grid

#### Scenario: Semantic color palette

- GIVEN dashboard elements with state
- WHEN they render
- THEN colors follow the semantic mapping:
  - Green: synced, pass, complete, aligned
  - Blue: in-progress, syncing, active
  - Amber: drift, warning, stale
  - Red: failed, stuck, halted
  - Gray: not started, baselined, neutral

#### Scenario: Card and table layout

- GIVEN rich summary data (spec cards, summary cards)
- WHEN the page renders
- THEN cards are used for rich summaries with elevation (shadow)
- AND flat rows are used for data tables (events, reviews)

#### Scenario: Dark mode

- GIVEN the user has dark mode enabled (system preference)
- WHEN any page renders
- THEN all elements adapt to dark mode with appropriate contrast
- AND dark mode uses subtle ring borders instead of shadows for card elevation

#### Scenario: Subtle animations

- GIVEN an in-progress task
- WHEN it renders
- THEN the progress bar segment for in-progress has a shimmer animation
- AND the worker pulse dot has a ping animation when recently active
- AND active phase bars pulse subtly

---

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

---

### Requirement: API Endpoints

The dashboard API SHALL provide endpoints for all dashboard views.

#### Scenario: Spec listing with sync metadata

- GIVEN the API endpoint `GET /api/specs`
- WHEN called
- THEN each spec includes: spec_ref, title, task counts (total, complete, in_progress, failed, not_started)
- AND additionally: drift_type (coverage, freshness, alignment, none), stage (lifecycle stage), last_audit_result, current_sha, pinned_sha

#### Scenario: Spec drift detail

- GIVEN the API endpoint `GET /api/specs/{ref}/drift`
- WHEN called for a spec with freshness drift
- THEN the response includes: drift_type, old_sha, new_sha, old_content, new_content (for diff rendering)

#### Scenario: Activity with reconcile detail

- GIVEN the API endpoint `GET /api/activity`
- WHEN called
- THEN each cycle includes: reconcile detail (drift_count, audits, gc_pruned, reconcile_duration_s) and audit_timeline (entries with start/duration for Gantt chart)

#### Scenario: Agent roster

- GIVEN the API endpoint `GET /api/agents`
- WHEN called with performance metrics
- THEN each agent role includes: success_rate, avg_duration_s, total_executions, failure_patterns

#### Scenario: Trend metrics

- GIVEN the API endpoint `GET /api/metrics/trend`
- WHEN called with `cycles=10`
- THEN the response includes aggregated metrics over the last 10 cycles: convergence rate trend, task throughput, average worker duration

#### Scenario: Worker heartbeats

- GIVEN the API endpoint `GET /api/activity/worker-heartbeats`
- WHEN called with `since` parameter
- THEN the response includes per-worker: task_id, role, last_message_at, last_message_type, last_tool_name, message_count_since, seconds_since_last

#### Scenario: Task prompt

- GIVEN the API endpoint `GET /api/tasks/{id}/prompt`
- WHEN called for a task
- THEN the response includes reconstructed prompts per agent role with section-by-section breakdown (source layer, label, content)
