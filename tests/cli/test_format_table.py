from __future__ import annotations

from hyperloop.cli.formatters.table import format_table


class TestFormatTable:
    def test_basic_table(self) -> None:
        headers = ["NAME", "STATUS"]
        rows = [["auth", "Synced"], ["users", "Failed"]]
        result = format_table(headers, rows)
        lines = result.strip().split("\n")
        assert len(lines) == 3
        assert "NAME" in lines[0]
        assert "STATUS" in lines[0]
        assert "auth" in lines[1]
        assert "users" in lines[2]

    def test_columns_are_aligned(self) -> None:
        headers = ["ID", "NAME"]
        rows = [["1", "short"], ["2", "much longer name"]]
        result = format_table(headers, rows)
        lines = result.strip().split("\n")
        header_name_pos = lines[0].index("NAME")
        row1_name_pos = lines[1].index("short")
        row2_name_pos = lines[2].index("much longer name")
        assert header_name_pos == row1_name_pos == row2_name_pos

    def test_empty_rows(self) -> None:
        headers = ["NAME", "STATUS"]
        rows: list[list[str]] = []
        result = format_table(headers, rows)
        lines = result.strip().split("\n")
        assert len(lines) == 1
        assert "NAME" in lines[0]

    def test_message_truncation(self) -> None:
        headers = ["MSG"]
        rows = [["This is a very long message that should be truncated"]]
        result = format_table(headers, rows, max_width=30)
        lines = result.strip().split("\n")
        assert lines[1].rstrip().endswith("...")
        assert len(lines[1].rstrip()) <= 30

    def test_no_truncation_when_fits(self) -> None:
        headers = ["MSG"]
        rows = [["short"]]
        result = format_table(headers, rows, max_width=80)
        lines = result.strip().split("\n")
        assert "..." not in lines[1]

    def test_multi_column_truncation_only_affects_last(self) -> None:
        headers = ["ID", "MSG"]
        rows = [["1", "This is a very long message that should be truncated"]]
        result = format_table(headers, rows, max_width=30)
        lines = result.strip().split("\n")
        assert lines[1].startswith("1")
        assert lines[1].rstrip().endswith("...")
