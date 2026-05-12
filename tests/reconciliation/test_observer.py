from __future__ import annotations

import inspect
from typing import get_type_hints

from hyperloop.reconciliation.adapters.composite_observer import CompositeObserver
from hyperloop.reconciliation.adapters.null_probe import NullProbe
from hyperloop.reconciliation.ports.observer import ChangeType, Observer
from tests.reconciliation.fakes.fake_observer import FakeObserver

EXPECTED_METHODS: dict[str, dict[str, type]] = {
    "reconciler_started": {"spec_count": int, "cycle": int},
    "reconciler_halted": {"reason": str, "total_cycles": int},
    "cycle_started": {"cycle": int, "specs_out_of_sync": int, "tasks_in_progress": int},
    "cycle_completed": {
        "cycle": int,
        "duration_s": float,
        "specs_out_of_sync": int,
        "tasks_dispatched": int,
        "tasks_completed": int,
        "tasks_failed": int,
    },
    "spec_divergence_detected": {
        "spec_path": str,
        "blob_sha": str,
        "change_type": ChangeType,
    },
    "spec_superseded": {"spec_path": str, "old_sha": str, "new_sha": str},
    "decomposition_started": {"specs_count": int, "cycle": int},
    "decomposition_completed": {
        "specs_count": int,
        "tasks_created": int,
        "cycle": int,
        "duration_s": float,
    },
    "decomposition_failed": {"reason": str, "cycle": int},
    "task_created": {
        "task_id": int,
        "spec_path": str,
        "spec_blob_sha": str,
        "name": str,
        "depends_on": list[int],
    },
    "task_dispatched": {
        "task_id": int,
        "spec_path": str,
        "spec_blob_sha": str,
        "retry_count": int,
        "cycle": int,
    },
    "task_completed": {
        "task_id": int,
        "spec_path": str,
        "spec_blob_sha": str,
        "cycle": int,
    },
    "task_failed": {
        "task_id": int,
        "spec_path": str,
        "spec_blob_sha": str,
        "reason": str,
        "retry_count": int,
        "cycle": int,
    },
    "task_retried": {
        "task_id": int,
        "spec_path": str,
        "reason": str,
        "retry_count": int,
        "cycle": int,
    },
    "dependency_invalidated": {
        "task_id": int,
        "spec_path": str,
        "dependency_task_id": int,
        "reason": str,
    },
    "task_merge_completed": {"task_id": int, "spec_blob_sha": str},
    "task_merge_conflict": {"task_id": int, "spec_blob_sha": str},
    "merge_resolution_launched": {"task_id": int, "spec_blob_sha": str},
    "merge_resolution_completed": {
        "task_id": int,
        "spec_blob_sha": str,
        "success": bool,
    },
    "trunk_integration_started": {
        "spec_path": str,
        "spec_blob_sha": str,
        "integration_id": str,
    },
    "trunk_integration_completed": {
        "spec_path": str,
        "spec_blob_sha": str,
        "integration_id": str,
    },
    "trunk_integration_failed": {"spec_path": str, "spec_blob_sha": str, "reason": str},
    "verification_launched": {"spec_path": str, "spec_blob_sha": str, "cycle": int},
    "verification_passed": {
        "spec_path": str,
        "spec_blob_sha": str,
        "rationale": str,
        "cycle": int,
    },
    "verification_failed": {
        "spec_path": str,
        "spec_blob_sha": str,
        "rationale": str,
        "cycle": int,
    },
    "spec_synced": {
        "spec_path": str,
        "spec_blob_sha": str,
        "total_tasks": int,
        "cycle": int,
    },
    "spec_failed": {
        "spec_path": str,
        "spec_blob_sha": str,
        "reason": str,
        "cycle": int,
    },
    "redecomposition_triggered": {
        "spec_path": str,
        "spec_blob_sha": str,
        "failed_task_count": int,
        "cycle": int,
    },
    "agent_cancelled": {"task_id": int, "spec_path": str, "reason": str},
    "agent_orphan_detected": {"task_id": int, "spec_path": str},
    "agent_launch_failed": {"task_id": int, "role": str, "reason": str, "cycle": int},
    "crash_recovery_started": {"orphaned_agent_count": int},
    "composer_rebuilt": {"template_count": int},
    "composer_rebuild_failed": {"reason": str},
    "plan_synced": {"cycle": int},
}


def _build_kwargs(params: dict[str, type]) -> dict[str, object]:
    defaults: dict[type, object] = {
        int: 1,
        float: 1.0,
        str: "test",
        bool: True,
        list[int]: [1, 2],
        ChangeType: ChangeType.NEW,
    }
    return {name: defaults[typ] for name, typ in params.items()}


class TestObserverProtocol:
    def test_all_expected_methods_exist(self) -> None:
        for method_name in EXPECTED_METHODS:
            assert hasattr(Observer, method_name), (
                f"Observer missing method: {method_name}"
            )

    def test_no_extra_methods(self) -> None:
        protocol_methods = {
            name
            for name, _ in inspect.getmembers(Observer, predicate=inspect.isfunction)
            if not name.startswith("_")
        }
        assert protocol_methods == set(EXPECTED_METHODS.keys())

    def test_all_parameters_are_keyword_only(self) -> None:
        for method_name in EXPECTED_METHODS:
            sig = inspect.signature(getattr(Observer, method_name))
            for param_name, param in sig.parameters.items():
                if param_name == "self":
                    continue
                assert param.kind == inspect.Parameter.KEYWORD_ONLY, (
                    f"{method_name}.{param_name} must be keyword-only"
                )

    def test_method_signatures_match_spec(self) -> None:
        for method_name, expected_params in EXPECTED_METHODS.items():
            hints = get_type_hints(getattr(Observer, method_name))
            hints.pop("return", None)
            assert hints == expected_params, (
                f"{method_name} type hints mismatch: expected {expected_params}, got {hints}"
            )

    def test_all_methods_return_none(self) -> None:
        for method_name in EXPECTED_METHODS:
            hints = get_type_hints(getattr(Observer, method_name))
            assert hints.get("return") is type(None), f"{method_name} must return None"


class TestChangeType:
    def test_values(self) -> None:
        assert ChangeType.NEW == "new"
        assert ChangeType.MODIFIED == "modified"
        assert ChangeType.DELETED == "deleted"

    def test_is_str_enum(self) -> None:
        assert isinstance(ChangeType.NEW, str)


class TestNullProbe:
    def test_all_probe_calls_succeed_silently(self) -> None:
        probe = NullProbe()
        for method_name, params in EXPECTED_METHODS.items():
            kwargs = _build_kwargs(params)
            getattr(probe, method_name)(**kwargs)

    def test_returns_none(self) -> None:
        probe = NullProbe()
        result = probe.reconciler_started(spec_count=5, cycle=1)
        assert result is None


class _RecordingObserver:
    """Fake observer that records all probe calls for verification."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def __getattr__(self, name: str) -> object:
        if name.startswith("_"):
            raise AttributeError(name)

        def record(**kwargs: object) -> None:
            self.calls.append((name, kwargs))

        return record


class _FailingObserver:
    """Fake observer that raises on every probe call."""

    def __getattr__(self, name: str) -> object:
        if name.startswith("_"):
            raise AttributeError(name)

        def fail(**kwargs: object) -> None:
            raise RuntimeError(f"adapter failure in {name}")

        return fail


class TestCompositeObserver:
    def test_fans_out_to_all_adapters(self) -> None:
        r1 = _RecordingObserver()
        r2 = _RecordingObserver()
        composite = CompositeObserver([r1, r2])

        composite.task_dispatched(
            task_id=1,
            spec_path="a.spec.md",
            spec_blob_sha="abc",
            retry_count=0,
            cycle=1,
        )

        assert len(r1.calls) == 1
        assert len(r2.calls) == 1
        assert r1.calls[0] == (
            "task_dispatched",
            {
                "task_id": 1,
                "spec_path": "a.spec.md",
                "spec_blob_sha": "abc",
                "retry_count": 0,
                "cycle": 1,
            },
        )

    def test_adapter_failure_does_not_affect_others(self) -> None:
        failing = _FailingObserver()
        recording = _RecordingObserver()
        composite = CompositeObserver([failing, recording])

        composite.reconciler_started(spec_count=3, cycle=1)

        assert len(recording.calls) == 1
        assert recording.calls[0] == (
            "reconciler_started",
            {"spec_count": 3, "cycle": 1},
        )

    def test_all_adapter_failures_suppressed(self) -> None:
        f1 = _FailingObserver()
        f2 = _FailingObserver()
        composite = CompositeObserver([f1, f2])

        composite.reconciler_started(spec_count=3, cycle=1)

    def test_empty_adapter_list(self) -> None:
        composite = CompositeObserver([])
        composite.reconciler_started(spec_count=3, cycle=1)

    def test_all_probe_methods_fan_out(self) -> None:
        recording = _RecordingObserver()
        composite = CompositeObserver([recording])

        for method_name, params in EXPECTED_METHODS.items():
            kwargs = _build_kwargs(params)
            getattr(composite, method_name)(**kwargs)

        assert len(recording.calls) == len(EXPECTED_METHODS)
        called_methods = {name for name, _ in recording.calls}
        assert called_methods == set(EXPECTED_METHODS.keys())

    def test_failure_in_first_adapter_still_reaches_third(self) -> None:
        r1 = _RecordingObserver()
        failing = _FailingObserver()
        r2 = _RecordingObserver()
        composite = CompositeObserver([r1, failing, r2])

        composite.cycle_started(cycle=1, specs_out_of_sync=2, tasks_in_progress=0)

        assert len(r1.calls) == 1
        assert len(r2.calls) == 1


class TestFakeObserverRecording:
    def test_starts_with_no_calls(self) -> None:
        observer = FakeObserver()

        assert observer.calls == []

    def test_records_method_and_kwargs(self) -> None:
        observer = FakeObserver()

        observer.reconciler_started(spec_count=5, cycle=1)

        assert len(observer.calls) == 1
        assert observer.calls[0].method == "reconciler_started"
        assert observer.calls[0].kwargs == {"spec_count": 5, "cycle": 1}

    def test_records_multiple_calls(self) -> None:
        observer = FakeObserver()

        observer.reconciler_started(spec_count=5, cycle=1)
        observer.cycle_started(cycle=1, specs_out_of_sync=2, tasks_in_progress=0)

        assert len(observer.calls) == 2

    def test_calls_for_filters_by_method(self) -> None:
        observer = FakeObserver()

        observer.reconciler_started(spec_count=5, cycle=1)
        observer.cycle_started(cycle=1, specs_out_of_sync=2, tasks_in_progress=0)
        observer.reconciler_started(spec_count=3, cycle=2)

        results = observer.calls_for("reconciler_started")

        assert len(results) == 2
        assert results[0] == {"spec_count": 5, "cycle": 1}
        assert results[1] == {"spec_count": 3, "cycle": 2}

    def test_calls_for_returns_empty_when_no_matches(self) -> None:
        observer = FakeObserver()

        observer.reconciler_started(spec_count=5, cycle=1)

        assert observer.calls_for("cycle_started") == []


class TestFakeObserverProtocolCompliance:
    def test_all_probe_methods_succeed(self) -> None:
        observer = FakeObserver()
        for method_name, params in EXPECTED_METHODS.items():
            kwargs = _build_kwargs(params)
            getattr(observer, method_name)(**kwargs)

    def test_all_probe_methods_recorded(self) -> None:
        observer = FakeObserver()
        for method_name, params in EXPECTED_METHODS.items():
            kwargs = _build_kwargs(params)
            getattr(observer, method_name)(**kwargs)

        assert len(observer.calls) == len(EXPECTED_METHODS)
        called_methods = {c.method for c in observer.calls}
        assert called_methods == set(EXPECTED_METHODS.keys())
