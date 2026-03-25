# scripts/check_severity.py

from __future__ import annotations

import sys

from engine.divpipe.check_severity import (
    _apply_o3_merges_to_rows,
    _apply_o3_suppression,
    _build_o3_merge_map,
    _o3_pair_key,
    main,
    resolve_run_root,
)

__all__ = [
    "main",
    "resolve_run_root",
    "_o3_pair_key",
    "_apply_o3_suppression",
    "_build_o3_merge_map",
    "_apply_o3_merges_to_rows",
]

if __name__ == "__main__":
    main(sys.argv[1:])