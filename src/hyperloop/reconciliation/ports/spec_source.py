from __future__ import annotations

from typing import Protocol

from hyperloop.reconciliation.models.spec_entry import SpecEntry


class SpecSource(Protocol):
    def list_specs(self) -> list[SpecEntry]: ...

    def read_at(self, path: str, blob_sha: str) -> str: ...

    def diff(self, path: str, old_sha: str | None, new_sha: str) -> str: ...

    def sync(self) -> None: ...
