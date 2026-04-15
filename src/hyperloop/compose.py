"""Prompt composition — assembles worker prompts from base + overlay + task context.

Three layers composed at spawn time:
1. Base prompt from base/{role}.yaml
2. Process overlay from specs/prompts/{role}-overlay.yaml (if exists)
3. Task context: spec content, findings, traceability refs (spec_ref, task_id)

For v1, kustomize integration (project overlay) is skipped. The orchestrator
reads base YAML files directly and injects process overlays + task context.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

import yaml

if TYPE_CHECKING:
    from hyperloop.ports.state import StateStore


class PromptComposer:
    """Composes agent prompts from base definitions + overlays + task context."""

    def __init__(self, base_dir: str | Path, state: StateStore) -> None:
        """Load base agent definitions from base_dir.

        Args:
            base_dir: Path to the directory containing base agent YAML files.
            state: StateStore used to read process overlays and spec files
                   from the target repo.
        """
        self._base_dir = Path(base_dir)
        self._state = state
        self._base_prompts: dict[str, str] = {}
        self._load_base_definitions()

    def _load_base_definitions(self) -> None:
        """Load all base agent YAML files and extract their prompt fields."""
        for yaml_file in self._base_dir.glob("*.yaml"):
            with open(yaml_file) as f:
                doc = yaml.safe_load(f)
            if doc and doc.get("kind") == "Agent" and "prompt" in doc:
                name = doc["name"]
                self._base_prompts[name] = doc["prompt"]

    def compose(
        self,
        role: str,
        task_id: str,
        spec_ref: str,
        findings: str,
    ) -> str:
        """Compose the full prompt for a worker.

        Layers:
        1. Base prompt from base/{role}.yaml
        2. Process overlay from specs/prompts/{role}-overlay.yaml (if exists)
        3. Task context: spec content, findings, traceability refs

        Args:
            role: Agent role name (e.g. "implementer", "verifier").
            task_id: Task identifier (e.g. "task-027").
            spec_ref: Path to the originating spec file (e.g. "specs/persistence.md").
            findings: Findings from prior rounds (empty string if none).

        Returns:
            The composed prompt string ready to pass to a worker.

        Raises:
            ValueError: If the role has no base agent definition.
        """
        # Layer 1: Base prompt
        if role not in self._base_prompts:
            msg = f"Unknown role '{role}': no base agent definition found in {self._base_dir}"
            raise ValueError(msg)

        base_prompt = self._base_prompts[role]

        # Replace template variables
        prompt = base_prompt.replace("{spec_ref}", spec_ref).replace("{task_id}", task_id)

        # Layer 2: Process overlay (from target repo specs/prompts/)
        overlay_path = f"specs/prompts/{role}-overlay.yaml"
        overlay_content = self._state.read_file(overlay_path)
        overlay_text = ""
        if overlay_content is not None:
            overlay_text = self._extract_overlay_prompt(overlay_content)

        # Layer 3: Task context — spec content
        spec_content = self._state.read_file(spec_ref)

        # Assemble the final prompt
        sections: list[str] = [prompt.rstrip()]

        if overlay_text:
            sections.append(f"## Process Overlay\n{overlay_text}")

        if spec_content is not None:
            sections.append(f"## Spec\n{spec_content}")
        else:
            sections.append(
                f"## Spec\n[Spec file '{spec_ref}' not found. Proceed with available context.]"
            )

        if findings:
            sections.append(f"## Findings\n{findings}")

        return "\n\n".join(sections) + "\n"

    @staticmethod
    def _extract_overlay_prompt(raw_yaml: str) -> str:
        """Extract prompt or content from overlay YAML.

        Overlay files may contain a 'prompt' field (like agent definitions)
        or raw text content. Handles both.
        """
        try:
            doc = yaml.safe_load(raw_yaml)
            if isinstance(doc, dict) and "prompt" in doc:
                return str(cast("dict[str, object]", doc)["prompt"]).strip()
        except yaml.YAMLError:
            pass
        # Fall back to raw content
        return raw_yaml.strip()
