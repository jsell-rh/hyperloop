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

- GIVEN all tasks for spec "auth.md@abc123" have status "completed"
- WHEN the reconciler evaluates convergence
- THEN it spawns auditor agents (up to `max_auditors` concurrently) to compare specs against the merged code
- AND if any auditor finds misalignment, the reconciler triggers PM intake with the audit finding

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

#### Scenario: Intake triggers only on terminal failure

- GIVEN a task at phase "verify" with round 2 and max_task_rounds 50
- WHEN the verifier returns verdict FAIL
- THEN the task retries (loops back to implement with round 3)
- AND PM intake is NOT triggered — the task is still in progress
- AND intake is only triggered when a task transitions to "failed" status (e.g. max rounds exceeded)

#### Scenario: PM prompt is customizable

- GIVEN the PM is an agent with a prompt template
- WHEN a team adds a project overlay with PM guidelines
- THEN the PM's prompt includes the team's custom guidelines
- AND the same three-layer composition (base, project overlay, process overlay) applies to the PM as to any other agent

### Requirement: Alignment Audit

The reconciler SHALL run auditor agents after all tasks for a spec reach "completed" status. Auditors run in parallel with a separate concurrency budget (`max_auditors`, default 3) that does not compete with the task worker pool. Each auditor compares a spec against the merged code to verify actual alignment.

Each auditor runs in an **isolated environment** (detached worktree for SDK runtime, separate session for ambient runtime) so that concurrent auditors do not interfere with each other. The auditor's verdict (aligned/misaligned with detail) is captured from the agent's WorkerResult, not inferred from success/failure of the agent process.

#### Scenario: Auditor confirms alignment

- GIVEN all tasks for "auth.md@abc123" are completed
- WHEN the auditor reads the spec and the code in its isolated environment
- THEN the auditor writes verdict "pass" with detail explaining alignment
- AND the runtime returns WorkerResult(verdict=PASS, detail=...)
- AND the reconciler marks the spec as converged at this SHA
- AND no further work is created until the spec or code changes

#### Scenario: Auditor finds misalignment

- GIVEN all tasks for "auth.md@abc123" are completed
- WHEN the auditor finds the code doesn't handle timeout cases described in the spec
- THEN the auditor writes verdict "fail" with detail "timeout handling missing"
- AND the runtime returns WorkerResult(verdict=FAIL, detail="timeout handling missing")
- AND the reconciler stores the finding (from WorkerResult.detail) in the state store
- AND the reconciler triggers PM intake with the audit finding as context
- AND the finding is available to the process-improver for guideline updates

#### Scenario: Multiple specs audited in parallel

- GIVEN specs "auth.md", "users.md", and "tenants.md" all have completed tasks
- WHEN the reconciler evaluates convergence
- THEN it invokes `run_auditor` up to `max_auditors` times concurrently
- AND each auditor runs in its own isolated environment
- AND each returns an independent WorkerResult with verdict and detail
- AND the reconciler marks each spec converged or misaligned based on the verdict

#### Scenario: Auditor verdict is captured, not inferred

- GIVEN an auditor agent completes without crashing
- WHEN the runtime collects the result
- THEN the verdict comes from the agent's actual output (worker-result.yaml or SDK ResultMessage)
- AND NOT from whether the agent process succeeded or failed
- AND an auditor that finds misalignment but completes successfully returns FAIL (misaligned), not PASS

#### Scenario: Audit finding reaches process-improver

- GIVEN the auditor found misalignment on spec "auth.md"
- WHEN the process-improver next runs (triggered by task failures)
- THEN it reads the audit finding from the state store alongside verification findings
- AND uses both to update agent guidelines

### Requirement: Convergence Tracking

The reconciler SHALL track convergence state per spec to prevent infinite audit loops. A spec is "converged" when the auditor confirms alignment. The reconciler MUST NOT re-audit a converged spec unless the spec file or the codebase changes.

#### Scenario: Converged spec skips audit

- GIVEN spec "auth.md@abc123" was previously audited and marked converged
- WHEN the reconciler runs and neither the spec nor the relevant code has changed
- THEN the alignment audit is skipped for this spec

#### Scenario: Code change breaks convergence

- GIVEN spec "auth.md@abc123" is marked converged
- WHEN a commit on main modifies files relevant to this spec
- THEN the convergence marker is invalidated
- AND the next cycle re-runs the alignment audit

### Requirement: Summary-Aware Coverage

The coverage check SHALL consider a spec "covered" if it has active tasks OR a summary record with a matching SHA. This prevents the GC-prune → coverage-gap → PM-recreate oscillation loop.

#### Scenario: Summary prevents re-creation after GC

- GIVEN spec "auth.md@abc123" has a summary (tasks were completed and pruned by GC)
- WHEN the coverage check runs
- THEN "auth.md" is considered covered at SHA abc123
- AND no PM intake is triggered

#### Scenario: Summary with stale SHA triggers intake

- GIVEN spec "auth.md" has a summary for SHA abc123 but current HEAD is def456
- WHEN the freshness check runs
- THEN the spec is flagged as drifted
- AND PM intake is triggered with the summary as historical context

### Requirement: Deleted Spec Handling

The reconciler SHALL detect specs that have been deleted from the repository and retire their associated tasks.

#### Scenario: Spec deleted

- GIVEN spec "old-feature.md" existed and has tasks in progress
- WHEN the spec file is deleted from the repository
- THEN the reconciler detects orphaned tasks (tasks referencing a spec that no longer exists)
- AND transitions those tasks to "failed" with reason "spec deleted"
- AND emits a probe event for each retired task

#### Scenario: Deleted spec with completed tasks

- GIVEN spec "old-feature.md" has all tasks in "completed" status
- WHEN the spec is deleted
- THEN the tasks are eligible for GC on the normal retention schedule
- AND no immediate action is needed

### Requirement: PM Failure Handling

When the PM agent fails during intake, the reconciler SHALL apply exponential backoff and halt after a configurable maximum number of consecutive failures.

#### Scenario: PM failure with retry

- GIVEN the PM fails during intake (run_serial returns false)
- WHEN the reconciler records the failure
- THEN it skips PM intake for the next N cycles (exponential backoff)
- AND emits a probe event indicating PM failure
- AND detected drift is preserved for the next intake attempt

#### Scenario: PM failure halt

- GIVEN the PM has failed M consecutive times (configurable, default 5)
- WHEN the reconciler evaluates PM health
- THEN it halts with reason "PM agent unreachable after M consecutive failures"
- AND emits orchestrator_halted probe event

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

#### Scenario: PM migration failure

- GIVEN the PM fails to produce a valid phase mapping
- WHEN the reconciler cannot apply the mapping
- THEN affected tasks are reset to the first phase in the new process
- AND the round counter is incremented
- AND the reset is logged via probe event task_reset with reason "process changed, PM migration failed"

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
