from __future__ import annotations


class CyclicDependencyError(Exception):
    def __init__(self, cycle: list[str]) -> None:
        self.cycle = cycle
        path = " -> ".join(cycle)
        super().__init__(f"Cyclic dependency detected: {path}")
