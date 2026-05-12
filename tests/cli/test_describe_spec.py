from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from click.testing import CliRunner

from hyperloop.cli.app import cli
from hyperloop.reconciliation.models import (
    EventType,
    Plan,
    SpecPlanStatus,
    Task,
    TaskStatus,
)

from .fakes.fake_plan_store import FakePlanStore


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _build_plan() -> Plan:
    now = _utc_now()
    plan = Plan()
    plan.add_spec("specs/auth.spec.md", "abc123")
    sp = plan.spec_plans[0]
    sp.status = SpecPlanStatus.RECONCILING
    sp.reconciliation_attempts = 1

    id1 = plan.next_task_id()
    id2 = plan.next_task_id()
    id3 = plan.next_task_id()
    plan.add_tasks(
        sp,
        [
            Task(
                id=id1,
                spec_path=sp.path,
                spec_blob_sha=sp.blob_sha,
                name="Create schema",
                description="D1",
                status=TaskStatus.COMPLETE,
            ),
            Task(
                id=id2,
                spec_path=sp.path,
                spec_blob_sha=sp.blob_sha,
                name="Implement repository",
                description="D2",
                status=TaskStatus.COMPLETE,
            ),
            Task(
                id=id3,
                spec_path=sp.path,
                spec_blob_sha=sp.blob_sha,
                name="Add API endpoint",
                description="D3",
                status=TaskStatus.IN_PROGRESS,
            ),
        ],
    )

    sp.record_event(
        reason="VerificationPassed",
        message="Implementation matches spec",
        event_type=EventType.NORMAL,
        timestamp=now - timedelta(hours=2),
    )
    sp.record_event(
        reason="VerificationFailed",
        message="Missing timeout handling in...",
        event_type=EventType.WARNING,
        timestamp=now - timedelta(hours=3),
    )
    sp.record_event(
        reason="VerificationFailed",
        message="Missing timeout handling updated",
        event_type=EventType.WARNING,
        timestamp=now - timedelta(hours=2),
    )

    return plan


class TestDescribeSpec:
    def test_displays_spec_metadata(self) -> None:
        plan = _build_plan()
        store = FakePlanStore(plan)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["describe", "spec", "specs/auth.spec.md"], obj=store
        )
        assert result.exit_code == 0
        assert "specs/auth.spec.md" in result.output
        assert "abc123" in result.output
        assert "Reconciling" in result.output

    def test_displays_superseded_field(self) -> None:
        plan = _build_plan()
        store = FakePlanStore(plan)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["describe", "spec", "specs/auth.spec.md"], obj=store
        )
        assert "Superseded:" in result.output
        assert "false" in result.output.lower() or "False" in result.output

    def test_displays_attempts(self) -> None:
        plan = _build_plan()
        store = FakePlanStore(plan)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["describe", "spec", "specs/auth.spec.md"], obj=store
        )
        assert "Attempts:" in result.output

    def test_displays_task_summary(self) -> None:
        plan = _build_plan()
        store = FakePlanStore(plan)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["describe", "spec", "specs/auth.spec.md"], obj=store
        )
        assert "2 Complete" in result.output
        assert "1 InProgress" in result.output
        assert "3 total" in result.output

    def test_displays_tasks_table(self) -> None:
        plan = _build_plan()
        store = FakePlanStore(plan)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["describe", "spec", "specs/auth.spec.md"], obj=store
        )
        assert "Create schema" in result.output
        assert "Implement repository" in result.output
        assert "Add API endpoint" in result.output

    def test_displays_events_section(self) -> None:
        plan = _build_plan()
        store = FakePlanStore(plan)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["describe", "spec", "specs/auth.spec.md"], obj=store
        )
        assert "Events:" in result.output
        assert "VerificationPassed" in result.output
        assert "VerificationFailed" in result.output

    def test_event_count_aggregation(self) -> None:
        plan = _build_plan()
        store = FakePlanStore(plan)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["describe", "spec", "specs/auth.spec.md"], obj=store
        )
        lines = result.output.split("\n")
        failed_line = [line for line in lines if "VerificationFailed" in line]
        assert len(failed_line) == 1
        assert "2" in failed_line[0]

    def test_nonexistent_spec(self) -> None:
        plan = _build_plan()
        store = FakePlanStore(plan)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["describe", "spec", "specs/nonexistent.spec.md"], obj=store
        )
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_json_output(self) -> None:
        plan = _build_plan()
        store = FakePlanStore(plan)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["describe", "spec", "specs/auth.spec.md", "--output", "json"],
            obj=store,
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["path"] == "specs/auth.spec.md"
        assert data["blob_sha"] == "abc123"
        assert len(data["tasks"]) == 3
