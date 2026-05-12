from __future__ import annotations

from typing import Protocol

from hyperloop.reconciliation.models.plan import Plan


class PlanStore(Protocol):
    def get_plan(self) -> Plan: ...

    def write_plan(self, plan: Plan) -> None: ...
