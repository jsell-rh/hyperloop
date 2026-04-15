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

from hyperloop.domain.model import (
    ActionStep,
    AgentContext,
    GateStep,
    ImprovementContext,
    IntakeContext,
    LoopStep,
    PipelineStep,
    Process,
    RoleStep,
    TaskContext,
)

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
    def load_from_kustomize(
        cls,
        overlay: str | None,
        state: StateStore,
        base_ref: str = HYPERLOOP_BASE_REF,
    ) -> tuple[PromptComposer, Process | None]:
        """Resolve templates and parse Process via kustomize build.

        Args:
            overlay: Path or git URL to a kustomization directory. If None,
                     a temporary kustomization referencing the hyperloop base
                     is created and built.
            state: StateStore for reading process overlays at spawn time.
            base_ref: Kustomize remote resource for the base definitions.

        Returns:
            A tuple of (PromptComposer, Process | None). Process is None when
            the kustomize output contains no ``kind: Process`` document.

        Raises:
            RuntimeError: If kustomize build fails.
        """
        raw_yaml = _kustomize_build(overlay, base_ref=base_ref)
        templates = _parse_multi_doc(raw_yaml)
        process = parse_process(raw_yaml)
        return cls(templates, state), process

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
        composer, _ = cls.load_from_kustomize(overlay, state, base_ref=base_ref)
        return composer

    def compose(
        self,
        role: str,
        context: AgentContext,
    ) -> str:
        """Compose the full prompt for a worker.

        Layers:
        1. Resolved template prompt (from kustomize, includes base + project overlay)
        2. Process overlay from specs/prompts/{role}-overlay.yaml (if exists)
        3. Context-specific injection (spec content, findings, spec list)

        Args:
            role: Agent role name (e.g. "implementer", "verifier", "pm").
            context: Typed context object -- TaskContext, IntakeContext, or
                     ImprovementContext -- carrying the data needed for this spawn.

        Returns:
            The composed prompt string ready to pass to a worker.

        Raises:
            ValueError: If the role has no resolved template.
        """
        if role not in self._templates:
            msg = f"Unknown role '{role}': no agent template resolved for this role"
            raise ValueError(msg)

        template = self._templates[role]

        if isinstance(context, TaskContext):
            return self._compose_task(role, template, context)
        if isinstance(context, IntakeContext):
            return self._compose_intake(role, template, context)
        return self._compose_improvement(role, template, context)

    def _compose_task(
        self,
        role: str,
        template: AgentTemplate,
        context: TaskContext,
    ) -> str:
        """Compose prompt for a per-task worker (implementer, verifier, rebase-resolver)."""
        prompt = template.prompt.replace("{spec_ref}", context.spec_ref).replace(
            "{task_id}", context.task_id
        )

        # Layer 2: Process overlay (from target repo specs/prompts/)
        overlay_text = self._read_overlay(role)

        # Layer 3: Task context -- spec content
        spec_content = self._state.read_file(context.spec_ref)

        # Assemble the final prompt
        sections: list[str] = [prompt.rstrip()]

        if overlay_text:
            sections.append(f"## Process Overlay\n{overlay_text}")

        if spec_content is not None:
            sections.append(f"## Spec\n{spec_content}")
        else:
            sections.append(
                f"## Spec\n[Spec file '{context.spec_ref}' not found."
                " Proceed with available context.]"
            )

        if context.findings:
            sections.append(f"## Findings\n{context.findings}")

        return "\n\n".join(sections) + "\n"

    def _compose_intake(
        self,
        role: str,
        template: AgentTemplate,
        context: IntakeContext,
    ) -> str:
        """Compose prompt for PM intake."""
        prompt = template.prompt

        # Layer 2: Process overlay
        overlay_text = self._read_overlay(role)

        sections: list[str] = [prompt.rstrip()]

        if overlay_text:
            sections.append(f"## Process Overlay\n{overlay_text}")

        spec_list = "\n".join(f"- {s}" for s in context.unprocessed_specs)
        sections.append(f"## Specs to Process\n\n{spec_list}")

        return "\n\n".join(sections) + "\n"

    def _compose_improvement(
        self,
        role: str,
        template: AgentTemplate,
        context: ImprovementContext,
    ) -> str:
        """Compose prompt for process-improver."""
        prompt = template.prompt

        # Layer 2: Process overlay
        overlay_text = self._read_overlay(role)

        sections: list[str] = [prompt.rstrip()]

        if overlay_text:
            sections.append(f"## Process Overlay\n{overlay_text}")

        if context.findings:
            sections.append(f"## Findings\n{context.findings}")

        return "\n\n".join(sections) + "\n"

    def _read_overlay(self, role: str) -> str:
        """Read and extract the process overlay for a given role."""
        overlay_path = f"specs/prompts/{role}-overlay.yaml"
        overlay_content = self._state.read_file(overlay_path)
        if overlay_content is not None:
            return self._extract_overlay_prompt(overlay_content)
        return ""

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

    # No overlay -- build a temp kustomization referencing the base
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
        meta = cast("dict[str, object]", metadata)
        return str(meta["name"])
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
    for raw_doc in yaml.safe_load_all(raw):
        if not isinstance(raw_doc, dict):
            continue
        doc = cast("dict[str, object]", raw_doc)
        if doc.get("kind") != "Agent":
            continue
        name = _extract_name(doc)
        prompt = doc.get("prompt", "")
        raw_annotations = doc.get("annotations", {})
        if not isinstance(raw_annotations, dict):
            raw_annotations = {}
        annotations = cast("dict[str, object]", raw_annotations)
        templates[name] = AgentTemplate(
            name=name,
            prompt=str(prompt),
            annotations={str(k): str(v) for k, v in annotations.items()},
        )
    return templates


def _parse_steps(steps_raw: object) -> list[PipelineStep]:
    """Parse a list of YAML step maps into pipeline primitives recursively.

    Args:
        steps_raw: A list of step maps from YAML.

    Returns:
        A list of PipelineStep objects.

    Raises:
        ValueError: If a step has an unrecognised primitive key or malformed structure.
    """
    if not isinstance(steps_raw, list):
        msg = f"Expected a list of pipeline steps, got {type(steps_raw).__name__}"
        raise ValueError(msg)

    result: list[PipelineStep] = []
    known_primitives = {"role", "gate", "loop", "action"}

    for raw_step in cast("list[object]", steps_raw):
        if not isinstance(raw_step, dict):
            msg = f"Pipeline step must be a mapping, got {type(raw_step).__name__}"
            raise ValueError(msg)

        step = cast("dict[str, object]", raw_step)
        step_dict: dict[str, object] = {str(k): v for k, v in step.items()}
        primitive_keys = set(step_dict.keys()) & known_primitives

        if not primitive_keys:
            unknown = sorted(set(step_dict.keys()) - {"on_pass", "on_fail"})
            msg = (
                f"Unrecognised pipeline primitive key(s): {unknown!r}. "
                "Expected one of: role, gate, loop, action"
            )
            raise ValueError(msg)

        if len(primitive_keys) > 1:
            msg = f"Pipeline step has multiple primitive keys: {sorted(primitive_keys)!r}"
            raise ValueError(msg)

        key = next(iter(primitive_keys))
        value = step_dict[key]

        if key == "role":
            on_pass_val = step_dict.get("on_pass")
            on_fail_val = step_dict.get("on_fail")
            result.append(
                RoleStep(
                    role=str(value),
                    on_pass=str(on_pass_val) if on_pass_val is not None else None,
                    on_fail=str(on_fail_val) if on_fail_val is not None else None,
                )
            )
        elif key == "gate":
            result.append(GateStep(gate=str(value)))
        elif key == "loop":
            nested = _parse_steps(value)
            result.append(LoopStep(steps=tuple(nested)))
        elif key == "action":
            result.append(ActionStep(action=str(value)))

    return result


def parse_process(raw: str) -> Process | None:
    """Parse a Process document from multi-document YAML.

    Args:
        raw: Multi-document YAML string (e.g., from ``kustomize build`` or a
             ``process.yaml`` file).

    Returns:
        A ``Process`` if a ``kind: Process`` document is found; ``None`` otherwise.

    Raises:
        ValueError: If an unrecognised pipeline primitive key is encountered.
    """
    for raw_doc in yaml.safe_load_all(raw):
        if not isinstance(raw_doc, dict):
            continue
        doc = cast("dict[str, object]", raw_doc)
        if doc.get("kind") != "Process":
            continue
        name = _extract_name(doc)
        intake_raw: object = doc.get("intake") or []
        pipeline_raw: object = doc.get("pipeline") or []
        intake = tuple(_parse_steps(intake_raw))
        pipeline = tuple(_parse_steps(pipeline_raw))
        return Process(name=name, intake=intake, pipeline=pipeline)
    return None


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
            raw_doc = yaml.safe_load(f)
        if raw_doc and isinstance(raw_doc, dict):
            doc = cast("dict[str, object]", raw_doc)
            if doc.get("kind") == "Agent" and "prompt" in doc:
                name = _extract_name(doc)
                raw_annotations = doc.get("annotations", {})
                if not isinstance(raw_annotations, dict):
                    raw_annotations = {}
                annotations = cast("dict[str, object]", raw_annotations)
                templates[name] = AgentTemplate(
                    name=name,
                    prompt=str(doc["prompt"]),
                    annotations={str(k): str(v) for k, v in annotations.items()},
                )
    return templates
