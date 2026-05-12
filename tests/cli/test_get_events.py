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


def _build_plan_with_events() -> Plan:
    now = _utc_now()
    plan = Plan()
    plan.add_spec("specs/auth.spec.md", "abc123")
    plan.add_spec("specs/rbac.spec.md", "ghi789")

    sp_auth = plan.spec_plans[0]
    sp_auth.status = SpecPlanStatus.SYNCED
    sp_auth.record_event(
        reason="VerificationPassed",
        message="Implementation matches spec",
        event_type=EventType.NORMAL,
        timestamp=now - timedelta(minutes=5),
    )

    sp_rbac = plan.spec_plans[1]
    sp_rbac.status = SpecPlanStatus.FAILED
    id1 = plan.next_task_id()
    plan.add_tasks(
        sp_rbac,
        [
            Task(
                id=id1,
                spec_path=sp_rbac.path,
                spec_blob_sha=sp_rbac.blob_sha,
                name="T1",
                description="D1",
                status=TaskStatus.FAILED,
            ),
        ],
    )
    sp_rbac.tasks[0].record_event(
        reason="TaskFailed",
        message="TypeError in auth handler",
        event_type=EventType.WARNING,
        timestamp=now - timedelta(minutes=10),
    )
    sp_rbac.record_event(
        reason="VerificationFailed",
        message="Missing error handling for...",
        event_type=EventType.WARNING,
        timestamp=now - timedelta(hours=1),
    )

    return plan


class TestGetEvents:
    def test_displays_table_with_correct_columns(self) -> None:
        plan = _build_plan_with_events()
        store = FakePlanStore(plan)
        runner = CliRunner()
        result = runner.invoke(cli, ["get", "events"], obj=store)
        assert result.exit_code == 0
        header = result.output.split("\n")[0]
        assert "LAST SEEN" in header
        assert "TYPE" in header
        assert "REASON" in header
        assert "OBJECT" in header
        assert "MESSAGE" in header

    def test_collects_events_from_all_resources(self) -> None:
        plan = _build_plan_with_events()
        store = FakePlanStore(plan)
        runner = CliRunner()
        result = runner.invoke(cli, ["get", "events"], obj=store)
        assert result.exit_code == 0
        assert "VerificationPassed" in result.output
        assert "TaskFailed" in result.output
        assert "VerificationFailed" in result.output

    def test_events_in_reverse_chronological_order(self) -> None:
        plan = _build_plan_with_events()
        store = FakePlanStore(plan)
        runner = CliRunner()
        result = runner.invoke(cli, ["get", "events"], obj=store)
        lines = [
            line
            for line in result.output.split("\n")
            if line.strip() and "LAST SEEN" not in line
        ]
        reasons = [line.split()[3] for line in lines if len(line.split()) >= 4]
        assert reasons.index("VerificationPassed") < reasons.index("TaskFailed")
        assert reasons.index("TaskFailed") < reasons.index("VerificationFailed")

    def test_object_column_shows_resource_type(self) -> None:
        plan = _build_plan_with_events()
        store = FakePlanStore(plan)
        runner = CliRunner()
        result = runner.invoke(cli, ["get", "events"], obj=store)
        assert "spec/specs/auth.spec.md" in result.output
        assert "task/1" in result.output

    def test_json_output(self) -> None:
        plan = _build_plan_with_events()
        store = FakePlanStore(plan)
        runner = CliRunner()
        result = runner.invoke(cli, ["get", "events", "--output", "json"], obj=store)
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 3

    def test_empty_plan(self) -> None:
        store = FakePlanStore(Plan())
        runner = CliRunner()
        result = runner.invoke(cli, ["get", "events"], obj=store)
        assert result.exit_code == 0
        assert "LAST SEEN" in result.output
