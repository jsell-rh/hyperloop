from __future__ import annotations

from structlog.testing import capture_logs

import pytest

from hyperloop.reconciliation.adapters.structlog_observer import (
    StructlogObserver,
    _WARNING_EVENTS,
)
from hyperloop.reconciliation.ports.observer import ChangeType
from tests.reconciliation.test_observer import EXPECTED_METHODS, _build_kwargs


class TestStructlogObserver:
    def test_every_probe_method_emits_structured_log(self) -> None:
        observer = StructlogObserver()

        for method_name, params in EXPECTED_METHODS.items():
            kwargs = _build_kwargs(params)
            with capture_logs() as cap:
                getattr(observer, method_name)(**kwargs)

            assert len(cap) == 1, f"{method_name} did not emit exactly one log entry"
            entry = cap[0]
            assert entry["event"] == method_name

    def test_probe_kwargs_appear_in_log_entry(self) -> None:
        observer = StructlogObserver()

        with capture_logs() as cap:
            observer.reconciler_started(spec_count=5, cycle=1)

        entry = cap[0]
        assert entry["spec_count"] == 5
        assert entry["cycle"] == 1

    def test_task_dispatched_includes_all_fields(self) -> None:
        observer = StructlogObserver()

        with capture_logs() as cap:
            observer.task_dispatched(
                task_id=42,
                spec_path="specs/auth.spec.md",
                spec_blob_sha="abc123",
                retry_count=2,
                cycle=3,
            )

        entry = cap[0]
        assert entry["event"] == "task_dispatched"
        assert entry["task_id"] == 42
        assert entry["spec_path"] == "specs/auth.spec.md"
        assert entry["spec_blob_sha"] == "abc123"
        assert entry["retry_count"] == 2
        assert entry["cycle"] == 3

    def test_change_type_enum_is_preserved(self) -> None:
        observer = StructlogObserver()

        with capture_logs() as cap:
            observer.spec_divergence_detected(
                spec_path="specs/a.spec.md",
                blob_sha="sha1",
                change_type=ChangeType.MODIFIED,
            )

        entry = cap[0]
        assert entry["change_type"] == ChangeType.MODIFIED

    @pytest.mark.parametrize("method_name", sorted(_WARNING_EVENTS))
    def test_all_warning_events_use_warning_level(self, method_name: str) -> None:
        observer = StructlogObserver()
        kwargs = _build_kwargs(EXPECTED_METHODS[method_name])

        with capture_logs() as cap:
            getattr(observer, method_name)(**kwargs)

        assert cap[0]["log_level"] == "warning", (
            f"{method_name} should emit at warning level"
        )

    def test_non_warning_events_use_info_level(self) -> None:
        observer = StructlogObserver()
        info_methods = set(EXPECTED_METHODS) - _WARNING_EVENTS

        for method_name in info_methods:
            kwargs = _build_kwargs(EXPECTED_METHODS[method_name])
            with capture_logs() as cap:
                getattr(observer, method_name)(**kwargs)

            assert cap[0]["log_level"] == "info", (
                f"{method_name} should emit at info level"
            )

    def test_list_kwargs_are_preserved(self) -> None:
        observer = StructlogObserver()

        with capture_logs() as cap:
            observer.task_created(
                task_id=1,
                spec_path="specs/a.spec.md",
                spec_blob_sha="abc",
                name="Create schema",
                depends_on=[2, 3],
            )

        assert cap[0]["depends_on"] == [2, 3]
