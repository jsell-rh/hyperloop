from __future__ import annotations

from click.testing import CliRunner

from hyperloop.cli.app import cli
from hyperloop.reconciliation.models import (
    Plan,
    SpecPlanStatus,
    Task,
    TaskStatus,
)

from .fakes.fake_plan_store import FakePlanStore


def _build_plan() -> Plan:
    plan = Plan()
    plan.add_spec("specs/auth.spec.md", "abc123")
    sp = plan.spec_plans[0]
    sp.status = SpecPlanStatus.RECONCILING
    id1 = plan.next_task_id()
    plan.add_tasks(
        sp,
        [
            Task(
                id=id1,
                spec_path=sp.path,
                spec_blob_sha=sp.blob_sha,
                name="T1",
                description="D1",
                status=TaskStatus.COMPLETE,
            ),
        ],
    )
    return plan


class TestReadOnlyStateAccess:
    def test_get_specs_does_not_write(self) -> None:
        store = FakePlanStore(_build_plan())
        runner = CliRunner()
        runner.invoke(cli, ["get", "specs"], obj=store)
        assert store.write_count == 0

    def test_get_tasks_does_not_write(self) -> None:
        store = FakePlanStore(_build_plan())
        runner = CliRunner()
        runner.invoke(cli, ["get", "tasks"], obj=store)
        assert store.write_count == 0

    def test_get_events_does_not_write(self) -> None:
        store = FakePlanStore(_build_plan())
        runner = CliRunner()
        runner.invoke(cli, ["get", "events"], obj=store)
        assert store.write_count == 0

    def test_describe_spec_does_not_write(self) -> None:
        store = FakePlanStore(_build_plan())
        runner = CliRunner()
        runner.invoke(cli, ["describe", "spec", "specs/auth.spec.md"], obj=store)
        assert store.write_count == 0

    def test_describe_task_does_not_write(self) -> None:
        store = FakePlanStore(_build_plan())
        runner = CliRunner()
        runner.invoke(cli, ["describe", "task", "1"], obj=store)
        assert store.write_count == 0
