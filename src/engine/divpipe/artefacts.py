# src/engine/divpipe/artefacts.py

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .paths import RunPaths


@dataclass(frozen=True)
class Artefacts:
    paths: RunPaths

    @property
    def run_root(self) -> Path:
        return self.paths.run_root

    @property
    def meta_dir(self) -> Path:
        return self.paths.meta_dir

    @property
    def stage1_dir(self) -> Path:
        return self.paths.stage1_dir

    @property
    def stage2_dir(self) -> Path:
        return self.paths.stage2_dir

    @property
    def run_args(self) -> Path:
        return self.meta_dir / "run_args.json"

    @property
    def run_status(self) -> Path:
        return self.meta_dir / "run_status.json"

    @property
    def stage1_summary(self) -> Path:
        return self.meta_dir / "stage1_summary.json"

    def tag_dir(self, tag: str) -> Path:
        return self.stage1_dir / tag

    def universe_tag(self, tag: str) -> Path:
        return self.tag_dir(tag) / f"universe_{tag}.csv"

    def seed_dividends_tag(self, tag: str) -> Path:
        return self.tag_dir(tag) / f"seed_yfinance_dividends_{tag}.csv"

    def seed_errors_tag(self, tag: str) -> Path:
        return self.tag_dir(tag) / f"seed_yfinance_errors_{tag}.csv"

    def seed_no_dividends_tag(self, tag: str) -> Path:
        return self.tag_dir(tag) / f"seed_yfinance_no_dividends_{tag}.csv"

    def seed_discovered_candidates_tag(self, tag: str) -> Path:
        return self.tag_dir(tag) / f"seed_yfinance_discovered_candidates_{tag}.csv"

    def seed_input_rejections_tag(self, tag: str) -> Path:
        return self.tag_dir(tag) / f"seed_input_rejections_{tag}.csv"

    @property
    def seed_dividends_all(self) -> Path:
        return self.stage1_dir / "seed_yfinance_dividends_all.csv"

    @property
    def seed_errors_all(self) -> Path:
        return self.stage1_dir / "seed_yfinance_errors_all.csv"

    @property
    def seed_no_dividends_all(self) -> Path:
        return self.stage1_dir / "seed_yfinance_no_dividends_all.csv"

    @property
    def seed_discovered_candidates_all(self) -> Path:
        return self.stage1_dir / "seed_yfinance_discovered_candidates_all.csv"

    @property
    def seed_input_rejections_all(self) -> Path:
        return self.stage1_dir / "seed_input_rejections_all.csv"