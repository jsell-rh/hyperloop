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
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast

import structlog
import yaml

from hyperloop.domain.model import (
    AgentContext,
    ComposedPrompt,
    ImprovementContext,
    IntakeContext,
    PhaseMap,
    PhaseStep,
    Process,
    PromptLabel,
    PromptSection,
    PromptSource,
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
    guidelines: list[str] = field(default_factory=list)
    annotations: dict[str, str] = field(default_factory=dict)


def _format_guidelines(guidelines: list[str]) -> str:
    """Format guidelines as a bulleted list string."""
    return "\n".join(f"- {g}" for g in guidelines)


class PromptComposer:
    """Composes agent prompts from kustomize-resolved templates + runtime context."""

    def __init__(
        self,
        templates: dict[str, AgentTemplate],
        state: StateStore,
        overlay: str | None = None,
    ) -> None:
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

        Returns:
            A PromptComposer with resolved templates.

        Raises:
            RuntimeError: If kustomize build fails.
        """
        composer, _ = cls.load_from_kustomize(overlay, state)
        return composer

    def rebuild(self) -> bool:
        """Re-run kustomize build and update templates in place.

        Called after the process-improver modifies overlay files so that
        any agent spawned afterward sees the updated guidelines.

        Returns:
            True if rebuild succeeded, False if it failed (previous templates retained).
        """
        if self._overlay is None:
            logger.warning("rebuild: no overlay path — skipping")
            return False
        try:
            raw_yaml = _run_kustomize(self._overlay)
            self._templates = _parse_multi_doc(raw_yaml)
            return True
        except RuntimeError:
            logger.warning("rebuild: kustomize build failed — retaining previous templates")
            return False

    def compose(
        self,
        role: str,
        context: AgentContext,
        epilogue: str = "",
    ) -> ComposedPrompt:
        """Compose the full prompt for a worker.

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
        """Compose prompt for a per-task worker."""
        prompt = (
            template.prompt.replace("{spec_ref}", context.spec_ref)
            .replace("{task_id}", context.task_id)
            .replace("{round}", str(context.round))
        )

        spec_path = context.spec_ref.split("@")[0] if "@" in context.spec_ref else context.spec_ref
        spec_content = self._state.read_file(spec_path)

        text_parts: list[str] = [prompt.rstrip()]
        prompt_source = PromptSource(
            template.annotations.get("hyperloop.io/source", PromptSource.BASE)
        )
        sections: list[PromptSection] = [
            PromptSection(source=prompt_source, label=PromptLabel.PROMPT, content=prompt.rstrip()),
        ]

        if template.guidelines:
            guidelines_text = _format_guidelines(template.guidelines)
            text_parts.append(f"## Guidelines\n{guidelines_text}")
            sections.append(
                PromptSection(
                    source=PromptSource.PROCESS_OVERLAY,
                    label=PromptLabel.GUIDELINES,
                    content=guidelines_text,
                )
            )

        if spec_content is not None:
            text_parts.append(f"## Spec\n{spec_content}")
            sections.append(
                PromptSection(
                    source=PromptSource.SPEC, label=PromptLabel.SPEC, content=spec_content
                )
            )
        else:
            fallback = (
                f"[Spec file '{context.spec_ref}' not found. Proceed with available context.]"
            )
            text_parts.append(f"## Spec\n{fallback}")
            sections.append(
                PromptSection(source=PromptSource.SPEC, label=PromptLabel.SPEC, content=fallback)
            )

        if context.findings:
            text_parts.append(f"## Findings\n{context.findings}")
            sections.append(
                PromptSection(
                    source=PromptSource.FINDINGS,
                    label=PromptLabel.FINDINGS,
                    content=context.findings,
                )
            )

        if context.pr_feedback:
            text_parts.append(f"## PR Feedback\n{context.pr_feedback}")
            sections.append(
                PromptSection(
                    source=PromptSource.PR,
                    label=PromptLabel.PR_FEEDBACK,
                    content=context.pr_feedback,
                )
            )

        if epilogue:
            text_parts.append(f"## Runtime\n{epilogue}")
            sections.append(
                PromptSection(
                    source=PromptSource.RUNTIME, label=PromptLabel.EPILOGUE, content=epilogue
                )
            )

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
        prompt_source = PromptSource(
            template.annotations.get("hyperloop.io/source", PromptSource.BASE)
        )
        sections: list[PromptSection] = [
            PromptSection(source=prompt_source, label=PromptLabel.PROMPT, content=prompt.rstrip()),
        ]

        if template.guidelines:
            guidelines_text = _format_guidelines(template.guidelines)
            text_parts.append(f"## Guidelines\n{guidelines_text}")
            sections.append(
                PromptSection(
                    source=PromptSource.PROCESS_OVERLAY,
                    label=PromptLabel.GUIDELINES,
                    content=guidelines_text,
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
            sections.append(
                PromptSection(source=PromptSource.SPEC, label=PromptLabel.SPEC, content=spec_text)
            )
        elif context.unprocessed_specs:
            spec_list = "\n".join(f"- {s}" for s in context.unprocessed_specs)
            text_parts.append(f"## Specs to Process\n\n{spec_list}")
            sections.append(
                PromptSection(source=PromptSource.SPEC, label=PromptLabel.SPEC, content=spec_list)
            )

        if context.failed_tasks:
            if context.failure_details:
                failed_list = "\n".join(f"- {d}" for d in context.failure_details)
            else:
                failed_list = "\n".join(f"- {t}" for t in context.failed_tasks)
            failed_section = (
                "The following tasks have failed and may need new approaches or "
                "different task decomposition:\n\n" + failed_list
            )
            text_parts.append(f"## Failed Tasks\n\n{failed_section}")
            sections.append(
                PromptSection(
                    source=PromptSource.FINDINGS,
                    label=PromptLabel.FINDINGS,
                    content=failed_section,
                )
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
        prompt_source = PromptSource(
            template.annotations.get("hyperloop.io/source", PromptSource.BASE)
        )
        sections: list[PromptSection] = [
            PromptSection(source=prompt_source, label=PromptLabel.PROMPT, content=prompt.rstrip()),
        ]

        if template.guidelines:
            guidelines_text = _format_guidelines(template.guidelines)
            text_parts.append(f"## Guidelines\n{guidelines_text}")
            sections.append(
                PromptSection(
                    source=PromptSource.PROCESS_OVERLAY,
                    label=PromptLabel.GUIDELINES,
                    content=guidelines_text,
                )
            )

        if context.findings:
            text_parts.append(f"## Findings\n{context.findings}")
            sections.append(
                PromptSection(
                    source=PromptSource.FINDINGS,
                    label=PromptLabel.FINDINGS,
                    content=context.findings,
                )
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
    """Extract the resource name from a YAML document."""
    metadata = doc.get("metadata")
    if isinstance(metadata, dict) and "name" in metadata:
        meta = cast("dict[str, object]", metadata)
        return str(meta["name"])
    return str(doc.get("name", ""))


def _parse_guidelines(raw_guidelines: object) -> list[str]:
    """Parse guidelines from YAML — supports list or string."""
    if isinstance(raw_guidelines, list):
        return [str(g) for g in raw_guidelines]
    if isinstance(raw_guidelines, str):
        stripped = raw_guidelines.strip()
        if stripped:
            return [stripped]
        return []
    if raw_guidelines is None:
        return []
    return [str(raw_guidelines)]


def _parse_multi_doc(raw: str) -> dict[str, AgentTemplate]:
    """Parse multi-document YAML output into AgentTemplate objects.

    Only documents with ``kind: Agent`` are extracted.
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
        guidelines = _parse_guidelines(doc.get("guidelines"))
        raw_annotations = doc.get("annotations", {})
        if not isinstance(raw_annotations, dict):
            raw_annotations = {}
        annotations = cast("dict[str, object]", raw_annotations)
        templates[name] = AgentTemplate(
            name=name,
            prompt=str(prompt),
            guidelines=guidelines,
            annotations={str(k): str(v) for k, v in annotations.items()},
        )
    return templates


def _parse_phase_map(phases_raw: dict[str, object]) -> PhaseMap:
    """Parse a flat phase map dict into a PhaseMap (dict[str, PhaseStep])."""
    result: PhaseMap = {}
    for phase_name, step_raw in phases_raw.items():
        if not isinstance(step_raw, dict):
            msg = f"Phase '{phase_name}' must be a mapping, got {type(step_raw).__name__}"
            raise ValueError(msg)
        step_dict = cast("dict[str, object]", step_raw)
        raw_args = step_dict.get("args")
        args: dict[str, object] = (
            cast("dict[str, object]", raw_args) if isinstance(raw_args, dict) else {}
        )
        on_wait_val = step_dict.get("on_wait")
        result[phase_name] = PhaseStep(
            run=str(step_dict.get("run", "")),
            on_pass=str(step_dict.get("on_pass", "")),
            on_fail=str(step_dict.get("on_fail", "")),
            on_wait=str(on_wait_val) if on_wait_val is not None else None,
            args=args,
        )
    return result


def parse_process(raw: str) -> Process | None:
    """Parse a Process document from multi-document YAML.

    Supports the flat phase map format (``phases`` key).

    Returns:
        A ``Process`` if a ``kind: Process`` document is found; ``None`` otherwise.
    """
    for raw_doc in yaml.safe_load_all(raw):
        if not isinstance(raw_doc, dict):
            continue
        doc = cast("dict[str, object]", raw_doc)
        if doc.get("kind") != "Process":
            continue
        name = _extract_name(doc)
        phases_raw = doc.get("phases")
        if isinstance(phases_raw, dict):
            phases = _parse_phase_map(cast("dict[str, object]", phases_raw))
        else:
            phases = {}
        return Process(name=name, phases=phases)
    return None


def validate_process(process: Process, templates: dict[str, AgentTemplate]) -> list[str]:
    """Validate that all agent roles referenced in the process have templates.

    Returns:
        A list of error messages for undefined roles. Empty list means valid.
    """
    errors: list[str] = []
    for phase_name, step in process.phases.items():
        if step.run.startswith("agent "):
            role = step.run[len("agent ") :]
            if role not in templates:
                errors.append(f"Phase '{phase_name}' references undefined agent role '{role}'")
    return errors


def check_kustomize_available() -> None:
    """Check that kustomize is on PATH.

    Raises:
        SystemExit: If kustomize is not found.
    """
    if shutil.which("kustomize") is None:
        msg = (
            "Error: kustomize CLI not found. "
            "Install it:"
            " https://kubectl.docs.kubernetes.io/installation/kustomize/"
        )
        raise SystemExit(msg)


def load_templates_from_dir(
    base_dir: str | Path,
) -> dict[str, AgentTemplate]:
    """Load agent templates directly from a directory of YAML files.

    This is used for testing and as a fallback when kustomize is not available.
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
                guidelines = _parse_guidelines(doc.get("guidelines"))
                raw_annotations = doc.get("annotations", {})
                if not isinstance(raw_annotations, dict):
                    raw_annotations = {}
                annotations = cast("dict[str, object]", raw_annotations)
                templates[name] = AgentTemplate(
                    name=name,
                    prompt=str(doc["prompt"]),
                    guidelines=guidelines,
                    annotations={str(k): str(v) for k, v in annotations.items()},
                )
    return templates
