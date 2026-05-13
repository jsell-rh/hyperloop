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
