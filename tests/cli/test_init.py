from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from hyperloop.cli.app import cli
from hyperloop.reconciliation.models.configuration import Configuration


def _git_init(path: Path) -> None:
    subprocess.run(
        ["git", "init", str(path)],
        check=True,
        capture_output=True,
    )


class TestInitCreatesOverlay:
    def test_creates_kustomization_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _git_init(tmp_path)
        monkeypatch.chdir(tmp_path)

        runner = CliRunner()
        result = runner.invoke(cli, ["init"])

        assert result.exit_code == 0
        kustomization = tmp_path / ".hyperloop" / "agents" / "kustomization.yaml"
        assert kustomization.is_file()

    def test_kustomization_references_base_templates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _git_init(tmp_path)
        monkeypatch.chdir(tmp_path)

        runner = CliRunner()
        result = runner.invoke(cli, ["init"])
        assert result.exit_code == 0

        kustomization = tmp_path / ".hyperloop" / "agents" / "kustomization.yaml"
        content = yaml.safe_load(kustomization.read_text())
        assert content["apiVersion"] == "kustomize.config.k8s.io/v1beta1"
        assert content["kind"] == "Kustomization"
        assert len(content["resources"]) == 1
        resource = content["resources"][0]
        assert "github.com" in resource
        assert "//base" in resource
        assert "?ref=" in resource

    def test_overlay_directory_exists_after_init(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _git_init(tmp_path)
        monkeypatch.chdir(tmp_path)

        runner = CliRunner()
        result = runner.invoke(cli, ["init"])
        assert result.exit_code == 0

        overlay = tmp_path / ".hyperloop" / "agents"
        assert overlay.is_dir()


class TestInitIdempotent:
    def test_does_not_overwrite_existing_kustomization(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _git_init(tmp_path)
        monkeypatch.chdir(tmp_path)

        overlay_dir = tmp_path / ".hyperloop" / "agents"
        overlay_dir.mkdir(parents=True)
        kustomization = overlay_dir / "kustomization.yaml"
        custom_content = "apiVersion: custom\nkind: Kustomization\n"
        kustomization.write_text(custom_content)

        runner = CliRunner()
        result = runner.invoke(cli, ["init"])

        assert result.exit_code == 0
        assert kustomization.read_text() == custom_content

    def test_exits_successfully_when_already_initialized(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _git_init(tmp_path)
        monkeypatch.chdir(tmp_path)

        overlay_dir = tmp_path / ".hyperloop" / "agents"
        overlay_dir.mkdir(parents=True)
        (overlay_dir / "kustomization.yaml").write_text("existing: true\n")

        runner = CliRunner()
        result = runner.invoke(cli, ["init"])

        assert result.exit_code == 0


class TestInitNonGitDirectory:
    def test_fails_with_non_zero_exit_code(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)

        runner = CliRunner()
        result = runner.invoke(cli, ["init"])

        assert result.exit_code != 0

    def test_error_mentions_git_repository(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)

        runner = CliRunner()
        result = runner.invoke(cli, ["init"])

        assert "git repository" in result.output.lower()


class TestInitOverlayPathValidation:
    def test_scaffolded_overlay_passes_configuration_validator(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _git_init(tmp_path)
        monkeypatch.chdir(tmp_path)

        runner = CliRunner()
        result = runner.invoke(cli, ["init"])
        assert result.exit_code == 0

        overlay = tmp_path / ".hyperloop" / "agents"
        assert overlay.is_dir()
        Configuration.overlay_path_must_exist(str(overlay))


class TestInitEdgeCases:
    def test_fails_when_hyperloop_dir_is_a_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _git_init(tmp_path)
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".hyperloop").write_text("not a directory")

        runner = CliRunner()
        result = runner.invoke(cli, ["init"])

        assert result.exit_code != 0


class TestInitRegistered:
    def test_init_appears_in_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])

        assert "init" in result.output
