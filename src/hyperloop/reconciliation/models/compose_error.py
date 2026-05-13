from __future__ import annotations


class ComposeError(Exception):
    def __init__(self, placeholders: set[str]) -> None:
        self.placeholders = placeholders
        names = ", ".join(sorted(placeholders))
        super().__init__(f"Unresolved placeholders: {names}")
