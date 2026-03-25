# src/engine/divpipe/utils/repo.py

from __future__ import annotations

import os
from pathlib import Path


def find_repo_root_from(start: Path) -> Path | None:
    start_resolved = start.expanduser().resolve()

    candidates = [start_resolved]
    candidates.extend(start_resolved.parents)

    for candidate in candidates:
        if (candidate / "pyproject.toml").exists():
            return candidate
        if (candidate / ".git").exists():
            return candidate

    return None


def get_repo_root(
    *,
    env_var: str = "DIVPIPE_ROOT",
    start: Path | None = None,
    fallback_to_cwd: bool = False,
) -> Path:
    env_root = os.environ.get(env_var, "").strip()
    if env_root:
        return Path(env_root).expanduser().resolve()

    anchor = start if start is not None else Path(__file__)
    found = find_repo_root_from(anchor)
    if found is not None:
        return found

    if fallback_to_cwd:
        return Path.cwd().resolve()

    raise FileNotFoundError(
        f"Could not determine repository root from start={anchor!s} and env_var={env_var!r}"
    )