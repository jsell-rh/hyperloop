"""Configuration loading — parse .hyperloop.yaml with defaults.

Reads the YAML config file, applies defaults for missing fields, and
returns a frozen Config dataclass. CLI arguments can override file values.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import yaml

if TYPE_CHECKING:
    from pathlib import Path


class ConfigError(Exception):
    """Raised when the config file cannot be parsed or is structurally invalid."""


@dataclass(frozen=True)
class Config:
    """Typed, immutable configuration for the orchestrator."""

    repo: str | None  # owner/repo or inferred from git remote
    base_branch: str  # default: "main"
    specs_dir: str  # default: "specs"
    overlay: str | None  # path or git URL to kustomization dir
    runtime: str  # "local" (v1 only)
    max_workers: int  # default: 6
    auto_merge: bool  # default: True
    merge_strategy: str  # default: "squash"
    delete_branch: bool  # default: True
    poll_interval: int  # default: 30
    max_rounds: int  # default: 50
    max_rebase_attempts: int  # default: 3


def _defaults() -> dict[str, object]:
    """Return the full default config as a flat dict."""
    return {
        "repo": None,
        "base_branch": "main",
        "specs_dir": "specs",
        "overlay": None,
        "runtime": "local",
        "max_workers": 6,
        "auto_merge": True,
        "merge_strategy": "squash",
        "delete_branch": True,
        "poll_interval": 30,
        "max_rounds": 50,
        "max_rebase_attempts": 3,
    }


def _flatten_yaml(raw: dict[str, object]) -> dict[str, object]:
    """Flatten the nested YAML structure into a flat dict matching Config fields.

    The YAML has nested sections (target, runtime, merge) but Config is flat.
    """
    flat: dict[str, object] = {}

    # Top-level scalars
    for key in ("overlay", "poll_interval", "max_rounds", "max_rebase_attempts"):
        if key in raw:
            flat[key] = raw[key]

    # target section
    target = raw.get("target")
    if isinstance(target, dict):
        if "repo" in target:
            flat["repo"] = target["repo"]
        if "base_branch" in target:
            flat["base_branch"] = target["base_branch"]
        if "specs_dir" in target:
            flat["specs_dir"] = target["specs_dir"]

    # runtime section
    runtime = raw.get("runtime")
    if isinstance(runtime, dict):
        if "default" in runtime:
            flat["runtime"] = runtime["default"]
        if "max_workers" in runtime:
            flat["max_workers"] = runtime["max_workers"]

    # merge section
    merge = raw.get("merge")
    if isinstance(merge, dict):
        if "auto_merge" in merge:
            flat["auto_merge"] = merge["auto_merge"]
        if "strategy" in merge:
            flat["merge_strategy"] = merge["strategy"]
        if "delete_branch" in merge:
            flat["delete_branch"] = merge["delete_branch"]

    return flat


def load_config(
    path: Path | None = None,
    *,
    repo: str | None = None,
    base_branch: str | None = None,
    max_workers: int | None = None,
) -> Config:
    """Load config from a YAML file, with defaults for missing fields.

    Args:
        path: Path to .hyperloop.yaml. If None or non-existent, use all defaults.
        repo: CLI override for target.repo.
        base_branch: CLI override for target.base_branch.
        max_workers: CLI override for runtime.max_workers.

    Returns:
        A frozen Config instance.

    Raises:
        ConfigError: If the file exists but contains invalid YAML or is not a mapping.
    """
    values = _defaults()

    # Load from file if it exists
    if path is not None and path.exists():
        try:
            raw = yaml.safe_load(path.read_text())
        except yaml.YAMLError as exc:
            msg = f"Failed to parse config file {path}: {exc}"
            raise ConfigError(msg) from exc

        if raw is not None:
            if not isinstance(raw, dict):
                msg = f"Config file {path} must be a YAML mapping, got {type(raw).__name__}"
                raise ConfigError(msg)

            file_values = _flatten_yaml(cast("dict[str, object]", raw))
            values.update(file_values)

    # Apply CLI overrides (only if not None)
    if repo is not None:
        values["repo"] = repo
    if base_branch is not None:
        values["base_branch"] = base_branch
    if max_workers is not None:
        values["max_workers"] = max_workers

    return Config(
        repo=values["repo"],  # type: ignore[arg-type]
        base_branch=str(values["base_branch"]),
        specs_dir=str(values["specs_dir"]),
        overlay=values["overlay"] if values["overlay"] is not None else None,  # type: ignore[arg-type]
        runtime=str(values["runtime"]),
        max_workers=int(values["max_workers"]),  # type: ignore[arg-type]
        auto_merge=bool(values["auto_merge"]),
        merge_strategy=str(values["merge_strategy"]),
        delete_branch=bool(values["delete_branch"]),
        poll_interval=int(values["poll_interval"]),  # type: ignore[arg-type]
        max_rounds=int(values["max_rounds"]),  # type: ignore[arg-type]
        max_rebase_attempts=int(values["max_rebase_attempts"]),  # type: ignore[arg-type]
    )
