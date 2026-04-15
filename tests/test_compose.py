"""Tests for prompt composition — resolved templates + overlay + task context.

Uses InMemoryStateStore with pre-loaded files and pre-resolved AgentTemplate
objects. No kustomize dependency — unit tests skip the kustomize build step.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from hyperloop.compose import AgentTemplate, PromptComposer, load_templates_from_dir
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

        result = composer.compose(
            role="implementer",
            task_id="task-001",
            spec_ref="specs/widget.md",
            findings="",
        )

        # Base prompt content should be present
        assert "You are a worker agent implementing a task" in result

    def test_compose_includes_spec_content(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        result = composer.compose(
            role="implementer",
            task_id="task-001",
            spec_ref="specs/widget.md",
            findings="",
        )

        assert "Build a widget." in result

    def test_compose_includes_no_findings_when_empty(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        result = composer.compose(
            role="implementer",
            task_id="task-001",
            spec_ref="specs/widget.md",
            findings="",
        )

        # Should not have a findings section with content
        assert "## Findings" not in result or result.split("## Findings")[-1].strip() == ""


class TestTemplateVariables:
    """Template variables {spec_ref} and {task_id} are replaced."""

    def test_spec_ref_is_replaced(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        result = composer.compose(
            role="implementer",
            task_id="task-027",
            spec_ref="specs/persistence.md",
            findings="",
        )

        assert "specs/persistence.md" in result
        assert "{spec_ref}" not in result

    def test_task_id_is_replaced(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        result = composer.compose(
            role="implementer",
            task_id="task-027",
            spec_ref="specs/persistence.md",
            findings="",
        )

        assert "task-027" in result
        assert "{task_id}" not in result


class TestProcessOverlay:
    """Compose with process overlay present in specs/prompts/."""

    def test_overlay_content_is_included(self) -> None:
        state = _state_with_spec()
        overlay_content = "prompt: |\n  Always run linter before submitting.\n"
        state.set_file("specs/prompts/implementer-overlay.yaml", overlay_content)

        composer = PromptComposer(templates=_templates(), state=state)

        result = composer.compose(
            role="implementer",
            task_id="task-001",
            spec_ref="specs/widget.md",
            findings="",
        )

        assert "Always run linter before submitting." in result

    def test_no_overlay_still_composes(self) -> None:
        """When no overlay file exists, composition still succeeds."""
        state = _state_with_spec()
        # No overlay file set

        composer = PromptComposer(templates=_templates(), state=state)

        result = composer.compose(
            role="implementer",
            task_id="task-001",
            spec_ref="specs/widget.md",
            findings="",
        )

        # Should still have the base prompt
        assert "You are a worker agent implementing a task" in result


class TestFindings:
    """Compose with findings from prior round."""

    def test_findings_are_appended(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        result = composer.compose(
            role="implementer",
            task_id="task-001",
            spec_ref="specs/widget.md",
            findings="Test suite failed: missing null check in widget.py line 42",
        )

        assert "Test suite failed: missing null check in widget.py line 42" in result
        assert "## Findings" in result


class TestUnknownRole:
    """Unknown role raises a clear error."""

    def test_unknown_role_raises_value_error(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(templates=_templates(), state=state)

        with pytest.raises(ValueError, match=r"(?i)unknown.*role.*nonexistent"):
            composer.compose(
                role="nonexistent",
                task_id="task-001",
                spec_ref="specs/widget.md",
                findings="",
            )


class TestMissingSpecRef:
    """Missing spec_ref file is gracefully handled — still composes, notes missing spec."""

    def test_missing_spec_still_composes(self) -> None:
        state = InMemoryStateStore()
        # No spec file set — spec_ref points to nothing
        composer = PromptComposer(templates=_templates(), state=state)

        result = composer.compose(
            role="implementer",
            task_id="task-001",
            spec_ref="specs/nonexistent.md",
            findings="",
        )

        # Should still compose with the base prompt
        assert "You are a worker agent implementing a task" in result

    def test_missing_spec_notes_absence(self) -> None:
        state = InMemoryStateStore()
        composer = PromptComposer(templates=_templates(), state=state)

        result = composer.compose(
            role="implementer",
            task_id="task-001",
            spec_ref="specs/nonexistent.md",
            findings="",
        )

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

        result = composer.compose(
            role=role,
            task_id="task-001",
            spec_ref="specs/widget.md",
            findings="",
        )

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

        result = composer.compose(
            role="implementer",
            task_id="task-001",
            spec_ref="specs/widget.md",
            findings="",
        )
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

        result = composer.compose(
            role="implementer",
            task_id="task-001",
            spec_ref="specs/widget.md",
            findings="",
        )
        assert len(result) > 0


class TestCheckKustomize:
    """check_kustomize_available raises SystemExit when kustomize is missing."""

    def test_raises_when_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from hyperloop.compose import check_kustomize_available

        monkeypatch.setattr(shutil, "which", lambda _name: None)

        with pytest.raises(SystemExit, match="kustomize CLI not found"):
            check_kustomize_available()
