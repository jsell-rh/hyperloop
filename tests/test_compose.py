"""Tests for prompt composition — resolved templates + overlay + task context.

Uses InMemoryStateStore with pre-loaded files and pre-resolved AgentTemplate
objects. No kustomize dependency — unit tests skip the kustomize build step.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from hyperloop.compose import AgentTemplate, PromptComposer, load_templates_from_dir
from hyperloop.domain.model import ImprovementContext, IntakeContext, TaskContext
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

    def test_compose_returns_base_prompt_content(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(task_id="task-001", spec_ref="specs/widget.md", findings="")
        result = composer.compose(role="implementer", context=ctx)

        # Base prompt content should be present
        assert "You are a worker agent implementing a task" in result

    def test_compose_includes_spec_content(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(task_id="task-001", spec_ref="specs/widget.md", findings="")
        result = composer.compose(role="implementer", context=ctx)

        assert "Build a widget." in result

    def test_compose_includes_no_findings_when_empty(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(task_id="task-001", spec_ref="specs/widget.md", findings="")
        result = composer.compose(role="implementer", context=ctx)

        # Should not have a findings section with content
        assert "## Findings" not in result or result.split("## Findings")[-1].strip() == ""


class TestTemplateVariables:
    """Template variables {spec_ref} and {task_id} are replaced."""

    def test_spec_ref_is_replaced(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(task_id="task-027", spec_ref="specs/persistence.md", findings="")
        result = composer.compose(role="implementer", context=ctx)

        assert "specs/persistence.md" in result
        assert "{spec_ref}" not in result

    def test_task_id_is_replaced(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(task_id="task-027", spec_ref="specs/persistence.md", findings="")
        result = composer.compose(role="implementer", context=ctx)

        assert "task-027" in result
        assert "{task_id}" not in result


class TestProcessOverlay:
    """Compose with process overlay present in specs/prompts/."""

    def test_overlay_content_is_included(self) -> None:
        state = _state_with_spec()
        overlay_content = "prompt: |\n  Always run linter before submitting.\n"
        state.set_file("specs/prompts/implementer-overlay.yaml", overlay_content)

        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(task_id="task-001", spec_ref="specs/widget.md", findings="")
        result = composer.compose(role="implementer", context=ctx)

        assert "Always run linter before submitting." in result

    def test_no_overlay_still_composes(self) -> None:
        """When no overlay file exists, composition still succeeds."""
        state = _state_with_spec()
        # No overlay file set

        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(task_id="task-001", spec_ref="specs/widget.md", findings="")
        result = composer.compose(role="implementer", context=ctx)

        # Should still have the base prompt
        assert "You are a worker agent implementing a task" in result


class TestFindings:
    """Compose with findings from prior round."""

    def test_findings_are_appended(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(
            task_id="task-001",
            spec_ref="specs/widget.md",
            findings="Test suite failed: missing null check in widget.py line 42",
        )
        result = composer.compose(role="implementer", context=ctx)

        assert "Test suite failed: missing null check in widget.py line 42" in result
        assert "## Findings" in result


class TestUnknownRole:
    """Unknown role raises a clear error."""

    def test_unknown_role_raises_value_error(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(task_id="task-001", spec_ref="specs/widget.md", findings="")
        with pytest.raises(ValueError, match=r"(?i)unknown.*role.*nonexistent"):
            composer.compose(role="nonexistent", context=ctx)


class TestMissingSpecRef:
    """Missing spec_ref file is gracefully handled — still composes, notes missing spec."""

    def test_missing_spec_still_composes(self) -> None:
        state = InMemoryStateStore()
        # No spec file set — spec_ref points to nothing
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(task_id="task-001", spec_ref="specs/nonexistent.md", findings="")
        result = composer.compose(role="implementer", context=ctx)

        # Should still compose with the base prompt
        assert "You are a worker agent implementing a task" in result

    def test_missing_spec_notes_absence(self) -> None:
        state = InMemoryStateStore()
        composer = PromptComposer(templates=_templates(), state=state)

        ctx = TaskContext(task_id="task-001", spec_ref="specs/nonexistent.md", findings="")
        result = composer.compose(role="implementer", context=ctx)

        # Should note that the spec file could not be read
        assert (
            "not found" in result.lower()
            or "could not" in result.lower()
            or "missing" in result.lower()
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
            ctx = TaskContext(task_id="task-001", spec_ref="specs/widget.md", findings="")

        result = composer.compose(role=role, context=ctx)

        assert len(result) > 0


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

    def test_template_has_annotations(self) -> None:
        templates = load_templates_from_dir(BASE_DIR)
        impl = templates["implementer"]
        assert "ambient.io/persona" in impl.annotations


class TestAgentTemplate:
    """AgentTemplate is a frozen dataclass."""

    def test_frozen(self) -> None:
        t = AgentTemplate(name="test", prompt="hello", annotations={})
        with pytest.raises(AttributeError):
            t.name = "other"  # type: ignore[misc]

    def test_equality(self) -> None:
        a = AgentTemplate(name="x", prompt="p", annotations={"k": "v"})
        b = AgentTemplate(name="x", prompt="p", annotations={"k": "v"})
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

        ctx = TaskContext(task_id="task-001", spec_ref="specs/widget.md", findings="")
        result = composer.compose(role="implementer", context=ctx)
        assert "You are a worker agent implementing a task" in result

    @pytest.mark.skipif(
        not shutil.which("kustomize"),
        reason="kustomize CLI not available",
    )
    def test_from_kustomize_no_overlay_fetches_base(self) -> None:
        """When overlay is None, builds from the hyperloop base remote resource."""
        state = _state_with_spec()
        # This actually hits GitHub — skip in CI if network is unavailable
        try:
            composer = PromptComposer.from_kustomize(None, state)
        except RuntimeError:
            pytest.skip("Network unavailable — cannot fetch remote base")

        ctx = TaskContext(task_id="task-001", spec_ref="specs/widget.md", findings="")
        result = composer.compose(role="implementer", context=ctx)
        assert len(result) > 0


class TestCheckKustomize:
    """check_kustomize_available raises SystemExit when kustomize is missing."""

    def test_raises_when_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from hyperloop.compose import check_kustomize_available

        monkeypatch.setattr(shutil, "which", lambda _name: None)

        with pytest.raises(SystemExit, match="kustomize CLI not found"):
            check_kustomize_available()


class TestParseProcess:
    """parse_process converts a multi-doc YAML string into Process domain objects."""

    BASE_PROCESS_YAML = """\
apiVersion: hyperloop.io/v1
kind: Process
metadata:
  name: default

intake:
  - role: pm

pipeline:
  - loop:
      - role: implementer
      - role: verifier
  - action: merge-pr
"""

    def test_base_process_yaml_produces_correct_process(self) -> None:
        """parse_process on the base process.yaml produces correct Process with nested LoopStep."""
        from hyperloop.compose import parse_process
        from hyperloop.domain.model import ActionStep, LoopStep, Process, RoleStep

        process = parse_process(self.BASE_PROCESS_YAML)

        assert process is not None
        assert isinstance(process, Process)
        assert process.name == "default"

        # intake: [role: pm]
        assert len(process.intake) == 1
        assert isinstance(process.intake[0], RoleStep)
        assert process.intake[0].role == "pm"
        assert process.intake[0].on_pass is None
        assert process.intake[0].on_fail is None

        # pipeline: [loop([implementer, verifier]), action(merge-pr)]
        assert len(process.pipeline) == 2
        loop = process.pipeline[0]
        assert isinstance(loop, LoopStep)
        assert len(loop.steps) == 2
        assert isinstance(loop.steps[0], RoleStep)
        assert loop.steps[0].role == "implementer"
        assert isinstance(loop.steps[1], RoleStep)
        assert loop.steps[1].role == "verifier"

        action = process.pipeline[1]
        assert isinstance(action, ActionStep)
        assert action.action == "merge-pr"

    def test_base_dir_process_yaml_matches(self) -> None:
        """parse_process on the real base/process.yaml file produces the default Process."""
        from hyperloop.compose import parse_process
        from hyperloop.domain.model import ActionStep, LoopStep, RoleStep

        process_yaml = (BASE_DIR / "process.yaml").read_text()
        process = parse_process(process_yaml)

        assert process is not None
        assert process.name == "default"
        assert len(process.intake) == 1
        assert isinstance(process.intake[0], RoleStep)
        assert process.intake[0].role == "pm"
        assert len(process.pipeline) == 2
        assert isinstance(process.pipeline[0], LoopStep)
        assert isinstance(process.pipeline[1], ActionStep)

    def test_overridden_pipeline_no_loop(self) -> None:
        """parse_process with an overridden pipeline (no loop, just implementer + action)."""
        from hyperloop.compose import parse_process
        from hyperloop.domain.model import ActionStep, RoleStep

        yaml_input = """\
kind: Process
metadata:
  name: simple
intake: []
pipeline:
  - role: implementer
  - action: merge-pr
"""
        process = parse_process(yaml_input)

        assert process is not None
        assert process.name == "simple"
        assert len(process.pipeline) == 2
        assert isinstance(process.pipeline[0], RoleStep)
        assert process.pipeline[0].role == "implementer"
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
        from hyperloop.domain.model import RoleStep

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
intake: []
pipeline:
  - role: implementer
"""
        process = parse_process(yaml_input)
        assert process is not None
        assert process.name == "default"
        assert len(process.pipeline) == 1
        assert isinstance(process.pipeline[0], RoleStep)
        assert process.pipeline[0].role == "implementer"

    def test_nested_loops_parsed_recursively(self) -> None:
        """parse_process handles nested loops (loop within loop)."""
        from hyperloop.compose import parse_process
        from hyperloop.domain.model import ActionStep, LoopStep, RoleStep

        yaml_input = """\
kind: Process
metadata:
  name: nested
intake: []
pipeline:
  - loop:
      - loop:
          - role: implementer
          - role: verifier
      - role: reviewer
  - action: merge-pr
"""
        process = parse_process(yaml_input)
        assert process is not None
        outer_loop = process.pipeline[0]
        assert isinstance(outer_loop, LoopStep)
        inner_loop = outer_loop.steps[0]
        assert isinstance(inner_loop, LoopStep)
        assert isinstance(inner_loop.steps[0], RoleStep)
        assert inner_loop.steps[0].role == "implementer"
        assert isinstance(outer_loop.steps[1], RoleStep)
        assert outer_loop.steps[1].role == "reviewer"
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
  - gate: human-pr-approval
"""
        process = parse_process(yaml_input)
        assert process is not None
        assert len(process.pipeline) == 1
        assert isinstance(process.pipeline[0], GateStep)
        assert process.pipeline[0].gate == "human-pr-approval"

    def test_role_step_with_on_pass_on_fail(self) -> None:
        """parse_process populates on_pass and on_fail when present."""
        from hyperloop.compose import parse_process
        from hyperloop.domain.model import RoleStep

        yaml_input = """\
kind: Process
metadata:
  name: routing
intake: []
pipeline:
  - role: implementer
    on_pass: next
    on_fail: retry
"""
        process = parse_process(yaml_input)
        assert process is not None
        step = process.pipeline[0]
        assert isinstance(step, RoleStep)
        assert step.role == "implementer"
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
