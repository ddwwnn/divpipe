# tests/test_run_pipeline_summary.py

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import engine.divpipe.run_pipeline as rp
from engine.divpipe.paths import RunPaths
from engine.divpipe.schema.columns import (
    STAGE1_ERRORS_REQUIRED_COLUMNS,
    STAGE1_NO_DIVIDENDS_REQUIRED_COLUMNS,
)


def test_main_logic_stage1_summary_timing_matches_tag_metrics(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)

    holdings_eem = repo_root / "holdings_EEM.csv"
    holdings_efa = repo_root / "holdings_EFA.csv"
    holdings_eem.write_text("dummy\n", encoding="utf-8")
    holdings_efa.write_text("dummy\n", encoding="utf-8")

    monkeypatch.setattr(rp, "_repo_root", lambda: repo_root)
    monkeypatch.setattr(rp, "update_latest_symlink", lambda out_root: None)
    monkeypatch.setattr(rp, "_get_error_columns", lambda: list(STAGE1_ERRORS_REQUIRED_COLUMNS))

    def fake_load_holdings(path: Path, include_zero_weight: bool = False) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "underlying": ["AAA"],
                "weight": [1.0],
                "underlying_ccy": ["USD"],
            }
        )

    def fake_build_universe(holdings: pd.DataFrame) -> pd.DataFrame:
        return holdings.assign(isin="US0000000001")

    monkeypatch.setattr(rp, "load_holdings", fake_load_holdings)
    monkeypatch.setattr(rp, "build_universe", fake_build_universe)

    class DummyAdaptor:
        def fetch_dividends(
            self,
            universe: pd.DataFrame,
            *,
            start: str = "",
            end: str = "",
            sleep_sec: float = 0.0,
            progress_every: int = 50,
            exists_lookback_period: str = "5d",
            chosen_map_path: str = "",
            return_details: bool = False,
            isin_search_timeout_sec: float = 10.0,
            isin_quotes_count: int = 10,
            universe_region: str = "EM",
            asof_date: str | None = None,
            max_workers: int = 8,
        ):
            seed_df = pd.DataFrame(
                {
                    "source": ["yfinance"],
                    "underlying": universe["underlying"].tolist(),
                    "underlying_ccy": universe["underlying_ccy"].tolist(),
                    "isin": universe["isin"].tolist(),
                    "amount": ["1.25"],
                    "ex_date": ["2025-01-15"],
                }
            )
            seed_err = pd.DataFrame(columns=STAGE1_ERRORS_REQUIRED_COLUMNS)
            seed_no_div = pd.DataFrame(columns=STAGE1_NO_DIVIDENDS_REQUIRED_COLUMNS)
            return seed_df, seed_err, seed_no_div, pd.DataFrame()

    monkeypatch.setattr(rp, "_build_stage1_adaptor", lambda: DummyAdaptor())

    args = rp.build_parser().parse_args(
        [
            "--holdings",
            str(holdings_eem),
            str(holdings_efa),
            "--tags",
            "EEM",
            "EFA",
            "--regions",
            "EM",
            "DM",
            "--out",
            "output",
            "--bgn",
            "20250101",
            "--end",
            "20250131",
        ]
    )

    rp.main_logic(args)

    runs_dir = repo_root / "output" / "runs"
    run_root = next(p for p in runs_dir.iterdir() if p.is_dir())
    artefacts = rp.Artefacts(RunPaths(run_root))

    summary = json.loads(artefacts.stage1_summary.read_text(encoding="utf-8"))
    timing = summary["timing"]
    tag_metrics = summary["tag_metrics"]

    elapsed_values = [float(row["elapsed_seconds"]) for row in tag_metrics]

    assert "total_elapsed_seconds" in timing
    assert "max_tag_elapsed_seconds" in timing
    assert "mean_tag_elapsed_seconds" in timing

    assert timing["total_elapsed_seconds"] >= 0.0
    assert timing["max_tag_elapsed_seconds"] >= 0.0
    assert timing["mean_tag_elapsed_seconds"] >= 0.0

    assert timing["total_elapsed_seconds"] == pytest.approx(sum(elapsed_values), abs=1e-6)
    assert timing["max_tag_elapsed_seconds"] == pytest.approx(max(elapsed_values), abs=1e-6)
    assert timing["mean_tag_elapsed_seconds"] == pytest.approx(sum(elapsed_values) / len(elapsed_values), abs=1e-6)


def test_build_stage1_summary_includes_failed_region() -> None:
    results = [
        rp.Stage1TagResult(
            tag="EEM",
            holdings_path=Path("holdings_EEM.csv"),
            universe_region="EM",
            stage_dir=Path("stage1_seed/EEM"),
            universe_rows=0,
            seed_df=None,
            err_df=None,
            no_div_df=None,
            failed=True,
            started_at="2026-03-17T00:00:00Z",
            finished_at="2026-03-17T00:00:00Z",
            elapsed_seconds=0.0,
            error="simulated fetch failure",
        ),
        rp.Stage1TagResult(
            tag="EFA",
            holdings_path=Path("holdings_EFA.csv"),
            universe_region="DM",
            stage_dir=Path("stage1_seed/EFA"),
            universe_rows=3,
            seed_df=pd.DataFrame({"a": [1, 2]}),
            err_df=pd.DataFrame(),
            no_div_df=pd.DataFrame({"b": [1]}),
            failed=False,
            started_at="2026-03-17T00:00:01Z",
            finished_at="2026-03-17T00:00:03Z",
            elapsed_seconds=2.0,
            error=None,
        ),
    ]

    summary = rp._build_stage1_summary(results)

    assert summary["tag_count"] == 2
    assert summary["failed_tag_count"] == 1
    assert summary["successful_tag_count"] == 1
    assert summary["regions"] == ["EM", "DM"]
    assert summary["failed_tags"][0]["tag"] == "EEM"
    assert summary["failed_tags"][0]["region"] == "EM"


def test_main_logic_writes_stage1_summary_with_failed_tag_count(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)

    holdings_eem = repo_root / "holdings_EEM.csv"
    holdings_efa = repo_root / "holdings_EFA.csv"
    holdings_eem.write_text("dummy\n", encoding="utf-8")
    holdings_efa.write_text("dummy\n", encoding="utf-8")

    monkeypatch.setattr(rp, "_repo_root", lambda: repo_root)
    monkeypatch.setattr(rp, "update_latest_symlink", lambda out_root: None)
    monkeypatch.setattr(rp, "_get_error_columns", lambda: list(STAGE1_ERRORS_REQUIRED_COLUMNS))

    def fake_load_holdings(path: Path, include_zero_weight: bool = False) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "underlying": ["AAA"],
                "weight": [1.0],
                "underlying_ccy": ["USD"],
            }
        )

    def fake_build_universe(holdings: pd.DataFrame) -> pd.DataFrame:
        return holdings.assign(isin="US0000000001")

    monkeypatch.setattr(rp, "load_holdings", fake_load_holdings)
    monkeypatch.setattr(rp, "build_universe", fake_build_universe)

    class DummyAdaptor:
        def __init__(self) -> None:
            self.calls = 0

        def fetch_dividends(
            self,
            universe: pd.DataFrame,
            *,
            start: str = "",
            end: str = "",
            sleep_sec: float = 0.0,
            progress_every: int = 50,
            exists_lookback_period: str = "5d",
            chosen_map_path: str = "",
            return_details: bool = False,
            isin_search_timeout_sec: float = 10.0,
            isin_quotes_count: int = 10,
            universe_region: str = "EM",
            asof_date: str | None = None,
            max_workers: int = 8,
        ):
            self.calls += 1

            if self.calls == 1:
                raise RuntimeError("simulated fetch failure")

            seed_df = pd.DataFrame(
                {
                    "source": ["yfinance"],
                    "underlying": universe["underlying"].tolist(),
                    "underlying_ccy": universe["underlying_ccy"].tolist(),
                    "isin": universe["isin"].tolist(),
                    "amount": ["0.5"],
                    "ex_date": ["2025-01-15"],
                }
            )
            seed_err = pd.DataFrame(columns=STAGE1_ERRORS_REQUIRED_COLUMNS)
            seed_no_div = pd.DataFrame(
                {
                    "source": ["yfinance"],
                    "underlying": ["BBB"],
                    "underlying_ccy": ["USD"],
                    "isin": [""],
                    "status": ["no_dividends_in_window"],
                    "exists_ticker": ["UNSUPPORTED_YF"],
                    "candidates": [""],
                    "start": [start],
                    "end": [end],
                }
            )
            return seed_df, seed_err, seed_no_div, pd.DataFrame()

    monkeypatch.setattr(rp, "_build_stage1_adaptor", lambda: DummyAdaptor())

    args = rp.build_parser().parse_args(
        [
            "--holdings",
            str(holdings_eem),
            str(holdings_efa),
            "--tags",
            "EEM",
            "EFA",
            "--regions",
            "EM",
            "DM",
            "--out",
            "output",
            "--bgn",
            "20250101",
            "--end",
            "20250131",
            "--progress-every",
            "10",
        ]
    )

    rp.main_logic(args)

    runs_dir = repo_root / "output" / "runs"
    run_roots = [p for p in runs_dir.iterdir() if p.is_dir()]
    assert len(run_roots) == 1

    run_root = run_roots[0]
    artefacts = rp.Artefacts(RunPaths(run_root))

    summary_path = artefacts.stage1_summary
    run_args_path = artefacts.run_args

    assert summary_path.exists()
    assert run_args_path.exists()

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    run_args = json.loads(run_args_path.read_text(encoding="utf-8"))

    assert summary["tag_count"] == 2
    assert summary["failed_tag_count"] == 1
    assert summary["successful_tag_count"] == 1
    assert summary["regions"] == ["EM", "DM"]
    assert summary["failed_tags"][0]["tag"] == "EEM"
    assert summary["failed_tags"][0]["region"] == "EM"
    assert "started_at" in summary["failed_tags"][0]
    assert "finished_at" in summary["failed_tags"][0]
    assert "elapsed_seconds" in summary["failed_tags"][0]
    assert "tag_metrics" in summary
    assert "timing" in summary

    failed = summary["failed_tags"][0]
    assert failed["started_at"] <= failed["finished_at"]
    assert failed["elapsed_seconds"] >= 0.0

    assert run_args["tags"] == ["EEM", "EFA"]
    assert run_args["regions"] == ["EM", "DM"]


def test_run_args_layout_matches_artefacts_and_runpaths(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)

    holdings = repo_root / "holdings_EEM.csv"
    holdings.write_text("dummy\n", encoding="utf-8")

    monkeypatch.setattr(rp, "_repo_root", lambda: repo_root)
    monkeypatch.setattr(rp, "update_latest_symlink", lambda out_root: None)
    monkeypatch.setattr(rp, "_get_error_columns", lambda: list(STAGE1_ERRORS_REQUIRED_COLUMNS))

    monkeypatch.setattr(
        rp,
        "load_holdings",
        lambda path, include_zero_weight=False: pd.DataFrame(
            {
                "underlying": ["AAA"],
                "weight": [1.0],
                "underlying_ccy": ["USD"],
            }
        ),
    )
    monkeypatch.setattr(
        rp,
        "build_universe",
        lambda holdings_df: holdings_df.assign(isin="US0000000001"),
    )

    class DummyAdaptor:
        def fetch_dividends(
            self,
            universe: pd.DataFrame,
            *,
            start: str = "",
            end: str = "",
            sleep_sec: float = 0.0,
            progress_every: int = 50,
            exists_lookback_period: str = "5d",
            chosen_map_path: str = "",
            return_details: bool = False,
            isin_search_timeout_sec: float = 10.0,
            isin_quotes_count: int = 10,
            universe_region: str = "EM",
            asof_date: str | None = None,
            max_workers: int = 8,
        ):
            seed_df = pd.DataFrame(
                {
                    "source": ["yfinance"],
                    "underlying": universe["underlying"].tolist(),
                    "underlying_ccy": universe["underlying_ccy"].tolist(),
                    "isin": universe["isin"].tolist(),
                    "amount": ["1.25"],
                    "ex_date": ["2025-01-15"],
                }
            )
            seed_err = pd.DataFrame(columns=STAGE1_ERRORS_REQUIRED_COLUMNS)
            seed_no_div = pd.DataFrame(columns=STAGE1_NO_DIVIDENDS_REQUIRED_COLUMNS)
            return seed_df, seed_err, seed_no_div, pd.DataFrame()

    monkeypatch.setattr(rp, "_build_stage1_adaptor", lambda: DummyAdaptor())

    args = rp.build_parser().parse_args(
        [
            "--holdings",
            str(holdings),
            "--tags",
            "EEM",
            "--regions",
            "EM",
            "--out",
            "output",
            "--bgn",
            "20250101",
            "--end",
            "20250131",
        ]
    )

    rp.main_logic(args)

    runs_dir = repo_root / "output" / "runs"
    run_root = next(p for p in runs_dir.iterdir() if p.is_dir())
    artefacts = rp.Artefacts(RunPaths(run_root))

    run_args = json.loads(artefacts.run_args.read_text(encoding="utf-8"))
    layout = run_args["layout"]

    assert layout["meta_dir"] == str(artefacts.meta_dir.relative_to(artefacts.run_root))
    assert layout["stage1_dir"] == str(artefacts.stage1_dir.relative_to(artefacts.run_root))
    assert layout["stage2_dir"] == str(artefacts.stage2_dir.relative_to(artefacts.run_root))
    assert layout["tag_dirs"] == f"{artefacts.stage1_dir.relative_to(artefacts.run_root)}/<TAG>/"
    assert layout["run_args"] == str(artefacts.run_args.relative_to(artefacts.run_root))
    assert layout["stage1_summary"] == str(artefacts.stage1_summary.relative_to(artefacts.run_root))
