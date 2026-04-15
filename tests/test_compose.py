"""Tests for prompt composition — base + overlay + task context.

Uses InMemoryStateStore with pre-loaded files. No real filesystem.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from k_orchestrate.compose import PromptComposer
from tests.fakes.state import InMemoryStateStore

# The base/ dir lives at the repo root, adjacent to src/
BASE_DIR = Path(__file__).parent.parent / "base"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
        composer = PromptComposer(base_dir=BASE_DIR, state=state)

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
        composer = PromptComposer(base_dir=BASE_DIR, state=state)

        result = composer.compose(
            role="implementer",
            task_id="task-001",
            spec_ref="specs/widget.md",
            findings="",
        )

        assert "Build a widget." in result

    def test_compose_includes_no_findings_when_empty(self) -> None:
        state = _state_with_spec()
        composer = PromptComposer(base_dir=BASE_DIR, state=state)

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
        composer = PromptComposer(base_dir=BASE_DIR, state=state)

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
        composer = PromptComposer(base_dir=BASE_DIR, state=state)

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

        composer = PromptComposer(base_dir=BASE_DIR, state=state)

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

        composer = PromptComposer(base_dir=BASE_DIR, state=state)

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
        composer = PromptComposer(base_dir=BASE_DIR, state=state)

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
        composer = PromptComposer(base_dir=BASE_DIR, state=state)

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
        composer = PromptComposer(base_dir=BASE_DIR, state=state)

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
        composer = PromptComposer(base_dir=BASE_DIR, state=state)

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
        composer = PromptComposer(base_dir=BASE_DIR, state=state)

        result = composer.compose(
            role=role,
            task_id="task-001",
            spec_ref="specs/widget.md",
            findings="",
        )

        assert len(result) > 0
