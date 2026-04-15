"""Tests for dependency cycle detection.

Spec: "intake rejects dependency cycles." This module tests the pure
detect_cycles function that identifies cycles in the task dependency graph.
"""

from __future__ import annotations

from hyperloop.domain.deps import detect_cycles
from hyperloop.domain.model import Task, TaskStatus


def _task(task_id: str, deps: tuple[str, ...] = ()) -> Task:
    """Create a minimal Task for cycle-detection tests."""
    return Task(
        id=task_id,
        title=f"Task {task_id}",
        spec_ref=f"specs/{task_id}.md",
        status=TaskStatus.NOT_STARTED,
        phase=None,
        deps=deps,
        round=0,
        branch=None,
        pr=None,
    )


class TestNoCycles:
    def test_no_tasks(self) -> None:
        assert detect_cycles({}) == []

    def test_linear_deps(self) -> None:
        tasks = {
            "A": _task("A", ("B",)),
            "B": _task("B", ("C",)),
            "C": _task("C"),
        }
        assert detect_cycles(tasks) == []

    def test_diamond_no_cycle(self) -> None:
        tasks = {
            "A": _task("A", ("B", "C")),
            "B": _task("B", ("D",)),
            "C": _task("C", ("D",)),
            "D": _task("D"),
        }
        assert detect_cycles(tasks) == []

    def test_missing_dep_not_a_cycle(self) -> None:
        """A depends on a task not in the dict -- unmet, not a cycle."""
        tasks = {
            "A": _task("A", ("nonexistent",)),
        }
        assert detect_cycles(tasks) == []


class TestSimpleCycles:
    def test_self_dependency(self) -> None:
        tasks = {"A": _task("A", ("A",))}
        cycles = detect_cycles(tasks)
        assert len(cycles) == 1
        assert "A" in cycles[0]

    def test_two_node_cycle(self) -> None:
        tasks = {
            "A": _task("A", ("B",)),
            "B": _task("B", ("A",)),
        }
        cycles = detect_cycles(tasks)
        assert len(cycles) == 1
        assert set(cycles[0]) == {"A", "B"}

    def test_three_node_cycle(self) -> None:
        tasks = {
            "A": _task("A", ("B",)),
            "B": _task("B", ("C",)),
            "C": _task("C", ("A",)),
        }
        cycles = detect_cycles(tasks)
        assert len(cycles) == 1
        assert set(cycles[0]) == {"A", "B", "C"}


class TestMultipleCycles:
    def test_two_independent_cycles(self) -> None:
        tasks = {
            "A": _task("A", ("B",)),
            "B": _task("B", ("A",)),
            "C": _task("C", ("D",)),
            "D": _task("D", ("C",)),
        }
        cycles = detect_cycles(tasks)
        assert len(cycles) == 2
        cycle_sets = [set(c) for c in cycles]
        assert {"A", "B"} in cycle_sets
        assert {"C", "D"} in cycle_sets
