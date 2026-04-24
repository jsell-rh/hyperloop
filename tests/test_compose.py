"""Tests for prompt composition — resolved templates + overlay + task context.

Uses InMemoryStateStore with pre-loaded files and pre-resolved AgentTemplate
objects. No kustomize dependency — unit tests skip the kustomize build step.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from hyperloop.compose import (
    AgentTemplate,
    PromptComposer,
    _parse_multi_doc,
    _parse_phase_map,
    load_templates_from_dir,
    parse_process,
    validate_process,
)
from hyperloop.domain.model import (
    ComposedPrompt,
    ImprovementContext,
    IntakeContext,
    PhaseMap,
    PhaseStep,
    Process,
    PromptSection,
    TaskContext,
)
from tests.fakes.state import InMemoryStateStore

# The base/ dir lives at the repo root, adjacent to src/
BASE_DIR = Path(__file__).parent.parent / "base"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _templates() -> dict[str, AgentTemplate]:
    """Load base templates from the repo's base/ directory."""
    return load_templates_from_dir(BASE_DIR)


def _state_with_spec(
    spec_ref: str = "specs/widget.md",
    spec_content: str = "Build a widget.",
) -> InMemoryStateStore:
    """Return an InMemoryStateStore with a spec file pre-loaded."""
    state = InMemoryStateStore()
    state.set_file(spec_ref, spec_content)
    return state


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBasePromptOnly:
    """Compose with base prompt only — no overlay, no findings."""

    def test_compose_returns_composed_prompt(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(
            task_id="task-001",
            spec_ref="specs/widget.md",
            findings="",
            round=0,
        )
        result = composer.compose(role="implementer", context=ctx)

        assert isinstance(result, ComposedPrompt)
        assert isinstance(result.sections, tuple)
        assert len(result.sections) > 0
        assert all(isinstance(s, PromptSection) for s in result.sections)

    def test_compose_returns_base_prompt_content(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(
            task_id="task-001",
            spec_ref="specs/widget.md",
            findings="",
            round=0,
        )
        result = composer.compose(role="implementer", context=ctx)

        assert "You are a worker agent implementing a task" in result.text

    def test_compose_includes_spec_content(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(
            task_id="task-001",
            spec_ref="specs/widget.md",
            findings="",
            round=0,
        )
        result = composer.compose(role="implementer", context=ctx)

        assert "Build a widget." in result.text

    def test_compose_includes_no_findings_when_empty(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(
            task_id="task-001",
            spec_ref="specs/widget.md",
            findings="",
            round=0,
        )
        result = composer.compose(role="implementer", context=ctx)

        has_findings = "## Findings" in result.text
        if has_findings:
            assert result.text.split("## Findings")[-1].strip() == ""


class TestTemplateVariables:
    """Template variables {spec_ref} and {task_id} are replaced."""

    def test_spec_ref_is_replaced(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(
            task_id="task-027",
            spec_ref="specs/persistence.md",
            findings="",
            round=0,
        )
        result = composer.compose(role="implementer", context=ctx)

        assert "specs/persistence.md" in result.text
        assert "{spec_ref}" not in result.text

    def test_task_id_is_replaced(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(
            task_id="task-027",
            spec_ref="specs/persistence.md",
            findings="",
            round=0,
        )
        result = composer.compose(role="implementer", context=ctx)

        assert "task-027" in result.text
        assert "{task_id}" not in result.text


class TestGuidelinesAsList:
    """Guidelines field is list[str], composed as bulleted list."""

    def test_guidelines_list_rendered_as_bullets(self) -> None:
        state = _state_with_spec()
        templates = _templates()
        templates["implementer"] = AgentTemplate(
            name="implementer",
            prompt=templates["implementer"].prompt,
            guidelines=["Always write tests", "Follow existing patterns"],
            annotations=templates["implementer"].annotations,
        )

        composer = PromptComposer(templates=templates, state=state)
        ctx = TaskContext(
            task_id="task-001",
            spec_ref="specs/widget.md",
            findings="",
            round=0,
        )
        result = composer.compose(role="implementer", context=ctx)

        assert "## Guidelines" in result.text
        assert "- Always write tests" in result.text
        assert "- Follow existing patterns" in result.text

    def test_empty_guidelines_omits_section(self) -> None:
        state = _state_with_spec()
        templates = _templates()
        templates["implementer"] = AgentTemplate(
            name="implementer",
            prompt=templates["implementer"].prompt,
            guidelines=[],
            annotations=templates["implementer"].annotations,
        )

        composer = PromptComposer(templates=templates, state=state)
        ctx = TaskContext(
            task_id="task-001",
            spec_ref="specs/widget.md",
            findings="",
            round=0,
        )
        result = composer.compose(role="implementer", context=ctx)

        assert "## Guidelines" not in result.text

    def test_single_guideline_rendered(self) -> None:
        state = _state_with_spec()
        templates = _templates()
        templates["implementer"] = AgentTemplate(
            name="implementer",
            prompt=templates["implementer"].prompt,
            guidelines=["Only one rule"],
            annotations=templates["implementer"].annotations,
        )

        composer = PromptComposer(templates=templates, state=state)
        ctx = TaskContext(
            task_id="task-001",
            spec_ref="specs/widget.md",
            findings="",
            round=0,
        )
        result = composer.compose(role="implementer", context=ctx)

        assert "## Guidelines" in result.text
        assert "- Only one rule" in result.text

    def test_guidelines_in_intake_compose(self) -> None:
        state = _state_with_spec()
        templates = _templates()
        templates["pm"] = AgentTemplate(
            name="pm",
            prompt=templates["pm"].prompt,
            guidelines=["Review deps carefully"],
            annotations=templates["pm"].annotations,
        )

        composer = PromptComposer(templates=templates, state=state)
        ctx = IntakeContext(unprocessed_specs=("specs/widget.md",))
        result = composer.compose(role="pm", context=ctx)

        assert "## Guidelines" in result.text
        assert "- Review deps carefully" in result.text

    def test_guidelines_in_improvement_compose(self) -> None:
        state = _state_with_spec()
        templates = _templates()
        templates["process-improver"] = AgentTemplate(
            name="process-improver",
            prompt=templates["process-improver"].prompt,
            guidelines=["Be conservative"],
            annotations=templates["process-improver"].annotations,
        )

        composer = PromptComposer(templates=templates, state=state)
        ctx = ImprovementContext(findings="Some findings")
        result = composer.compose(role="process-improver", context=ctx)

        assert "## Guidelines" in result.text
        assert "- Be conservative" in result.text


class TestGuidelinesYAMLParsing:
    """_parse_multi_doc handles guidelines as YAML list or string."""

    def test_guidelines_yaml_list_parsed_as_list(self) -> None:
        raw = """\
apiVersion: hyperloop.io/v1
kind: Agent
metadata:
  name: implementer
prompt: |
  You are a worker.
guidelines:
  - Always write tests
  - Follow existing patterns
annotations: {}
"""
        templates = _parse_multi_doc(raw)
        assert templates["implementer"].guidelines == [
            "Always write tests",
            "Follow existing patterns",
        ]

    def test_guidelines_yaml_string_wrapped_in_list(self) -> None:
        raw = """\
apiVersion: hyperloop.io/v1
kind: Agent
metadata:
  name: implementer
prompt: |
  You are a worker.
guidelines: "Run the linter"
annotations: {}
"""
        templates = _parse_multi_doc(raw)
        assert templates["implementer"].guidelines == ["Run the linter"]

    def test_guidelines_yaml_empty_string_becomes_empty_list(self) -> None:
        raw = """\
apiVersion: hyperloop.io/v1
kind: Agent
metadata:
  name: implementer
prompt: |
  You are a worker.
guidelines: ""
annotations: {}
"""
        templates = _parse_multi_doc(raw)
        assert templates["implementer"].guidelines == []

    def test_guidelines_yaml_missing_becomes_empty_list(self) -> None:
        raw = """\
apiVersion: hyperloop.io/v1
kind: Agent
metadata:
  name: implementer
prompt: |
  You are a worker.
annotations: {}
"""
        templates = _parse_multi_doc(raw)
        assert templates["implementer"].guidelines == []


class TestProcessOverlay:
    """Compose with process overlay present in specs/prompts/."""

    def test_overlay_content_is_included(self) -> None:
        state = _state_with_spec()
        templates = _templates()
        templates["implementer"] = AgentTemplate(
            name="implementer",
            prompt=templates["implementer"].prompt,
            guidelines=["Always run linter before submitting."],
            annotations=templates["implementer"].annotations,
        )

        composer = PromptComposer(templates=templates, state=state)

        ctx = TaskContext(
            task_id="task-001",
            spec_ref="specs/widget.md",
            findings="",
            round=0,
        )
        result = composer.compose(role="implementer", context=ctx)

        assert "## Guidelines" in result.text
        assert "- Always run linter before submitting." in result.text

    def test_no_overlay_still_composes(self) -> None:
        """When no overlay file exists, composition still succeeds."""
        state = _state_with_spec()

        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(
            task_id="task-001",
            spec_ref="specs/widget.md",
            findings="",
            round=0,
        )
        result = composer.compose(role="implementer", context=ctx)

        assert "You are a worker agent implementing a task" in result.text


class TestFindings:
    """Compose with findings from prior round."""

    def test_findings_are_appended(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(
            task_id="task-001",
            spec_ref="specs/widget.md",
            findings=("Test suite failed: missing null check in widget.py line 42"),
            round=0,
        )
        result = composer.compose(role="implementer", context=ctx)

        assert "Test suite failed: missing null check in widget.py line 42" in result.text
        assert "## Findings" in result.text


class TestSectionProvenance:
    """ComposedPrompt sections carry correct source and label attribution."""

    def test_task_prompt_has_base_source(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(
            task_id="task-001",
            spec_ref="specs/widget.md",
            findings="",
            round=0,
        )
        result = composer.compose(role="implementer", context=ctx)

        prompt_sections = [s for s in result.sections if s.label == "prompt"]
        assert len(prompt_sections) == 1
        assert prompt_sections[0].source == "base"

    def test_task_spec_has_spec_source(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(
            task_id="task-001",
            spec_ref="specs/widget.md",
            findings="",
            round=0,
        )
        result = composer.compose(role="implementer", context=ctx)

        spec_sections = [s for s in result.sections if s.label == "spec"]
        assert len(spec_sections) == 1
        assert spec_sections[0].source == "spec"
        assert "Build a widget." in spec_sections[0].content

    def test_task_guidelines_has_process_overlay_source(self) -> None:
        state = _state_with_spec()
        templates = _templates()
        templates["implementer"] = AgentTemplate(
            name="implementer",
            prompt=templates["implementer"].prompt,
            guidelines=["Run tests first."],
            annotations=templates["implementer"].annotations,
        )
        composer = PromptComposer(templates=templates, state=state)

        ctx = TaskContext(
            task_id="task-001",
            spec_ref="specs/widget.md",
            findings="",
            round=0,
        )
        result = composer.compose(role="implementer", context=ctx)

        guidelines_sections = [s for s in result.sections if s.label == "guidelines"]
        assert len(guidelines_sections) == 1
        assert guidelines_sections[0].source == "process-overlay"
        assert "- Run tests first." in guidelines_sections[0].content

    def test_task_findings_has_findings_source(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(
            task_id="task-001",
            spec_ref="specs/widget.md",
            findings="null check missing",
            round=1,
        )
        result = composer.compose(role="implementer", context=ctx)

        findings_sections = [s for s in result.sections if s.label == "findings"]
        assert len(findings_sections) == 1
        assert findings_sections[0].source == "findings"
        assert "null check missing" in findings_sections[0].content

    def test_task_epilogue_has_runtime_source(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(
            task_id="task-001",
            spec_ref="specs/widget.md",
            findings="",
            round=0,
        )
        result = composer.compose(role="implementer", context=ctx, epilogue="Push your branch.")

        epilogue_sections = [s for s in result.sections if s.label == "epilogue"]
        assert len(epilogue_sections) == 1
        assert epilogue_sections[0].source == "runtime"
        assert "Push your branch." in epilogue_sections[0].content

    def test_no_findings_means_no_findings_section(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(
            task_id="task-001",
            spec_ref="specs/widget.md",
            findings="",
            round=0,
        )
        result = composer.compose(role="implementer", context=ctx)

        findings_sections = [s for s in result.sections if s.label == "findings"]
        assert len(findings_sections) == 0

    def test_no_epilogue_means_no_epilogue_section(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(
            task_id="task-001",
            spec_ref="specs/widget.md",
            findings="",
            round=0,
        )
        result = composer.compose(role="implementer", context=ctx)

        epilogue_sections = [s for s in result.sections if s.label == "epilogue"]
        assert len(epilogue_sections) == 0

    def test_project_overlay_source_from_annotation(self) -> None:
        state = _state_with_spec()
        templates = _templates()
        templates["implementer"] = AgentTemplate(
            name="implementer",
            prompt=templates["implementer"].prompt,
            guidelines=[],
            annotations={"hyperloop.io/source": "project-overlay"},
        )
        composer = PromptComposer(templates=templates, state=state)

        ctx = TaskContext(
            task_id="task-001",
            spec_ref="specs/widget.md",
            findings="",
            round=0,
        )
        result = composer.compose(role="implementer", context=ctx)

        prompt_sections = [s for s in result.sections if s.label == "prompt"]
        assert prompt_sections[0].source == "project-overlay"

    def test_intake_sections(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = IntakeContext(unprocessed_specs=("specs/widget.md",))
        result = composer.compose(role="pm", context=ctx)

        assert any(s.label == "prompt" and s.source == "base" for s in result.sections)
        assert any(s.label == "spec" for s in result.sections)

    def test_improvement_sections(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = ImprovementContext(findings="Some failure details")
        result = composer.compose(role="process-improver", context=ctx)

        assert any(s.label == "prompt" and s.source == "base" for s in result.sections)
        findings_sections = [s for s in result.sections if s.label == "findings"]
        assert len(findings_sections) == 1
        assert findings_sections[0].source == "findings"


class TestUnknownRole:
    """Unknown role raises a clear error."""

    def test_unknown_role_raises_value_error(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(
            task_id="task-001",
            spec_ref="specs/widget.md",
            findings="",
            round=0,
        )
        with pytest.raises(ValueError, match=r"(?i)unknown.*role.*nonexistent"):
            composer.compose(role="nonexistent", context=ctx)


class TestMissingSpecRef:
    """Missing spec_ref file is gracefully handled."""

    def test_missing_spec_still_composes(self) -> None:
        state = InMemoryStateStore()
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(
            task_id="task-001",
            spec_ref="specs/nonexistent.md",
            findings="",
            round=0,
        )
        result = composer.compose(role="implementer", context=ctx)

        assert "You are a worker agent implementing a task" in result.text

    def test_missing_spec_notes_absence(self) -> None:
        state = InMemoryStateStore()
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(
            task_id="task-001",
            spec_ref="specs/nonexistent.md",
            findings="",
            round=0,
        )
        result = composer.compose(role="implementer", context=ctx)

        assert (
            "not found" in result.text.lower()
            or "could not" in result.text.lower()
            or "missing" in result.text.lower()
        )


class TestAllRoles:
    """All base agent roles can be composed."""

    @pytest.mark.parametrize(
        "role",
        [
            "implementer",
            "verifier",
            "pm",
            "process-improver",
            "rebase-resolver",
        ],
    )
    def test_all_base_roles_compose(self, role: str) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        if role == "pm":
            ctx: TaskContext | IntakeContext | ImprovementContext = IntakeContext(
                unprocessed_specs=("specs/widget.md",)
            )
        elif role == "process-improver":
            ctx = ImprovementContext(findings="Some findings")
        else:
            ctx = TaskContext(
                task_id="task-001",
                spec_ref="specs/widget.md",
                findings="",
                round=0,
            )

        result = composer.compose(role=role, context=ctx)

        assert isinstance(result, ComposedPrompt)
        assert len(result.text) > 0
        assert len(result.sections) > 0


class TestLoadTemplatesFromDir:
    """load_templates_from_dir reads YAML files and builds AgentTemplate."""

    def test_loads_all_base_agents(self) -> None:
        templates = load_templates_from_dir(BASE_DIR)
        assert "implementer" in templates
        assert "verifier" in templates
        assert "pm" in templates
        assert "process-improver" in templates
        assert "rebase-resolver" in templates

    def test_skips_non_agent_kinds(self) -> None:
        templates = load_templates_from_dir(BASE_DIR)
        assert "default" not in templates

    def test_template_has_prompt(self) -> None:
        templates = load_templates_from_dir(BASE_DIR)
        impl = templates["implementer"]
        assert "You are a worker agent implementing a task" in impl.prompt

    def test_base_templates_have_empty_annotations(self) -> None:
        templates = load_templates_from_dir(BASE_DIR)
        impl = templates["implementer"]
        assert impl.annotations == {}

    def test_base_templates_have_list_guidelines(self) -> None:
        """Guidelines should be list[str] even from base dir loading."""
        templates = load_templates_from_dir(BASE_DIR)
        impl = templates["implementer"]
        assert isinstance(impl.guidelines, list)


class TestAgentTemplate:
    """AgentTemplate is a frozen dataclass."""

    def test_frozen(self) -> None:
        t = AgentTemplate(name="test", prompt="hello", guidelines=[], annotations={})
        with pytest.raises(AttributeError):
            t.name = "other"  # type: ignore[misc]

    def test_equality(self) -> None:
        a = AgentTemplate(name="x", prompt="p", guidelines=[], annotations={"k": "v"})
        b = AgentTemplate(name="x", prompt="p", guidelines=[], annotations={"k": "v"})
        assert a == b

    def test_guidelines_is_list(self) -> None:
        t = AgentTemplate(
            name="test",
            prompt="hello",
            guidelines=["a", "b"],
            annotations={},
        )
        assert t.guidelines == ["a", "b"]


class TestParseMultiDoc:
    """_parse_multi_doc extracts Agent definitions from multi-doc YAML."""

    def test_parses_agent_definitions(self) -> None:
        raw = """\
apiVersion: hyperloop.io/v1
kind: Agent
metadata:
  name: implementer
prompt: |
  You are a worker.
guidelines: []
annotations:
  ambient.io/persona: ""
---
apiVersion: hyperloop.io/v1
kind: Process
metadata:
  name: default
phases:
  implement:
    run: agent implementer
    on_pass: done
    on_fail: implement
---
apiVersion: hyperloop.io/v1
kind: Agent
metadata:
  name: verifier
prompt: |
  You are a reviewer.
guidelines: []
annotations: {}
"""
        templates = _parse_multi_doc(raw)
        assert "implementer" in templates
        assert "verifier" in templates
        assert "default" not in templates

    def test_handles_empty_input(self) -> None:
        templates = _parse_multi_doc("")
        assert templates == {}


class TestParsePhaseMap:
    """_parse_phase_map converts flat phase map YAML into PhaseMap."""

    def test_basic_phase_map(self) -> None:
        phases_raw: dict[str, object] = {
            "implement": {
                "run": "agent implementer",
                "on_pass": "verify",
                "on_fail": "implement",
            },
            "verify": {
                "run": "agent verifier",
                "on_pass": "merge",
                "on_fail": "implement",
            },
            "merge": {
                "run": "action merge",
                "on_pass": "done",
                "on_fail": "implement",
            },
        }

        result = _parse_phase_map(phases_raw)

        assert len(result) == 3
        assert result["implement"] == PhaseStep(
            run="agent implementer",
            on_pass="verify",
            on_fail="implement",
        )
        assert result["verify"] == PhaseStep(
            run="agent verifier",
            on_pass="merge",
            on_fail="implement",
        )
        assert result["merge"] == PhaseStep(
            run="action merge",
            on_pass="done",
            on_fail="implement",
        )

    def test_phase_with_on_wait(self) -> None:
        phases_raw: dict[str, object] = {
            "await-review": {
                "run": "signal pr-review",
                "on_pass": "merge",
                "on_fail": "implement",
                "on_wait": "await-review",
            },
        }

        result = _parse_phase_map(phases_raw)

        assert result["await-review"].on_wait == "await-review"

    def test_phase_with_args(self) -> None:
        phases_raw: dict[str, object] = {
            "merge": {
                "run": "action merge",
                "on_pass": "done",
                "on_fail": "implement",
                "args": {"strategy": "squash"},
            },
        }

        result = _parse_phase_map(phases_raw)

        assert result["merge"].args == {"strategy": "squash"}

    def test_on_wait_defaults_to_none(self) -> None:
        phases_raw: dict[str, object] = {
            "implement": {
                "run": "agent implementer",
                "on_pass": "verify",
                "on_fail": "implement",
            },
        }

        result = _parse_phase_map(phases_raw)

        assert result["implement"].on_wait is None

    def test_args_defaults_to_empty_dict(self) -> None:
        phases_raw: dict[str, object] = {
            "implement": {
                "run": "agent implementer",
                "on_pass": "verify",
                "on_fail": "implement",
            },
        }

        result = _parse_phase_map(phases_raw)

        assert result["implement"].args == {}

    def test_empty_phases_map(self) -> None:
        result = _parse_phase_map({})
        assert result == {}


class TestParseProcess:
    """parse_process converts multi-doc YAML with flat phase map."""

    def test_phase_map_process(self) -> None:
        yaml_input = """\
apiVersion: hyperloop.io/v1
kind: Process
metadata:
  name: default
phases:
  implement:
    run: agent implementer
    on_pass: verify
    on_fail: implement
  verify:
    run: agent verifier
    on_pass: merge
    on_fail: implement
  merge:
    run: action merge
    on_pass: done
    on_fail: implement
"""
        process = parse_process(yaml_input)

        assert process is not None
        assert process.name == "default"
        assert len(process.phases) == 3
        assert process.phases["implement"].run == "agent implementer"
        assert process.phases["verify"].on_pass == "merge"
        assert process.phases["merge"].on_pass == "done"

    def test_no_process_doc_returns_none(self) -> None:
        yaml_input = """\
kind: Agent
metadata:
  name: implementer
prompt: |
  You are a worker.
"""
        result = parse_process(yaml_input)
        assert result is None

    def test_empty_yaml_returns_none(self) -> None:
        result = parse_process("")
        assert result is None

    def test_multi_doc_yaml_finds_process(self) -> None:
        yaml_input = """\
kind: Agent
metadata:
  name: implementer
prompt: |
  Worker prompt.
---
kind: Process
metadata:
  name: default
phases:
  implement:
    run: agent implementer
    on_pass: done
    on_fail: implement
"""
        process = parse_process(yaml_input)
        assert process is not None
        assert process.name == "default"
        assert "implement" in process.phases

    def test_process_with_on_wait(self) -> None:
        yaml_input = """\
kind: Process
metadata:
  name: gated
phases:
  implement:
    run: agent implementer
    on_pass: await-review
    on_fail: implement
  await-review:
    run: signal pr-review
    on_pass: merge
    on_fail: implement
    on_wait: await-review
  merge:
    run: action merge
    on_pass: done
    on_fail: implement
"""
        process = parse_process(yaml_input)
        assert process is not None
        assert process.phases["await-review"].on_wait == "await-review"


class TestValidateProcess:
    """validate_process catches undefined agent roles."""

    def test_valid_process_returns_empty_list(self) -> None:
        phases: PhaseMap = {
            "implement": PhaseStep(
                run="agent implementer",
                on_pass="verify",
                on_fail="implement",
            ),
            "verify": PhaseStep(
                run="agent verifier",
                on_pass="merge",
                on_fail="implement",
            ),
            "merge": PhaseStep(
                run="action merge",
                on_pass="done",
                on_fail="implement",
            ),
        }
        process = Process(name="default", phases=phases)
        templates = {
            "implementer": AgentTemplate(
                name="implementer",
                prompt="p",
                guidelines=[],
                annotations={},
            ),
            "verifier": AgentTemplate(
                name="verifier",
                prompt="p",
                guidelines=[],
                annotations={},
            ),
        }

        errors = validate_process(process, templates)
        assert errors == []

    def test_undefined_agent_role_returns_error(self) -> None:
        phases: PhaseMap = {
            "implement": PhaseStep(
                run="agent implementer",
                on_pass="audit",
                on_fail="implement",
            ),
            "audit": PhaseStep(
                run="agent auditor",
                on_pass="done",
                on_fail="implement",
            ),
        }
        process = Process(name="default", phases=phases)
        templates = {
            "implementer": AgentTemplate(
                name="implementer",
                prompt="p",
                guidelines=[],
                annotations={},
            ),
        }

        errors = validate_process(process, templates)
        assert len(errors) == 1
        assert "auditor" in errors[0]

    def test_action_steps_not_validated_as_agents(self) -> None:
        phases: PhaseMap = {
            "merge": PhaseStep(
                run="action merge",
                on_pass="done",
                on_fail="implement",
            ),
        }
        process = Process(name="default", phases=phases)
        templates: dict[str, AgentTemplate] = {}

        errors = validate_process(process, templates)
        assert errors == []

    def test_multiple_undefined_roles(self) -> None:
        phases: PhaseMap = {
            "implement": PhaseStep(
                run="agent implementer",
                on_pass="audit",
                on_fail="implement",
            ),
            "audit": PhaseStep(
                run="agent auditor",
                on_pass="review",
                on_fail="implement",
            ),
            "review": PhaseStep(
                run="agent reviewer",
                on_pass="done",
                on_fail="implement",
            ),
        }
        process = Process(name="default", phases=phases)
        templates: dict[str, AgentTemplate] = {}

        errors = validate_process(process, templates)
        assert len(errors) == 3


class TestRebuildFailureRetainsPrevious:
    """Kustomize build failure retains previous templates."""

    def test_rebuild_failure_keeps_old_templates(self) -> None:
        state = _state_with_spec()
        original_templates = {
            "implementer": AgentTemplate(
                name="implementer",
                prompt="Original prompt",
                guidelines=["Original guideline"],
                annotations={},
            ),
        }
        composer = PromptComposer(
            templates=original_templates,
            state=state,
            overlay="/nonexistent/path/that/will/fail",
        )

        result = composer.rebuild()

        assert result is False
        ctx = TaskContext(
            task_id="task-001",
            spec_ref="specs/widget.md",
            findings="",
            round=0,
        )
        composed = composer.compose(role="implementer", context=ctx)
        assert "Original prompt" in composed.text

    def test_rebuild_no_overlay_returns_false(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates={}, state=state, overlay=None)

        result = composer.rebuild()
        assert result is False


class TestKustomizeIntegration:
    """Integration tests that require kustomize on PATH."""

    @pytest.mark.skipif(
        not shutil.which("kustomize"),
        reason="kustomize CLI not available",
    )
    def test_from_kustomize_with_local_base(self, tmp_path: Path) -> None:
        import os

        rel_base = os.path.relpath(BASE_DIR, tmp_path)
        kustomization = tmp_path / "kustomization.yaml"
        kustomization.write_text(f"resources:\n  - {rel_base}\n")

        state = _state_with_spec()
        composer = PromptComposer.from_kustomize(str(tmp_path), state)

        ctx = TaskContext(
            task_id="task-001",
            spec_ref="specs/widget.md",
            findings="",
            round=0,
        )
        result = composer.compose(role="implementer", context=ctx)
        assert "You are a worker agent implementing a task" in result.text


class TestCheckKustomize:
    """check_kustomize_available raises SystemExit when missing."""

    def test_raises_when_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from hyperloop.compose import check_kustomize_available

        monkeypatch.setattr(
            shutil,
            "which",
            lambda _name: None,  # type: ignore[arg-type]
        )

        with pytest.raises(SystemExit, match="kustomize CLI not found"):
            check_kustomize_available()


class TestLoadFromKustomize:
    """load_from_kustomize returns (PromptComposer, Process | None)."""

    @pytest.mark.skipif(
        not shutil.which("kustomize"),
        reason="kustomize CLI not available",
    )
    def test_returns_composer_and_process(self, tmp_path: Path) -> None:
        import os

        rel_base = os.path.relpath(BASE_DIR, tmp_path)
        kustomization = tmp_path / "kustomization.yaml"
        kustomization.write_text(f"resources:\n  - {rel_base}\n")

        state = _state_with_spec()
        composer, process = PromptComposer.load_from_kustomize(str(tmp_path), state)

        assert isinstance(composer, PromptComposer)
        assert process is not None
        assert process.name == "default"

    @pytest.mark.skipif(
        not shutil.which("kustomize"),
        reason="kustomize CLI not available",
    )
    def test_returns_none_process_when_no_process_doc(self, tmp_path: Path) -> None:
        agent_yaml = tmp_path / "agent.yaml"
        agent_yaml.write_text(
            "kind: Agent\nmetadata:\n  name: test\nprompt: hello\nannotations: {}\n"
        )
        kustomization = tmp_path / "kustomization.yaml"
        kustomization.write_text("resources:\n  - agent.yaml\n")

        state = _state_with_spec()
        composer, process = PromptComposer.load_from_kustomize(str(tmp_path), state)

        assert isinstance(composer, PromptComposer)
        assert process is None
