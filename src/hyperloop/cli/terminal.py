from __future__ import annotations

import shutil


def terminal_width() -> int:
    return shutil.get_terminal_size(fallback=(80, 24)).columns
