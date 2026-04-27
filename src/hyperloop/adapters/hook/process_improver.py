"""ProcessImproverHook -- runs the process-improver agent after failed results."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import structlog

from hyperloop.domain.model import ImprovementContext, Verdict

if TYPE_CHECKING:
    from hyperloop.compose import PromptComposer
    from hyperloop.domain.model import WorkerResult
    from hyperloop.ports.probe import OrchestratorProbe
    from hyperloop.ports.runtime import Runtime

logger = structlog.get_logger()


class ProcessImproverHook:
    """CycleHook adapter that runs the process-improver on failed results."""

    def __init__(
        self,
        runtime: Runtime,
        composer: PromptComposer,
        probe: OrchestratorProbe,
    ) -> None:
        self._runtime = runtime
        self._composer = composer
        self._probe = probe

    def after_reap(self, *, results: dict[str, WorkerResult], cycle: int) -> None:
        """Run process-improver if any results failed this cycle."""
        findings_text = self._collect_findings(results)
        if not findings_text:
            return

        context = ImprovementContext(findings=findings_text)
        composed = self._composer.compose(role="process-improver", context=context)
        prompt = composed.text

        failed_ids = tuple(task_id for task_id, r in results.items() if r.verdict == Verdict.FAIL)

        start = time.monotonic()
        result = self._runtime.run_trunk_agent("process-improver", prompt)
        success = result.verdict == Verdict.PASS
        self._probe.process_improver_ran(
            failed_task_ids=failed_ids,
            success=success,
            cycle=cycle,
            duration_s=time.monotonic() - start,
        )
        if success:
            self._composer.rebuild()

    @staticmethod
    def _collect_findings(results: dict[str, WorkerResult]) -> str:
        sections: list[str] = []
        for task_id, result in results.items():
            if result.verdict == Verdict.FAIL:
                sections.append(f"### {task_id}\n{result.detail}")
        return "\n\n".join(sections)
