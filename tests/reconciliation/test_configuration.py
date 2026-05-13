from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from hyperloop.reconciliation.models import Configuration
from hyperloop.reconciliation.models.executor_type import ExecutorType
from hyperloop.reconciliation.models.observer_adapter import ObserverAdapter


@pytest.fixture()
def specs_dir(tmp_path: Path) -> Path:
    d = tmp_path / "specs"
    d.mkdir()
    return d


def _write_yaml(path: Path, data: dict[str, object]) -> None:
    path.write_text(yaml.dump(data))


class TestDefaultValues:
    def test_convergence_bound_defaults_to_3(self, specs_dir: Path) -> None:
        config = Configuration(specs_directory=str(specs_dir))
        assert config.convergence_bound == 3

    def test_max_task_retries_defaults_to_3(self, specs_dir: Path) -> None:
        config = Configuration(specs_directory=str(specs_dir))
        assert config.max_task_retries == 3

    def test_max_redecompositions_defaults_to_1(self, specs_dir: Path) -> None:
        config = Configuration(specs_directory=str(specs_dir))
        assert config.max_redecompositions == 1

    def test_max_concurrent_tasks_defaults_to_5(self, specs_dir: Path) -> None:
        config = Configuration(specs_directory=str(specs_dir))
        assert config.max_concurrent_tasks == 5

    def test_cycle_interval_seconds_defaults_to_30(self, specs_dir: Path) -> None:
        config = Configuration(specs_directory=str(specs_dir))
        assert config.cycle_interval_seconds == 30

    def test_specs_directory_defaults_to_specs(self) -> None:
        config = Configuration()
        assert config.specs_directory == "specs/"

    def test_overlay_path_defaults_to_hyperloop_agents(self, specs_dir: Path) -> None:
        config = Configuration(specs_directory=str(specs_dir))
        assert config.overlay_path == ".hyperloop/agents"

    def test_plan_branch_defaults_to_hyperloop_plan(self, specs_dir: Path) -> None:
        config = Configuration(specs_directory=str(specs_dir))
        assert config.plan_branch == "hyperloop/plan"

    def test_trunk_branch_defaults_to_main(self, specs_dir: Path) -> None:
        config = Configuration(specs_directory=str(specs_dir))
        assert config.trunk_branch == "main"

    def test_branch_prefix_defaults_to_hyperloop_slash(self, specs_dir: Path) -> None:
        config = Configuration(specs_directory=str(specs_dir))
        assert config.branch_prefix == "hyperloop/"

    def test_observer_adapters_defaults_to_empty_list(self, specs_dir: Path) -> None:
        config = Configuration(specs_directory=str(specs_dir))
        assert config.observer_adapters == []

    def test_model_fields_default_to_none(self, specs_dir: Path) -> None:
        config = Configuration(specs_directory=str(specs_dir))
        assert config.implementation_model is None
        assert config.verification_model is None
        assert config.decomposition_model is None

    def test_executor_type_defaults_to_claude_sdk(self, specs_dir: Path) -> None:
        config = Configuration(specs_directory=str(specs_dir))
        assert config.executor_type == ExecutorType.CLAUDE_SDK

    def test_repository_url_defaults_to_none(self, specs_dir: Path) -> None:
        config = Configuration(specs_directory=str(specs_dir))
        assert config.repository_url is None

    def test_project_identifier_defaults_to_none(self, specs_dir: Path) -> None:
        config = Configuration(specs_directory=str(specs_dir))
        assert config.project_identifier is None


class TestValidation:
    def test_convergence_bound_zero_rejected(self, specs_dir: Path) -> None:
        with pytest.raises(ValueError, match="convergence_bound"):
            Configuration(convergence_bound=0, specs_directory=str(specs_dir))

    def test_convergence_bound_negative_rejected(self, specs_dir: Path) -> None:
        with pytest.raises(ValueError, match="convergence_bound"):
            Configuration(convergence_bound=-1, specs_directory=str(specs_dir))

    def test_convergence_bound_one_accepted(self, specs_dir: Path) -> None:
        config = Configuration(convergence_bound=1, specs_directory=str(specs_dir))
        assert config.convergence_bound == 1

    def test_max_task_retries_negative_rejected(self, specs_dir: Path) -> None:
        with pytest.raises(ValueError, match="max_task_retries"):
            Configuration(max_task_retries=-1, specs_directory=str(specs_dir))

    def test_max_task_retries_zero_accepted(self, specs_dir: Path) -> None:
        config = Configuration(max_task_retries=0, specs_directory=str(specs_dir))
        assert config.max_task_retries == 0

    def test_max_redecompositions_negative_rejected(self, specs_dir: Path) -> None:
        with pytest.raises(ValueError, match="max_redecompositions"):
            Configuration(max_redecompositions=-1, specs_directory=str(specs_dir))

    def test_max_redecompositions_zero_accepted(self, specs_dir: Path) -> None:
        config = Configuration(max_redecompositions=0, specs_directory=str(specs_dir))
        assert config.max_redecompositions == 0

    def test_max_concurrent_tasks_zero_rejected(self, specs_dir: Path) -> None:
        with pytest.raises(ValueError, match="max_concurrent_tasks"):
            Configuration(max_concurrent_tasks=0, specs_directory=str(specs_dir))

    def test_max_concurrent_tasks_negative_rejected(self, specs_dir: Path) -> None:
        with pytest.raises(ValueError, match="max_concurrent_tasks"):
            Configuration(max_concurrent_tasks=-1, specs_directory=str(specs_dir))

    def test_max_concurrent_tasks_one_accepted(self, specs_dir: Path) -> None:
        config = Configuration(max_concurrent_tasks=1, specs_directory=str(specs_dir))
        assert config.max_concurrent_tasks == 1

    def test_cycle_interval_seconds_zero_rejected(self, specs_dir: Path) -> None:
        with pytest.raises(ValueError, match="cycle_interval_seconds"):
            Configuration(cycle_interval_seconds=0, specs_directory=str(specs_dir))

    def test_cycle_interval_seconds_negative_rejected(self, specs_dir: Path) -> None:
        with pytest.raises(ValueError, match="cycle_interval_seconds"):
            Configuration(cycle_interval_seconds=-1, specs_directory=str(specs_dir))

    def test_cycle_interval_seconds_one_accepted(self, specs_dir: Path) -> None:
        config = Configuration(cycle_interval_seconds=1, specs_directory=str(specs_dir))
        assert config.cycle_interval_seconds == 1

    def test_specs_directory_nonexistent_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="specs_directory"):
            Configuration(specs_directory=str(tmp_path / "nonexistent"))

    def test_specs_directory_existing_accepted(self, tmp_path: Path) -> None:
        specs = tmp_path / "my_specs"
        specs.mkdir()
        config = Configuration(specs_directory=str(specs))
        assert config.specs_directory == str(specs)

    def test_valid_configuration_accepted(self, specs_dir: Path) -> None:
        config = Configuration(
            convergence_bound=5,
            max_task_retries=2,
            max_redecompositions=3,
            max_concurrent_tasks=10,
            cycle_interval_seconds=60,
            specs_directory=str(specs_dir),
            implementation_model="claude-sonnet",
            verification_model="gemini-pro",
        )
        assert config.convergence_bound == 5
        assert config.max_task_retries == 2
        assert config.max_concurrent_tasks == 10
        assert config.implementation_model == "claude-sonnet"
        assert config.verification_model == "gemini-pro"


class TestExecutorConfiguration:
    def test_claude_sdk_executor_type_accepted(self, specs_dir: Path) -> None:
        config = Configuration(
            executor_type=ExecutorType.CLAUDE_SDK,
            specs_directory=str(specs_dir),
        )
        assert config.executor_type == ExecutorType.CLAUDE_SDK

    def test_ambient_executor_type_accepted_with_required_fields(
        self, specs_dir: Path
    ) -> None:
        config = Configuration(
            executor_type=ExecutorType.AMBIENT,
            repository_url="https://github.com/org/repo.git",
            project_identifier="my-project",
            specs_directory=str(specs_dir),
        )
        assert config.executor_type == ExecutorType.AMBIENT
        assert config.repository_url == "https://github.com/org/repo.git"
        assert config.project_identifier == "my-project"

    def test_ambient_without_repository_url_rejected(self, specs_dir: Path) -> None:
        with pytest.raises(ValueError, match="repository_url"):
            Configuration(
                executor_type=ExecutorType.AMBIENT,
                project_identifier="my-project",
                specs_directory=str(specs_dir),
            )

    def test_ambient_without_project_identifier_rejected(self, specs_dir: Path) -> None:
        with pytest.raises(ValueError, match="project_identifier"):
            Configuration(
                executor_type=ExecutorType.AMBIENT,
                repository_url="https://github.com/org/repo.git",
                specs_directory=str(specs_dir),
            )

    def test_ambient_without_both_fields_rejected(self, specs_dir: Path) -> None:
        with pytest.raises(ValueError, match="repository_url"):
            Configuration(
                executor_type=ExecutorType.AMBIENT,
                specs_directory=str(specs_dir),
            )

    def test_claude_sdk_ignores_ambient_fields(self, specs_dir: Path) -> None:
        config = Configuration(
            executor_type=ExecutorType.CLAUDE_SDK,
            repository_url="https://github.com/org/repo.git",
            project_identifier="my-project",
            specs_directory=str(specs_dir),
        )
        assert config.executor_type == ExecutorType.CLAUDE_SDK

    def test_unknown_executor_type_rejected(self, specs_dir: Path) -> None:
        with pytest.raises(ValueError):
            Configuration(
                executor_type="unknown",  # type: ignore[arg-type]
                specs_directory=str(specs_dir),
            )

    def test_executor_type_from_string_in_yaml(
        self, specs_dir: Path, tmp_path: Path
    ) -> None:
        config_file = tmp_path / "hyperloop.yaml"
        _write_yaml(
            config_file,
            {
                "executor_type": "claude-sdk",
                "specs_directory": str(specs_dir),
            },
        )
        config = Configuration.from_yaml(config_file)
        assert config.executor_type == ExecutorType.CLAUDE_SDK

    def test_ambient_from_yaml_with_required_fields(
        self, specs_dir: Path, tmp_path: Path
    ) -> None:
        config_file = tmp_path / "hyperloop.yaml"
        _write_yaml(
            config_file,
            {
                "executor_type": "ambient",
                "repository_url": "https://github.com/org/repo.git",
                "project_identifier": "my-project",
                "specs_directory": str(specs_dir),
            },
        )
        config = Configuration.from_yaml(config_file)
        assert config.executor_type == ExecutorType.AMBIENT
        assert config.repository_url == "https://github.com/org/repo.git"
        assert config.project_identifier == "my-project"


class TestImmutability:
    def test_cannot_modify_convergence_bound(self, specs_dir: Path) -> None:
        config = Configuration(specs_directory=str(specs_dir))
        with pytest.raises(ValueError):
            config.convergence_bound = 10  # type: ignore[misc]

    def test_cannot_modify_trunk_branch(self, specs_dir: Path) -> None:
        config = Configuration(specs_directory=str(specs_dir))
        with pytest.raises(ValueError):
            config.trunk_branch = "develop"  # type: ignore[misc]

    def test_cannot_modify_observer_adapters(self, specs_dir: Path) -> None:
        config = Configuration(specs_directory=str(specs_dir))
        with pytest.raises(ValueError):
            config.observer_adapters = [ObserverAdapter.STRUCTLOG]  # type: ignore[misc]

    def test_cannot_modify_executor_type(self, specs_dir: Path) -> None:
        config = Configuration(specs_directory=str(specs_dir))
        with pytest.raises(ValueError):
            config.executor_type = ExecutorType.AMBIENT  # type: ignore[misc]


class TestYamlLoading:
    def test_load_from_yaml_with_all_fields(self, tmp_path: Path) -> None:
        specs = tmp_path / "doc" / "specs"
        specs.mkdir(parents=True)
        config_file = tmp_path / "hyperloop.yaml"
        _write_yaml(
            config_file,
            {
                "convergence_bound": 5,
                "max_task_retries": 2,
                "max_redecompositions": 3,
                "max_concurrent_tasks": 10,
                "cycle_interval_seconds": 60,
                "implementation_model": "claude-sonnet",
                "verification_model": "gemini-pro",
                "decomposition_model": "claude-haiku",
                "specs_directory": str(specs),
                "overlay_path": ".hyperloop/overlays",
                "observer_adapters": ["structlog"],
                "plan_branch": "hyperloop/state",
                "trunk_branch": "develop",
                "branch_prefix": "hl/",
            },
        )
        config = Configuration.from_yaml(config_file)
        assert config.convergence_bound == 5
        assert config.max_task_retries == 2
        assert config.max_redecompositions == 3
        assert config.max_concurrent_tasks == 10
        assert config.cycle_interval_seconds == 60
        assert config.implementation_model == "claude-sonnet"
        assert config.verification_model == "gemini-pro"
        assert config.decomposition_model == "claude-haiku"
        assert config.specs_directory == str(specs)
        assert config.overlay_path == ".hyperloop/overlays"
        assert config.observer_adapters == ["structlog"]
        assert config.plan_branch == "hyperloop/state"
        assert config.trunk_branch == "develop"
        assert config.branch_prefix == "hl/"

    def test_missing_yaml_uses_defaults(self, tmp_path: Path) -> None:
        config = Configuration.from_yaml(tmp_path / "nonexistent.yaml")
        assert config.convergence_bound == 3
        assert config.max_task_retries == 3
        assert config.max_concurrent_tasks == 5
        assert config.specs_directory == "specs/"

    def test_partial_yaml_fills_defaults(self, specs_dir: Path, tmp_path: Path) -> None:
        config_file = tmp_path / "hyperloop.yaml"
        _write_yaml(
            config_file, {"convergence_bound": 7, "specs_directory": str(specs_dir)}
        )
        config = Configuration.from_yaml(config_file)
        assert config.convergence_bound == 7
        assert config.max_task_retries == 3
        assert config.trunk_branch == "main"

    def test_yaml_with_invalid_values_raises(
        self, specs_dir: Path, tmp_path: Path
    ) -> None:
        config_file = tmp_path / "hyperloop.yaml"
        _write_yaml(
            config_file, {"convergence_bound": 0, "specs_directory": str(specs_dir)}
        )
        with pytest.raises(ValueError, match="convergence_bound"):
            Configuration.from_yaml(config_file)


class TestModelSelection:
    def test_different_models_for_different_roles(self, specs_dir: Path) -> None:
        config = Configuration(
            specs_directory=str(specs_dir),
            implementation_model="claude-sonnet",
            verification_model="gemini-pro",
            decomposition_model="claude-haiku",
        )
        assert config.implementation_model == "claude-sonnet"
        assert config.verification_model == "gemini-pro"
        assert config.decomposition_model == "claude-haiku"

    def test_verification_can_differ_from_implementation(self, specs_dir: Path) -> None:
        config = Configuration(
            specs_directory=str(specs_dir),
            implementation_model="claude-sonnet",
            verification_model="gemini-pro",
        )
        assert config.implementation_model != config.verification_model
