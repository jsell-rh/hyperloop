"""SerialRunner port — interface for running serial agents on trunk.

PM and process-improver run serially on trunk during the orchestrator's
serial section.  They are not pipeline workers — they block the loop
until they complete.

Implementations: SubprocessSerialRunner (CLI subprocess),
                 FakeSerialRunner (in-memory for tests).
"""

from __future__ import annotations

from typing import Protocol


class SerialRunner(Protocol):
    """Run an agent serially on trunk. Blocks until complete."""

    def run(self, role: str, prompt: str) -> bool:
        """Execute a serial agent with the given prompt.

        Returns True on success, False on failure.
        """
        ...
