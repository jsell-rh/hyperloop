from __future__ import annotations

import inspect
from typing import get_type_hints

from hyperloop.reconciliation.models.plan import Plan
from hyperloop.reconciliation.ports.plan_store import PlanStore
from tests.reconciliation.fakes.fake_plan_store import FakePlanStore


class TestPlanStoreProtocol:
    def test_defines_get_plan(self) -> None:
        assert hasattr(PlanStore, "get_plan")

    def test_defines_write_plan(self) -> None:
        assert hasattr(PlanStore, "write_plan")

    def test_get_plan_returns_plan(self) -> None:
        hints = get_type_hints(PlanStore.get_plan)
        assert hints["return"] is Plan

    def test_write_plan_accepts_plan(self) -> None:
        hints = get_type_hints(PlanStore.write_plan)
        assert hints["plan"] is Plan

    def test_write_plan_returns_none(self) -> None:
        hints = get_type_hints(PlanStore.write_plan)
        assert hints["return"] is type(None)

    def test_no_extra_methods(self) -> None:
        methods = {
            name
            for name, _ in inspect.getmembers(PlanStore, predicate=inspect.isfunction)
            if not name.startswith("_")
        }
        assert methods == {"get_plan", "write_plan"}

    def test_port_imports_only_domain_types(self) -> None:
        import hyperloop.reconciliation.ports.plan_store as module

        source = inspect.getsource(module)
        assert "adapters" not in source


class TestFakePlanStoreGetPlan:
    def test_returns_empty_plan_by_default(self) -> None:
        store = FakePlanStore()

        plan = store.get_plan()

        assert plan.spec_plans == []
        assert plan.events == []

    def test_returns_injected_plan(self) -> None:
        plan = Plan()
        plan.add_spec("auth.spec.md", "abc123")
        store = FakePlanStore(plan=plan)

        result = store.get_plan()

        assert len(result.spec_plans) == 1
        assert result.spec_plans[0].path == "auth.spec.md"

    def test_returns_same_reference(self) -> None:
        store = FakePlanStore()

        first = store.get_plan()
        second = store.get_plan()

        assert first is second


class TestFakePlanStoreWritePlan:
    def test_increments_write_count(self) -> None:
        store = FakePlanStore()
        assert store.write_count == 0

        store.write_plan(Plan())

        assert store.write_count == 1

    def test_stores_written_plan(self) -> None:
        store = FakePlanStore()
        new_plan = Plan()
        new_plan.add_spec("auth.spec.md", "abc123")

        store.write_plan(new_plan)

        assert store.get_plan() is new_plan

    def test_multiple_writes(self) -> None:
        store = FakePlanStore()

        store.write_plan(Plan())
        store.write_plan(Plan())
        store.write_plan(Plan())

        assert store.write_count == 3
