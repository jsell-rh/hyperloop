"""Tests for the reconciler domain logic — pure drift detection and GC.

Covers every scenario from specs/reconciler.spec.md:
 1. Coverage gap detected
 2. Freshness drift detected
 3. No drift when SHA matches
 4. Alignment audit triggered
 5. Summary prevents re-creation after GC
 6. Summary with stale SHA triggers intake
 7. Deleted spec handling
 8. Deleted spec with completed tasks
 9. PM failure with backoff
10. PM failure halt
11. GC prunes terminal tasks past retention
12. Active tasks never pruned
13. Phase orphans detected
14. Multiple drift types in one cycle
15. No drift when everything is covered and fresh
"""

from hyperloop.domain.model import Phase, Task, TaskStatus
from hyperloop.domain.reconciler import (
    PhaseMap,
    Summary,
    check_convergence_needed,
    detect_coverage_gaps,
    detect_freshness_drift,
    detect_phase_orphans,
    handle_deleted_specs,
    handle_pm_failure,
    plan_gc,
    summary_covers_spec,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _task(
    id: str = "task-001",
    spec_ref: str = "specs/auth.md@abc123",
    status: TaskStatus = TaskStatus.IN_PROGRESS,
    phase: Phase | None = None,
) -> Task:
    return Task(
        id=id,
        title=f"Task {id}",
        spec_ref=spec_ref,
        status=status,
        phase=phase,
        deps=(),
        round=0,
        branch=None,
        pr=None,
    )


def _summary(
    spec_path: str = "specs/auth.md",
    spec_ref: str = "specs/auth.md@abc123",
    total_tasks: int = 5,
    completed: int = 4,
    failed: int = 1,
    failure_themes: list[str] | None = None,
    last_audit: str | None = "aligned",
    last_audit_result: str | None = None,
) -> Summary:
    return Summary(
        spec_path=spec_path,
        spec_ref=spec_ref,
        total_tasks=total_tasks,
        completed=completed,
        failed=failed,
        failure_themes=failure_themes if failure_themes is not None else [],
        last_audit=last_audit,
        last_audit_result=last_audit_result,
    )


# ---------------------------------------------------------------------------
# 1. Coverage gap detected
# ---------------------------------------------------------------------------


class TestCoverageGap:
    def test_spec_with_no_tasks_and_no_summary_is_uncovered(self):
        tasks: dict[str, Task] = {}
        spec_paths = ["specs/persistence.md"]
        summaries: dict[str, Summary] = {}

        gaps = detect_coverage_gaps(tasks, spec_paths, summaries)

        assert len(gaps) == 1
        assert gaps[0].spec_path == "specs/persistence.md"
        assert gaps[0].drift_type == "coverage"

    def test_spec_with_task_is_covered(self):
        t = _task(spec_ref="specs/persistence.md@abc123")
        tasks = {t.id: t}
        spec_paths = ["specs/persistence.md"]
        summaries: dict[str, Summary] = {}

        gaps = detect_coverage_gaps(tasks, spec_paths, summaries)

        assert gaps == []

    def test_spec_with_summary_is_covered(self):
        tasks: dict[str, Task] = {}
        spec_paths = ["specs/auth.md"]
        summaries = {"specs/auth.md": _summary()}

        gaps = detect_coverage_gaps(tasks, spec_paths, summaries)

        assert gaps == []


# ---------------------------------------------------------------------------
# 2. Freshness drift detected
# ---------------------------------------------------------------------------


class TestFreshnessDrift:
    def test_sha_mismatch_triggers_drift(self):
        t = _task(spec_ref="specs/auth.md@abc123")
        tasks = {t.id: t}
        spec_versions = {"specs/auth.md": "def456"}

        drifts = detect_freshness_drift(tasks, spec_versions)

        assert len(drifts) == 1
        assert drifts[0].spec_path == "specs/auth.md"
        assert drifts[0].drift_type == "freshness"
        assert "abc123" in drifts[0].detail
        assert "def456" in drifts[0].detail


# ---------------------------------------------------------------------------
# 3. No drift when SHA matches
# ---------------------------------------------------------------------------


class TestNoDriftOnMatch:
    def test_matching_sha_no_drift(self):
        t = _task(spec_ref="specs/auth.md@abc123")
        tasks = {t.id: t}
        spec_versions = {"specs/auth.md": "abc123"}

        drifts = detect_freshness_drift(tasks, spec_versions)

        assert drifts == []


# ---------------------------------------------------------------------------
# 4. Alignment audit triggered
# ---------------------------------------------------------------------------


class TestAlignmentAudit:
    def test_all_completed_not_converged_needs_audit(self):
        t1 = _task(id="t1", spec_ref="specs/auth.md@abc123", status=TaskStatus.COMPLETE)
        t2 = _task(id="t2", spec_ref="specs/auth.md@abc123", status=TaskStatus.COMPLETE)
        tasks = {t1.id: t1, t2.id: t2}
        converged: set[str] = set()

        needs = check_convergence_needed(tasks, converged)

        assert "specs/auth.md@abc123" in needs

    def test_already_converged_skipped(self):
        t1 = _task(id="t1", spec_ref="specs/auth.md@abc123", status=TaskStatus.COMPLETE)
        tasks = {t1.id: t1}
        converged = {"specs/auth.md@abc123"}

        needs = check_convergence_needed(tasks, converged)

        assert needs == []

    def test_mixed_status_not_triggered(self):
        t1 = _task(id="t1", spec_ref="specs/auth.md@abc123", status=TaskStatus.COMPLETE)
        t2 = _task(id="t2", spec_ref="specs/auth.md@abc123", status=TaskStatus.IN_PROGRESS)
        tasks = {t1.id: t1, t2.id: t2}
        converged: set[str] = set()

        needs = check_convergence_needed(tasks, converged)

        assert needs == []


# ---------------------------------------------------------------------------
# 5. Summary prevents re-creation after GC
# ---------------------------------------------------------------------------


class TestSummaryPreventsRecreation:
    def test_summary_with_matching_sha_counts_as_coverage(self):
        result = summary_covers_spec(
            "specs/auth.md",
            "abc123",
            {"specs/auth.md": _summary(spec_ref="specs/auth.md@abc123")},
        )

        assert result is True

    def test_summary_missing_not_covered(self):
        result = summary_covers_spec("specs/auth.md", "abc123", {})

        assert result is False


# ---------------------------------------------------------------------------
# 6. Summary with stale SHA triggers intake
# ---------------------------------------------------------------------------


class TestStaleSummary:
    def test_summary_with_old_sha_not_covered(self):
        result = summary_covers_spec(
            "specs/auth.md",
            "def456",
            {"specs/auth.md": _summary(spec_ref="specs/auth.md@abc123")},
        )

        assert result is False


# ---------------------------------------------------------------------------
# 7. Deleted spec handling
# ---------------------------------------------------------------------------


class TestDeletedSpec:
    def test_orphaned_tasks_retired(self):
        t = _task(id="t1", spec_ref="specs/old-feature.md@abc123", status=TaskStatus.IN_PROGRESS)
        tasks = {t.id: t}
        current_specs = {"specs/auth.md"}

        retirements = handle_deleted_specs(tasks, current_specs)

        assert len(retirements) == 1
        assert retirements[0].task_id == "t1"
        assert retirements[0].reason == "spec deleted"

    def test_existing_spec_not_retired(self):
        t = _task(id="t1", spec_ref="specs/auth.md@abc123", status=TaskStatus.IN_PROGRESS)
        tasks = {t.id: t}
        current_specs = {"specs/auth.md"}

        retirements = handle_deleted_specs(tasks, current_specs)

        assert retirements == []


# ---------------------------------------------------------------------------
# 8. Deleted spec with completed tasks
# ---------------------------------------------------------------------------


class TestDeletedSpecCompleted:
    def test_completed_tasks_not_retired(self):
        t = _task(id="t1", spec_ref="specs/old-feature.md@abc123", status=TaskStatus.COMPLETE)
        tasks = {t.id: t}
        current_specs = {"specs/auth.md"}

        retirements = handle_deleted_specs(tasks, current_specs)

        assert retirements == []

    def test_failed_tasks_not_retired(self):
        t = _task(id="t1", spec_ref="specs/old-feature.md@abc123", status=TaskStatus.FAILED)
        tasks = {t.id: t}
        current_specs = {"specs/auth.md"}

        retirements = handle_deleted_specs(tasks, current_specs)

        assert retirements == []


# ---------------------------------------------------------------------------
# 9. PM failure with backoff
# ---------------------------------------------------------------------------


class TestPMFailureBackoff:
    def test_below_max_returns_backoff(self):
        result = handle_pm_failure(consecutive_failures=2, max_failures=5)

        assert result == "backoff"

    def test_one_failure_returns_backoff(self):
        result = handle_pm_failure(consecutive_failures=1, max_failures=5)

        assert result == "backoff"


# ---------------------------------------------------------------------------
# 10. PM failure halt
# ---------------------------------------------------------------------------


class TestPMFailureHalt:
    def test_at_max_returns_halt(self):
        result = handle_pm_failure(consecutive_failures=5, max_failures=5)

        assert result == "halt"

    def test_above_max_returns_halt(self):
        result = handle_pm_failure(consecutive_failures=7, max_failures=5)

        assert result == "halt"


# ---------------------------------------------------------------------------
# 11. GC prunes terminal tasks past retention
# ---------------------------------------------------------------------------


class TestGCPruning:
    def test_completed_past_retention_pruned(self):
        t = _task(id="t1", spec_ref="specs/auth.md@abc123", status=TaskStatus.COMPLETE)
        tasks = {t.id: t}
        task_ages = {"t1": 45.0}

        actions = plan_gc(tasks, retention_days=30, task_ages=task_ages)

        assert len(actions) == 1
        assert actions[0].task_id == "t1"
        assert actions[0].spec_ref == "specs/auth.md@abc123"

    def test_failed_past_retention_pruned(self):
        t = _task(id="t1", spec_ref="specs/auth.md@abc123", status=TaskStatus.FAILED)
        tasks = {t.id: t}
        task_ages = {"t1": 45.0}

        actions = plan_gc(tasks, retention_days=30, task_ages=task_ages)

        assert len(actions) == 1

    def test_terminal_within_retention_not_pruned(self):
        t = _task(id="t1", spec_ref="specs/auth.md@abc123", status=TaskStatus.COMPLETE)
        tasks = {t.id: t}
        task_ages = {"t1": 15.0}

        actions = plan_gc(tasks, retention_days=30, task_ages=task_ages)

        assert actions == []


# ---------------------------------------------------------------------------
# 12. Active tasks never pruned
# ---------------------------------------------------------------------------


class TestActiveTasksNeverPruned:
    def test_in_progress_not_pruned(self):
        t = _task(id="t1", status=TaskStatus.IN_PROGRESS)
        tasks = {t.id: t}
        task_ages = {"t1": 100.0}

        actions = plan_gc(tasks, retention_days=30, task_ages=task_ages)

        assert actions == []

    def test_not_started_not_pruned(self):
        t = _task(id="t1", status=TaskStatus.NOT_STARTED)
        tasks = {t.id: t}
        task_ages = {"t1": 100.0}

        actions = plan_gc(tasks, retention_days=30, task_ages=task_ages)

        assert actions == []


# ---------------------------------------------------------------------------
# 13. Phase orphans detected
# ---------------------------------------------------------------------------


class TestPhaseOrphans:
    def test_task_at_missing_phase_is_orphan(self):
        t = _task(
            id="t1",
            status=TaskStatus.IN_PROGRESS,
            phase=Phase("code-review"),
        )
        tasks = {t.id: t}
        phase_map: PhaseMap = {
            "implement": {"run": "implementer"},
            "verify": {"run": "verifier"},
        }

        orphans = detect_phase_orphans(tasks, phase_map)

        assert len(orphans) == 1
        assert orphans[0].task_id == "t1"
        assert orphans[0].phase == "code-review"

    def test_task_at_existing_phase_not_orphan(self):
        t = _task(
            id="t1",
            status=TaskStatus.IN_PROGRESS,
            phase=Phase("implement"),
        )
        tasks = {t.id: t}
        phase_map: PhaseMap = {
            "implement": {"run": "implementer"},
        }

        orphans = detect_phase_orphans(tasks, phase_map)

        assert orphans == []

    def test_completed_task_not_checked_for_orphan(self):
        t = _task(
            id="t1",
            status=TaskStatus.COMPLETE,
            phase=Phase("old-phase"),
        )
        tasks = {t.id: t}
        phase_map: PhaseMap = {}

        orphans = detect_phase_orphans(tasks, phase_map)

        assert orphans == []

    def test_task_with_no_phase_not_orphan(self):
        t = _task(id="t1", status=TaskStatus.IN_PROGRESS, phase=None)
        tasks = {t.id: t}
        phase_map: PhaseMap = {}

        orphans = detect_phase_orphans(tasks, phase_map)

        assert orphans == []


# ---------------------------------------------------------------------------
# 14. Multiple drift types in one cycle
# ---------------------------------------------------------------------------


class TestMultipleDriftTypes:
    def test_coverage_and_freshness_drift_in_same_cycle(self):
        t = _task(id="t1", spec_ref="specs/auth.md@abc123")
        tasks = {t.id: t}
        spec_paths = ["specs/auth.md", "specs/persistence.md"]
        spec_versions = {"specs/auth.md": "def456"}
        summaries: dict[str, Summary] = {}

        coverage_gaps = detect_coverage_gaps(tasks, spec_paths, summaries)
        freshness_drifts = detect_freshness_drift(tasks, spec_versions)

        all_drifts = coverage_gaps + freshness_drifts

        coverage = [d for d in all_drifts if d.drift_type == "coverage"]
        freshness = [d for d in all_drifts if d.drift_type == "freshness"]

        assert len(coverage) == 1
        assert coverage[0].spec_path == "specs/persistence.md"
        assert len(freshness) == 1
        assert freshness[0].spec_path == "specs/auth.md"


# ---------------------------------------------------------------------------
# 15. No drift when everything is covered and fresh
# ---------------------------------------------------------------------------


class TestNoDrift:
    def test_all_covered_and_fresh_no_drift(self):
        t1 = _task(id="t1", spec_ref="specs/auth.md@abc123")
        t2 = _task(id="t2", spec_ref="specs/persistence.md@def456")
        tasks = {t1.id: t1, t2.id: t2}
        spec_paths = ["specs/auth.md", "specs/persistence.md"]
        spec_versions = {"specs/auth.md": "abc123", "specs/persistence.md": "def456"}
        summaries: dict[str, Summary] = {}

        coverage_gaps = detect_coverage_gaps(tasks, spec_paths, summaries)
        freshness_drifts = detect_freshness_drift(tasks, spec_versions)

        assert coverage_gaps == []
        assert freshness_drifts == []
