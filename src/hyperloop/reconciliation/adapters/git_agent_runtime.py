from __future__ import annotations

import re
import subprocess
from pathlib import Path

from hyperloop.reconciliation.adapters.agent_executor import AgentExecutor
from hyperloop.reconciliation.models.agent_handle import AgentHandle
from hyperloop.reconciliation.models.agent_role import AgentRole
from hyperloop.reconciliation.models.event import Event
from hyperloop.reconciliation.models.integration_summary import IntegrationSummary
from hyperloop.reconciliation.models.poll_result import (
    AgentStatus,
    AgentVerdict,
    PollResult,
)
from hyperloop.reconciliation.models.proposed_task import ProposedTask
from hyperloop.reconciliation.models.prompt_section import PromptSection
from hyperloop.reconciliation.models.spec_diff import SpecDiff
from hyperloop.reconciliation.models.task import Task
from hyperloop.reconciliation.models.task_briefing import TaskBriefing
from hyperloop.reconciliation.models.workspace_type import WorkspaceType
from hyperloop.reconciliation.ports.prompt_composer import PromptComposer

_TASK_STATUS_RE = re.compile(r"^Task-Status:\s*(Complete|Failed)\s*$", re.MULTILINE)
_VERIFICATION_STATUS_RE = re.compile(
    r"^Verification-Status:\s*(Pass|Fail)\s*$", re.MULTILINE
)

_TASK_EPILOGUE = (
    "Signal completion by creating an empty commit.\n\n"
    "On success:\n"
    "<Summary of work performed>\n\n"
    f"Task-Status: {AgentStatus.COMPLETE}\n\n"
    "On failure:\n"
    "<Rationale for failure>\n\n"
    f"Task-Status: {AgentStatus.FAILED}"
)

_VERIFICATION_EPILOGUE = (
    "Signal completion by creating an empty commit.\n\n"
    "On alignment:\n"
    "<Assessment rationale>\n\n"
    f"Verification-Status: {AgentVerdict.PASS}\n\n"
    "On misalignment:\n"
    "<Detailed rationale>\n\n"
    f"Verification-Status: {AgentVerdict.FAIL}"
)


def _build_branch_patterns(
    branch_prefix: str,
) -> tuple[re.Pattern[str], re.Pattern[str]]:
    escaped = re.escape(branch_prefix)
    task_pattern = re.compile(rf"^{escaped}spec/[^/]+/task/\d+$")
    verifier_pattern = re.compile(rf"^{escaped}spec/[^/]+/verifier$")
    return task_pattern, verifier_pattern


def _format_events(events: list[Event]) -> str:
    return "\n".join(f"[{e.type}] {e.reason}: {e.message}" for e in events)


def _format_tasks(tasks: list[Task]) -> str:
    return "\n".join(f"- [{t.status}] {t.name}: {t.description}" for t in tasks)


def _format_task_summaries(summaries: list[tuple[str, str]]) -> str:
    return "\n".join(f"- {name}: {desc}" for name, desc in summaries)


class GitAgentRuntime:
    def __init__(
        self,
        repo_path: Path,
        *,
        branch_prefix: str,
        executor: AgentExecutor,
        prompt_composer: PromptComposer,
        remote: str = "origin",
    ) -> None:
        self._repo_path = repo_path
        self._branch_prefix = branch_prefix
        self._executor = executor
        self._prompt_composer = prompt_composer
        self._remote = remote
        self._task_branch_re, self._verifier_branch_re = _build_branch_patterns(
            branch_prefix
        )

    def poll(self, handle: AgentHandle) -> PollResult:
        self._fetch_branch(handle.id)
        message = self._latest_commit_message(handle.id)
        is_empty = self._is_empty_commit(handle.id)

        if not is_empty:
            return PollResult(status=AgentStatus.RUNNING)

        return self._parse_signal(message)

    def detect_orphans(self) -> list[AgentHandle]:
        self._fetch_all_managed_branches()
        branches = self._list_remote_managed_branches()
        orphans: list[AgentHandle] = []

        for branch in branches:
            if not (
                self._task_branch_re.match(branch)
                or self._verifier_branch_re.match(branch)
            ):
                continue

            message = self._latest_commit_message_remote(branch)
            is_empty = self._is_empty_commit_remote(branch)

            if not is_empty or not self._has_signal(message):
                orphans.append(AgentHandle(id=branch))

        return orphans

    def launch_task(self, briefing: TaskBriefing) -> AgentHandle:
        branch = self._workspace_to_branch(briefing.workspace_id)
        task_id = briefing.workspace_id.split("/")[2]
        spec_ref = f"{briefing.spec_path}@{briefing.spec_blob_sha}"

        sections = [PromptSection(heading="Spec", content=briefing.spec_content)]
        if briefing.events:
            sections.append(
                PromptSection(heading="Events", content=_format_events(briefing.events))
            )

        prompt = self._prompt_composer.compose(
            AgentRole.IMPLEMENTER,
            substitutions={"task_id": task_id, "spec_ref": spec_ref},
            sections=sections,
            epilogue=_TASK_EPILOGUE,
        )
        self._executor.start_task_agent(branch=branch, prompt=prompt)
        return AgentHandle(id=branch)

    def launch_decomposition(
        self,
        spec_diffs: list[SpecDiff],
        existing_tasks: list[Task],
        events: list[Event],
    ) -> list[ProposedTask]:
        sections: list[PromptSection] = []
        for diff in spec_diffs:
            sections.append(
                PromptSection(
                    heading=f"Spec: {diff.spec_path}",
                    content=diff.diff_text,
                )
            )
        if existing_tasks:
            sections.append(
                PromptSection(
                    heading="Existing Tasks",
                    content=_format_tasks(existing_tasks),
                )
            )
        if events:
            sections.append(
                PromptSection(heading="Events", content=_format_events(events))
            )

        prompt = self._prompt_composer.compose(
            AgentRole.DECOMPOSER,
            substitutions={},
            sections=sections,
            epilogue="",
        )
        return self._executor.run_decomposition(prompt=prompt)

    def launch_verification(
        self,
        spec_content: str,
        spec_path: str,
        spec_blob_sha: str,
        workspace_id: str,
    ) -> AgentHandle:
        branch = self._workspace_to_branch(workspace_id)
        spec_ref = f"{spec_path}@{spec_blob_sha}"

        sections = [PromptSection(heading="Spec", content=spec_content)]

        prompt = self._prompt_composer.compose(
            AgentRole.VERIFIER,
            substitutions={"spec_ref": spec_ref},
            sections=sections,
            epilogue=_VERIFICATION_EPILOGUE,
        )
        self._executor.start_verification_agent(branch=branch, prompt=prompt)
        return AgentHandle(id=branch)

    def launch_merge_resolution(
        self,
        task_workspace_id: str,
        delivery_workspace_id: str,
        conflict_details: str,
    ) -> bool:
        task_branch = self._workspace_to_branch(task_workspace_id)
        delivery_branch = self._workspace_to_branch(delivery_workspace_id)

        sections = [
            PromptSection(heading="Conflict Details", content=conflict_details),
        ]

        prompt = self._prompt_composer.compose(
            AgentRole.MERGE_RESOLVER,
            substitutions={},
            sections=sections,
            epilogue="",
        )
        return self._executor.resolve_merge(
            task_branch=task_branch,
            delivery_branch=delivery_branch,
            prompt=prompt,
        )

    def compose_integration_summary(
        self,
        spec_content: str,
        task_summaries: list[tuple[str, str]],
        verification_rationale: str,
    ) -> IntegrationSummary:
        sections = [
            PromptSection(heading="Spec", content=spec_content),
            PromptSection(
                heading="Completed Tasks",
                content=_format_task_summaries(task_summaries),
            ),
            PromptSection(
                heading="Verification Rationale",
                content=verification_rationale,
            ),
        ]

        prompt = self._prompt_composer.compose(
            AgentRole.INTEGRATION_SUMMARIZER,
            substitutions={},
            sections=sections,
            epilogue="",
        )
        return self._executor.compose_summary(prompt=prompt)

    def cancel(self, handle: AgentHandle) -> None:
        self._git(
            "branch",
            "-D",
            handle.id,
            check=False,
        )
        self._git(
            "push",
            self._remote,
            "--delete",
            handle.id,
            check=False,
        )

    def _workspace_to_branch(self, workspace_id: str) -> str:
        parts = workspace_id.split("/")
        ws_type = parts[0]
        blob_sha = parts[1]
        if ws_type == WorkspaceType.TASK:
            task_id = parts[2]
            return f"{self._branch_prefix}spec/{blob_sha}/task/{task_id}"
        if ws_type == WorkspaceType.VERIFICATION:
            return f"{self._branch_prefix}spec/{blob_sha}/verifier"
        if ws_type == WorkspaceType.DELIVERY:
            return f"{self._branch_prefix}spec/{blob_sha}/delivery"
        raise ValueError(f"Unknown workspace type: {ws_type}")

    def _fetch_branch(self, branch: str) -> None:
        self._git(
            "fetch",
            self._remote,
            f"+refs/heads/{branch}:refs/heads/{branch}",
            check=False,
        )

    def _fetch_all_managed_branches(self) -> None:
        self._git(
            "fetch",
            self._remote,
            f"+refs/heads/{self._branch_prefix}*:refs/remotes/{self._remote}/{self._branch_prefix}*",
            check=False,
        )

    def _latest_commit_message(self, branch: str) -> str:
        result = self._git("log", "-1", "--format=%B", branch)
        return result.stdout.strip()

    def _latest_commit_message_remote(self, branch: str) -> str:
        result = self._git("log", "-1", "--format=%B", f"{self._remote}/{branch}")
        return result.stdout.strip()

    def _is_empty_commit(self, branch: str) -> bool:
        result = self._git("diff-tree", "--no-commit-id", "--name-only", "-r", branch)
        return result.stdout.strip() == ""

    def _is_empty_commit_remote(self, branch: str) -> bool:
        result = self._git(
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            f"{self._remote}/{branch}",
        )
        return result.stdout.strip() == ""

    def _list_remote_managed_branches(self) -> list[str]:
        result = self._git(
            "for-each-ref",
            "--format=%(refname:strip=3)",
            f"refs/remotes/{self._remote}/{self._branch_prefix}",
        )
        if not result.stdout.strip():
            return []
        return result.stdout.strip().splitlines()

    def _parse_signal(self, message: str) -> PollResult:
        task_match = _TASK_STATUS_RE.search(message)
        if task_match:
            status_value = task_match.group(1)
            rationale = message[: task_match.start()].strip()
            if status_value == AgentStatus.COMPLETE:
                return PollResult(
                    status=AgentStatus.COMPLETE,
                    rationale=rationale or None,
                )
            return PollResult(
                status=AgentStatus.FAILED,
                rationale=rationale or None,
            )

        verification_match = _VERIFICATION_STATUS_RE.search(message)
        if verification_match:
            verdict_value = verification_match.group(1)
            rationale = message[: verification_match.start()].strip()
            verdict = (
                AgentVerdict.PASS
                if verdict_value == AgentVerdict.PASS
                else AgentVerdict.FAIL
            )
            return PollResult(
                status=AgentStatus.COMPLETE,
                rationale=rationale or None,
                verdict=verdict,
            )

        return PollResult(status=AgentStatus.RUNNING)

    def _has_signal(self, message: str) -> bool:
        return bool(
            _TASK_STATUS_RE.search(message) or _VERIFICATION_STATUS_RE.search(message)
        )

    def _git(
        self,
        *args: str,
        input: str | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=self._repo_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            input=input,
            check=check,
        )
