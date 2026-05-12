from __future__ import annotations

import json
from datetime import datetime, timezone

from click.testing import CliRunner

from hyperloop.cli.app import cli
from hyperloop.reconciliation.models import (
    Plan,
    SpecPlanStatus,
    Task,
    TaskStatus,
)

from .fakes.fake_plan_store import FakePlanStore


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _build_plan_with_specs() -> Plan:
    plan = Plan()
    plan.add_spec("specs/auth.spec.md", "abc123")
    plan.add_spec("specs/users.spec.md", "def456")
    plan.add_spec("specs/rbac.spec.md", "ghi789")

    sp_auth = plan.spec_plans[0]
    sp_auth.status = SpecPlanStatus.RECONCILING
    id1 = plan.next_task_id()
    id2 = plan.next_task_id()
    id3 = plan.next_task_id()
    id4 = plan.next_task_id()
    id5 = plan.next_task_id()
    plan.add_tasks(
        sp_auth,
        [
            Task(
                id=id1,
                spec_path=sp_auth.path,
                spec_blob_sha=sp_auth.blob_sha,
                name="T1",
                description="D1",
                status=TaskStatus.COMPLETE,
            ),
            Task(
                id=id2,
                spec_path=sp_auth.path,
                spec_blob_sha=sp_auth.blob_sha,
                name="T2",
                description="D2",
                status=TaskStatus.COMPLETE,
            ),
            Task(
                id=id3,
                spec_path=sp_auth.path,
                spec_blob_sha=sp_auth.blob_sha,
                name="T3",
                description="D3",
                status=TaskStatus.IN_PROGRESS,
            ),
        ],
    )

    sp_users = plan.spec_plans[1]
    sp_users.status = SpecPlanStatus.SYNCED
    plan.add_tasks(
        sp_users,
        [
            Task(
                id=id4,
                spec_path=sp_users.path,
                spec_blob_sha=sp_users.blob_sha,
                name="T4",
                description="D4",
                status=TaskStatus.COMPLETE,
            ),
        ],
    )

    sp_rbac = plan.spec_plans[2]
    sp_rbac.status = SpecPlanStatus.FAILED
    plan.add_tasks(
        sp_rbac,
        [
            Task(
                id=id5,
                spec_path=sp_rbac.path,
                spec_blob_sha=sp_rbac.blob_sha,
                name="T5",
                description="D5",
                status=TaskStatus.FAILED,
            ),
        ],
    )

    return plan


class TestGetSpecs:
    def test_displays_table_with_correct_columns(self) -> None:
        plan = _build_plan_with_specs()
        store = FakePlanStore(plan)
        runner = CliRunner()
        result = runner.invoke(cli, ["get", "specs"], obj=store)
        assert result.exit_code == 0
        header = result.output.split("\n")[0]
        assert "PATH" in header
        assert "BLOB SHA" in header
        assert "STATUS" in header
        assert "TASKS" in header

    def test_displays_all_non_superseded_specs(self) -> None:
        plan = _build_plan_with_specs()
        store = FakePlanStore(plan)
        runner = CliRunner()
        result = runner.invoke(cli, ["get", "specs"], obj=store)
        assert result.exit_code == 0
        assert "specs/auth.spec.md" in result.output
        assert "specs/users.spec.md" in result.output
        assert "specs/rbac.spec.md" in result.output

    def test_shows_task_completion_ratio(self) -> None:
        plan = _build_plan_with_specs()
        store = FakePlanStore(plan)
        runner = CliRunner()
        result = runner.invoke(cli, ["get", "specs"], obj=store)
        assert "2/3" in result.output
        assert "1/1" in result.output

    def test_hides_superseded_by_default(self) -> None:
        plan = _build_plan_with_specs()
        plan.add_spec("specs/auth.spec.md", "new_sha")
        store = FakePlanStore(plan)
        runner = CliRunner()
        result = runner.invoke(cli, ["get", "specs"], obj=store)
        assert result.exit_code == 0
        lines = [
            line for line in result.output.split("\n") if "specs/auth.spec.md" in line
        ]
        assert len(lines) == 1
        assert "new_sha" in lines[0]

    def test_shows_superseded_with_all_flag(self) -> None:
        plan = _build_plan_with_specs()
        plan.add_spec("specs/auth.spec.md", "new_sha")
        store = FakePlanStore(plan)
        runner = CliRunner()
        result = runner.invoke(cli, ["get", "specs", "--all"], obj=store)
        assert result.exit_code == 0
        lines = [
            line for line in result.output.split("\n") if "specs/auth.spec.md" in line
        ]
        assert len(lines) == 2
        superseded_line = [line for line in lines if "abc123" in line][0]
        assert "Superseded" in superseded_line

    def test_empty_plan(self) -> None:
        store = FakePlanStore(Plan())
        runner = CliRunner()
        result = runner.invoke(cli, ["get", "specs"], obj=store)
        assert result.exit_code == 0
        assert "PATH" in result.output

    def test_json_output(self) -> None:
        plan = _build_plan_with_specs()
        store = FakePlanStore(plan)
        runner = CliRunner()
        result = runner.invoke(cli, ["get", "specs", "--output", "json"], obj=store)
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 3
        assert data[0]["path"] == "specs/auth.spec.md"
