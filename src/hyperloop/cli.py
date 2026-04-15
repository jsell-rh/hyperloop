"""CLI entry point — typer app with rich output formatting.

Provides the ``hyperloop run`` command that loads config, constructs
the orchestrator, and runs the loop with rich status output.
"""

from __future__ import annotations

import sys
from importlib.metadata import version as pkg_version
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from hyperloop.config import Config, ConfigError, load_config

app = typer.Typer(
    name="hyperloop",
    no_args_is_help=True,
)
console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"hyperloop {pkg_version('hyperloop')}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """AI agent orchestrator for composable process pipelines."""


def _config_table(cfg: Config) -> Table:
    """Build a rich table showing the current configuration."""
    table = Table(title="Configuration", show_header=True, header_style="bold cyan")
    table.add_column("Setting", style="bold")
    table.add_column("Value")

    table.add_row("repo", str(cfg.repo) if cfg.repo else "[dim]not set (will infer from git)[/dim]")
    table.add_row("base_branch", cfg.base_branch)
    table.add_row("specs_dir", cfg.specs_dir)
    table.add_row("overlay", cfg.overlay or "[dim]none[/dim]")
    table.add_row("runtime", cfg.runtime)
    table.add_row("max_workers", str(cfg.max_workers))
    table.add_row("auto_merge", str(cfg.auto_merge))
    table.add_row("merge_strategy", cfg.merge_strategy)
    table.add_row("delete_branch", str(cfg.delete_branch))
    table.add_row("poll_interval", f"{cfg.poll_interval}s")
    table.add_row("max_rounds", str(cfg.max_rounds))
    table.add_row("max_rebase_attempts", str(cfg.max_rebase_attempts))

    return table


def _make_composer(state: object) -> object | None:
    """Construct a PromptComposer using the base/ directory.

    Tries two locations:
    1. Development: relative to this file (src/hyperloop/../../base)
    2. Installed package: via importlib.resources

    Returns None if base/ directory cannot be found.
    """
    from hyperloop.compose import PromptComposer

    # Development path: relative to this source file
    dev_base = Path(__file__).resolve().parent.parent.parent / "base"
    if dev_base.is_dir():
        return PromptComposer(base_dir=dev_base, state=state)  # type: ignore[arg-type]

    # Installed package: try importlib.resources
    try:
        import importlib.resources as pkg_resources

        ref = pkg_resources.files("hyperloop").joinpath("../../base")
        base_path = Path(str(ref))
        if base_path.is_dir():
            return PromptComposer(base_dir=base_path, state=state)  # type: ignore[arg-type]
    except (ImportError, TypeError, FileNotFoundError):
        pass

    console.print("[dim]Warning: base/ directory not found — prompts will be empty.[/dim]")
    return None


@app.command()
def run(
    path: Path = typer.Option(
        Path.cwd(),
        help="Path to the target repo. Default: current directory.",
    ),
    repo: str | None = typer.Option(
        None,
        help="GitHub repo (owner/repo). Inferred from git remote if not set.",
    ),
    branch: str | None = typer.Option(
        None,
        help="Base branch. Default: from config or 'main'.",
    ),
    config_file: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Config file path. Default: .hyperloop.yaml in the target repo.",
    ),
    max_workers: int | None = typer.Option(
        None,
        help="Max parallel workers.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be done without executing.",
    ),
) -> None:
    """Run the orchestrator loop."""
    # 1. Load config (file + CLI overrides)
    repo_path = path.resolve()
    config_path = config_file or (repo_path / ".hyperloop.yaml")
    try:
        cfg = load_config(
            config_path,
            repo=repo,
            base_branch=branch,
            max_workers=max_workers,
        )
    except ConfigError as exc:
        console.print(f"[bold red]Config error:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc

    # 2. Show config
    console.print()
    console.print(
        Panel(
            "[bold]hyperloop[/bold]",
            subtitle="AI agent orchestrator",
            style="blue",
        )
    )
    table = _config_table(cfg)
    table.add_row("path", str(repo_path))
    console.print(table)
    console.print()

    # 3. Dry run — show config and exit
    if dry_run:
        console.print("[bold yellow]Dry run[/bold yellow] -- exiting without executing.")
        return

    # 4. Validate repo path exists and is a git repo
    if not (repo_path / ".git").exists():
        console.print(f"[bold red]Error:[/bold red] {repo_path} is not a git repository.")
        raise typer.Exit(code=1)

    if cfg.repo is None:
        console.print(
            "[dim]No --repo set. PR operations (draft, merge, gate) will be skipped.[/dim]"
        )

    # 5. Construct runtime and state store, run loop
    from hyperloop.adapters.git_state import GitStateStore
    from hyperloop.adapters.local import LocalRuntime
    from hyperloop.domain.model import ActionStep, LoopStep, Process, RoleStep
    from hyperloop.loop import Orchestrator

    # Default process: loop(implementer, verifier) -> merge-pr
    default_process = Process(
        name="default",
        intake=(),
        pipeline=(
            LoopStep(
                steps=(
                    RoleStep(role="implementer", on_pass=None, on_fail=None),
                    RoleStep(role="verifier", on_pass=None, on_fail=None),
                )
            ),
            ActionStep(action="merge-pr"),
        ),
    )

    state = GitStateStore(repo_path, specs_dir=cfg.specs_dir)
    runtime = LocalRuntime(repo_path=str(repo_path))

    # Resolve base/ directory for agent prompt definitions
    composer = _make_composer(state)

    def _on_cycle(summary: dict[str, object]) -> None:
        """Print a rich status line after each orchestrator cycle."""
        cycle = summary.get("cycle", "?")
        tasks = summary.get("tasks", {})
        workers = summary.get("workers", 0)
        halt = summary.get("halt_reason")

        if isinstance(tasks, dict):
            total = tasks.get("total", 0)
            done = tasks.get("complete", 0)
            in_prog = tasks.get("in_progress", 0)
            failed = tasks.get("failed", 0)
            task_str = (
                f"[dim]{total} total[/dim]  "
                f"[green]{done} done[/green]  "
                f"[yellow]{in_prog} active[/yellow]  "
                f"[red]{failed} failed[/red]"
            )
        else:
            task_str = "[dim]unknown[/dim]"

        status = f"[bold]cycle {cycle}[/bold]  tasks: {task_str}  workers: {workers}"
        if halt:
            status += f"  [bold]{halt}[/bold]"
        console.print(status)

    orchestrator = Orchestrator(
        state=state,
        runtime=runtime,
        process=default_process,
        max_workers=cfg.max_workers,
        max_rounds=cfg.max_rounds,
        composer=composer,
        poll_interval=cfg.poll_interval,
        on_cycle=_on_cycle,
    )

    # 6. Recover and run
    with console.status("[bold green]Recovering state...[/bold green]"):
        orchestrator.recover()

    console.print("[bold green]Starting orchestrator loop[/bold green]")
    console.print()

    reason = orchestrator.run_loop()

    # 7. Final summary
    console.print()
    if "complete" in reason.lower():
        console.print(Panel(f"[bold green]{reason}[/bold green]", title="Done"))
    else:
        console.print(Panel(f"[bold red]{reason}[/bold red]", title="Halted"))
        sys.exit(1)
