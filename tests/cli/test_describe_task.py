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
    plan.add_spec("specs/users.spec.md", "def456")
    sp = plan.spec_plans[0]
    sp.status = SpecPlanStatus.RECONCILING

    id1 = plan.next_task_id()
    id2 = plan.next_task_id()
    plan.add_tasks(
        sp,
        [
            Task(
                id=id1,
                spec_path=sp.path,
                spec_blob_sha=sp.blob_sha,
                name="Add validation",
                description="D1",
                status=TaskStatus.BACKLOG,
            ),
            Task(
                id=id2,
                spec_path=sp.path,
                spec_blob_sha=sp.blob_sha,
                name="Write migrations",
                description="D2",
                status=TaskStatus.FAILED,
                depends_on=[id1],
            ),
        ],
    )

    sp.tasks[1].record_event(
        reason="TaskFailed",
        message="TypeError: 'NoneType' has...",
        event_type=EventType.WARNING,
        timestamp=now - timedelta(minutes=45),
    )
    sp.tasks[1].record_event(
        reason="TaskFailed",
        message="TypeError: 'NoneType' updated",
        event_type=EventType.WARNING,
        timestamp=now - timedelta(minutes=30),
    )
    sp.tasks[1].record_event(
        reason="TaskFailed",
        message="TypeError: 'NoneType' latest",
        event_type=EventType.WARNING,
        timestamp=now - timedelta(minutes=10),
    )

    return plan


class TestDescribeTask:
    def test_displays_task_metadata(self) -> None:
        plan = _build_plan()
        store = FakePlanStore(plan)
        runner = CliRunner()
        result = runner.invoke(cli, ["describe", "task", "2"], obj=store)
        assert result.exit_code == 0
        assert "Write migrations" in result.output
        assert "specs/users.spec.md" in result.output
        assert "def456" in result.output
        assert "Failed" in result.output

    def test_displays_dependencies(self) -> None:
        plan = _build_plan()
        store = FakePlanStore(plan)
        runner = CliRunner()
        result = runner.invoke(cli, ["describe", "task", "2"], obj=store)
        assert "Dependencies:" in result.output
        assert "[1]" in result.output

    def test_displays_events(self) -> None:
        plan = _build_plan()
        store = FakePlanStore(plan)
        runner = CliRunner()
        result = runner.invoke(cli, ["describe", "task", "2"], obj=store)
        assert "Events:" in result.output
        assert "TaskFailed" in result.output
        assert "3" in result.output

    def test_nonexistent_task(self) -> None:
        plan = _build_plan()
        store = FakePlanStore(plan)
        runner = CliRunner()
        result = runner.invoke(cli, ["describe", "task", "99"], obj=store)
        assert result.exit_code != 0
        assert "task 99 not found" in result.output

    def test_json_output(self) -> None:
        plan = _build_plan()
        store = FakePlanStore(plan)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["describe", "task", "2", "--output", "json"], obj=store
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["id"] == 2
        assert data["name"] == "Write migrations"
        assert data["depends_on"] == [1]

    def test_task_without_events(self) -> None:
        plan = _build_plan()
        store = FakePlanStore(plan)
        runner = CliRunner()
        result = runner.invoke(cli, ["describe", "task", "1"], obj=store)
        assert result.exit_code == 0
        assert "Add validation" in result.output
