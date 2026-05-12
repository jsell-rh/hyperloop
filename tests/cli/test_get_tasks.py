from __future__ import annotations

import json

from click.testing import CliRunner

from hyperloop.cli.app import cli
from hyperloop.reconciliation.models import (
    Plan,
    SpecPlanStatus,
    Task,
    TaskStatus,
)

from .fakes.fake_plan_store import FakePlanStore


def _build_plan_with_tasks() -> Plan:
    plan = Plan()
    plan.add_spec("specs/auth.spec.md", "abc123")
    plan.add_spec("specs/users.spec.md", "def456")

    sp_auth = plan.spec_plans[0]
    sp_auth.status = SpecPlanStatus.RECONCILING
    id1 = plan.next_task_id()
    id2 = plan.next_task_id()
    id3 = plan.next_task_id()
    plan.add_tasks(
        sp_auth,
        [
            Task(
                id=id1,
                spec_path=sp_auth.path,
                spec_blob_sha=sp_auth.blob_sha,
                name="Create schema",
                description="D1",
                status=TaskStatus.COMPLETE,
            ),
            Task(
                id=id2,
                spec_path=sp_auth.path,
                spec_blob_sha=sp_auth.blob_sha,
                name="Implement repository",
                description="D2",
                status=TaskStatus.COMPLETE,
            ),
            Task(
                id=id3,
                spec_path=sp_auth.path,
                spec_blob_sha=sp_auth.blob_sha,
                name="Add API endpoint",
                description="D3",
                status=TaskStatus.IN_PROGRESS,
            ),
        ],
    )

    sp_users = plan.spec_plans[1]
    sp_users.status = SpecPlanStatus.RECONCILING
    id4 = plan.next_task_id()
    id5 = plan.next_task_id()
    plan.add_tasks(
        sp_users,
        [
            Task(
                id=id4,
                spec_path=sp_users.path,
                spec_blob_sha=sp_users.blob_sha,
                name="Add validation",
                description="D4",
                status=TaskStatus.BACKLOG,
            ),
            Task(
                id=id5,
                spec_path=sp_users.path,
                spec_blob_sha=sp_users.blob_sha,
                name="Write migrations",
                description="D5",
                status=TaskStatus.FAILED,
            ),
        ],
    )

    return plan


class TestGetTasks:
    def test_displays_table_with_correct_columns(self) -> None:
        plan = _build_plan_with_tasks()
        store = FakePlanStore(plan)
        runner = CliRunner()
        result = runner.invoke(cli, ["get", "tasks"], obj=store)
        assert result.exit_code == 0
        header = result.output.split("\n")[0]
        assert "ID" in header
        assert "NAME" in header
        assert "SPEC" in header
        assert "STATUS" in header
        assert "RETRIES" in header
        assert "AGE" in header

    def test_displays_all_tasks(self) -> None:
        plan = _build_plan_with_tasks()
        store = FakePlanStore(plan)
        runner = CliRunner()
        result = runner.invoke(cli, ["get", "tasks"], obj=store)
        assert result.exit_code == 0
        assert "Create schema" in result.output
        assert "Write migrations" in result.output

    def test_filter_by_spec(self) -> None:
        plan = _build_plan_with_tasks()
        store = FakePlanStore(plan)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["get", "tasks", "--spec", "specs/auth.spec.md"], obj=store
        )
        assert result.exit_code == 0
        assert "Create schema" in result.output
        assert "Add validation" not in result.output
        assert "Write migrations" not in result.output

    def test_json_output(self) -> None:
        plan = _build_plan_with_tasks()
        store = FakePlanStore(plan)
        runner = CliRunner()
        result = runner.invoke(cli, ["get", "tasks", "--output", "json"], obj=store)
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 5

    def test_empty_plan(self) -> None:
        store = FakePlanStore(Plan())
        runner = CliRunner()
        result = runner.invoke(cli, ["get", "tasks"], obj=store)
        assert result.exit_code == 0
        assert "ID" in result.output
