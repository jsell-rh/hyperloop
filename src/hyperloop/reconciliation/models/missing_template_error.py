from __future__ import annotations


class MissingTemplateError(Exception):
    def __init__(self, roles: set[str]) -> None:
        self.roles = roles
        names = ", ".join(sorted(roles))
        super().__init__(f"Missing agent templates for roles: {names}")
