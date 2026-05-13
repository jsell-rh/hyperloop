from __future__ import annotations

from pathlib import Path
from typing import Protocol


class KustomizeBuildRunner(Protocol):
    def build(self, path: Path) -> str: ...
