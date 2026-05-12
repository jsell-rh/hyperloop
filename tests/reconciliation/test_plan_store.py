from __future__ import annotations

import inspect
from typing import get_type_hints

from hyperloop.reconciliation.models.plan import Plan
from hyperloop.reconciliation.ports.plan_store import PlanStore


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
