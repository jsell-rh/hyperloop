from __future__ import annotations

import inspect
from typing import get_type_hints

import pytest

from hyperloop.reconciliation.models.spec_entry import SpecEntry
from hyperloop.reconciliation.ports.spec_source import SpecSource
from tests.reconciliation.fakes.fake_spec_source import FakeSpecSource


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


class TestFakeSpecSourceSync:
    def test_sync_increments_counter(self) -> None:
        source = FakeSpecSource()
        assert source.sync_count == 0

        source.sync()

        assert source.sync_count == 1

    def test_multiple_syncs(self) -> None:
        source = FakeSpecSource()

        source.sync()
        source.sync()
        source.sync()

        assert source.sync_count == 3


class TestFakeSpecSourceListSpecs:
    def test_empty_by_default(self) -> None:
        source = FakeSpecSource()

        assert source.list_specs() == []

    def test_returns_added_specs(self) -> None:
        source = FakeSpecSource()
        source.add_spec("auth.spec.md", "abc123")

        entries = source.list_specs()

        assert len(entries) == 1
        assert entries[0] == SpecEntry(path="auth.spec.md", blob_sha="abc123")

    def test_adding_same_path_replaces(self) -> None:
        source = FakeSpecSource()
        source.add_spec("auth.spec.md", "abc123")
        source.add_spec("auth.spec.md", "def456")

        entries = source.list_specs()

        assert len(entries) == 1
        assert entries[0].blob_sha == "def456"

    def test_remove_spec(self) -> None:
        source = FakeSpecSource()
        source.add_spec("auth.spec.md", "abc123")

        source.remove_spec("auth.spec.md")

        assert source.list_specs() == []

    def test_remove_nonexistent_is_noop(self) -> None:
        source = FakeSpecSource()

        source.remove_spec("nonexistent.spec.md")

        assert source.list_specs() == []

    def test_returns_copy(self) -> None:
        source = FakeSpecSource()
        source.add_spec("auth.spec.md", "abc123")

        first = source.list_specs()
        second = source.list_specs()

        assert first is not second


class TestFakeSpecSourceReadAt:
    def test_returns_content(self) -> None:
        source = FakeSpecSource()
        source.add_spec("auth.spec.md", "abc123", content="# Auth Spec")

        content = source.read_at("auth.spec.md", "abc123")

        assert content == "# Auth Spec"

    def test_missing_raises(self) -> None:
        source = FakeSpecSource()

        with pytest.raises(KeyError):
            source.read_at("missing.spec.md", "abc123")

    def test_default_content_is_empty(self) -> None:
        source = FakeSpecSource()
        source.add_spec("auth.spec.md", "abc123")

        assert source.read_at("auth.spec.md", "abc123") == ""


class TestFakeSpecSourceDiff:
    def test_returns_configured_diff(self) -> None:
        source = FakeSpecSource()
        source.set_diff("auth.spec.md", "abc123", "def456", "+ new requirement")

        diff = source.diff("auth.spec.md", "abc123", "def456")

        assert diff == "+ new requirement"

    def test_unconfigured_returns_empty(self) -> None:
        source = FakeSpecSource()

        diff = source.diff("auth.spec.md", None, "abc123")

        assert diff == ""

    def test_diff_with_none_old_sha(self) -> None:
        source = FakeSpecSource()
        source.set_diff("auth.spec.md", None, "abc123", "+ entire file")

        diff = source.diff("auth.spec.md", None, "abc123")

        assert diff == "+ entire file"
