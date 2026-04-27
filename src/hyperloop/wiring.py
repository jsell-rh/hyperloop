"""Wiring -- config to object graph.

Constructs the full Orchestrator from a Config, state store, and runtime.
Extracted from cli.py so it can be reused in tests and alternative entry points.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hyperloop.adapters.git.state import GitStateStore
from hyperloop.adapters.probe import NullProbe
from hyperloop.domain.model import PhaseStep, Process
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
    phases={
        "implement": PhaseStep(run="agent implementer", on_pass="verify", on_fail="implement"),
        "verify": PhaseStep(run="agent verifier", on_pass="merge", on_fail="implement"),
        "merge": PhaseStep(run="action merge", on_pass="done", on_fail="implement"),
    },
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
        composer: Optional PromptComposer (if None, built from kustomize overlay).
        process: Optional Process override. If None, uses kustomize-parsed or default.

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
            base_branch=cfg.base_branch,
            probe=resolved_probe,
        )

    # Build composer from kustomize if not provided
    resolved_composer = composer
    parsed_process: Process | None = None
    if resolved_composer is None:
        from pathlib import Path as _Path

        from hyperloop.compose import PromptComposer as _PromptComposer

        overlay = cfg.overlay or str(repo_path / ".hyperloop" / "agents")
        kustomization = _Path(overlay) / "kustomization.yaml"
        if kustomization.is_file():
            resolved_composer, parsed_process = _PromptComposer.load_from_kustomize(overlay, state)

    # Resolve process: explicit > kustomize-parsed > default
    resolved_process = process or parsed_process or DEFAULT_PROCESS

    # Build StepExecutor, SignalPort, ChannelPort
    step_executor = None
    signal_port = None
    channel = None

    if pr_manager is not None:
        from hyperloop.adapters.signal.label import LabelSignal
        from hyperloop.adapters.step_executor.composite import CompositeStepExecutor
        from hyperloop.adapters.step_executor.pr_actions import MarkReadyStep, PostCommentStep
        from hyperloop.adapters.step_executor.pr_merge import PRMergeStep

        assert cfg.repo is not None
        step_executor = CompositeStepExecutor(
            merge=PRMergeStep(
                pr_manager,
                base_branch=cfg.base_branch,
                repo_path=str(repo_path),
            ),
            mark_ready=MarkReadyStep(pr_manager),
            post_comment=PostCommentStep(repo=cfg.repo),
        )
        signal_port = LabelSignal(pr_manager)

    if cfg.notifications_type == "github-comment" and cfg.repo is not None:
        from hyperloop.adapters.channel.github_comment import GitHubCommentChannel

        channel = GitHubCommentChannel(repo=cfg.repo)

    # Build spec source
    from hyperloop.adapters.git.spec_source import GitSpecSource

    spec_source = GitSpecSource(repo_path)

    # Build hooks
    hooks: list[CycleHook] = []
    if resolved_composer is not None:
        from hyperloop.adapters.hook.process_improver import ProcessImproverHook

        hooks.append(ProcessImproverHook(runtime, resolved_composer, resolved_probe))

    return Orchestrator(
        state=state,
        runtime=runtime,
        process=resolved_process,
        max_workers=cfg.max_workers,
        max_task_rounds=cfg.max_task_rounds,
        max_action_attempts=cfg.max_action_attempts,
        base_branch=cfg.base_branch,
        step_executor=step_executor,
        signal_port=signal_port,
        channel=channel,
        pr=pr_manager,
        spec_source=spec_source,
        hooks=hooks,
        composer=resolved_composer,
        poll_interval=cfg.poll_interval,
        probe=resolved_probe,
        max_auditors=cfg.max_auditors,
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
            probe=probe,
        )

    from hyperloop.adapters.git.runtime import AgentSdkRuntime

    return AgentSdkRuntime(repo_path=str(repo_path), probe=probe)
