"""Dependency cycle detection for the task graph.

Pure function, no I/O. Used by intake to reject dependency cycles.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from k_orchestrate.domain.model import Task


def detect_cycles(tasks: dict[str, Task]) -> list[list[str]]:
    """Detect dependency cycles in the task graph.

    Returns a list of cycles, where each cycle is a list of task IDs.
    Empty list means no cycles. Dependencies referencing task IDs not
    present in the dict are ignored (unmet, not cyclic).
    """
    # Standard DFS-based cycle detection with three coloring states
    WHITE = 0  # not visited
    GRAY = 1  # on the current DFS path
    BLACK = 2  # fully processed

    color: dict[str, int] = {tid: WHITE for tid in tasks}
    parent: dict[str, str | None] = {}
    cycles: list[list[str]] = []

    def dfs(node: str) -> None:
        color[node] = GRAY
        task = tasks[node]
        for dep in task.deps:
            if dep not in tasks:
                # Dependency references a task not in the dict -- skip
                continue
            if color[dep] == GRAY:
                # Found a cycle -- trace back from node to dep
                cycle = _extract_cycle(node, dep, parent)
                cycles.append(cycle)
            elif color[dep] == WHITE:
                parent[dep] = node
                dfs(dep)
        color[node] = BLACK

    for tid in tasks:
        if color[tid] == WHITE:
            parent[tid] = None
            dfs(tid)

    return cycles


def _extract_cycle(current: str, back_edge_target: str, parent: dict[str, str | None]) -> list[str]:
    """Extract the cycle path from the parent map.

    Walks from `current` back through `parent` until reaching `back_edge_target`.
    """
    cycle = [back_edge_target]
    node: str | None = current
    while node != back_edge_target:
        assert node is not None
        cycle.append(node)
        node = parent.get(node)
    cycle.reverse()
    return cycle
