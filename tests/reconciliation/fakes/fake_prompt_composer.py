from __future__ import annotations

from dataclasses import dataclass

from hyperloop.reconciliation.models.prompt_section import PromptSection


@dataclass
class ComposeCall:
    role: str
    substitutions: dict[str, str]
    sections: list[PromptSection]
    epilogue: str


class FakePromptComposer:
    def __init__(self) -> None:
        self.calls: list[ComposeCall] = []
        self._responses: dict[str, str] = {}
        self._validated: bool = False

    def set_response(self, role: str, response: str) -> None:
        self._responses[role] = response

    def compose(
        self,
        role: str,
        *,
        substitutions: dict[str, str],
        sections: list[PromptSection],
        epilogue: str,
    ) -> str:
        self.calls.append(
            ComposeCall(
                role=role,
                substitutions=substitutions,
                sections=sections,
                epilogue=epilogue,
            )
        )
        return self._responses.get(role, f"composed prompt for {role}")

    def validate(self, required_roles: set[str]) -> None:
        self._validated = True

    def rebuild(self) -> None:
        pass
