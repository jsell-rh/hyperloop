from __future__ import annotations

from hyperloop.reconciliation.models.spec_entry import SpecEntry


class FakeSpecSource:
    def __init__(self) -> None:
        self._entries: list[SpecEntry] = []
        self._contents: dict[tuple[str, str], str] = {}
        self._diffs: dict[tuple[str, str | None, str], str] = {}
        self._read_error: Exception | None = None
        self.sync_count: int = 0

    def set_read_error(self, error: Exception) -> None:
        self._read_error = error

    def add_spec(self, path: str, blob_sha: str, content: str = "") -> None:
        self._entries = [e for e in self._entries if e.path != path]
        self._entries.append(SpecEntry(path=path, blob_sha=blob_sha))
        self._contents[(path, blob_sha)] = content

    def remove_spec(self, path: str) -> None:
        self._entries = [e for e in self._entries if e.path != path]

    def set_diff(
        self, path: str, old_sha: str | None, new_sha: str, diff_text: str
    ) -> None:
        self._diffs[(path, old_sha, new_sha)] = diff_text

    def list_specs(self) -> list[SpecEntry]:
        return list(self._entries)

    def read_at(self, path: str, blob_sha: str) -> str:
        if self._read_error is not None:
            raise self._read_error
        return self._contents[(path, blob_sha)]

    def diff(self, path: str, old_sha: str | None, new_sha: str) -> str:
        return self._diffs.get((path, old_sha, new_sha), "")

    def sync(self) -> None:
        self.sync_count += 1
