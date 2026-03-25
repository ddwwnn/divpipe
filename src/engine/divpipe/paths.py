# src/engine/divpipe/paths.py

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RunPaths:
    run_root: Path

    @property
    def meta_dir(self) -> Path:
        return self.run_root / "_meta"

    @property
    def stage1_dir(self) -> Path:
        return self.run_root / "stage1_seed"

    @property
    def stage2_dir(self) -> Path:
        return self.run_root / "stage2_analysis"

    def tag_dir(self, tag: str) -> Path:
        return self.stage1_dir / str(tag).strip().upper()

    def ensure(self) -> None:
        self.run_root.mkdir(parents=True, exist_ok=True)
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        self.stage1_dir.mkdir(parents=True, exist_ok=True)
        self.stage2_dir.mkdir(parents=True, exist_ok=True)