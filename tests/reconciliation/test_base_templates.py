from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from hyperloop.reconciliation.adapters.kustomize_prompt_composer import (
    KustomizePromptComposer,
)
from hyperloop.reconciliation.adapters.subprocess_kustomize_build_runner import (
    SubprocessKustomizeBuildRunner,
)
from hyperloop.reconciliation.models.agent_role import AgentRole
from hyperloop.reconciliation.models.template_kind import TemplateKind
from tests.reconciliation.fakes.fake_observer import FakeObserver

BASE_DIR = Path(__file__).resolve().parents[2] / "base"
ALL_ROLES = {role.value for role in AgentRole}


class TestBaseDirectoryStructure:
    def test_base_directory_exists(self) -> None:
        assert BASE_DIR.is_dir()

    def test_kustomization_yaml_exists(self) -> None:
        assert (BASE_DIR / "kustomization.yaml").is_file()

    def test_template_file_exists_for_each_role(self) -> None:
        for role in ALL_ROLES:
            path = BASE_DIR / f"{role}.yaml"
            assert path.is_file(), f"Missing template file: {path}"

    def test_kustomization_lists_all_role_files(self) -> None:
        kustomization = yaml.safe_load((BASE_DIR / "kustomization.yaml").read_text())
        resources = set(kustomization["resources"])
        expected = {f"{role}.yaml" for role in ALL_ROLES}
        assert resources == expected


class TestTemplateSchema:
    @pytest.fixture()
    def templates(self) -> dict[str, dict[str, object]]:
        result: dict[str, dict[str, object]] = {}
        for role in ALL_ROLES:
            doc = yaml.safe_load((BASE_DIR / f"{role}.yaml").read_text())
            result[role] = doc
        return result

    def test_each_template_has_kind_agent(
        self, templates: dict[str, dict[str, object]]
    ) -> None:
        for role, doc in templates.items():
            assert doc["kind"] == TemplateKind.AGENT, f"{role}: kind must be Agent"

    def test_each_template_name_matches_role(
        self, templates: dict[str, dict[str, object]]
    ) -> None:
        for role, doc in templates.items():
            assert doc["name"] == role, f"{role}: name must match role"

    def test_each_template_has_non_empty_prompt(
        self, templates: dict[str, dict[str, object]]
    ) -> None:
        for role, doc in templates.items():
            assert isinstance(doc["prompt"], str), f"{role}: prompt must be a string"
            assert doc["prompt"].strip(), f"{role}: prompt must not be empty"

    def test_each_template_has_empty_guidelines(
        self, templates: dict[str, dict[str, object]]
    ) -> None:
        for role, doc in templates.items():
            assert doc["guidelines"] == [], f"{role}: base guidelines must be empty"


class TestSubstitutionPlaceholders:
    def test_implementer_has_task_id_placeholder(self) -> None:
        doc = yaml.safe_load((BASE_DIR / "implementer.yaml").read_text())
        assert "{task_id}" in doc["prompt"]

    def test_implementer_has_spec_ref_placeholder(self) -> None:
        doc = yaml.safe_load((BASE_DIR / "implementer.yaml").read_text())
        assert "{spec_ref}" in doc["prompt"]

    def test_verifier_has_spec_ref_placeholder(self) -> None:
        doc = yaml.safe_load((BASE_DIR / "verifier.yaml").read_text())
        assert "{spec_ref}" in doc["prompt"]


def _make_composer_from_output(raw_yaml: str) -> KustomizePromptComposer:
    class FixedRunner:
        def __init__(self, output: str) -> None:
            self._output = output

        def build(self, path: Path) -> str:
            return self._output

    return KustomizePromptComposer(
        overlay_path=BASE_DIR,
        kustomize_runner=FixedRunner(raw_yaml),
        observer=FakeObserver(),
    )


_PROJECT_SPECIFIC_FILE_REFERENCES = [
    "AGENTS.md",
    "CLAUDE.md",
    "pyproject.toml",
    "Makefile",
    "Dockerfile",
    "package.json",
    "Cargo.toml",
    "go.mod",
]

_PROJECT_SPECIFIC_TESTING_TERMS = [
    "test driven development",
    "test-driven development",
    "tdd",
    "behavior driven development",
    "behavior-driven development",
    "bdd",
]

_PROJECT_SPECIFIC_TEST_DOUBLE_TERMS = [
    "fakes instead of mocks",
    "mocks instead of fakes",
    "use fakes",
    "use mocks",
    "no unittest.mock",
    "no MagicMock",
    "no patch",
]


class TestImplementerWorkflowPhases:
    """agent-prompts.spec.md — Requirement: Implementer Workflow.

    The implementer base prompt SHALL instruct the agent to follow a
    multi-phase workflow: understand, implement with tests, then self-critique.
    """

    @pytest.fixture()
    def implementer_prompt(self) -> str:
        doc = yaml.safe_load((BASE_DIR / "implementer.yaml").read_text())
        return doc["prompt"]

    def test_addresses_orientation_phase(self, implementer_prompt: str) -> None:
        prompt_lower = implementer_prompt.lower()
        assert any(
            phrase in prompt_lower
            for phrase in [
                "read the spec",
                "read the codebase",
                "orientation",
                "understand",
            ]
        ), (
            "Implementer prompt must address orientation: reading the spec and codebase before writing code"
        )

    def test_addresses_configuration_awareness(self, implementer_prompt: str) -> None:
        prompt_lower = implementer_prompt.lower()
        assert "configur" in prompt_lower, (
            "Implementer prompt must address configuration awareness"
        )

    def test_addresses_implementation_with_tests(self, implementer_prompt: str) -> None:
        prompt_lower = implementer_prompt.lower()
        assert "test" in prompt_lower, (
            "Implementer prompt must instruct the agent to write tests"
        )

    def test_addresses_atomic_commits(self, implementer_prompt: str) -> None:
        prompt_lower = implementer_prompt.lower()
        assert "atomic" in prompt_lower or "commit" in prompt_lower, (
            "Implementer prompt must address atomic commits"
        )

    def test_addresses_critic_pass(self, implementer_prompt: str) -> None:
        prompt_lower = implementer_prompt.lower()
        assert any(
            phrase in prompt_lower for phrase in ["critic", "self-review", "review"]
        ), "Implementer prompt must address a critic/self-review pass"

    def test_addresses_iterative_refinement(self, implementer_prompt: str) -> None:
        prompt_lower = implementer_prompt.lower()
        assert any(
            phrase in prompt_lower
            for phrase in ["refine", "iterate", "fix issues", "repeat"]
        ), "Implementer prompt must address iterative refinement"

    def test_orientation_appears_before_implementation(
        self, implementer_prompt: str
    ) -> None:
        prompt_lower = implementer_prompt.lower()
        orientation_phrases = ["read", "understand", "orientation"]
        implementation_phrases = ["implement", "write", "code"]

        orientation_pos = len(prompt_lower)
        for phrase in orientation_phrases:
            idx = prompt_lower.find(phrase)
            if idx >= 0:
                orientation_pos = min(orientation_pos, idx)

        implementation_pos = 0
        for phrase in implementation_phrases:
            idx = prompt_lower.find(phrase)
            if idx >= 0:
                implementation_pos = max(implementation_pos, idx)

        assert orientation_pos < implementation_pos, (
            "Orientation (reading spec/codebase) must appear before "
            "implementation instructions"
        )


class TestGenericPrompts:
    """agent-prompts.spec.md — Requirement: Generic Prompts.

    Base agent prompts SHALL NOT contain project-specific references.
    Testing methodology is a project-level concern.
    """

    @pytest.fixture()
    def prompts_by_role(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for role in ALL_ROLES:
            doc = yaml.safe_load((BASE_DIR / f"{role}.yaml").read_text())
            result[role] = doc["prompt"]
        return result

    def test_no_project_specific_file_references(
        self, prompts_by_role: dict[str, str]
    ) -> None:
        for role, prompt in prompts_by_role.items():
            for ref in _PROJECT_SPECIFIC_FILE_REFERENCES:
                assert ref not in prompt, (
                    f"{role}: base prompt must not reference project-specific "
                    f"file '{ref}'"
                )

    def test_no_specific_testing_methodology(
        self, prompts_by_role: dict[str, str]
    ) -> None:
        for role, prompt in prompts_by_role.items():
            prompt_lower = prompt.lower()
            for term in _PROJECT_SPECIFIC_TESTING_TERMS:
                assert term not in prompt_lower, (
                    f"{role}: base prompt must not specify testing methodology "
                    f"'{term}' — this belongs in the project overlay"
                )

    def test_no_specific_test_double_conventions(
        self, prompts_by_role: dict[str, str]
    ) -> None:
        for role, prompt in prompts_by_role.items():
            prompt_lower = prompt.lower()
            for term in _PROJECT_SPECIFIC_TEST_DOUBLE_TERMS:
                assert term.lower() not in prompt_lower, (
                    f"{role}: base prompt must not specify test double "
                    f"convention '{term}' — this belongs in the project overlay"
                )

    def test_prompts_are_language_agnostic(
        self, prompts_by_role: dict[str, str]
    ) -> None:
        language_specific_terms = [
            "python",
            "javascript",
            "typescript",
            "golang",
            "rustlang",
            "java ",
        ]
        for role, prompt in prompts_by_role.items():
            prompt_lower = prompt.lower()
            for term in language_specific_terms:
                assert term not in prompt_lower, (
                    f"{role}: base prompt must be language-agnostic, "
                    f"but contains '{term}'"
                )


OVERLAY_DIR = Path(__file__).resolve().parents[2] / ".hyperloop" / "agents"


class TestProjectOverlay:
    """prompt-composition.spec.md — Requirement: Three-Layer Composition.

    Project overlay adds project-specific guidelines via kustomize patches.
    """

    def test_overlay_directory_exists(self) -> None:
        assert OVERLAY_DIR.is_dir()

    def test_overlay_kustomization_exists(self) -> None:
        assert (OVERLAY_DIR / "kustomization.yaml").is_file()

    def test_implementer_patch_exists(self) -> None:
        assert (OVERLAY_DIR / "implementer-patch.yaml").is_file()

    def test_implementer_patch_has_agent_kind(self) -> None:
        doc = yaml.safe_load((OVERLAY_DIR / "implementer-patch.yaml").read_text())
        assert doc["kind"] == TemplateKind.AGENT

    def test_implementer_patch_targets_implementer(self) -> None:
        doc = yaml.safe_load((OVERLAY_DIR / "implementer-patch.yaml").read_text())
        assert doc["metadata"]["name"] == "implementer"

    def test_implementer_patch_has_guidelines(self) -> None:
        doc = yaml.safe_load((OVERLAY_DIR / "implementer-patch.yaml").read_text())
        guidelines = doc.get("guidelines", [])
        assert len(guidelines) > 0, "Patch must add at least one guideline"

    def test_patch_guidelines_contain_project_testing_methodology(self) -> None:
        doc = yaml.safe_load((OVERLAY_DIR / "implementer-patch.yaml").read_text())
        guidelines_text = " ".join(doc.get("guidelines", [])).lower()
        assert "tdd" in guidelines_text or "test-driven" in guidelines_text, (
            "Project overlay must specify the project's testing methodology"
        )

    def test_patch_guidelines_contain_test_double_convention(self) -> None:
        doc = yaml.safe_load((OVERLAY_DIR / "implementer-patch.yaml").read_text())
        guidelines_text = " ".join(doc.get("guidelines", [])).lower()
        assert "fake" in guidelines_text, (
            "Project overlay must specify the project's test double convention"
        )

    def test_kustomization_references_patch(self) -> None:
        kustomization = yaml.safe_load((OVERLAY_DIR / "kustomization.yaml").read_text())
        patches = kustomization.get("patches", [])
        patch_paths = [
            p.get("path", "") if isinstance(p, dict) else "" for p in patches
        ]
        assert "implementer-patch.yaml" in patch_paths

    def test_composed_prompt_includes_overlay_guidelines(self) -> None:
        base_doc = yaml.safe_load((BASE_DIR / "implementer.yaml").read_text())
        patch_doc = yaml.safe_load((OVERLAY_DIR / "implementer-patch.yaml").read_text())

        merged = {
            "kind": "Agent",
            "name": "implementer",
            "prompt": base_doc["prompt"],
            "guidelines": patch_doc["guidelines"],
        }
        raw_yaml = yaml.dump(merged, default_flow_style=False, allow_unicode=True)
        composer = _make_composer_from_output(raw_yaml)
        result = composer.compose(
            "implementer",
            substitutions={"task_id": "1", "spec_ref": "specs/test.spec.md@abc"},
            sections=[],
            epilogue="",
        )

        for guideline in patch_doc["guidelines"]:
            assert guideline in result, (
                f"Composed prompt must include overlay guideline: {guideline}"
            )


class TestKustomizeBuildIntegration:
    @pytest.fixture()
    def kustomize_output(self) -> str:
        runner = SubprocessKustomizeBuildRunner()
        return runner.build(BASE_DIR)

    def test_kustomize_build_produces_all_five_templates(
        self, kustomize_output: str
    ) -> None:
        docs = [
            doc
            for doc in yaml.safe_load_all(kustomize_output)
            if doc is not None and doc.get("kind") == TemplateKind.AGENT
        ]
        names = {doc["name"] for doc in docs}
        assert names == ALL_ROLES

    def test_composer_validates_with_all_required_roles(
        self, kustomize_output: str
    ) -> None:
        composer = _make_composer_from_output(kustomize_output)
        composer.validate(ALL_ROLES)

    def test_compose_implementer_resolves_placeholders(
        self, kustomize_output: str
    ) -> None:
        composer = _make_composer_from_output(kustomize_output)
        result = composer.compose(
            AgentRole.IMPLEMENTER,
            substitutions={
                "task_id": "5",
                "spec_ref": "specs/auth.spec.md@abc123",
            },
            sections=[],
            epilogue="",
        )
        assert "5" in result
        assert "specs/auth.spec.md@abc123" in result
        assert "{task_id}" not in result
        assert "{spec_ref}" not in result

    def test_compose_verifier_resolves_placeholders(
        self, kustomize_output: str
    ) -> None:
        composer = _make_composer_from_output(kustomize_output)
        result = composer.compose(
            AgentRole.VERIFIER,
            substitutions={
                "spec_ref": "specs/auth.spec.md@abc123",
            },
            sections=[],
            epilogue="",
        )
        assert "specs/auth.spec.md@abc123" in result
        assert "{spec_ref}" not in result

    def test_compose_each_role_produces_non_empty_prompt(
        self, kustomize_output: str
    ) -> None:
        composer = _make_composer_from_output(kustomize_output)

        substitutions: dict[str, dict[str, str]] = {
            AgentRole.IMPLEMENTER: {
                "task_id": "1",
                "spec_ref": "specs/test.spec.md@def456",
            },
            AgentRole.DECOMPOSER: {},
            AgentRole.VERIFIER: {"spec_ref": "specs/test.spec.md@def456"},
            AgentRole.MERGE_RESOLVER: {},
            AgentRole.INTEGRATION_SUMMARIZER: {},
        }

        for role in AgentRole:
            result = composer.compose(
                role,
                substitutions=substitutions[role],
                sections=[],
                epilogue="",
            )
            assert result.strip(), f"{role}: composed prompt must not be empty"
