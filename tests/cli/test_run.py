from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from hyperloop.cli.app import cli
from hyperloop.reconciliation.reconciler import Reconciler


class FakeReconciler(Reconciler):
    def __init__(self) -> None:
        self.started = False

    def run(self) -> None:
        self.started = True

    def stop(self) -> None:
        pass


class TestRunCommand:
    def test_run_starts_injected_reconciler(self) -> None:
        reconciler = FakeReconciler()
        runner = CliRunner()
        result = runner.invoke(cli, ["run"], obj=reconciler)
        assert result.exit_code == 0
        assert reconciler.started is True

    def test_run_without_reconciler_requires_executor(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["run"], obj=object())
        assert result.exit_code != 0
        assert "agent executor" in result.output.lower()

    def test_run_fails_on_invalid_config(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".hyperloop.yaml"
        config_file.write_text("convergence_bound: -1\n")
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--config", str(config_file)], obj=object())
        assert result.exit_code != 0
        assert "convergence_bound" in result.output.lower()

    def test_run_with_valid_config_still_requires_executor(
        self, tmp_path: Path
    ) -> None:
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        config_file = tmp_path / ".hyperloop.yaml"
        config_file.write_text(f"specs_directory: '{specs_dir}'\n")
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--config", str(config_file)], obj=object())
        assert result.exit_code != 0
        assert "agent executor" in result.output.lower()
