"""Prompt composition — kustomize-resolved templates + runtime context.

Three layers composed at spawn time:
1. Base + project overlay via kustomize (resolved at startup)
2. Process overlay from specs/prompts/{role}-overlay.yaml (injected at spawn time)
3. Task context: spec content, findings, traceability refs (spec_ref, task_id)

The orchestrator runs ``kustomize build`` at startup to resolve layers 1+2 into
AgentTemplate objects. Layer 3 (process overlay + task context) is injected at
spawn time because it changes during the loop.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

import yaml

if TYPE_CHECKING:
    from hyperloop.ports.state import StateStore

logger = logging.getLogger(__name__)

HYPERLOOP_BASE_REF = "github.com/jsell-rh/hyperloop//base?ref=main"


@dataclass(frozen=True)
class AgentTemplate:
    """A resolved agent definition from kustomize build."""

    name: str
    prompt: str
    annotations: dict[str, str]


class PromptComposer:
    """Composes agent prompts from kustomize-resolved templates + runtime context."""

    def __init__(self, templates: dict[str, AgentTemplate], state: StateStore) -> None:
        """
        Args:
            templates: role name -> resolved agent definition (from kustomize build).
            state: StateStore for reading process overlays and spec files at spawn time.
        """
        self._templates = templates
        self._state = state

    @classmethod
    def from_kustomize(
        cls,
        overlay: str | None,
        state: StateStore,
        base_ref: str = HYPERLOOP_BASE_REF,
    ) -> PromptComposer:
        """Resolve templates via kustomize build, then construct.

        Args:
            overlay: Path or git URL to a kustomization directory. If None,
                     a temporary kustomization referencing the hyperloop base
                     is created and built.
            state: StateStore for reading process overlays at spawn time.
            base_ref: Kustomize remote resource for the base definitions.
                      Configurable via .hyperloop.yaml or HYPERLOOP_BASE_REF env var.

        Returns:
            A PromptComposer with resolved templates.

        Raises:
            RuntimeError: If kustomize build fails.
        """
        raw_yaml = _kustomize_build(overlay, base_ref=base_ref)
        templates = _parse_multi_doc(raw_yaml)
        return cls(templates, state)

    def compose(
        self,
        role: str,
        task_id: str,
        spec_ref: str,
        findings: str,
    ) -> str:
        """Compose the full prompt for a worker.

        Layers:
        1. Resolved template prompt (from kustomize, includes base + project overlay)
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
            ValueError: If the role has no resolved template.
        """
        if role not in self._templates:
            msg = f"Unknown role '{role}': no agent template resolved for this role"
            raise ValueError(msg)

        template = self._templates[role]
        prompt = template.prompt.replace("{spec_ref}", spec_ref).replace("{task_id}", task_id)

        # Layer 2: Process overlay (from target repo specs/prompts/)
        overlay_path = f"specs/prompts/{role}-overlay.yaml"
        overlay_content = self._state.read_file(overlay_path)
        overlay_text = ""
        if overlay_content is not None:
            overlay_text = self._extract_overlay_prompt(overlay_content)

        # Layer 3: Task context — spec content
        spec_content = self._state.read_file(spec_ref) if spec_ref else None

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


def _kustomize_build(overlay: str | None, base_ref: str = HYPERLOOP_BASE_REF) -> str:
    """Run ``kustomize build`` and return the raw YAML output.

    Args:
        overlay: Path or git URL to a kustomization directory.
                 If None, builds from a temporary kustomization that
                 references the hyperloop base.
        base_ref: Kustomize remote resource for the base definitions.

    Returns:
        The multi-document YAML output from kustomize build.

    Raises:
        RuntimeError: If kustomize build exits non-zero.
    """
    if overlay is not None:
        return _run_kustomize(overlay)

    # No overlay — build a temp kustomization referencing the base
    with tempfile.TemporaryDirectory() as tmp:
        kustomization = Path(tmp) / "kustomization.yaml"
        kustomization.write_text(f"resources:\n  - {base_ref}\n")
        return _run_kustomize(tmp)


def _run_kustomize(target: str) -> str:
    """Execute ``kustomize build <target>`` and return stdout.

    Raises:
        RuntimeError: If the command fails.
    """
    result = subprocess.run(
        ["kustomize", "build", target],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        msg = f"kustomize build failed (exit {result.returncode}): {result.stderr.strip()}"
        raise RuntimeError(msg)
    return result.stdout


def _extract_name(doc: dict[str, object]) -> str:
    """Extract the resource name from a YAML document.

    Supports both kustomize-style ``metadata.name`` and legacy top-level
    ``name`` for backward compatibility.
    """
    metadata = doc.get("metadata")
    if isinstance(metadata, dict) and "name" in metadata:
        return str(metadata["name"])
    return str(doc.get("name", ""))


def _parse_multi_doc(raw: str) -> dict[str, AgentTemplate]:
    """Parse multi-document YAML output into AgentTemplate objects.

    Only documents with ``kind: Agent`` are extracted. Process definitions
    and other kinds are ignored for prompt composition purposes.

    Args:
        raw: Multi-document YAML string from kustomize build.

    Returns:
        A dict mapping agent name -> AgentTemplate.
    """
    templates: dict[str, AgentTemplate] = {}
    for doc in yaml.safe_load_all(raw):
        if not isinstance(doc, dict):
            continue
        if doc.get("kind") != "Agent":
            continue
        name = _extract_name(doc)
        prompt = doc.get("prompt", "")
        annotations = doc.get("annotations", {})
        if not isinstance(annotations, dict):
            annotations = {}
        templates[name] = AgentTemplate(
            name=name,
            prompt=str(prompt),
            annotations={str(k): str(v) for k, v in annotations.items()},
        )
    return templates


def check_kustomize_available() -> None:
    """Check that kustomize is on PATH.

    Raises:
        SystemExit: If kustomize is not found.
    """
    if shutil.which("kustomize") is None:
        msg = (
            "Error: kustomize CLI not found. "
            "Install it: https://kubectl.docs.kubernetes.io/installation/kustomize/"
        )
        raise SystemExit(msg)


def load_templates_from_dir(base_dir: str | Path) -> dict[str, AgentTemplate]:
    """Load agent templates directly from a directory of YAML files.

    This is used for testing and as a fallback when kustomize is not available.
    It reads all ``*.yaml`` files in ``base_dir`` and extracts Agent definitions.

    Args:
        base_dir: Path to the directory containing base agent YAML files.

    Returns:
        A dict mapping agent name -> AgentTemplate.
    """
    templates: dict[str, AgentTemplate] = {}
    base_path = Path(base_dir)
    for yaml_file in base_path.glob("*.yaml"):
        if yaml_file.name == "kustomization.yaml":
            continue
        with open(yaml_file) as f:
            doc = yaml.safe_load(f)
        if doc and doc.get("kind") == "Agent" and "prompt" in doc:
            name = _extract_name(doc)
            annotations = doc.get("annotations", {})
            if not isinstance(annotations, dict):
                annotations = {}
            templates[name] = AgentTemplate(
                name=name,
                prompt=doc["prompt"],
                annotations={str(k): str(v) for k, v in annotations.items()},
            )
    return templates
