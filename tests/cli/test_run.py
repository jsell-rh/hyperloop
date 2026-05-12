from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from hyperloop.cli.app import cli


class FakeReconciler:
    def __init__(self) -> None:
        self.started = False

    def run(self) -> None:
        self.started = True


class TestRunCommand:
    def test_run_starts_reconciler(self) -> None:
        reconciler = FakeReconciler()
        runner = CliRunner()
        result = runner.invoke(cli, ["run"], obj=reconciler)
        assert result.exit_code == 0
        assert reconciler.started is True

    def test_run_with_config_flag(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".hyperloop.yaml"
        config_file.write_text("convergence_bound: 5\n")
        reconciler = FakeReconciler()
        runner = CliRunner()
        result = runner.invoke(
            cli, ["run", "--config", str(config_file)], obj=reconciler
        )
        assert result.exit_code == 0
