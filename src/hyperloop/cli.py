"""CLI entry point — typer app with rich output formatting.

Provides ``hyperloop init`` (project scaffolding) and ``hyperloop run``
(orchestrator loop) commands.
"""

from __future__ import annotations

import sys
from importlib.metadata import version as pkg_version
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from hyperloop.config import Config, ConfigError, load_config

if TYPE_CHECKING:
    from hyperloop.compose import PromptComposer
    from hyperloop.config import ObservabilityConfig
    from hyperloop.domain.model import Process
    from hyperloop.ports.hook import CycleHook
    from hyperloop.ports.probe import OrchestratorProbe
    from hyperloop.ports.state import StateStore

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
    table.add_row("overlay", cfg.overlay or "[dim].hyperloop/agents/[/dim]")
    table.add_row("base_ref", cfg.base_ref)
    table.add_row("max_workers", str(cfg.max_workers))
    table.add_row("auto_merge", str(cfg.auto_merge))
    table.add_row("merge_strategy", cfg.merge_strategy)
    table.add_row("delete_branch", str(cfg.delete_branch))
    table.add_row("poll_interval", f"{cfg.poll_interval}s")
    table.add_row("max_task_rounds", str(cfg.max_task_rounds))
    table.add_row("max_cycles", str(cfg.max_cycles))
    table.add_row("max_action_attempts", str(cfg.max_action_attempts))
    table.add_row("runtime", cfg.runtime)

    return table


def _make_composer(
    cfg: Config, state: StateStore, repo_path: Path
) -> tuple[PromptComposer, Process | None]:
    """Construct a PromptComposer via kustomize build.

    Requires ``.hyperloop/agents/kustomization.yaml`` to exist.  If the
    configured ``overlay`` points elsewhere that is used; otherwise the
    default ``.hyperloop/agents/`` directory is used.

    Args:
        cfg: Config object with an ``overlay`` attribute.
        state: StateStore instance for reading spec files at spawn time.
        repo_path: Resolved path to the target repository.

    Returns:
        A tuple of (PromptComposer, Process | None).

    Raises:
        typer.Exit: If the kustomization directory does not exist.
    """
    from hyperloop.compose import PromptComposer, check_kustomize_available

    check_kustomize_available()

    overlay = cfg.overlay or str(repo_path / ".hyperloop" / "agents")
    kustomization = Path(overlay) / "kustomization.yaml"
    if not kustomization.is_file():
        console.print(
            "[bold red]Error:[/bold red] "
            f"{kustomization} not found.\n"
            "Run [bold]hyperloop init[/bold] to set up the project."
        )
        raise typer.Exit(code=1)

    return PromptComposer.load_from_kustomize(overlay, state)


def _build_probe(obs_cfg: ObservabilityConfig, repo_path: Path) -> OrchestratorProbe:
    """Construct an OrchestratorProbe from observability config.

    Always includes a StructlogProbe. Optionally adds a MatrixProbe if
    Matrix config is present and credentials can be resolved (explicit
    token, cached credentials, or auto-registration).
    """
    from hyperloop.adapters.probe import MultiProbe
    from hyperloop.adapters.probe.structlog import StructlogProbe
    from hyperloop.logging import configure_logging

    configure_logging(log_format=obs_cfg.log_format, log_level=obs_cfg.log_level)

    probes: list[OrchestratorProbe] = [StructlogProbe()]

    if obs_cfg.matrix is not None:
        from hyperloop.adapters.probe.matrix import MatrixProbe
        from hyperloop.adapters.probe.matrix_setup import ensure_matrix_ready

        access_token, room_id = ensure_matrix_ready(obs_cfg.matrix, repo_path)
        if access_token and room_id:
            probes.append(
                MatrixProbe(
                    homeserver=obs_cfg.matrix.homeserver,
                    room_id=room_id,
                    access_token=access_token,
                    verbose=obs_cfg.matrix.verbose,
                )
            )

    if obs_cfg.otel is not None:
        from hyperloop.adapters.probe.otel import OtelProbe

        probes.append(
            OtelProbe(
                service_name=obs_cfg.otel.service_name,
                endpoint=obs_cfg.otel.endpoint,
            )
        )

    if len(probes) == 1:
        return probes[0]
    return MultiProbe(tuple(probes))


@app.command()
def init(
    path: Path = typer.Option(
        Path.cwd(),
        help="Path to the target repo. Default: current directory.",
    ),
    base_ref: str = typer.Option(
        "",
        "--base-ref",
        help="Kustomize remote resource for the base definitions.",
    ),
    overlay: str = typer.Option(
        "",
        "--overlay",
        help="Kustomize remote resource for a project overlay (includes base).",
    ),
) -> None:
    """Scaffold the required hyperloop structure in a target repo.

    Creates ``.hyperloop/agents/kustomization.yaml`` (composition point),
    ``.hyperloop/agents/process/kustomization.yaml`` (empty Component for the
    process-improver), and ``.hyperloop.yaml`` (if absent).

    Idempotent — running again does not overwrite existing files.
    """
    from hyperloop.compose import check_kustomize_available
    from hyperloop.config import DEFAULT_BASE_REF

    check_kustomize_available()

    repo_path = path.resolve()
    if not (repo_path / ".git").exists():
        console.print(f"[bold red]Error:[/bold red] {repo_path} is not a git repository.")
        raise typer.Exit(code=1)

    resolved_base_ref = base_ref or DEFAULT_BASE_REF

    # --- .hyperloop/agents/kustomization.yaml ---
    agents_dir = repo_path / ".hyperloop" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    agents_kustomization = agents_dir / "kustomization.yaml"
    if not agents_kustomization.exists():
        resource = overlay if overlay else resolved_base_ref
        content = f"resources:\n  - {resource}\n\ncomponents:\n  - process\n"
        agents_kustomization.write_text(content)
        console.print(f"  Created {agents_kustomization.relative_to(repo_path)}")
    else:
        console.print(f"  [dim]Exists[/dim]  {agents_kustomization.relative_to(repo_path)}")

    # --- .hyperloop/agents/process/kustomization.yaml ---
    process_dir = agents_dir / "process"
    process_dir.mkdir(parents=True, exist_ok=True)

    process_kustomization = process_dir / "kustomization.yaml"
    if not process_kustomization.exists():
        process_kustomization.write_text(
            "apiVersion: kustomize.config.k8s.io/v1alpha1\nkind: Component\npatches: []\n"
        )
        console.print(f"  Created {process_kustomization.relative_to(repo_path)}")
    else:
        console.print(f"  [dim]Exists[/dim]  {process_kustomization.relative_to(repo_path)}")

    # --- .hyperloop.yaml ---
    config_file = repo_path / ".hyperloop.yaml"
    if not config_file.exists():
        config_file.write_text("overlay: .hyperloop/agents/\n")
        console.print(f"  Created {config_file.relative_to(repo_path)}")
    else:
        console.print(f"  [dim]Exists[/dim]  {config_file.relative_to(repo_path)}")

    # --- Validate ---
    import subprocess

    console.print()
    console.print("  Validating kustomize build...")
    result = subprocess.run(
        ["kustomize", "build", str(agents_dir)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        console.print(f"[bold red]Validation failed:[/bold red] {result.stderr.strip()}")
        raise typer.Exit(code=1)

    console.print("  [bold green]Done.[/bold green] kustomize build succeeded.")


@app.command()
def dashboard(
    path: Path = typer.Option(
        Path.cwd(),
        help="Path to the target repo. Default: current directory.",
    ),
    port: int = typer.Option(8787, help="Port for the dashboard server."),
) -> None:
    """Start the read-only dashboard server."""
    import uvicorn

    from dashboard.server.app import create_app

    repo_path = path.resolve()
    if not (repo_path / ".git").exists():
        console.print(f"[bold red]Error:[/bold red] {repo_path} is not a git repository.")
        raise typer.Exit(code=1)

    console.print(f"[bold green]Starting dashboard[/bold green] on http://localhost:{port}")
    console.print(f"  Repo: {repo_path}")

    dash_app = create_app(str(repo_path))
    uvicorn.run(dash_app, host="0.0.0.0", port=port, log_level="info")


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
    from hyperloop.adapters.git.state import GitStateStore
    from hyperloop.domain.model import ActionStep, AgentStep, LoopStep, Process
    from hyperloop.loop import Orchestrator

    # Default process: loop(implementer, verifier) -> merge-pr
    default_process = Process(
        name="default",
        pipeline=(
            LoopStep(
                steps=(
                    AgentStep(agent="implementer", on_pass=None, on_fail=None),
                    AgentStep(agent="verifier", on_pass=None, on_fail=None),
                )
            ),
            ActionStep(action="merge-pr"),
        ),
    )

    state = GitStateStore(repo_path)

    # Build observability probe (before runtime so it can be passed in)
    obs_cfg = getattr(cfg, "observability", None)
    if obs_cfg is not None:
        probe = _build_probe(obs_cfg, repo_path)
    else:
        from hyperloop.adapters.probe import NullProbe

        probe = NullProbe()

    # Wire FileProbe for dashboard event streaming
    if cfg.dashboard.enabled:
        import hashlib

        from hyperloop.adapters.probe import MultiProbe as _MultiProbe
        from hyperloop.adapters.probe.file import FileProbe

        repo_hash = hashlib.md5(str(repo_path).encode()).hexdigest()[:8]
        events_path = Path.home() / ".cache" / "hyperloop" / repo_hash / "events.jsonl"
        file_probe = FileProbe(events_path, max_events=cfg.dashboard.events_limit)

        # Wrap existing probe in MultiProbe with FileProbe
        if not isinstance(probe, _MultiProbe):
            probe = _MultiProbe((probe, file_probe))
        else:
            probe = _MultiProbe((*probe._probes, file_probe))

        # Write a pointer file so the dashboard knows where events are
        # Lives in the cache dir, not the repo, to avoid polluting git
        pointer_path = events_path.parent / "repo-path"
        pointer_path.write_text(str(repo_path))

    if cfg.runtime == "ambient":
        if cfg.ambient is None:
            console.print(
                "[bold red]Error:[/bold red] runtime: ambient requires"
                " an 'ambient' section in config."
            )
            raise typer.Exit(code=1)
        from hyperloop.adapters.ambient.runtime import AmbientRuntime

        runtime = AmbientRuntime(
            repo_path=str(repo_path),
            project_id=cfg.ambient.project_id,
            acpctl=cfg.ambient.acpctl,
            base_branch=cfg.base_branch,
            repo_url=cfg.ambient.repo_url,
        )
    else:
        from hyperloop.adapters.git.runtime import AgentSdkRuntime

        runtime = AgentSdkRuntime(repo_path=str(repo_path), probe=probe)

    pr_manager = None
    if cfg.repo is not None:
        from hyperloop.pr import PRManager

        pr_manager = PRManager(
            repo=cfg.repo,
            delete_branch=cfg.delete_branch,
            probe=probe,
        )
        pr_manager.ensure_gate_labels()

    # Resolve agent definitions and process via kustomize build
    composer, parsed_process = _make_composer(cfg, state, repo_path)
    process = parsed_process if parsed_process is not None else default_process

    if cfg.runtime == "ambient" and hasattr(runtime, "ensure_project"):
        runtime.ensure_project()  # type: ignore[attr-defined]

    # Build gate + action adapters from PRPort
    gate = None
    action = None
    if pr_manager is not None:
        from hyperloop.adapters.action.pr_merge import PRMergeAction
        from hyperloop.adapters.gate.label import LabelGate

        gate = LabelGate(pr_manager)
        action = PRMergeAction(
            pr_manager,
            base_branch=cfg.base_branch,
            repo_path=str(repo_path),
        )

    # Build notification adapter
    notification = None
    if cfg.notifications_type == "github-comment" and cfg.repo is not None:
        from hyperloop.adapters.notification.github_comment import GitHubCommentNotification

        notification = GitHubCommentNotification(repo=cfg.repo)

    # Build hooks
    hooks: list[CycleHook] = []
    if composer is not None:
        from hyperloop.adapters.hook.process_improver import ProcessImproverHook

        hooks.append(ProcessImproverHook(runtime, composer, probe))

    # Build spec source
    from hyperloop.adapters.git.spec_source import GitSpecSource

    spec_source = GitSpecSource(repo_path)

    orchestrator = Orchestrator(
        state=state,
        runtime=runtime,
        process=process,
        max_workers=cfg.max_workers,
        max_task_rounds=cfg.max_task_rounds,
        max_action_attempts=cfg.max_action_attempts,
        base_branch=cfg.base_branch,
        gate=gate,
        action=action,
        pr=pr_manager,
        spec_source=spec_source,
        hooks=tuple(hooks),
        notification=notification,
        composer=composer,
        poll_interval=cfg.poll_interval,
        probe=probe,
    )

    # 6. Recover and run
    with console.status("[bold green]Recovering state...[/bold green]"):
        orchestrator.recover()

    console.print("[bold green]Starting orchestrator loop[/bold green]")
    console.print()

    reason = orchestrator.run_loop(max_cycles=cfg.max_cycles)

    # 7. Final summary
    console.print()
    if "complete" in reason.lower():
        console.print(Panel(f"[bold green]{reason}[/bold green]", title="Done"))
    else:
        console.print(Panel(f"[bold red]{reason}[/bold red]", title="Halted"))
        sys.exit(1)
