from __future__ import annotations

import inspect
from typing import get_type_hints

from hyperloop.reconciliation.models.spec_entry import SpecEntry
from hyperloop.reconciliation.ports.spec_source import SpecSource


class TestSpecSourceProtocol:
    def test_defines_list_specs(self) -> None:
        assert hasattr(SpecSource, "list_specs")

    def test_defines_read_at(self) -> None:
        assert hasattr(SpecSource, "read_at")

    def test_defines_diff(self) -> None:
        assert hasattr(SpecSource, "diff")

    def test_defines_sync(self) -> None:
        assert hasattr(SpecSource, "sync")

    def test_list_specs_returns_list_of_spec_entry(self) -> None:
        hints = get_type_hints(SpecSource.list_specs)
        assert hints["return"] == list[SpecEntry]

    def test_read_at_accepts_path_and_blob_sha(self) -> None:
        hints = get_type_hints(SpecSource.read_at)
        assert hints["path"] is str
        assert hints["blob_sha"] is str

    def test_read_at_returns_str(self) -> None:
        hints = get_type_hints(SpecSource.read_at)
        assert hints["return"] is str

    def test_diff_accepts_path_and_optional_old_sha_and_new_sha(self) -> None:
        hints = get_type_hints(SpecSource.diff)
        assert hints["path"] is str
        assert hints["old_sha"] == str | None
        assert hints["new_sha"] is str

    def test_diff_returns_str(self) -> None:
        hints = get_type_hints(SpecSource.diff)
        assert hints["return"] is str

    def test_sync_returns_none(self) -> None:
        hints = get_type_hints(SpecSource.sync)
        assert hints["return"] is type(None)

    def test_no_extra_methods(self) -> None:
        methods = {
            name
            for name, _ in inspect.getmembers(SpecSource, predicate=inspect.isfunction)
            if not name.startswith("_")
        }
        assert methods == {"list_specs", "read_at", "diff", "sync"}

    def test_port_imports_only_domain_types(self) -> None:
        import hyperloop.reconciliation.ports.spec_source as module

        source = inspect.getsource(module)
        assert "adapters" not in source
