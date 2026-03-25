from __future__ import annotations

from pathlib import Path


def format_display_path(path: Path | str, *, repo_root: Path | None = None) -> str:
    p = Path(path)

    try:
        p_resolved = p.resolve()
    except Exception:
        return str(p)

    if repo_root is not None:
        try:
            root_resolved = repo_root.resolve()
            return str(p_resolved.relative_to(root_resolved))
        except Exception:
            pass

    try:
        home = Path.home().resolve()
        return str(Path("~") / p_resolved.relative_to(home))
    except Exception:
        return str(p_resolved)
