# Hyperloop Baseline Specification

## Purpose

The baseline command bootstraps hyperloop state for brownfield projects by pre-seeding Summary records for all existing specs. This treats already-implemented code as "complete" with respect to historical spec versions, so hyperloop only acts on future spec changes rather than attempting to re-implement everything.

When a mature project adopts hyperloop, pointing it at 30 existing specs with no state history would normally trigger 30 coverage gaps, spawning the PM to re-task everything. Instead, baseline captures the current state ("these specs are already built at this SHA"), storing summaries that satisfy the coverage check. The reconciler then only detects drift when specs are actually modified.

## Requirements

### Requirement: Summary Pre-Seeding on Brownfield Projects

The baseline command SHALL discover all spec files in a repository, compute each spec's current blob SHA via git, and create Summary records with that SHA. This allows hyperloop to treat existing code as complete at a pinned version.

#### Scenario: First baseline on a brownfield project

- GIVEN a mature project with 30 spec files and no hyperloop state
- WHEN `hyperloop baseline` is run
- THEN the command discovers all spec files matching `specs/**/*.spec.md`
- AND for each spec, it computes the current HEAD blob SHA
- AND it creates a Summary record with `spec_ref = "specs/feature.md@<sha>"`
- AND all summaries are persisted to the state branch in `.hyperloop/state/summaries/`
- AND the reconciler's coverage check now sees all specs as "covered" (no gaps triggered)

#### Scenario: Baseline recognizes pre-existing summaries

- GIVEN spec "auth.md" already has a summary with SHA abc123
- WHEN baseline runs again
- THEN baseline detects the existing summary
- AND if the spec SHA still matches, baseline skips it
- AND if the spec SHA differs (spec was modified), baseline updates the summary

#### Scenario: Selective baseline with glob filter

- GIVEN a project with specs in `specs/iam/`, `specs/api/`, and `specs/storage/`
- WHEN `hyperloop baseline --spec "specs/iam/**"` is run
- THEN only specs matching the glob are baselined
- AND other specs are left untouched

### Requirement: Dry-Run Mode

The baseline command SHALL support a `--dry-run` flag that shows what would be captured without writing to the state branch.

#### Scenario: Dry-run displays planned summaries

- GIVEN a project with specs not yet baselined
- WHEN `hyperloop baseline --dry-run` is run
- THEN the command prints: spec path, blob SHA at HEAD, and action (new/update/skip)
- AND no state changes are written
- AND no commits are made to the state branch

### Requirement: Idempotency

Running baseline multiple times SHALL be safe. Repeated runs detect existing summaries and skip unchanged specs.

#### Scenario: Running baseline twice with no spec changes

- GIVEN baseline was run once and all specs have summaries
- WHEN baseline is run again with no spec modifications
- THEN baseline skips all specs
- AND makes no new commits

#### Scenario: Spec modified between baseline runs

- GIVEN spec "feature.md" has summary @abc123
- WHEN the spec file is modified and baseline is run again
- THEN baseline detects the new SHA
- AND updates the summary

### Requirement: Output Format

#### Scenario: Output format

- GIVEN baseline is run on a project with 5 specs, 2 already baselined, 3 new
- THEN output includes:
  - Discovery: "Found 5 specs"
  - Per-spec: action and SHA
  - Summary: "Baselined 5 specs (3 new, 1 updated, 1 skipped)"

### Requirement: Bootstrap State Branch if Absent

If the state branch does not exist, baseline SHALL create it via the state store's existing bootstrap logic.

#### Scenario: First baseline creates state branch

- GIVEN a fresh repo with no `hyperloop/state` branch
- WHEN `hyperloop baseline` is run
- THEN the state store bootstraps the orphan branch
- AND summaries are persisted to it

### Requirement: Command Signature

```
hyperloop baseline [OPTIONS]

Options:
  --path PATH     Path to the target repo. Default: current directory.
  --spec GLOB     Glob pattern to select specs. Default: all specs.
  --dry-run       Show what would be baselined without writing.
  --help, -h      Show help and exit.
```

### Requirement: Error Handling

#### Scenario: Path is not a git repository

- GIVEN a path that is not inside a git repository
- WHEN baseline is run
- THEN it prints an error and exits with code 1

#### Scenario: No specs found

- GIVEN a repo with no matching spec files
- WHEN baseline is run
- THEN it reports no specs found and exits with code 0

#### Scenario: Git command failures

- GIVEN a git operation fails for a specific spec
- WHEN baseline processes that spec
- THEN it logs a warning and continues with remaining specs
- AND reports the failure count at the end
