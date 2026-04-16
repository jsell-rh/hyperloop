"""Tests for config loading — TDD, written before implementation."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from hyperloop.config import ConfigError, load_config

if TYPE_CHECKING:
    from pathlib import Path


class TestLoadConfigFromFile:
    """Load a complete .hyperloop.yaml file."""

    def test_loads_all_fields(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".hyperloop.yaml"
        config_file.write_text(
            """\
overlay: .hyperloop/agents/

target:
  repo: acme/widgets
  base_branch: develop
runtime:
  default: local
  max_workers: 4

merge:
  auto_merge: false
  strategy: merge
  delete_branch: false

poll_interval: 60
max_task_rounds: 100
max_rebase_attempts: 5
"""
        )

        cfg = load_config(config_file)

        assert cfg.repo == "acme/widgets"
        assert cfg.base_branch == "develop"
        assert cfg.overlay == ".hyperloop/agents/"
        assert cfg.max_workers == 4
        assert cfg.auto_merge is False
        assert cfg.merge_strategy == "merge"
        assert cfg.delete_branch is False
        assert cfg.poll_interval == 60
        assert cfg.max_task_rounds == 100
        assert cfg.max_rebase_attempts == 5


class TestLoadConfigDefaults:
    """Load config with no file — all defaults."""

    def test_all_defaults_when_no_file(self) -> None:
        cfg = load_config(None)

        assert cfg.repo is None
        assert cfg.base_branch == "main"
        assert cfg.overlay is None
        assert cfg.max_workers == 6
        assert cfg.auto_merge is True
        assert cfg.merge_strategy == "squash"
        assert cfg.delete_branch is True
        assert cfg.poll_interval == 30
        assert cfg.max_task_rounds == 50
        assert cfg.max_cycles == 200
        assert cfg.max_rebase_attempts == 3

    def test_all_defaults_when_file_not_found(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "nope.yaml"
        cfg = load_config(nonexistent)

        assert cfg.repo is None
        assert cfg.base_branch == "main"
        assert cfg.max_workers == 6


class TestLoadConfigPartial:
    """Load config with some fields set, others defaulted."""

    def test_partial_target_section(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".hyperloop.yaml"
        config_file.write_text(
            """\
target:
  base_branch: develop
"""
        )

        cfg = load_config(config_file)

        assert cfg.base_branch == "develop"
        assert cfg.repo is None
        assert cfg.max_workers == 6
        assert cfg.auto_merge is True

    def test_partial_merge_section(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".hyperloop.yaml"
        config_file.write_text(
            """\
merge:
  auto_merge: false
"""
        )

        cfg = load_config(config_file)

        assert cfg.auto_merge is False
        assert cfg.merge_strategy == "squash"
        assert cfg.delete_branch is True

    def test_partial_runtime_section(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".hyperloop.yaml"
        config_file.write_text(
            """\
runtime:
  max_workers: 2
"""
        )

        cfg = load_config(config_file)

        assert cfg.max_workers == 2

    def test_overlay_only(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".hyperloop.yaml"
        config_file.write_text("overlay: git@github.com:org/gitops//overlays/api\n")

        cfg = load_config(config_file)

        assert cfg.overlay == "git@github.com:org/gitops//overlays/api"
        assert cfg.base_branch == "main"

    def test_top_level_fields_only(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".hyperloop.yaml"
        config_file.write_text(
            """\
poll_interval: 45
max_task_rounds: 20
max_rebase_attempts: 1
"""
        )

        cfg = load_config(config_file)

        assert cfg.poll_interval == 45
        assert cfg.max_task_rounds == 20
        assert cfg.max_rebase_attempts == 1


class TestLoadConfigCliOverrides:
    """Override specific fields from CLI arguments."""

    def test_override_repo(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".hyperloop.yaml"
        config_file.write_text(
            """\
target:
  repo: acme/widgets
"""
        )

        cfg = load_config(config_file, repo="other/repo")

        assert cfg.repo == "other/repo"

    def test_override_base_branch(self, tmp_path: Path) -> None:
        cfg = load_config(None, base_branch="develop")

        assert cfg.base_branch == "develop"

    def test_override_max_workers(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".hyperloop.yaml"
        config_file.write_text(
            """\
runtime:
  max_workers: 8
"""
        )

        cfg = load_config(config_file, max_workers=2)

        assert cfg.max_workers == 2

    def test_override_none_does_not_replace(self, tmp_path: Path) -> None:
        """CLI args that are None should not override file values."""
        config_file = tmp_path / ".hyperloop.yaml"
        config_file.write_text(
            """\
target:
  repo: acme/widgets
"""
        )

        cfg = load_config(config_file, repo=None)

        assert cfg.repo == "acme/widgets"


class TestLoadConfigErrors:
    """Invalid YAML or config raises useful errors."""

    def test_invalid_yaml_raises_config_error(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".hyperloop.yaml"
        config_file.write_text("invalid: yaml: {{{bad")

        with pytest.raises(ConfigError, match="Failed to parse"):
            load_config(config_file)

    def test_non_dict_yaml_raises_config_error(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".hyperloop.yaml"
        config_file.write_text("- a list\n- not a mapping\n")

        with pytest.raises(ConfigError, match="must be a YAML mapping"):
            load_config(config_file)


class TestRuntimeConfig:
    """Runtime type selection and ambient configuration."""

    def test_default_runtime_is_local(self) -> None:
        cfg = load_config(None)

        assert cfg.runtime == "local"
        assert cfg.ambient is None

    def test_runtime_ambient_with_ambient_section(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".hyperloop.yaml"
        config_file.write_text(
            """\
runtime: ambient

ambient:
  project_id: my-project
  acpctl: /usr/bin/acpctl
"""
        )

        cfg = load_config(config_file)

        assert cfg.runtime == "ambient"
        assert cfg.ambient is not None
        assert cfg.ambient.project_id == "my-project"
        assert cfg.ambient.acpctl == "/usr/bin/acpctl"

    def test_runtime_ambient_acpctl_defaults_to_acpctl(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".hyperloop.yaml"
        config_file.write_text(
            """\
runtime: ambient

ambient:
  project_id: my-project
"""
        )

        cfg = load_config(config_file)

        assert cfg.ambient is not None
        assert cfg.ambient.acpctl == "acpctl"

    def test_missing_ambient_section_when_runtime_ambient(self, tmp_path: Path) -> None:
        """Config loading succeeds; validation happens at CLI level."""
        config_file = tmp_path / ".hyperloop.yaml"
        config_file.write_text("runtime: ambient\n")

        cfg = load_config(config_file)

        assert cfg.runtime == "ambient"
        assert cfg.ambient is None

    def test_old_format_runtime_dict_still_works(self, tmp_path: Path) -> None:
        """Backwards compat: runtime as dict extracts max_workers."""
        config_file = tmp_path / ".hyperloop.yaml"
        config_file.write_text(
            """\
runtime:
  max_workers: 4
"""
        )

        cfg = load_config(config_file)

        assert cfg.runtime == "local"
        assert cfg.max_workers == 4

    def test_top_level_max_workers(self, tmp_path: Path) -> None:
        """New format: max_workers as top-level key."""
        config_file = tmp_path / ".hyperloop.yaml"
        config_file.write_text(
            """\
runtime: ambient
max_workers: 3

ambient:
  project_id: proj
"""
        )

        cfg = load_config(config_file)

        assert cfg.runtime == "ambient"
        assert cfg.max_workers == 3


class TestConfigFrozen:
    """Config should be immutable."""

    def test_frozen(self) -> None:
        cfg = load_config(None)

        with pytest.raises(AttributeError):
            cfg.repo = "nope"  # type: ignore[misc]
