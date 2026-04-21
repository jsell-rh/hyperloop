"""Tests for prompt composition — resolved templates + overlay + task context.

Uses InMemoryStateStore with pre-loaded files and pre-resolved AgentTemplate
objects. No kustomize dependency — unit tests skip the kustomize build step.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from hyperloop.compose import AgentTemplate, PromptComposer, load_templates_from_dir
from hyperloop.domain.model import (
    ComposedPrompt,
    ImprovementContext,
    IntakeContext,
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
    spec_ref: str = "specs/widget.md", spec_content: str = "Build a widget."
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

        ctx = TaskContext(task_id="task-001", spec_ref="specs/widget.md", findings="", round=0)
        result = composer.compose(role="implementer", context=ctx)

        assert isinstance(result, ComposedPrompt)
        assert isinstance(result.sections, tuple)
        assert len(result.sections) > 0
        assert all(isinstance(s, PromptSection) for s in result.sections)

    def test_compose_returns_base_prompt_content(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(task_id="task-001", spec_ref="specs/widget.md", findings="", round=0)
        result = composer.compose(role="implementer", context=ctx)

        # Base prompt content should be present
        assert "You are a worker agent implementing a task" in result.text

    def test_compose_includes_spec_content(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(task_id="task-001", spec_ref="specs/widget.md", findings="", round=0)
        result = composer.compose(role="implementer", context=ctx)

        assert "Build a widget." in result.text

    def test_compose_includes_no_findings_when_empty(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(task_id="task-001", spec_ref="specs/widget.md", findings="", round=0)
        result = composer.compose(role="implementer", context=ctx)

        # Should not have a findings section with content
        has_findings = "## Findings" in result.text
        if has_findings:
            assert result.text.split("## Findings")[-1].strip() == ""


class TestTemplateVariables:
    """Template variables {spec_ref} and {task_id} are replaced."""

    def test_spec_ref_is_replaced(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(task_id="task-027", spec_ref="specs/persistence.md", findings="", round=0)
        result = composer.compose(role="implementer", context=ctx)

        assert "specs/persistence.md" in result.text
        assert "{spec_ref}" not in result.text

    def test_task_id_is_replaced(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(task_id="task-027", spec_ref="specs/persistence.md", findings="", round=0)
        result = composer.compose(role="implementer", context=ctx)

        assert "task-027" in result.text
        assert "{task_id}" not in result.text


class TestProcessOverlay:
    """Compose with process overlay present in specs/prompts/."""

    def test_overlay_content_is_included(self) -> None:
        state = _state_with_spec()
        # Guidelines now come from the kustomize-resolved template, not a file read
        templates = _templates()
        templates["implementer"] = AgentTemplate(
            name="implementer",
            prompt=templates["implementer"].prompt,
            guidelines="Always run linter before submitting.",
            annotations=templates["implementer"].annotations,
        )

        composer = PromptComposer(templates=templates, state=state)

        ctx = TaskContext(task_id="task-001", spec_ref="specs/widget.md", findings="", round=0)
        result = composer.compose(role="implementer", context=ctx)

        assert "## Guidelines" in result.text
        assert "Always run linter before submitting." in result.text

    def test_no_overlay_still_composes(self) -> None:
        """When no overlay file exists, composition still succeeds."""
        state = _state_with_spec()
        # No overlay file set

        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(task_id="task-001", spec_ref="specs/widget.md", findings="", round=0)
        result = composer.compose(role="implementer", context=ctx)

        # Should still have the base prompt
        assert "You are a worker agent implementing a task" in result.text


class TestFindings:
    """Compose with findings from prior round."""

    def test_findings_are_appended(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(
            task_id="task-001",
            spec_ref="specs/widget.md",
            findings="Test suite failed: missing null check in widget.py line 42",
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

        ctx = TaskContext(task_id="task-001", spec_ref="specs/widget.md", findings="", round=0)
        result = composer.compose(role="implementer", context=ctx)

        prompt_sections = [s for s in result.sections if s.label == "prompt"]
        assert len(prompt_sections) == 1
        assert prompt_sections[0].source == "base"

    def test_task_spec_has_spec_source(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(task_id="task-001", spec_ref="specs/widget.md", findings="", round=0)
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
            guidelines="Run tests first.",
            annotations=templates["implementer"].annotations,
        )
        composer = PromptComposer(templates=templates, state=state)

        ctx = TaskContext(task_id="task-001", spec_ref="specs/widget.md", findings="", round=0)
        result = composer.compose(role="implementer", context=ctx)

        guidelines_sections = [s for s in result.sections if s.label == "guidelines"]
        assert len(guidelines_sections) == 1
        assert guidelines_sections[0].source == "process-overlay"
        assert "Run tests first." in guidelines_sections[0].content

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

        ctx = TaskContext(task_id="task-001", spec_ref="specs/widget.md", findings="", round=0)
        result = composer.compose(role="implementer", context=ctx, epilogue="Push your branch.")

        epilogue_sections = [s for s in result.sections if s.label == "epilogue"]
        assert len(epilogue_sections) == 1
        assert epilogue_sections[0].source == "runtime"
        assert "Push your branch." in epilogue_sections[0].content

    def test_no_findings_means_no_findings_section(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(task_id="task-001", spec_ref="specs/widget.md", findings="", round=0)
        result = composer.compose(role="implementer", context=ctx)

        findings_sections = [s for s in result.sections if s.label == "findings"]
        assert len(findings_sections) == 0

    def test_no_epilogue_means_no_epilogue_section(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(task_id="task-001", spec_ref="specs/widget.md", findings="", round=0)
        result = composer.compose(role="implementer", context=ctx)

        epilogue_sections = [s for s in result.sections if s.label == "epilogue"]
        assert len(epilogue_sections) == 0

    def test_project_overlay_source_from_annotation(self) -> None:
        state = _state_with_spec()
        templates = _templates()
        templates["implementer"] = AgentTemplate(
            name="implementer",
            prompt=templates["implementer"].prompt,
            guidelines="",
            annotations={"hyperloop.io/source": "project-overlay"},
        )
        composer = PromptComposer(templates=templates, state=state)

        ctx = TaskContext(task_id="task-001", spec_ref="specs/widget.md", findings="", round=0)
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

        ctx = TaskContext(task_id="task-001", spec_ref="specs/widget.md", findings="", round=0)
        with pytest.raises(ValueError, match=r"(?i)unknown.*role.*nonexistent"):
            composer.compose(role="nonexistent", context=ctx)


class TestMissingSpecRef:
    """Missing spec_ref file is gracefully handled — still composes, notes missing spec."""

    def test_missing_spec_still_composes(self) -> None:
        state = InMemoryStateStore()
        # No spec file set — spec_ref points to nothing
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(task_id="task-001", spec_ref="specs/nonexistent.md", findings="", round=0)
        result = composer.compose(role="implementer", context=ctx)

        # Should still compose with the base prompt
        assert "You are a worker agent implementing a task" in result.text

    def test_missing_spec_notes_absence(self) -> None:
        state = InMemoryStateStore()
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(task_id="task-001", spec_ref="specs/nonexistent.md", findings="", round=0)
        result = composer.compose(role="implementer", context=ctx)

        # Should note that the spec file could not be read
        assert (
            "not found" in result.text.lower()
            or "could not" in result.text.lower()
            or "missing" in result.text.lower()
        )


class TestAllRoles:
    """All base agent roles can be composed."""

    @pytest.mark.parametrize(
        "role", ["implementer", "verifier", "pm", "process-improver", "rebase-resolver"]
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
            ctx = TaskContext(task_id="task-001", spec_ref="specs/widget.md", findings="", round=0)

        result = composer.compose(role=role, context=ctx)

        assert isinstance(result, ComposedPrompt)
        assert len(result.text) > 0
        assert len(result.sections) > 0


class TestLoadTemplatesFromDir:
    """load_templates_from_dir reads YAML files and builds AgentTemplate objects."""

    def test_loads_all_base_agents(self) -> None:
        templates = load_templates_from_dir(BASE_DIR)
        assert "implementer" in templates
        assert "verifier" in templates
        assert "pm" in templates
        assert "process-improver" in templates
        assert "rebase-resolver" in templates

    def test_skips_non_agent_kinds(self) -> None:
        """Process definitions (kind: Process) are not loaded as templates."""
        templates = load_templates_from_dir(BASE_DIR)
        assert "default" not in templates  # process.yaml has name: default

    def test_template_has_prompt(self) -> None:
        templates = load_templates_from_dir(BASE_DIR)
        impl = templates["implementer"]
        assert "You are a worker agent implementing a task" in impl.prompt

    def test_base_templates_have_empty_annotations(self) -> None:
        templates = load_templates_from_dir(BASE_DIR)
        impl = templates["implementer"]
        assert impl.annotations == {}


class TestAgentTemplate:
    """AgentTemplate is a frozen dataclass."""

    def test_frozen(self) -> None:
        t = AgentTemplate(name="test", prompt="hello", guidelines="", annotations={})
        with pytest.raises(AttributeError):
            t.name = "other"  # type: ignore[misc]

    def test_equality(self) -> None:
        a = AgentTemplate(name="x", prompt="p", guidelines="", annotations={"k": "v"})
        b = AgentTemplate(name="x", prompt="p", guidelines="", annotations={"k": "v"})
        assert a == b


class TestParseMultiDoc:
    """_parse_multi_doc extracts Agent definitions from multi-document YAML."""

    def test_parses_agent_definitions(self) -> None:
        from hyperloop.compose import _parse_multi_doc

        raw = """\
apiVersion: hyperloop.io/v1
kind: Agent
metadata:
  name: implementer
prompt: |
  You are a worker.
guidelines: ""
annotations:
  ambient.io/persona: ""
---
apiVersion: hyperloop.io/v1
kind: Process
metadata:
  name: default
pipeline:
  - role: implementer
---
apiVersion: hyperloop.io/v1
kind: Agent
metadata:
  name: verifier
prompt: |
  You are a reviewer.
guidelines: ""
annotations: {}
"""
        templates = _parse_multi_doc(raw)
        assert "implementer" in templates
        assert "verifier" in templates
        assert "default" not in templates  # Process kind skipped

    def test_handles_empty_input(self) -> None:
        from hyperloop.compose import _parse_multi_doc

        templates = _parse_multi_doc("")
        assert templates == {}


class TestKustomizeIntegration:
    """Integration tests that require kustomize on PATH."""

    @pytest.mark.skipif(
        not shutil.which("kustomize"),
        reason="kustomize CLI not available",
    )
    def test_from_kustomize_with_local_base(self, tmp_path: Path) -> None:
        """Build from a local kustomization that references the base dir."""
        import os

        # kustomize requires relative paths for local resources
        rel_base = os.path.relpath(BASE_DIR, tmp_path)
        kustomization = tmp_path / "kustomization.yaml"
        kustomization.write_text(f"resources:\n  - {rel_base}\n")

        state = _state_with_spec()
        composer = PromptComposer.from_kustomize(str(tmp_path), state)

        ctx = TaskContext(task_id="task-001", spec_ref="specs/widget.md", findings="", round=0)
        result = composer.compose(role="implementer", context=ctx)
        assert "You are a worker agent implementing a task" in result.text


class TestCheckKustomize:
    """check_kustomize_available raises SystemExit when kustomize is missing."""

    def test_raises_when_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from hyperloop.compose import check_kustomize_available

        monkeypatch.setattr(shutil, "which", lambda _name: None)  # type: ignore[arg-type]

        with pytest.raises(SystemExit, match="kustomize CLI not found"):
            check_kustomize_available()


class TestParseProcess:
    """parse_process converts a multi-doc YAML string into Process domain objects."""

    BASE_PROCESS_YAML = """\
apiVersion: hyperloop.io/v1
kind: Process
metadata:
  name: default

pipeline:
  - loop:
      - agent: implementer
      - agent: verifier
  - action: merge-pr
"""

    def test_base_process_yaml_produces_correct_process(self) -> None:
        """parse_process on the base process.yaml produces correct Process with nested LoopStep."""
        from hyperloop.compose import parse_process
        from hyperloop.domain.model import ActionStep, AgentStep, LoopStep, Process

        process = parse_process(self.BASE_PROCESS_YAML)

        assert process is not None
        assert isinstance(process, Process)
        assert process.name == "default"

        # pipeline: [loop([implementer, verifier]), action(merge-pr)]
        assert len(process.pipeline) == 2
        loop = process.pipeline[0]
        assert isinstance(loop, LoopStep)
        assert len(loop.steps) == 2
        assert isinstance(loop.steps[0], AgentStep)
        assert loop.steps[0].agent == "implementer"
        assert isinstance(loop.steps[1], AgentStep)
        assert loop.steps[1].agent == "verifier"

        action = process.pipeline[1]
        assert isinstance(action, ActionStep)
        assert action.action == "merge-pr"

    def test_base_dir_process_yaml_matches(self) -> None:
        """parse_process on the real base/process.yaml file produces the default Process."""
        from hyperloop.compose import parse_process
        from hyperloop.domain.model import ActionStep, LoopStep

        process_yaml = (BASE_DIR / "process.yaml").read_text()
        process = parse_process(process_yaml)

        assert process is not None
        assert process.name == "default"
        assert len(process.pipeline) == 2
        assert isinstance(process.pipeline[0], LoopStep)
        assert isinstance(process.pipeline[1], ActionStep)

    def test_overridden_pipeline_no_loop(self) -> None:
        """parse_process with an overridden pipeline (no loop, just implementer + action)."""
        from hyperloop.compose import parse_process
        from hyperloop.domain.model import ActionStep, AgentStep

        yaml_input = """\
kind: Process
metadata:
  name: simple
pipeline:
  - agent: implementer
  - action: merge-pr
"""
        process = parse_process(yaml_input)

        assert process is not None
        assert process.name == "simple"
        assert len(process.pipeline) == 2
        assert isinstance(process.pipeline[0], AgentStep)
        assert process.pipeline[0].agent == "implementer"
        assert isinstance(process.pipeline[1], ActionStep)
        assert process.pipeline[1].action == "merge-pr"

    def test_no_process_doc_returns_none(self) -> None:
        """parse_process on YAML with no kind: Process doc returns None."""
        from hyperloop.compose import parse_process

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
        """parse_process on empty string returns None."""
        from hyperloop.compose import parse_process

        result = parse_process("")
        assert result is None

    def test_unknown_primitive_key_raises_value_error(self) -> None:
        """parse_process with an unknown primitive key raises ValueError."""
        from hyperloop.compose import parse_process

        yaml_input = """\
kind: Process
metadata:
  name: bad
pipeline:
  - unknown_key: something
"""
        with pytest.raises(ValueError, match="unknown_key"):
            parse_process(yaml_input)

    def test_multi_doc_yaml_finds_process(self) -> None:
        """parse_process finds the Process doc in multi-document YAML."""
        from hyperloop.compose import parse_process
        from hyperloop.domain.model import AgentStep

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
pipeline:
  - agent: implementer
"""
        process = parse_process(yaml_input)
        assert process is not None
        assert process.name == "default"
        assert len(process.pipeline) == 1
        assert isinstance(process.pipeline[0], AgentStep)
        assert process.pipeline[0].agent == "implementer"

    def test_nested_loops_parsed_recursively(self) -> None:
        """parse_process handles nested loops (loop within loop)."""
        from hyperloop.compose import parse_process
        from hyperloop.domain.model import ActionStep, AgentStep, LoopStep

        yaml_input = """\
kind: Process
metadata:
  name: nested
pipeline:
  - loop:
      - loop:
          - agent: implementer
          - agent: verifier
      - agent: reviewer
  - action: merge-pr
"""
        process = parse_process(yaml_input)
        assert process is not None
        outer_loop = process.pipeline[0]
        assert isinstance(outer_loop, LoopStep)
        inner_loop = outer_loop.steps[0]
        assert isinstance(inner_loop, LoopStep)
        assert isinstance(inner_loop.steps[0], AgentStep)
        assert inner_loop.steps[0].agent == "implementer"
        assert isinstance(outer_loop.steps[1], AgentStep)
        assert outer_loop.steps[1].agent == "reviewer"
        assert isinstance(process.pipeline[1], ActionStep)

    def test_gate_step_parsed(self) -> None:
        """parse_process handles gate steps."""
        from hyperloop.compose import parse_process
        from hyperloop.domain.model import GateStep

        yaml_input = """\
kind: Process
metadata:
  name: gated
intake: []
pipeline:
  - gate: pr-require-label
"""
        process = parse_process(yaml_input)
        assert process is not None
        assert len(process.pipeline) == 1
        assert isinstance(process.pipeline[0], GateStep)
        assert process.pipeline[0].gate == "pr-require-label"

    def test_agent_step_with_on_pass_on_fail(self) -> None:
        """parse_process populates on_pass and on_fail when present."""
        from hyperloop.compose import parse_process
        from hyperloop.domain.model import AgentStep

        yaml_input = """\
kind: Process
metadata:
  name: routing
pipeline:
  - agent: implementer
    on_pass: next
    on_fail: retry
"""
        process = parse_process(yaml_input)
        assert process is not None
        step = process.pipeline[0]
        assert isinstance(step, AgentStep)
        assert step.agent == "implementer"
        assert step.on_pass == "next"
        assert step.on_fail == "retry"


class TestLoadFromKustomize:
    """load_from_kustomize returns (PromptComposer, Process | None)."""

    @pytest.mark.skipif(
        not shutil.which("kustomize"),
        reason="kustomize CLI not available",
    )
    def test_returns_composer_and_process_when_process_doc_present(self, tmp_path: Path) -> None:
        """load_from_kustomize returns (PromptComposer, Process) when Process doc present."""
        import os

        rel_base = os.path.relpath(BASE_DIR, tmp_path)
        kustomization = tmp_path / "kustomization.yaml"
        kustomization.write_text(f"resources:\n  - {rel_base}\n")

        state = _state_with_spec()
        composer, process = PromptComposer.load_from_kustomize(str(tmp_path), state)

        assert isinstance(composer, PromptComposer)
        assert process is not None
        assert process.name == "default"
        from hyperloop.domain.model import ActionStep, LoopStep

        assert len(process.pipeline) == 2
        assert isinstance(process.pipeline[0], LoopStep)
        assert isinstance(process.pipeline[1], ActionStep)

    @pytest.mark.skipif(
        not shutil.which("kustomize"),
        reason="kustomize CLI not available",
    )
    def test_returns_none_process_when_no_process_doc(self, tmp_path: Path) -> None:
        """load_from_kustomize returns (PromptComposer, None) when no Process doc."""
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
