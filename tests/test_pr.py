"""Tests for PRManager — PR lifecycle: creation, labeling, gate polling, merge.

Uses FakePRManager (in-memory implementation). No mocks. No gh CLI calls.
"""

from __future__ import annotations

from tests.fakes.pr import FakePRManager


class TestCreateDraft:
    def test_returns_url(self):
        pr = FakePRManager(repo="org/repo")
        url = pr.create_draft(
            "task-001", "hyperloop/task-001", "Implement widget", "specs/widget.md"
        )
        assert url.startswith("https://")
        assert "org/repo" in url

    def test_records_labels(self):
        pr = FakePRManager(repo="org/repo")
        url = pr.create_draft(
            "task-001", "hyperloop/task-001", "Implement widget", "specs/widget.md"
        )
        labels = pr.get_labels(url)
        assert "task/task-001" in labels
        assert "spec/widget" in labels

    def test_records_pr_as_draft(self):
        pr = FakePRManager(repo="org/repo")
        url = pr.create_draft(
            "task-001", "hyperloop/task-001", "Implement widget", "specs/widget.md"
        )
        assert pr.is_draft(url)

    def test_stores_branch_and_title(self):
        pr = FakePRManager(repo="org/repo")
        url = pr.create_draft(
            "task-001", "hyperloop/task-001", "Implement widget", "specs/widget.md"
        )
        info = pr.get_pr_info(url)
        assert info["branch"] == "hyperloop/task-001"
        assert info["title"] == "Implement widget"

    def test_spec_ref_label_derives_name_from_path(self):
        pr = FakePRManager(repo="org/repo")
        url = pr.create_draft(
            "task-027", "hyperloop/task-027", "Implement persistence", "specs/persistence.md"
        )
        labels = pr.get_labels(url)
        assert "spec/persistence" in labels

    def test_spec_ref_label_handles_nested_paths(self):
        pr = FakePRManager(repo="org/repo")
        url = pr.create_draft(
            "task-050", "hyperloop/task-050", "Implement feature", "specs/sub/feature.md"
        )
        labels = pr.get_labels(url)
        assert "spec/sub/feature" in labels


class TestCheckGate:
    def test_returns_true_when_lgtm_present(self):
        pr = FakePRManager(repo="org/repo")
        url = pr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")
        pr.add_label(url, "lgtm")
        assert pr.check_gate(url, "human-pr-approval") is True

    def test_removes_lgtm_label_after_clearing(self):
        pr = FakePRManager(repo="org/repo")
        url = pr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")
        pr.add_label(url, "lgtm")
        pr.check_gate(url, "human-pr-approval")
        assert "lgtm" not in pr.get_labels(url)

    def test_returns_false_when_no_lgtm(self):
        pr = FakePRManager(repo="org/repo")
        url = pr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")
        assert pr.check_gate(url, "human-pr-approval") is False

    def test_gate_does_not_remove_other_labels(self):
        pr = FakePRManager(repo="org/repo")
        url = pr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")
        pr.add_label(url, "lgtm")
        pr.check_gate(url, "human-pr-approval")
        labels = pr.get_labels(url)
        assert "task/task-001" in labels
        assert "spec/widget" in labels


class TestMarkReady:
    def test_marks_draft_as_ready(self):
        pr = FakePRManager(repo="org/repo")
        url = pr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")
        assert pr.is_draft(url)
        pr.mark_ready(url)
        assert not pr.is_draft(url)

    def test_records_mark_ready_call(self):
        pr = FakePRManager(repo="org/repo")
        url = pr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")
        pr.mark_ready(url)
        assert url in pr.marked_ready


class TestMerge:
    def test_merge_succeeds_by_default(self):
        pr = FakePRManager(repo="org/repo")
        url = pr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")
        result = pr.merge(url, "task-001", "specs/widget.md")
        assert result is True

    def test_merge_records_call(self):
        pr = FakePRManager(repo="org/repo")
        url = pr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")
        pr.merge(url, "task-001", "specs/widget.md")
        assert url in pr.merged

    def test_merge_fails_when_configured(self):
        pr = FakePRManager(repo="org/repo")
        url = pr.create_draft("task-001", "hyperloop/task-001", "Widget", "specs/widget.md")
        pr.set_merge_fails(url)
        result = pr.merge(url, "task-001", "specs/widget.md")
        assert result is False
        assert url not in pr.merged

    def test_merge_uses_squash_strategy_by_default(self):
        pr = FakePRManager(repo="org/repo")
        assert pr.merge_strategy == "squash"


class TestRebaseBranch:
    def test_rebase_succeeds_by_default(self):
        pr = FakePRManager(repo="org/repo")
        result = pr.rebase_branch("hyperloop/task-001", "main")
        assert result is True

    def test_rebase_fails_when_configured(self):
        pr = FakePRManager(repo="org/repo")
        pr.set_rebase_fails("hyperloop/task-001")
        result = pr.rebase_branch("hyperloop/task-001", "main")
        assert result is False

    def test_rebase_records_call(self):
        pr = FakePRManager(repo="org/repo")
        pr.rebase_branch("hyperloop/task-001", "main")
        assert ("hyperloop/task-001", "main") in pr.rebased
