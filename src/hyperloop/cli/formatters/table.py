from __future__ import annotations

COLUMN_GAP = 3


def format_table(
    headers: list[str],
    rows: list[list[str]],
    *,
    max_width: int | None = None,
) -> str:
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))

    def _format_row(cells: list[str]) -> str:
        parts: list[str] = []
        for i, cell in enumerate(cells):
            if i < len(cells) - 1:
                parts.append(cell.ljust(col_widths[i] + COLUMN_GAP))
            else:
                parts.append(cell)
        line = "".join(parts)
        if max_width is not None and len(line) > max_width:
            line = line[: max_width - 3] + "..."
        return line

    lines = [_format_row(headers)]
    for row in rows:
        lines.append(_format_row(row))
    return "\n".join(lines) + "\n"
