"""Prompt composition — kustomize all the way down.

All three prompt layers use kustomize resources with a consistent schema:
1. Base definitions (hyperloop repo ``base/``)
2. Project overlay (gitops repo or in-repo patches)
3. Process overlay (``.hyperloop/agents/process/`` kustomize Component)

A single ``kustomize build`` resolves all three layers into AgentTemplate
objects with ``prompt`` + ``guidelines``.  At compose time the final prompt
is: ``prompt + guidelines + spec + findings``.

The ``rebuild()`` method re-runs ``kustomize build`` after the process-improver
modifies overlay files mid-loop, so any agent spawned afterward is guaranteed
to see the updated guidelines.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

import structlog
import yaml

from hyperloop.domain.model import (
    ActionStep,
    AgentContext,
    AgentStep,
    CheckStep,
    ComposedPrompt,
    GateStep,
    ImprovementContext,
    IntakeContext,
    LoopStep,
    PipelineStep,
    Process,
    PromptSection,
    TaskContext,
)

if TYPE_CHECKING:
    from hyperloop.ports.state import StateStore

logger: structlog.stdlib.BoundLogger = structlog.get_logger()


@dataclass(frozen=True)
class AgentTemplate:
    """A resolved agent definition from kustomize build."""

    name: str
    prompt: str
    guidelines: str
    annotations: dict[str, str]


class PromptComposer:
    """Composes agent prompts from kustomize-resolved templates + runtime context."""

    def __init__(
        self,
        templates: dict[str, AgentTemplate],
        state: StateStore,
        overlay: str | None = None,
    ) -> None:
        """
        Args:
            templates: role name -> resolved agent definition (from kustomize build).
            state: StateStore for reading spec files at spawn time.
            overlay: Path to the kustomization directory (for rebuild).
        """
        self._templates = templates
        self._state = state
        self._overlay = overlay

    @classmethod
    def load_from_kustomize(
        cls,
        overlay: str,
        state: StateStore,
    ) -> tuple[PromptComposer, Process | None]:
        """Resolve templates and parse Process via kustomize build.

        Args:
            overlay: Path to the kustomization directory
                     (e.g. ``.hyperloop/agents/``).
            state: StateStore for reading spec files at spawn time.

        Returns:
            A tuple of (PromptComposer, Process | None). Process is None when
            the kustomize output contains no ``kind: Process`` document.

        Raises:
            RuntimeError: If kustomize build fails.
        """
        raw_yaml = _run_kustomize(overlay)
        templates = _parse_multi_doc(raw_yaml)
        process = parse_process(raw_yaml)
        return cls(templates, state, overlay=overlay), process

    @classmethod
    def from_kustomize(
        cls,
        overlay: str,
        state: StateStore,
    ) -> PromptComposer:
        """Resolve templates via kustomize build, then construct.

        Args:
            overlay: Path to the kustomization directory
                     (e.g. ``.hyperloop/agents/``).
            state: StateStore for reading spec files at spawn time.

        Returns:
            A PromptComposer with resolved templates.

        Raises:
            RuntimeError: If kustomize build fails.
        """
        composer, _ = cls.load_from_kustomize(overlay, state)
        return composer

    def rebuild(self) -> None:
        """Re-run kustomize build and update templates in place.

        Called after the process-improver modifies overlay files so that
        any agent spawned afterward sees the updated guidelines.
        """
        if self._overlay is None:
            logger.warning("rebuild: no overlay path — skipping")
            return
        raw_yaml = _run_kustomize(self._overlay)
        self._templates = _parse_multi_doc(raw_yaml)

    def compose(
        self,
        role: str,
        context: AgentContext,
        epilogue: str = "",
    ) -> ComposedPrompt:
        """Compose the full prompt for a worker.

        Layers:
        1. Resolved template prompt + guidelines (from kustomize build,
           includes base + project overlay + process overlay)
        2. Context-specific injection (spec content, findings, spec list)
        3. Optional runtime epilogue (for task workers only)

        Args:
            role: Agent role name (e.g. "implementer", "verifier", "pm").
            context: Typed context object -- TaskContext, IntakeContext, or
                     ImprovementContext -- carrying the data needed for this spawn.
            epilogue: Runtime-specific instructions appended to task worker prompts.

        Returns:
            A ComposedPrompt with section provenance and flattened text.

        Raises:
            ValueError: If the role has no resolved template.
        """
        if role not in self._templates:
            msg = f"Unknown role '{role}': no agent template resolved for this role"
            raise ValueError(msg)

        template = self._templates[role]

        if isinstance(context, TaskContext):
            return self._compose_task(role, template, context, epilogue=epilogue)
        if isinstance(context, IntakeContext):
            return self._compose_intake(role, template, context)
        return self._compose_improvement(role, template, context)

    def _compose_task(
        self,
        role: str,
        template: AgentTemplate,
        context: TaskContext,
        epilogue: str = "",
    ) -> ComposedPrompt:
        """Compose prompt for a per-task worker (implementer, verifier, rebase-resolver)."""
        prompt = (
            template.prompt.replace("{spec_ref}", context.spec_ref)
            .replace("{task_id}", context.task_id)
            .replace("{round}", str(context.round))
        )

        # Read spec content — strip @sha suffix for filesystem lookup
        spec_path = context.spec_ref.split("@")[0] if "@" in context.spec_ref else context.spec_ref
        spec_content = self._state.read_file(spec_path)

        # Assemble: prompt + guidelines + spec + findings + epilogue
        text_parts: list[str] = [prompt.rstrip()]
        prompt_source = template.annotations.get("hyperloop.io/source", "base")
        sections: list[PromptSection] = [
            PromptSection(source=prompt_source, label="prompt", content=prompt.rstrip()),
        ]

        if template.guidelines:
            text_parts.append(f"## Guidelines\n{template.guidelines}")
            sections.append(
                PromptSection(
                    source="process-overlay", label="guidelines", content=template.guidelines
                )
            )

        if spec_content is not None:
            text_parts.append(f"## Spec\n{spec_content}")
            sections.append(PromptSection(source="spec", label="spec", content=spec_content))
        else:
            fallback = (
                f"[Spec file '{context.spec_ref}' not found. Proceed with available context.]"
            )
            text_parts.append(f"## Spec\n{fallback}")
            sections.append(PromptSection(source="spec", label="spec", content=fallback))

        if context.findings:
            text_parts.append(f"## Findings\n{context.findings}")
            sections.append(
                PromptSection(source="findings", label="findings", content=context.findings)
            )

        if context.pr_feedback:
            text_parts.append(f"## PR Feedback\n{context.pr_feedback}")
            sections.append(
                PromptSection(source="pr", label="pr-feedback", content=context.pr_feedback)
            )

        if epilogue:
            text_parts.append(f"## Runtime\n{epilogue}")
            sections.append(PromptSection(source="runtime", label="epilogue", content=epilogue))

        text = "\n\n".join(text_parts) + "\n"
        return ComposedPrompt(sections=tuple(sections), text=text)

    def _compose_intake(
        self,
        role: str,
        template: AgentTemplate,
        context: IntakeContext,
    ) -> ComposedPrompt:
        """Compose prompt for PM intake."""
        prompt = template.prompt

        text_parts: list[str] = [prompt.rstrip()]
        prompt_source = template.annotations.get("hyperloop.io/source", "base")
        sections: list[PromptSection] = [
            PromptSection(source=prompt_source, label="prompt", content=prompt.rstrip()),
        ]

        if template.guidelines:
            text_parts.append(f"## Guidelines\n{template.guidelines}")
            sections.append(
                PromptSection(
                    source="process-overlay", label="guidelines", content=template.guidelines
                )
            )

        if context.spec_entries:
            spec_lines: list[str] = []
            for entry in context.spec_entries:
                spec_lines.append(f"- `{entry.path}` ({entry.change_type})")
                if entry.diff:
                    spec_lines.append(f"\n```diff\n{entry.diff.rstrip()}\n```\n")
            spec_text = "\n".join(spec_lines)
            text_parts.append(f"## Specs to Process\n\n{spec_text}")
            sections.append(PromptSection(source="spec", label="spec", content=spec_text))
        elif context.unprocessed_specs:
            spec_list = "\n".join(f"- {s}" for s in context.unprocessed_specs)
            text_parts.append(f"## Specs to Process\n\n{spec_list}")
            sections.append(PromptSection(source="spec", label="spec", content=spec_list))

        if context.failed_tasks:
            failed_list = "\n".join(f"- {t}" for t in context.failed_tasks)
            failed_section = (
                "The following tasks have failed and may need new approaches or "
                "different task decomposition:\n\n" + failed_list
            )
            text_parts.append(f"## Failed Tasks\n\n{failed_section}")
            sections.append(
                PromptSection(source="findings", label="findings", content=failed_section)
            )

        if not context.unprocessed_specs and not context.failed_tasks:
            text_parts.append("## Specs to Process\n\n(none)")

        text = "\n\n".join(text_parts) + "\n"
        return ComposedPrompt(sections=tuple(sections), text=text)

    def _compose_improvement(
        self,
        role: str,
        template: AgentTemplate,
        context: ImprovementContext,
    ) -> ComposedPrompt:
        """Compose prompt for process-improver."""
        prompt = template.prompt

        text_parts: list[str] = [prompt.rstrip()]
        prompt_source = template.annotations.get("hyperloop.io/source", "base")
        sections: list[PromptSection] = [
            PromptSection(source=prompt_source, label="prompt", content=prompt.rstrip()),
        ]

        if template.guidelines:
            text_parts.append(f"## Guidelines\n{template.guidelines}")
            sections.append(
                PromptSection(
                    source="process-overlay", label="guidelines", content=template.guidelines
                )
            )

        if context.findings:
            text_parts.append(f"## Findings\n{context.findings}")
            sections.append(
                PromptSection(source="findings", label="findings", content=context.findings)
            )

        text = "\n\n".join(text_parts) + "\n"
        return ComposedPrompt(sections=tuple(sections), text=text)


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
        guidelines = doc.get("guidelines", "")
        raw_annotations = doc.get("annotations", {})
        if not isinstance(raw_annotations, dict):
            raw_annotations = {}
        annotations = cast("dict[str, object]", raw_annotations)
        templates[name] = AgentTemplate(
            name=name,
            prompt=str(prompt),
            guidelines=str(guidelines).strip(),
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
    known_primitives = {"agent", "gate", "check", "loop", "action"}
    meta_keys = {"on_pass", "on_fail", "args"}

    for raw_step in cast("list[object]", steps_raw):
        if not isinstance(raw_step, dict):
            msg = f"Pipeline step must be a mapping, got {type(raw_step).__name__}"
            raise ValueError(msg)

        step = cast("dict[str, object]", raw_step)
        step_dict: dict[str, object] = {str(k): v for k, v in step.items()}
        primitive_keys = set(step_dict.keys()) & known_primitives

        if not primitive_keys:
            unknown = sorted(set(step_dict.keys()) - meta_keys)
            msg = (
                f"Unrecognised pipeline primitive key(s): {unknown!r}. "
                "Expected one of: agent, gate, check, loop, action"
            )
            raise ValueError(msg)

        if len(primitive_keys) > 1:
            msg = f"Pipeline step has multiple primitive keys: {sorted(primitive_keys)!r}"
            raise ValueError(msg)

        key = next(iter(primitive_keys))
        value = step_dict[key]
        raw_args = step_dict.get("args")
        step_args: dict[str, object] = (
            cast("dict[str, object]", raw_args) if isinstance(raw_args, dict) else {}
        )

        if key == "agent":
            on_pass_val = step_dict.get("on_pass")
            on_fail_val = step_dict.get("on_fail")
            result.append(
                AgentStep(
                    agent=str(value),
                    on_pass=str(on_pass_val) if on_pass_val is not None else None,
                    on_fail=str(on_fail_val) if on_fail_val is not None else None,
                )
            )
        elif key == "gate":
            result.append(GateStep(gate=str(value)))
        elif key == "check":
            result.append(CheckStep(check=str(value), args=step_args))
        elif key == "loop":
            nested = _parse_steps(value)
            result.append(LoopStep(steps=tuple(nested)))
        elif key == "action":
            result.append(ActionStep(action=str(value), args=step_args))

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
        pipeline_raw: object = doc.get("pipeline") or []
        pipeline = tuple(_parse_steps(pipeline_raw))
        return Process(name=name, pipeline=pipeline)
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
                guidelines = doc.get("guidelines", "")
                raw_annotations = doc.get("annotations", {})
                if not isinstance(raw_annotations, dict):
                    raw_annotations = {}
                annotations = cast("dict[str, object]", raw_annotations)
                templates[name] = AgentTemplate(
                    name=name,
                    prompt=str(doc["prompt"]),
                    guidelines=str(guidelines).strip() if guidelines else "",
                    annotations={str(k): str(v) for k, v in annotations.items()},
                )
    return templates
