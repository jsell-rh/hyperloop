from __future__ import annotations

import subprocess
from pathlib import Path


_BUILD_TIMEOUT_SECONDS = 30


class SubprocessKustomizeBuildRunner:
    def build(self, path: Path) -> str:
        result = subprocess.run(
            ["kustomize", "build", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
            timeout=_BUILD_TIMEOUT_SECONDS,
        )
        return result.stdout
