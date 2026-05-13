from __future__ import annotations

import subprocess
from pathlib import Path


class SubprocessKustomizeBuildRunner:
    def build(self, path: Path) -> str:
        result = subprocess.run(
            ["kustomize", "build", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        return result.stdout
