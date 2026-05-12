from __future__ import annotations

from hyperloop.reconciliation.models.plan import Plan


class FakePlanStore:
    def __init__(self, plan: Plan | None = None) -> None:
        self._plan = plan or Plan()

    def get_plan(self) -> Plan:
        return self._plan

    def write_plan(self, plan: Plan) -> None:
        self._plan = plan
