from __future__ import annotations

from pathlib import Path

import yaml

from hyperloop.reconciliation.models.agent_template import AgentTemplate


class FakeKustomizeBuildRunner:
    def __init__(self, templates: list[AgentTemplate] | None = None) -> None:
        self._templates = templates or []
        self._fail: bool = False
        self._failure_message: str = ""
        self.build_count: int = 0
        self.last_build_path: Path | None = None

    def set_templates(self, templates: list[AgentTemplate]) -> None:
        self._templates = templates

    def set_failure(self, message: str) -> None:
        self._fail = True
        self._failure_message = message

    def build(self, path: Path) -> str:
        self.build_count += 1
        self.last_build_path = path
        if self._fail:
            raise RuntimeError(self._failure_message)
        docs = []
        for template in self._templates:
            doc = {
                "kind": "Agent",
                "name": template.name,
                "prompt": template.prompt,
                "guidelines": template.guidelines,
            }
            docs.append(yaml.dump(doc, default_flow_style=False))
        return "---\n".join(docs)
