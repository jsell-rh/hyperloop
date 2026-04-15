"""CLI entry point — typer app with rich output formatting.

Provides the ``k-orchestrate run`` command that loads config, constructs
the orchestrator, and runs the loop with rich status output.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from k_orchestrate.config import Config, ConfigError, load_config

app = typer.Typer(
    name="k-orchestrate",
    no_args_is_help=True,
)
console = Console()


@app.callback()
def main() -> None:
    """AI agent orchestrator for composable workflow pipelines."""


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


@app.command()
def run(
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
        help="Config file path. Default: .k-orchestrate.yaml",
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
    config_path = config_file or Path(".k-orchestrate.yaml")
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
            "[bold]k-orchestrate[/bold]",
            subtitle="AI agent orchestrator",
            style="blue",
        )
    )
    console.print(_config_table(cfg))
    console.print()

    # 3. Dry run — show config and exit
    if dry_run:
        console.print("[bold yellow]Dry run[/bold yellow] -- exiting without executing.")
        return

    # 4. Validate repo is set (required for actual run)
    if cfg.repo is None:
        console.print(
            "[bold red]Error:[/bold red] No repo specified. "
            "Use --repo owner/repo or set target.repo in .k-orchestrate.yaml"
        )
        raise typer.Exit(code=1)

    # 5. Construct runtime and state store, run loop
    from k_orchestrate.adapters.git_state import GitStateStore
    from k_orchestrate.adapters.local import LocalRuntime
    from k_orchestrate.domain.model import ActionStep, LoopStep, RoleStep, Workflow
    from k_orchestrate.loop import Orchestrator

    # Default workflow: loop(implementer, verifier) -> merge-pr
    default_workflow = Workflow(
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

    repo_path = Path.cwd()
    state = GitStateStore(repo_path, specs_dir=cfg.specs_dir)
    runtime = LocalRuntime(repo_path=str(repo_path))

    orchestrator = Orchestrator(
        state=state,
        runtime=runtime,
        workflow=default_workflow,
        max_workers=cfg.max_workers,
        max_rounds=cfg.max_rounds,
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
