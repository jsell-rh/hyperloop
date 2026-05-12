from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from hyperloop.reconciliation.models.configuration import Configuration


def _write_yaml(path: Path, data: dict[str, object]) -> None:
    path.write_text(yaml.dump(data))


class TestDefaultValues:
    def test_convergence_bound_defaults_to_3(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        specs.mkdir()
        config = Configuration(specs_directory=str(specs))
        assert config.convergence_bound == 3

    def test_max_task_retries_defaults_to_3(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        specs.mkdir()
        config = Configuration(specs_directory=str(specs))
        assert config.max_task_retries == 3

    def test_max_redecompositions_defaults_to_1(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        specs.mkdir()
        config = Configuration(specs_directory=str(specs))
        assert config.max_redecompositions == 1

    def test_max_concurrent_tasks_defaults_to_5(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        specs.mkdir()
        config = Configuration(specs_directory=str(specs))
        assert config.max_concurrent_tasks == 5

    def test_cycle_interval_seconds_defaults_to_30(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        specs.mkdir()
        config = Configuration(specs_directory=str(specs))
        assert config.cycle_interval_seconds == 30

    def test_specs_directory_defaults_to_specs(self) -> None:
        config = Configuration()
        assert config.specs_directory == "specs/"

    def test_overlay_path_defaults_to_hyperloop_agents(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        specs.mkdir()
        config = Configuration(specs_directory=str(specs))
        assert config.overlay_path == ".hyperloop/agents"

    def test_plan_branch_defaults_to_hyperloop_plan(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        specs.mkdir()
        config = Configuration(specs_directory=str(specs))
        assert config.plan_branch == "hyperloop/plan"

    def test_trunk_branch_defaults_to_main(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        specs.mkdir()
        config = Configuration(specs_directory=str(specs))
        assert config.trunk_branch == "main"

    def test_branch_prefix_defaults_to_hyperloop_slash(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        specs.mkdir()
        config = Configuration(specs_directory=str(specs))
        assert config.branch_prefix == "hyperloop/"

    def test_observer_adapters_defaults_to_empty_list(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        specs.mkdir()
        config = Configuration(specs_directory=str(specs))
        assert config.observer_adapters == []

    def test_model_fields_default_to_none(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        specs.mkdir()
        config = Configuration(specs_directory=str(specs))
        assert config.implementation_model is None
        assert config.verification_model is None
        assert config.decomposition_model is None


class TestValidation:
    def test_convergence_bound_zero_rejected(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        specs.mkdir()
        with pytest.raises(ValueError, match="convergence_bound"):
            Configuration(convergence_bound=0, specs_directory=str(specs))

    def test_convergence_bound_negative_rejected(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        specs.mkdir()
        with pytest.raises(ValueError, match="convergence_bound"):
            Configuration(convergence_bound=-1, specs_directory=str(specs))

    def test_convergence_bound_one_accepted(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        specs.mkdir()
        config = Configuration(convergence_bound=1, specs_directory=str(specs))
        assert config.convergence_bound == 1

    def test_max_task_retries_negative_rejected(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        specs.mkdir()
        with pytest.raises(ValueError, match="max_task_retries"):
            Configuration(max_task_retries=-1, specs_directory=str(specs))

    def test_max_task_retries_zero_accepted(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        specs.mkdir()
        config = Configuration(max_task_retries=0, specs_directory=str(specs))
        assert config.max_task_retries == 0

    def test_max_redecompositions_negative_rejected(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        specs.mkdir()
        with pytest.raises(ValueError, match="max_redecompositions"):
            Configuration(max_redecompositions=-1, specs_directory=str(specs))

    def test_max_redecompositions_zero_accepted(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        specs.mkdir()
        config = Configuration(max_redecompositions=0, specs_directory=str(specs))
        assert config.max_redecompositions == 0

    def test_max_concurrent_tasks_zero_rejected(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        specs.mkdir()
        with pytest.raises(ValueError, match="max_concurrent_tasks"):
            Configuration(max_concurrent_tasks=0, specs_directory=str(specs))

    def test_max_concurrent_tasks_negative_rejected(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        specs.mkdir()
        with pytest.raises(ValueError, match="max_concurrent_tasks"):
            Configuration(max_concurrent_tasks=-1, specs_directory=str(specs))

    def test_cycle_interval_seconds_zero_rejected(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        specs.mkdir()
        with pytest.raises(ValueError, match="cycle_interval_seconds"):
            Configuration(cycle_interval_seconds=0, specs_directory=str(specs))

    def test_cycle_interval_seconds_negative_rejected(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        specs.mkdir()
        with pytest.raises(ValueError, match="cycle_interval_seconds"):
            Configuration(cycle_interval_seconds=-1, specs_directory=str(specs))

    def test_specs_directory_nonexistent_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="specs_directory"):
            Configuration(specs_directory=str(tmp_path / "nonexistent"))

    def test_specs_directory_existing_accepted(self, tmp_path: Path) -> None:
        specs = tmp_path / "my_specs"
        specs.mkdir()
        config = Configuration(specs_directory=str(specs))
        assert config.specs_directory == str(specs)

    def test_valid_configuration_accepted(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        specs.mkdir()
        config = Configuration(
            convergence_bound=5,
            max_task_retries=2,
            max_redecompositions=3,
            max_concurrent_tasks=10,
            cycle_interval_seconds=60,
            specs_directory=str(specs),
            implementation_model="claude-sonnet",
            verification_model="gemini-pro",
        )
        assert config.convergence_bound == 5
        assert config.max_task_retries == 2
        assert config.max_concurrent_tasks == 10
        assert config.implementation_model == "claude-sonnet"
        assert config.verification_model == "gemini-pro"


class TestImmutability:
    def test_cannot_modify_convergence_bound(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        specs.mkdir()
        config = Configuration(specs_directory=str(specs))
        with pytest.raises(ValueError):
            config.convergence_bound = 10  # type: ignore[misc]

    def test_cannot_modify_trunk_branch(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        specs.mkdir()
        config = Configuration(specs_directory=str(specs))
        with pytest.raises(ValueError):
            config.trunk_branch = "develop"  # type: ignore[misc]

    def test_cannot_modify_observer_adapters(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        specs.mkdir()
        config = Configuration(specs_directory=str(specs))
        with pytest.raises(ValueError):
            config.observer_adapters = ["structlog"]  # type: ignore[misc]


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

    def test_partial_yaml_fills_defaults(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        specs.mkdir()
        config_file = tmp_path / "hyperloop.yaml"
        _write_yaml(config_file, {"convergence_bound": 7, "specs_directory": str(specs)})
        config = Configuration.from_yaml(config_file)
        assert config.convergence_bound == 7
        assert config.max_task_retries == 3
        assert config.trunk_branch == "main"

    def test_yaml_with_invalid_values_raises(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        specs.mkdir()
        config_file = tmp_path / "hyperloop.yaml"
        _write_yaml(config_file, {"convergence_bound": 0, "specs_directory": str(specs)})
        with pytest.raises(ValueError, match="convergence_bound"):
            Configuration.from_yaml(config_file)


class TestModelSelection:
    def test_different_models_for_different_roles(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        specs.mkdir()
        config = Configuration(
            specs_directory=str(specs),
            implementation_model="claude-sonnet",
            verification_model="gemini-pro",
            decomposition_model="claude-haiku",
        )
        assert config.implementation_model == "claude-sonnet"
        assert config.verification_model == "gemini-pro"
        assert config.decomposition_model == "claude-haiku"

    def test_verification_can_differ_from_implementation(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        specs.mkdir()
        config = Configuration(
            specs_directory=str(specs),
            implementation_model="claude-sonnet",
            verification_model="gemini-pro",
        )
        assert config.implementation_model != config.verification_model
