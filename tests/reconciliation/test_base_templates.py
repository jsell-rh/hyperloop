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


class TestDecomposerWorkflowPhases:
    """agent-prompts.spec.md — Requirement: Decomposer Workflow.

    The decomposer base prompt SHALL instruct the agent to follow a
    read-first, dependency-ordered decomposition workflow.
    """

    @pytest.fixture()
    def decomposer_prompt(self) -> str:
        doc = yaml.safe_load((BASE_DIR / "decomposer.yaml").read_text())
        return doc["prompt"]

    def test_addresses_read_specs_phase(self, decomposer_prompt: str) -> None:
        prompt_lower = decomposer_prompt.lower()
        assert any(
            phrase in prompt_lower
            for phrase in ["read each spec", "read the spec", "read specs"]
        ), "Decomposer prompt must address reading specs"

    def test_addresses_read_diffs_phase(self, decomposer_prompt: str) -> None:
        prompt_lower = decomposer_prompt.lower()
        assert "diff" in prompt_lower, (
            "Decomposer prompt must address reading diffs for modified specs"
        )

    def test_addresses_read_implementation_phase(self, decomposer_prompt: str) -> None:
        prompt_lower = decomposer_prompt.lower()
        assert any(
            phrase in prompt_lower
            for phrase in [
                "read the current",
                "current implementation",
                "current codebase",
                "existing code",
            ]
        ), "Decomposer prompt must address reading current implementation"

    def test_addresses_prior_failures_phase(self, decomposer_prompt: str) -> None:
        prompt_lower = decomposer_prompt.lower()
        assert any(
            phrase in prompt_lower
            for phrase in ["prior failure", "prior event", "verification fail"]
        ), (
            "Decomposer prompt must address checking for prior failures "
            "and producing targeted corrective tasks"
        )

    def test_prior_failures_instruct_targeted_corrective_tasks(
        self, decomposer_prompt: str
    ) -> None:
        prompt_lower = decomposer_prompt.lower()
        assert any(
            phrase in prompt_lower
            for phrase in [
                "targeted corrective",
                "corrective task",
                "only tasks that address",
                "only targeted",
            ]
        ), (
            "Decomposer prompt must instruct producing only targeted corrective "
            "tasks when prior failures exist, not re-decomposing from scratch"
        )

    def test_prior_failures_instruct_no_duplication(
        self, decomposer_prompt: str
    ) -> None:
        prompt_lower = decomposer_prompt.lower()
        assert any(
            phrase in prompt_lower
            for phrase in [
                "do not duplicate",
                "not duplicate work",
                "already succeeded",
                "not re-decompos",
            ]
        ), "Decomposer prompt must instruct not duplicating work that already succeeded"

    def test_addresses_cross_spec_dependency_awareness(
        self, decomposer_prompt: str
    ) -> None:
        prompt_lower = decomposer_prompt.lower()
        assert any(
            phrase in prompt_lower
            for phrase in [
                "cross-spec",
                "existing tasks from other specs",
                "other specs",
            ]
        ), "Decomposer prompt must address cross-spec dependency awareness"

    def test_cross_spec_instructs_declaring_dependencies(
        self, decomposer_prompt: str
    ) -> None:
        prompt_lower = decomposer_prompt.lower()
        assert any(
            phrase in prompt_lower
            for phrase in [
                "cross-spec dependenc",
                "declare depend",
                "reference existing tasks",
            ]
        ), (
            "Decomposer prompt must instruct declaring cross-spec dependencies "
            "when proposed tasks depend on work from another spec"
        )

    def test_addresses_gap_analysis_phase(self, decomposer_prompt: str) -> None:
        prompt_lower = decomposer_prompt.lower()
        assert "gap" in prompt_lower, "Decomposer prompt must address gap analysis"

    def test_addresses_dependency_ordering_phase(self, decomposer_prompt: str) -> None:
        prompt_lower = decomposer_prompt.lower()
        assert any(
            phrase in prompt_lower for phrase in ["depend", "order", "blocking"]
        ), "Decomposer prompt must address dependency ordering"

    def test_addresses_proposed_task_formatting_phase(
        self, decomposer_prompt: str
    ) -> None:
        prompt_lower = decomposer_prompt.lower()
        assert "testing scenario" in prompt_lower or (
            "test" in prompt_lower and "scenario" in prompt_lower
        ), (
            "Decomposer prompt must instruct including testing scenarios "
            "in proposed tasks"
        )

    def test_diff_scoping_instructs_only_changed_requirements(
        self, decomposer_prompt: str
    ) -> None:
        prompt_lower = decomposer_prompt.lower()
        assert any(
            phrase in prompt_lower
            for phrase in [
                "scope",
                "only what changed",
                "only the requirements that changed",
                "changed requirements",
            ]
        ), (
            "Decomposer prompt must instruct scoping to only "
            "changed requirements when a diff is provided"
        )

    def test_reading_phases_appear_before_gap_analysis(
        self, decomposer_prompt: str
    ) -> None:
        prompt_lower = decomposer_prompt.lower()
        read_pos = prompt_lower.find("read")
        gap_pos = prompt_lower.find("gap")
        assert read_pos >= 0 and gap_pos >= 0, (
            "Decomposer prompt must contain both reading and gap analysis phases"
        )
        assert read_pos < gap_pos, "Reading phases must appear before gap analysis"


class TestVerifierWorkflowConcerns:
    """agent-prompts.spec.md — Requirement: Verifier Workflow.

    The verifier base prompt SHALL instruct the agent to systematically
    check every spec requirement against the implementation.
    """

    @pytest.fixture()
    def verifier_prompt(self) -> str:
        doc = yaml.safe_load((BASE_DIR / "verifier.yaml").read_text())
        return doc["prompt"]

    def test_addresses_requirement_enumeration(self, verifier_prompt: str) -> None:
        prompt_lower = verifier_prompt.lower()
        assert any(
            phrase in prompt_lower
            for phrase in [
                "every requirement",
                "every scenario",
                "each requirement",
                "each scenario",
                "all requirements",
                "all scenarios",
            ]
        ), (
            "Verifier prompt must instruct the agent to check every requirement "
            "and every scenario in the spec, not just a sample"
        )

    def test_addresses_not_just_a_sample(self, verifier_prompt: str) -> None:
        prompt_lower = verifier_prompt.lower()
        assert any(
            phrase in prompt_lower
            for phrase in [
                "not a sample",
                "not just a sample",
                "do not skip",
                "do not sample",
                "none may be skipped",
            ]
        ), (
            "Verifier prompt must explicitly instruct against sampling or "
            "skipping requirements"
        )

    def test_addresses_evidence_based_assessment(self, verifier_prompt: str) -> None:
        prompt_lower = verifier_prompt.lower()
        assert any(
            phrase in prompt_lower
            for phrase in [
                "cite",
                "reference",
                "specific code location",
                "specific file",
                "evidence",
            ]
        ), (
            "Verifier prompt must instruct the agent to cite specific code "
            "locations that satisfy or violate each requirement"
        )

    def test_addresses_test_execution(self, verifier_prompt: str) -> None:
        prompt_lower = verifier_prompt.lower()
        assert any(
            phrase in prompt_lower
            for phrase in [
                "run the test",
                "run tests",
                "execute the test",
                "execute tests",
            ]
        ), "Verifier prompt must instruct the agent to run the test suite"

    def test_addresses_test_result_reporting(self, verifier_prompt: str) -> None:
        prompt_lower = verifier_prompt.lower()
        assert any(
            phrase in prompt_lower
            for phrase in [
                "report the results",
                "include the results",
                "report results",
                "include results",
            ]
        ), (
            "Verifier prompt must instruct the agent to report or include "
            "the test results in its assessment"
        )

    def test_addresses_actionable_rationale(self, verifier_prompt: str) -> None:
        prompt_lower = verifier_prompt.lower()
        assert any(
            phrase in prompt_lower
            for phrase in [
                "actionable",
                "corrective task",
                "targeted task",
                "decomposer",
            ]
        ), (
            "Verifier prompt must instruct the agent to provide actionable "
            "rationale that can drive targeted corrective tasks"
        )

    def test_addresses_verdict(self, verifier_prompt: str) -> None:
        prompt_lower = verifier_prompt.lower()
        assert "pass" in prompt_lower and "fail" in prompt_lower, (
            "Verifier prompt must instruct the agent to report PASS or FAIL"
        )

    def test_verdict_fail_includes_per_requirement_rationale(
        self, verifier_prompt: str
    ) -> None:
        prompt_lower = verifier_prompt.lower()
        assert any(
            phrase in prompt_lower
            for phrase in [
                "rationale per unmet requirement",
                "per unmet requirement",
                "per requirement",
                "each unmet requirement",
            ]
        ), (
            "Verifier prompt must instruct the agent to provide detailed "
            "rationale per unmet requirement when reporting FAIL"
        )

    def test_verdict_requires_all_requirements_met_for_pass(
        self, verifier_prompt: str
    ) -> None:
        prompt_lower = verifier_prompt.lower()
        assert any(
            phrase in prompt_lower
            for phrase in [
                "pass only if all",
                "pass only when all",
                "all requirements are met",
                "all requirements are satisfied",
            ]
        ), (
            "Verifier prompt must instruct the agent to report PASS only if "
            "all requirements are met"
        )

    def test_requirement_enumeration_appears_before_verdict(
        self, verifier_prompt: str
    ) -> None:
        prompt_lower = verifier_prompt.lower()
        enumeration_phrases = [
            "every requirement",
            "each requirement",
            "all requirements and",
        ]
        verdict_phrases = ["verdict", "report pass", "report fail"]

        enumeration_pos = len(prompt_lower)
        for phrase in enumeration_phrases:
            idx = prompt_lower.find(phrase)
            if idx >= 0:
                enumeration_pos = min(enumeration_pos, idx)

        verdict_pos = 0
        for phrase in verdict_phrases:
            idx = prompt_lower.find(phrase)
            if idx >= 0:
                verdict_pos = max(verdict_pos, idx)

        assert enumeration_pos < len(prompt_lower) and verdict_pos > 0, (
            "Verifier prompt must contain both enumeration and verdict phases"
        )
        assert enumeration_pos < verdict_pos, (
            "Requirement enumeration must appear before the verdict instruction"
        )


class TestMergeResolverWorkflowConcerns:
    """agent-prompts.spec.md — Requirement: Merge Resolver Workflow.

    The merge resolver base prompt SHALL instruct the agent to resolve
    conflicts while preserving the intent of both contributions.
    """

    @pytest.fixture()
    def merge_resolver_prompt(self) -> str:
        doc = yaml.safe_load((BASE_DIR / "merge-resolver.yaml").read_text())
        return doc["prompt"]

    def test_addresses_intent_preservation(self, merge_resolver_prompt: str) -> None:
        prompt_lower = merge_resolver_prompt.lower()
        assert any(
            phrase in prompt_lower
            for phrase in [
                "intent",
                "purpose of changes",
                "understand",
                "both sides",
            ]
        ), (
            "Merge resolver prompt must instruct the agent to understand "
            "the intent/purpose of changes on both sides before resolving"
        )

    def test_addresses_correctness_verification(
        self, merge_resolver_prompt: str
    ) -> None:
        prompt_lower = merge_resolver_prompt.lower()
        assert any(
            phrase in prompt_lower
            for phrase in [
                "tests pass",
                "test suite",
                "compiles",
                "builds",
            ]
        ), (
            "Merge resolver prompt must instruct the agent to ensure the "
            "merged result builds successfully and tests pass"
        )

    def test_addresses_newer_wins_tiebreaker(self, merge_resolver_prompt: str) -> None:
        prompt_lower = merge_resolver_prompt.lower()
        assert any(
            phrase in prompt_lower
            for phrase in [
                "newer",
                "latest",
                "most recent",
            ]
        ), (
            "Merge resolver prompt must instruct the agent to prefer the "
            "newer task's intent when contributions are genuinely incompatible"
        )

    def test_addresses_preserving_both_contributions(
        self, merge_resolver_prompt: str
    ) -> None:
        prompt_lower = merge_resolver_prompt.lower()
        assert any(
            phrase in prompt_lower
            for phrase in [
                "preserve",
                "both contributions",
                "do not discard",
                "both sides",
            ]
        ), (
            "Merge resolver prompt must instruct the agent to preserve "
            "both contributions rather than discarding one side"
        )

    def test_intent_understanding_appears_before_resolution(
        self, merge_resolver_prompt: str
    ) -> None:
        prompt_lower = merge_resolver_prompt.lower()
        understanding_phrases = ["understanding", "understand", "intent"]
        resolution_phrases = ["resolve", "ensure", "after resolving"]

        understanding_pos = len(prompt_lower)
        for phrase in understanding_phrases:
            idx = prompt_lower.find(phrase)
            if idx >= 0:
                understanding_pos = min(understanding_pos, idx)

        resolution_pos = 0
        for phrase in resolution_phrases:
            idx = prompt_lower.find(phrase)
            if idx >= 0:
                resolution_pos = max(resolution_pos, idx)

        assert understanding_pos < len(prompt_lower) and resolution_pos > 0, (
            "Merge resolver prompt must contain both understanding and "
            "resolution phases"
        )
        assert understanding_pos < resolution_pos, (
            "Understanding intent must appear before resolution/verification "
            "instructions"
        )


class TestIntegrationSummarizerWorkflowConcerns:
    """agent-prompts.spec.md — Requirement: Integration Summarizer Workflow.

    The integration summarizer base prompt SHALL instruct the agent to
    produce a structured summary suitable for a pull request.
    """

    @pytest.fixture()
    def summarizer_prompt(self) -> str:
        doc = yaml.safe_load((BASE_DIR / "integration-summarizer.yaml").read_text())
        return doc["prompt"]

    def test_addresses_audience(self, summarizer_prompt: str) -> None:
        prompt_lower = summarizer_prompt.lower()
        assert any(
            phrase in prompt_lower
            for phrase in [
                "reviewer",
                "human",
                "reader",
            ]
        ), (
            "Integration summarizer prompt must address the audience — "
            "human reviewers who have not seen the individual tasks"
        )

    def test_addresses_structure(self, summarizer_prompt: str) -> None:
        prompt_lower = summarizer_prompt.lower()
        assert "title" in prompt_lower and "body" in prompt_lower, (
            "Integration summarizer prompt must instruct the agent to "
            "produce a PR title and body"
        )

    def test_addresses_scope_clarity(self, summarizer_prompt: str) -> None:
        prompt_lower = summarizer_prompt.lower()
        assert any(
            phrase in prompt_lower
            for phrase in [
                "what changed",
                "scope",
                "explains",
                "understand",
            ]
        ), (
            "Integration summarizer prompt must instruct the agent to explain "
            "what changed and why, without requiring the reader to inspect "
            "every file"
        )

    def test_addresses_traceability(self, summarizer_prompt: str) -> None:
        prompt_lower = summarizer_prompt.lower()
        assert any(
            phrase in prompt_lower
            for phrase in [
                "spec",
                "task",
                "reference",
            ]
        ), (
            "Integration summarizer prompt must instruct the agent to "
            "reference the spec and completed tasks that drove the changes"
        )

    def test_summary_described_as_for_pull_request(
        self, summarizer_prompt: str
    ) -> None:
        prompt_lower = summarizer_prompt.lower()
        assert any(
            phrase in prompt_lower
            for phrase in [
                "pull request",
                "pr",
            ]
        ), (
            "Integration summarizer prompt must describe the output as "
            "suitable for a pull request"
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
