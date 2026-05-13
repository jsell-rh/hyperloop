from __future__ import annotations

import subprocess
from pathlib import Path

import click


def find_git_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise click.ClickException("Not a git repository")
    return Path(result.stdout.strip())
