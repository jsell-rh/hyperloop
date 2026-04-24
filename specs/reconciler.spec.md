# Reconciler Specification

## Purpose

The reconciler is the subsystem that detects gaps between specs (desired state) and code (actual state) and creates work to close them. It runs three tiers of drift detection, dispatches the PM agent for task planning, audits post-convergence alignment, manages process configuration hot-reload, and garbage-collects terminal state.

## Requirements

### Requirement: Three-Tier Drift Detection

The reconciler SHALL detect drift at three levels, checked in order:

| Tier | Question | Method | Frequency |
|---|---|---|---|
| Coverage | Does every spec have at least one task? | Mechanical (set membership) | Every cycle |
| Freshness | Has the spec changed since tasks were pinned? | Mechanical (SHA comparison) | Every cycle |
| Alignment | Does the code implement what the spec says? | Agent (auditor) | After all tasks for a spec reach synced |

#### Scenario: Coverage gap detected

- GIVEN spec "persistence.md" exists in the specs directory
- WHEN no task has a spec_ref starting with "specs/persistence.md"
- THEN the reconciler identifies a coverage gap
- AND includes "persistence.md" in the next PM intake with reason "uncovered"

#### Scenario: Freshness drift detected

- GIVEN task-001 has spec_ref "specs/auth.md@abc123"
- WHEN specs/auth.md HEAD SHA is now def456
- THEN the reconciler identifies freshness drift
- AND includes "auth.md" in the next PM intake with reason "drifted"

#### Scenario: No drift when SHA matches

- GIVEN task-001 has spec_ref "specs/auth.md@abc123"
- WHEN specs/auth.md HEAD SHA is still abc123
- THEN no drift is detected for this spec
- AND no PM intake is triggered for this spec

#### Scenario: Alignment audit triggered

- GIVEN all tasks for spec "auth.md@abc123" have status "synced"
- WHEN the reconciler evaluates convergence
- THEN it spawns an auditor agent to compare the spec against the merged code
- AND if the auditor finds misalignment, the reconciler triggers PM intake with the audit finding

### Requirement: PM Intake

The PM agent SHALL be a mandatory, first-class component of the reconciler. It is responsible for task decomposition and dependency ordering. The reconciler MUST NOT create tasks without the PM.

#### Scenario: PM creates tasks from spec gap

- GIVEN the reconciler detects spec "widget.md" is uncovered
- WHEN it runs PM intake
- THEN the PM receives: spec content, existing tasks, codebase context
- AND the PM produces task proposals with titles, spec_refs (SHA-pinned), and dependency ordering
- AND the reconciler creates tasks from these proposals

#### Scenario: PM sees spec diff on freshness drift

- GIVEN spec "auth.md" has changed from @abc123 to @def456
- WHEN the PM is invoked
- THEN the PM receives: the spec diff between the two SHAs, existing tasks for this spec, and their outcomes
- AND the PM creates incremental tasks for the changes, not a full redo

#### Scenario: PM sees failure history

- GIVEN spec "auth.md" had 3 previous tasks that failed
- WHEN the PM is invoked for this spec (due to drift or re-intake)
- THEN the PM receives: failure summaries from all previous attempts
- AND the PM uses this context to create better-scoped tasks

#### Scenario: PM prompt is customizable

- GIVEN the PM is an agent with a prompt template
- WHEN a team adds a project overlay with PM guidelines
- THEN the PM's prompt includes the team's custom guidelines
- AND the same three-layer composition (base, project overlay, process overlay) applies to the PM as to any other agent

### Requirement: Alignment Audit

The reconciler SHALL spawn an auditor agent after all tasks for a spec reach "synced" status. The auditor compares the spec against the merged code to verify actual alignment.

#### Scenario: Auditor confirms alignment

- GIVEN all tasks for "auth.md@abc123" are synced
- WHEN the auditor reads the spec and the code
- THEN the auditor reports "aligned"
- AND the reconciler marks the spec as converged
- AND no further work is created

#### Scenario: Auditor finds misalignment

- GIVEN all tasks for "auth.md@abc123" are synced
- WHEN the auditor finds the code doesn't handle timeout cases described in the spec
- THEN the auditor reports "misaligned" with detail "timeout handling missing"
- AND the reconciler stores the finding in the state store
- AND the reconciler triggers PM intake with the audit finding as context
- AND the finding is available to the process-improver for guideline updates

#### Scenario: Audit finding reaches process-improver

- GIVEN the auditor found misalignment on spec "auth.md"
- WHEN the process-improver next runs (triggered by task failures)
- THEN it reads the audit finding from the state store alongside verification findings
- AND uses both to update agent guidelines

### Requirement: Overlay Hot-Reload

The reconciler SHALL detect changes to prompt overlays and the process configuration without requiring a restart.

#### Scenario: Prompt overlay changed

- GIVEN a team member pushes changes to .hyperloop/agents/implementer-patch.yaml
- WHEN the reconciler syncs and detects the overlay directory SHA has changed
- THEN it triggers a prompt composer rebuild
- AND subsequent workers receive the updated prompts
- AND no orchestrator restart is required

#### Scenario: Phase map changed

- GIVEN a team member modifies the process definition (phase map) in the kustomize overlay
- WHEN the reconciler detects the overlay SHA change and rebuilds
- THEN the new phase map is loaded
- AND in-flight tasks in phases that still exist continue from their current phase

### Requirement: Phase Map Migration

When the phase map changes and in-flight tasks reference phases that no longer exist, the reconciler SHALL invoke the PM to map old phases to new ones.

#### Scenario: Phase renamed

- GIVEN task-001 is at phase "code-review" which was renamed to "await-review"
- WHEN the reconciler detects the orphaned phase
- THEN it invokes the PM with: the task, the old process, and the new process
- AND the PM maps "code-review" to "await-review"
- AND the task continues from "await-review"

#### Scenario: Phase removed

- GIVEN task-001 is at phase "lint" which was removed from the process entirely
- WHEN the PM evaluates the mapping
- THEN the PM decides whether to advance past the removed phase or reset to the beginning
- AND the reconciler applies the PM's decision

### Requirement: Garbage Collection

The reconciler SHALL prune terminal tasks after a configurable retention period to prevent unbounded state growth.

#### Scenario: Terminal task pruned

- GIVEN task-001 has status "synced" and was completed 45 days ago
- WHEN the retention period is 30 days
- THEN the reconciler archives the task: writes a summary record and removes the task file and its review files from the working state

#### Scenario: Summary record preserves context

- GIVEN task-001 for spec "auth.md@abc123" is being pruned
- WHEN the GC runs
- THEN a summary record is written containing: spec_ref (with SHA), task count, completion/failure stats, failure themes, and last audit result
- AND the full detail remains accessible via git history

#### Scenario: Summary enables future PM context

- GIVEN summaries exist for spec "auth.md"
- WHEN the PM is invoked for this spec due to new drift
- THEN the PM receives the summary: "12 previous tasks, 3 failed with error handling issues, 9 succeeded"
- AND uses this historical context for better task decomposition

### Requirement: Reconciler Cycle

The reconciler SHALL execute its checks every cycle, after syncing state with the remote. The cycle structure is:

1. Sync state with remote
2. Check coverage (mechanical)
3. Check freshness (mechanical)
4. Check overlay changes (mechanical, triggers rebuild)
5. Check alignment for converged specs (agentic, on convergence)
6. Run PM intake if any gaps detected (agentic)
7. Run GC if retention period exceeded (mechanical)

#### Scenario: Reconciler with no drift

- GIVEN all specs are covered, fresh, and aligned
- WHEN the reconciler runs
- THEN steps 2-5 complete with no gaps detected
- AND PM intake is not invoked
- AND no new tasks are created

#### Scenario: Multiple drift types in one cycle

- GIVEN spec A is uncovered and spec B has SHA drift
- WHEN the reconciler runs
- THEN both gaps are collected
- AND the PM receives both in a single intake invocation
- AND the PM creates tasks for both specs
