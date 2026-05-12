from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def _git_template(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    base = tmp_path_factory.mktemp("git_template")
    remote = base / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", str(remote)], check=True, capture_output=True
    )

    local = base / "local"
    subprocess.run(
        ["git", "clone", str(remote), str(local)], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(local), "config", "user.name", "Test User"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(local), "config", "user.email", "test@example.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(local), "commit", "--allow-empty", "-m", "Initial commit"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(local), "push", "origin", "main"],
        check=True,
        capture_output=True,
    )

    return local, remote


@pytest.fixture()
def git_env(tmp_path: Path, _git_template: tuple[Path, Path]) -> tuple[Path, Path]:
    template_local, template_remote = _git_template

    new_remote = tmp_path / "remote.git"
    new_local = tmp_path / "local"

    shutil.copytree(template_remote, new_remote)
    shutil.copytree(template_local, new_local)

    subprocess.run(
        ["git", "remote", "set-url", "origin", str(new_remote)],
        cwd=new_local,
        check=True,
        capture_output=True,
    )

    return new_local, new_remote
