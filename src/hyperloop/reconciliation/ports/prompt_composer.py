from __future__ import annotations

from typing import Protocol

from hyperloop.reconciliation.models.prompt_section import PromptSection


class PromptComposer(Protocol):
    def compose(
        self,
        role: str,
        *,
        substitutions: dict[str, str],
        sections: list[PromptSection],
        epilogue: str,
    ) -> str: ...

    def validate(self, required_roles: set[str]) -> None: ...

    def rebuild(self) -> None: ...

    def rebuild_if_changed(self) -> None: ...
