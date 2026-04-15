"""SubprocessSerialRunner — runs serial agents via CLI subprocess on trunk.

Used for PM intake and process-improver. Blocks until the agent completes.
"""

from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger(__name__)


class SubprocessSerialRunner:
    """Run a serial agent as a subprocess in the repo directory."""

    _DEFAULT_CMD = "claude --dangerously-skip-permissions"

    def __init__(self, repo_path: str, command: str = _DEFAULT_CMD) -> None:
        self._repo_path = repo_path
        self._command = command

    def run(self, role: str, prompt: str) -> bool:
        """Execute a serial agent with the given prompt. Blocks until complete."""
        logger.info("Running serial agent: %s", role)

        try:
            result = subprocess.run(
                self._command.split(),
                input=prompt,
                capture_output=True,
                text=True,
                cwd=self._repo_path,
                timeout=600,
            )
            if result.returncode != 0:
                logger.warning(
                    "Serial agent %s failed (exit %d): %s",
                    role,
                    result.returncode,
                    result.stderr[:500],
                )
                return False

            logger.info("Serial agent %s completed successfully", role)
            return True

        except subprocess.TimeoutExpired:
            logger.warning("Serial agent %s timed out after 600s", role)
            return False
