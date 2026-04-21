"""Wiring -- config to object graph.

Constructs the full Orchestrator from a Config, state store, and runtime.
Extracted from cli.py so it can be reused in tests and alternative entry points.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hyperloop.adapters.git.state import GitStateStore
from hyperloop.adapters.probe import NullProbe
from hyperloop.domain.model import ActionStep, AgentStep, LoopStep, Process
from hyperloop.loop import Orchestrator

if TYPE_CHECKING:
    from pathlib import Path

    from hyperloop.compose import PromptComposer
    from hyperloop.config import Config
    from hyperloop.ports.hook import CycleHook
    from hyperloop.ports.probe import OrchestratorProbe
    from hyperloop.ports.runtime import Runtime

DEFAULT_PROCESS = Process(
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


def wire_orchestrator(
    cfg: Config,
    repo_path: Path,
    *,
    probe: OrchestratorProbe | None = None,
    composer: PromptComposer | None = None,
    process: Process | None = None,
) -> Orchestrator:
    """Build a fully wired Orchestrator from a Config.

    Args:
        cfg: Typed Config from load_config().
        repo_path: Resolved path to the target repository.
        probe: Optional probe (if None, NullProbe is used).
        composer: Optional PromptComposer (if None, prompt composition is skipped).
        process: Optional Process override. If None, uses the default process.

    Returns:
        A fully constructed Orchestrator, ready for recover() + run_loop().
    """
    resolved_probe = probe or NullProbe()
    state = GitStateStore(repo_path)

    # Build runtime
    runtime = _build_runtime(cfg, repo_path, resolved_probe)

    # Build PR manager
    pr_manager = None
    if cfg.repo is not None:
        from hyperloop.pr import PRManager

        pr_manager = PRManager(
            repo=cfg.repo,
            delete_branch=cfg.delete_branch,
        )

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
    if cfg.notifications_type == "github-comment":
        # GitHubCommentNotification not yet implemented; fall back to null
        pass

    # Build hooks
    hooks: list[CycleHook] = []
    if composer is not None:
        from hyperloop.adapters.hook.process_improver import ProcessImproverHook

        hooks.append(ProcessImproverHook(runtime, composer, resolved_probe))

    resolved_process = process or DEFAULT_PROCESS

    return Orchestrator(
        state=state,
        runtime=runtime,
        process=resolved_process,
        max_workers=cfg.max_workers,
        max_task_rounds=cfg.max_task_rounds,
        max_action_attempts=cfg.max_action_attempts,
        gate=gate,
        action=action,
        pr=pr_manager,
        hooks=tuple(hooks),
        notification=notification,
        composer=composer,
        poll_interval=cfg.poll_interval,
        probe=resolved_probe,
    )


def _build_runtime(cfg: Config, repo_path: Path, probe: OrchestratorProbe) -> Runtime:
    """Construct the appropriate runtime from config."""
    if cfg.runtime == "ambient":
        if cfg.ambient is None:
            msg = "runtime: ambient requires an 'ambient' section in config"
            raise ValueError(msg)
        from hyperloop.adapters.ambient.runtime import AmbientRuntime

        return AmbientRuntime(
            repo_path=str(repo_path),
            project_id=cfg.ambient.project_id,
            acpctl=cfg.ambient.acpctl,
            base_branch=cfg.base_branch,
            repo_url=cfg.ambient.repo_url,
        )

    from hyperloop.adapters.git.runtime import AgentSdkRuntime

    return AgentSdkRuntime(repo_path=str(repo_path), probe=probe)
