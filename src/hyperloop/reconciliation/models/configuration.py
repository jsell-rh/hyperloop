from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings

from hyperloop.reconciliation.models.executor_type import ExecutorType
from hyperloop.reconciliation.models.observer_adapter import ObserverAdapter


DEFAULT_CONFIG_FILENAME = ".hyperloop.yaml"


class Configuration(BaseSettings):
    model_config = {"frozen": True}

    convergence_bound: int = 3
    max_task_retries: int = 3
    max_redecompositions: int = 1
    max_integration_retries: int = 3
    max_concurrent_tasks: int = 5

    cycle_interval_seconds: int = 30

    implementation_model: str | None = None
    verification_model: str | None = None
    decomposition_model: str | None = None

    specs_directory: str = "specs/"
    overlay_path: str = ".hyperloop/agents"

    observer_adapters: list[ObserverAdapter] = []

    plan_branch: str = "hyperloop/plan"
    plan_file: str = "plan.json"
    trunk_branch: str = "main"
    branch_prefix: str = "hyperloop/"

    executor_type: ExecutorType = ExecutorType.CLAUDE_SDK
    executor_timeout_seconds: int = 300
    executor_max_retries: int = 3
    repository_url: str | None = None
    project_identifier: str | None = None

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

    @field_validator("max_integration_retries")
    @classmethod
    def max_integration_retries_must_be_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("max_integration_retries must be >= 1")
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

    @field_validator("executor_timeout_seconds")
    @classmethod
    def executor_timeout_must_be_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("executor_timeout_seconds must be >= 1")
        return v

    @field_validator("executor_max_retries")
    @classmethod
    def executor_max_retries_must_be_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("executor_max_retries must be >= 0")
        return v

    @field_validator("specs_directory")
    @classmethod
    def specs_directory_must_exist(cls, v: str) -> str:
        if not Path(v).is_dir():
            raise ValueError(
                f"specs_directory '{v}' does not exist or is not a directory"
            )
        return v

    @field_validator("overlay_path")
    @classmethod
    def overlay_path_must_exist(cls, v: str) -> str:
        if not Path(v).is_dir():
            raise ValueError(
                f"overlay_path '{v}' does not exist or is not a directory. "
                "Run `hyperloop init` to scaffold the default configuration"
            )
        return v

    @model_validator(mode="after")
    def ambient_requires_url_and_project(self) -> Configuration:
        if self.executor_type == ExecutorType.AMBIENT:
            if self.repository_url is None:
                raise ValueError(
                    "repository_url is required when executor_type is 'ambient'"
                )
            if self.project_identifier is None:
                raise ValueError(
                    "project_identifier is required when executor_type is 'ambient'"
                )
        return self

    @classmethod
    def from_yaml(cls, path: Path) -> Configuration:
        if path.exists():
            data = yaml.safe_load(path.read_text()) or {}
            return cls(**data)
        return cls()
