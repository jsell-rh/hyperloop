from __future__ import annotations

import re
from pathlib import Path

import yaml

from hyperloop.reconciliation.adapters.kustomize_build_runner import (
    KustomizeBuildRunner,
)
from hyperloop.reconciliation.models.agent_template import AgentTemplate
from hyperloop.reconciliation.models.compose_error import ComposeError
from hyperloop.reconciliation.models.missing_template_error import MissingTemplateError
from hyperloop.reconciliation.models.prompt_section import PromptSection
from hyperloop.reconciliation.models.template_kind import TemplateKind
from hyperloop.reconciliation.ports.observer import Observer

_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


class KustomizePromptComposer:
    def __init__(
        self,
        *,
        overlay_path: Path,
        kustomize_runner: KustomizeBuildRunner,
        observer: Observer,
    ) -> None:
        self._overlay_path = overlay_path
        self._runner = kustomize_runner
        self._observer = observer
        self._templates: dict[str, AgentTemplate] = {}
        self._build()

    def compose(
        self,
        role: str,
        *,
        substitutions: dict[str, str],
        sections: list[PromptSection],
        epilogue: str,
    ) -> str:
        template = self._templates.get(role)
        if template is None:
            raise MissingTemplateError({role})

        prompt_text = _substitute(template.prompt, substitutions)

        parts: list[str] = [prompt_text]

        if template.guidelines:
            items = "\n".join(f"- {g}" for g in template.guidelines)
            parts.append(f"## Guidelines\n\n{items}")

        for section in sections:
            parts.append(f"## {section.heading}\n\n{section.content}")

        if epilogue:
            parts.append(f"## Epilogue\n\n{epilogue}")

        return "\n\n".join(parts)

    def validate(self, required_roles: set[str]) -> None:
        available = set(self._templates.keys())
        missing = required_roles - available
        if missing:
            raise MissingTemplateError(missing)

    def rebuild(self) -> None:
        try:
            self._build()
        except Exception as exc:
            self._observer.composer_rebuild_failed(reason=str(exc))

    def _build(self) -> None:
        raw = self._runner.build(self._overlay_path)
        templates = _parse_templates(raw)
        self._templates = {t.name: t for t in templates}
        self._observer.composer_rebuilt(template_count=len(self._templates))


def _substitute(template: str, substitutions: dict[str, str]) -> str:
    found = set(_PLACEHOLDER_RE.findall(template))
    unknown = found - set(substitutions.keys())
    if unknown:
        raise ComposeError(unknown)
    return _PLACEHOLDER_RE.sub(lambda m: substitutions[m.group(1)], template)


def _parse_templates(raw_yaml: str) -> list[AgentTemplate]:
    templates: list[AgentTemplate] = []
    for doc in yaml.safe_load_all(raw_yaml):
        if doc is None:
            continue
        if doc.get("kind") != TemplateKind.AGENT:
            continue
        templates.append(
            AgentTemplate(
                name=doc["name"],
                prompt=doc["prompt"],
                guidelines=doc.get("guidelines", []),
            )
        )
    return templates
