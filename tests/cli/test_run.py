from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import structlog
import pytest
from click.testing import CliRunner

from hyperloop.cli.app import cli
from hyperloop.reconciliation.adapters.structlog_observer import StructlogObserver
from hyperloop.reconciliation.models.configuration import DEFAULT_CONFIG_FILENAME
from hyperloop.reconciliation.models.halt_reason import HaltReason
from hyperloop.reconciliation.ports.observer import Observer
from hyperloop.reconciliation.reconciler import Reconciler


class FakeReconciler(Reconciler):
    def __init__(self) -> None:
        self.started = False

    def run(self) -> None:
        self.started = True

    def stop(self) -> None:
        pass


class FakeStreamingReconciler(Reconciler):
    def __init__(self, observer: Observer) -> None:
        self._observer = observer

    def run(self) -> None:
        self._observer.reconciler_started(spec_count=2, cycle=0)
        self._observer.cycle_started(cycle=1, specs_out_of_sync=1, tasks_in_progress=0)
        self._observer.reconciler_halted(reason=HaltReason.SHUTDOWN, total_cycles=1)

    def stop(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _reset_structlog() -> Iterator[None]:
    yield
    structlog.reset_defaults()


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
        config_file = tmp_path / DEFAULT_CONFIG_FILENAME
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
        config_file = tmp_path / DEFAULT_CONFIG_FILENAME
        config_file.write_text(f"specs_directory: '{specs_dir}'\n")
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--config", str(config_file)], obj=object())
        assert result.exit_code != 0
        assert "agent executor" in result.output.lower()


class TestRunStreamsEvents:
    def test_probe_events_appear_on_stdout(self) -> None:
        reconciler = FakeStreamingReconciler(StructlogObserver())
        runner = CliRunner()
        result = runner.invoke(cli, ["run"], obj=reconciler)

        assert result.exit_code == 0
        assert "reconciler_started" in result.output
        assert "reconciler_halted" in result.output

    def test_events_are_valid_json_lines(self) -> None:
        reconciler = FakeStreamingReconciler(StructlogObserver())
        runner = CliRunner()
        result = runner.invoke(cli, ["run"], obj=reconciler)

        lines = [line for line in result.output.strip().split("\n") if line.strip()]
        assert len(lines) >= 3

        for line in lines:
            parsed = json.loads(line)
            assert "event" in parsed

    def test_event_lines_contain_parameters(self) -> None:
        reconciler = FakeStreamingReconciler(StructlogObserver())
        runner = CliRunner()
        result = runner.invoke(cli, ["run"], obj=reconciler)

        lines = [line for line in result.output.strip().split("\n") if line.strip()]
        events = [json.loads(line) for line in lines]

        started = next(e for e in events if e["event"] == "reconciler_started")
        assert started["spec_count"] == 2
        assert started["cycle"] == 0

        halted = next(e for e in events if e["event"] == "reconciler_halted")
        assert halted["reason"] == HaltReason.SHUTDOWN
        assert halted["total_cycles"] == 1

    def test_events_include_log_level(self) -> None:
        reconciler = FakeStreamingReconciler(StructlogObserver())
        runner = CliRunner()
        result = runner.invoke(cli, ["run"], obj=reconciler)

        lines = [line for line in result.output.strip().split("\n") if line.strip()]
        events = [json.loads(line) for line in lines]

        started = next(e for e in events if e["event"] == "reconciler_started")
        assert started["level"] == "info"

    def test_events_include_timestamp(self) -> None:
        reconciler = FakeStreamingReconciler(StructlogObserver())
        runner = CliRunner()
        result = runner.invoke(cli, ["run"], obj=reconciler)

        lines = [line for line in result.output.strip().split("\n") if line.strip()]
        events = [json.loads(line) for line in lines]

        for event in events:
            assert "timestamp" in event
