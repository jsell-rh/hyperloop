from __future__ import annotations

from pathlib import Path

import pytest

from hyperloop.reconciliation.adapters.kustomize_prompt_composer import (
    KustomizePromptComposer,
)
from hyperloop.reconciliation.models.agent_template import AgentTemplate
from hyperloop.reconciliation.models.compose_error import ComposeError
from hyperloop.reconciliation.models.missing_template_error import MissingTemplateError
from hyperloop.reconciliation.models.prompt_section import PromptSection
from tests.reconciliation.fakes.fake_kustomize_build_runner import (
    FakeKustomizeBuildRunner,
)
from tests.reconciliation.fakes.fake_observer import FakeObserver


def _make_composer(
    templates: list[AgentTemplate],
    observer: FakeObserver | None = None,
) -> tuple[KustomizePromptComposer, FakeKustomizeBuildRunner, FakeObserver]:
    runner = FakeKustomizeBuildRunner(templates)
    obs = observer or FakeObserver()
    composer = KustomizePromptComposer(
        overlay_path=Path("/fake/overlay"),
        kustomize_runner=runner,
        observer=obs,
    )
    return composer, runner, obs


class TestTemplateLoading:
    def test_loads_templates_from_kustomize_output(self) -> None:
        templates = [
            AgentTemplate(
                name="implementer", prompt="Implement the task.", guidelines=[]
            ),
            AgentTemplate(name="verifier", prompt="Verify the spec.", guidelines=[]),
        ]
        composer, _, _ = _make_composer(templates)

        result = composer.compose(
            "implementer",
            substitutions={},
            sections=[],
            epilogue="",
        )

        assert "Implement the task." in result

    def test_non_agent_kind_docs_are_skipped(self) -> None:
        raw_yaml = (
            "kind: Agent\nname: implementer\nprompt: Implement.\nguidelines: []\n"
            "---\n"
            "kind: ConfigMap\nname: settings\ndata: {}\n"
        )

        class DirectRunner:
            def __init__(self, yaml_output: str) -> None:
                self._yaml = yaml_output

            def build(self, path: Path) -> str:
                return self._yaml

        obs = FakeObserver()
        composer = KustomizePromptComposer(
            overlay_path=Path("/fake"),
            kustomize_runner=DirectRunner(raw_yaml),
            observer=obs,
        )

        result = composer.compose(
            "implementer",
            substitutions={},
            sections=[],
            epilogue="",
        )
        assert "Implement." in result
        with pytest.raises(MissingTemplateError):
            composer.compose("settings", substitutions={}, sections=[], epilogue="")

    def test_empty_yaml_output_produces_no_templates(self) -> None:
        class EmptyRunner:
            def build(self, path: Path) -> str:
                return ""

        obs = FakeObserver()
        composer = KustomizePromptComposer(
            overlay_path=Path("/fake"),
            kustomize_runner=EmptyRunner(),
            observer=obs,
        )

        rebuilt = obs.calls_for("composer_rebuilt")
        assert rebuilt[0]["template_count"] == 0

        with pytest.raises(MissingTemplateError):
            composer.compose("implementer", substitutions={}, sections=[], epilogue="")

    def test_base_layer_provides_identity_when_no_overlays(self) -> None:
        templates = [
            AgentTemplate(
                name="implementer",
                prompt="You are the implementer agent.",
                guidelines=[],
            ),
        ]
        composer, _, _ = _make_composer(templates)

        result = composer.compose(
            "implementer",
            substitutions={},
            sections=[],
            epilogue="",
        )

        assert "You are the implementer agent." in result


class TestSubstitution:
    def test_placeholders_resolved(self) -> None:
        templates = [
            AgentTemplate(
                name="implementer",
                prompt="Work on task {task_id} for spec {spec_ref}.",
                guidelines=[],
            ),
        ]
        composer, _, _ = _make_composer(templates)

        result = composer.compose(
            "implementer",
            substitutions={
                "task_id": "5",
                "spec_ref": "specs/auth.spec.md@abc123",
            },
            sections=[],
            epilogue="",
        )

        assert "Work on task 5 for spec specs/auth.spec.md@abc123." in result

    def test_unknown_placeholder_raises_compose_error(self) -> None:
        templates = [
            AgentTemplate(
                name="implementer",
                prompt="Work on {unknown_field}.",
                guidelines=[],
            ),
        ]
        composer, _, _ = _make_composer(templates)

        with pytest.raises(ComposeError) as exc_info:
            composer.compose(
                "implementer",
                substitutions={},
                sections=[],
                epilogue="",
            )

        assert "unknown_field" in str(exc_info.value)

    def test_extra_substitutions_are_ignored(self) -> None:
        templates = [
            AgentTemplate(
                name="implementer",
                prompt="Work on task {task_id}.",
                guidelines=[],
            ),
        ]
        composer, _, _ = _make_composer(templates)

        result = composer.compose(
            "implementer",
            substitutions={"task_id": "5", "extra_key": "ignored"},
            sections=[],
            epilogue="",
        )

        assert "Work on task 5." in result


class TestContextInjection:
    def test_first_round_task_prompt(self) -> None:
        templates = [
            AgentTemplate(
                name="implementer",
                prompt="Implement changes.",
                guidelines=["Write tests first"],
            ),
        ]
        composer, _, _ = _make_composer(templates)

        result = composer.compose(
            "implementer",
            substitutions={},
            sections=[
                PromptSection(heading="Spec", content="The auth spec content."),
            ],
            epilogue="",
        )

        assert "Implement changes." in result
        assert "Write tests first" in result
        assert "The auth spec content." in result
        assert "Events" not in result

    def test_retry_prompt_with_failure_context(self) -> None:
        templates = [
            AgentTemplate(
                name="implementer",
                prompt="Implement changes.",
                guidelines=[],
            ),
        ]
        composer, _, _ = _make_composer(templates)

        result = composer.compose(
            "implementer",
            substitutions={},
            sections=[
                PromptSection(heading="Spec", content="The auth spec content."),
                PromptSection(
                    heading="Events", content="TaskFailed: tests did not pass"
                ),
            ],
            epilogue="",
        )

        assert "The auth spec content." in result
        assert "Events" in result
        assert "TaskFailed: tests did not pass" in result

    def test_epilogue_injected_by_adapter(self) -> None:
        templates = [
            AgentTemplate(
                name="implementer",
                prompt="Implement changes.",
                guidelines=[],
            ),
        ]
        composer, _, _ = _make_composer(templates)

        result = composer.compose(
            "implementer",
            substitutions={},
            sections=[],
            epilogue="Signal completion with Task-Status: Complete",
        )

        assert "Signal completion with Task-Status: Complete" in result

    def test_no_epilogue_when_empty(self) -> None:
        templates = [
            AgentTemplate(
                name="implementer",
                prompt="Implement changes.",
                guidelines=[],
            ),
        ]
        composer, _, _ = _make_composer(templates)

        result = composer.compose(
            "implementer",
            substitutions={},
            sections=[],
            epilogue="",
        )

        assert "Epilogue" not in result

    def test_sections_appear_in_order(self) -> None:
        templates = [
            AgentTemplate(
                name="implementer",
                prompt="Implement.",
                guidelines=[],
            ),
        ]
        composer, _, _ = _make_composer(templates)

        result = composer.compose(
            "implementer",
            substitutions={},
            sections=[
                PromptSection(heading="Spec", content="spec content"),
                PromptSection(heading="Events", content="event content"),
            ],
            epilogue="epilogue content",
        )

        spec_pos = result.index("spec content")
        events_pos = result.index("event content")
        epilogue_pos = result.index("epilogue content")
        assert spec_pos < events_pos < epilogue_pos


class TestGuidelines:
    def test_guidelines_as_discrete_list_items(self) -> None:
        templates = [
            AgentTemplate(
                name="implementer",
                prompt="Implement.",
                guidelines=["Write tests first", "Follow coding standards"],
            ),
        ]
        composer, _, _ = _make_composer(templates)

        result = composer.compose(
            "implementer",
            substitutions={},
            sections=[],
            epilogue="",
        )

        assert "- Write tests first" in result
        assert "- Follow coding standards" in result

    def test_no_guidelines_section_when_empty(self) -> None:
        templates = [
            AgentTemplate(
                name="implementer",
                prompt="Implement.",
                guidelines=[],
            ),
        ]
        composer, _, _ = _make_composer(templates)

        result = composer.compose(
            "implementer",
            substitutions={},
            sections=[],
            epilogue="",
        )

        assert "Guidelines" not in result

    def test_guidelines_appear_between_prompt_and_sections(self) -> None:
        templates = [
            AgentTemplate(
                name="implementer",
                prompt="Implement.",
                guidelines=["Guideline one"],
            ),
        ]
        composer, _, _ = _make_composer(templates)

        result = composer.compose(
            "implementer",
            substitutions={},
            sections=[
                PromptSection(heading="Spec", content="spec content"),
            ],
            epilogue="",
        )

        prompt_pos = result.index("Implement.")
        guideline_pos = result.index("Guideline one")
        spec_pos = result.index("spec content")
        assert prompt_pos < guideline_pos < spec_pos


class TestValidation:
    def test_missing_template_raises_error(self) -> None:
        templates = [
            AgentTemplate(name="implementer", prompt="Implement.", guidelines=[]),
        ]
        composer, _, _ = _make_composer(templates)

        with pytest.raises(MissingTemplateError) as exc_info:
            composer.validate({"implementer", "verifier"})

        assert "verifier" in str(exc_info.value)

    def test_all_required_templates_present(self) -> None:
        templates = [
            AgentTemplate(name="implementer", prompt="Implement.", guidelines=[]),
            AgentTemplate(name="verifier", prompt="Verify.", guidelines=[]),
        ]
        composer, _, _ = _make_composer(templates)

        composer.validate({"implementer", "verifier"})

    def test_extra_templates_are_allowed(self) -> None:
        templates = [
            AgentTemplate(name="implementer", prompt="Implement.", guidelines=[]),
            AgentTemplate(name="verifier", prompt="Verify.", guidelines=[]),
            AgentTemplate(
                name="experimental-reviewer",
                prompt="Review.",
                guidelines=[],
            ),
        ]
        composer, _, _ = _make_composer(templates)

        composer.validate({"implementer", "verifier"})

    def test_compose_unknown_role_raises_missing_template_error(self) -> None:
        templates = [
            AgentTemplate(name="implementer", prompt="Implement.", guidelines=[]),
        ]
        composer, _, _ = _make_composer(templates)

        with pytest.raises(MissingTemplateError) as exc_info:
            composer.compose(
                "nonexistent",
                substitutions={},
                sections=[],
                epilogue="",
            )

        assert "nonexistent" in str(exc_info.value)


class TestHotReload:
    def test_rebuild_loads_new_templates(self) -> None:
        initial = [
            AgentTemplate(name="implementer", prompt="Old prompt.", guidelines=[]),
        ]
        composer, runner, _ = _make_composer(initial)

        runner.set_templates(
            [
                AgentTemplate(name="implementer", prompt="New prompt.", guidelines=[]),
            ]
        )
        composer.rebuild()

        result = composer.compose(
            "implementer",
            substitutions={},
            sections=[],
            epilogue="",
        )
        assert "New prompt." in result

    def test_rebuild_failure_retains_previous_templates(self) -> None:
        initial = [
            AgentTemplate(name="implementer", prompt="Good prompt.", guidelines=[]),
        ]
        composer, runner, _ = _make_composer(initial)

        runner.set_failure("kustomize build failed: invalid YAML")
        composer.rebuild()

        result = composer.compose(
            "implementer",
            substitutions={},
            sections=[],
            epilogue="",
        )
        assert "Good prompt." in result

    def test_rebuild_failure_emits_probe(self) -> None:
        initial = [
            AgentTemplate(name="implementer", prompt="Good prompt.", guidelines=[]),
        ]
        composer, runner, observer = _make_composer(initial)

        runner.set_failure("kustomize build failed")
        composer.rebuild()

        rebuild_failed = observer.calls_for("composer_rebuild_failed")
        assert len(rebuild_failed) == 1
        assert "kustomize build failed" in rebuild_failed[0]["reason"]

    def test_successful_rebuild_emits_probe(self) -> None:
        initial = [
            AgentTemplate(name="implementer", prompt="Prompt.", guidelines=[]),
        ]
        composer, runner, observer = _make_composer(initial)

        runner.set_templates(
            [
                AgentTemplate(name="implementer", prompt="Updated.", guidelines=[]),
                AgentTemplate(name="verifier", prompt="Verify.", guidelines=[]),
            ]
        )
        composer.rebuild()

        rebuilt = observer.calls_for("composer_rebuilt")
        assert len(rebuilt) == 2
        assert rebuilt[1]["template_count"] == 2

    def test_initial_build_emits_probe(self) -> None:
        templates = [
            AgentTemplate(name="implementer", prompt="Prompt.", guidelines=[]),
        ]
        _, _, observer = _make_composer(templates)

        rebuilt = observer.calls_for("composer_rebuilt")
        assert len(rebuilt) == 1
        assert rebuilt[0]["template_count"] == 1
