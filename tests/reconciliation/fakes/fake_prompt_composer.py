from __future__ import annotations

from dataclasses import dataclass

from hyperloop.reconciliation.models.agent_template import AgentTemplate
from hyperloop.reconciliation.models.compose_error import ComposeError
from hyperloop.reconciliation.models.missing_template_error import MissingTemplateError
from hyperloop.reconciliation.models.prompt_section import PromptSection


@dataclass
class ComposeCall:
    role: str
    substitutions: dict[str, str]
    sections: list[PromptSection]
    epilogue: str


class FakePromptComposer:
    def __init__(self, templates: list[AgentTemplate] | None = None) -> None:
        self.calls: list[ComposeCall] = []
        self._templates: dict[str, AgentTemplate] = {
            t.name: t for t in (templates or [])
        }
        self._rebuild_failure: str | None = None

    def set_templates(self, templates: list[AgentTemplate]) -> None:
        self._templates = {t.name: t for t in templates}

    def set_rebuild_failure(self, reason: str) -> None:
        self._rebuild_failure = reason

    def compose(
        self,
        role: str,
        *,
        substitutions: dict[str, str],
        sections: list[PromptSection],
        epilogue: str,
    ) -> str:
        if role not in self._templates:
            raise ComposeError({role})
        self.calls.append(
            ComposeCall(
                role=role,
                substitutions=substitutions,
                sections=sections,
                epilogue=epilogue,
            )
        )
        template = self._templates[role]
        return template.prompt

    def validate(self, required_roles: set[str]) -> None:
        missing = required_roles - set(self._templates.keys())
        if missing:
            raise MissingTemplateError(missing)

    def rebuild(self) -> None:
        if self._rebuild_failure is not None:
            raise RuntimeError(self._rebuild_failure)
