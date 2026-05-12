from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import field_validator
from pydantic_settings import BaseSettings


class Configuration(BaseSettings):
    model_config = {"frozen": True}

    convergence_bound: int = 3
    max_task_retries: int = 3
    max_redecompositions: int = 1
    max_concurrent_tasks: int = 5

    cycle_interval_seconds: int = 30

    implementation_model: str | None = None
    verification_model: str | None = None
    decomposition_model: str | None = None

    specs_directory: str = "specs/"
    overlay_path: str = ".hyperloop/agents"

    observer_adapters: list[str] = []

    plan_branch: str = "hyperloop/plan"
    trunk_branch: str = "main"
    branch_prefix: str = "hyperloop/"

    @field_validator("convergence_bound")
    @classmethod
    def convergence_bound_must_be_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("convergence_bound must be >= 1")
        return v

    @field_validator("max_task_retries")
    @classmethod
    def max_task_retries_must_be_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("max_task_retries must be >= 0")
        return v

    @field_validator("max_redecompositions")
    @classmethod
    def max_redecompositions_must_be_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("max_redecompositions must be >= 0")
        return v

    @field_validator("max_concurrent_tasks")
    @classmethod
    def max_concurrent_tasks_must_be_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("max_concurrent_tasks must be >= 1")
        return v

    @field_validator("cycle_interval_seconds")
    @classmethod
    def cycle_interval_must_be_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("cycle_interval_seconds must be >= 1")
        return v

    @field_validator("specs_directory")
    @classmethod
    def specs_directory_must_exist(cls, v: str) -> str:
        if not Path(v).is_dir():
            raise ValueError(f"specs_directory '{v}' does not exist or is not a directory")
        return v

    @classmethod
    def from_yaml(cls, path: Path) -> Configuration:
        if path.exists():
            data = yaml.safe_load(path.read_text()) or {}
            return cls(**data)
        return cls()
