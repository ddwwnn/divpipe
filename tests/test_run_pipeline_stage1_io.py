# tests/test_run_pipeline_stage1_io.py

from __future__ import annotations

from pathlib import Path

import pandas as pd

import engine.divpipe.run_pipeline as rp
from engine.divpipe.paths import RunPaths
from engine.divpipe.schema.columns import (
    STAGE1_DIVIDENDS_REQUIRED_COLUMNS,
    STAGE1_ERRORS_REQUIRED_COLUMNS,
    STAGE1_NO_DIVIDENDS_REQUIRED_COLUMNS,
)


def test_process_single_tag_writes_non_empty_outputs(tmp_path: Path, monkeypatch) -> None:
    out_root = tmp_path / "output" / "runs" / "demo"
    run_paths = RunPaths(out_root)
    run_paths.ensure()
    artefacts = rp.Artefacts(run_paths)

    holdings_path = tmp_path / "holdings_EEM.csv"
    holdings_path.write_text("dummy\n", encoding="utf-8")

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
        lambda holdings: holdings.assign(isin="US0000000001"),
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

    args = rp.build_parser().parse_args(
        [
            "--holdings",
            str(holdings_path),
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

    processed = rp._process_single_tag(
        holdings_path=holdings_path,
        tag="EEM",
        universe_region="EM",
        artefacts=artefacts,
        args=args,
        yfa=DummyAdaptor(),
        err_cols=STAGE1_ERRORS_REQUIRED_COLUMNS,
    )

    assert processed.universe_rows == 1
    assert processed.seed_df is not None
    assert processed.err_df is not None
    assert processed.no_div_df is not None

    assert artefacts.universe_tag("EEM").exists()
    assert artefacts.seed_dividends_tag("EEM").exists()
    assert artefacts.seed_errors_tag("EEM").exists()
    assert artefacts.seed_no_dividends_tag("EEM").exists()

    seed_df = pd.read_csv(artefacts.seed_dividends_tag("EEM"))
    assert len(seed_df) == 1
    assert seed_df.iloc[0]["underlying"] == "AAA"
    assert pd.api.types.is_float_dtype(seed_df["amount"])
    assert seed_df.iloc[0]["amount"] == 1.25


def test_write_stage1_aggregate_outputs_preserves_empty_column_contract(tmp_path: Path) -> None:
    out_root = tmp_path / "output" / "runs" / "demo"
    run_paths = RunPaths(out_root)
    run_paths.ensure()
    artefacts = rp.Artefacts(run_paths)

    results = [
        rp.Stage1TagResult(
            tag="EEM",
            holdings_path=Path("holdings_EEM.csv"),
            universe_region="EM",
            stage_dir=artefacts.tag_dir("EEM"),
            universe_rows=0,
            seed_df=None,
            err_df=None,
            no_div_df=None,
            failed=True,
            started_at="2026-03-17T00:00:00Z",
            finished_at="2026-03-17T00:00:00Z",
            elapsed_seconds=0.0,
            error="boom",
        )
    ]

    rp._write_stage1_aggregate_outputs(
        artefacts=artefacts,
        results=results,
        err_cols=STAGE1_ERRORS_REQUIRED_COLUMNS,
    )

    seed_all = pd.read_csv(artefacts.seed_dividends_all)
    err_all = pd.read_csv(artefacts.seed_errors_all)
    no_div_all = pd.read_csv(artefacts.seed_no_dividends_all)

    assert list(seed_all.columns) == rp._DEFAULT_SEED_COLS
    assert list(err_all.columns) == list(STAGE1_ERRORS_REQUIRED_COLUMNS)
    assert list(no_div_all.columns) == list(STAGE1_NO_DIVIDENDS_REQUIRED_COLUMNS)

    assert seed_all.empty
    assert err_all.empty
    assert no_div_all.empty


def test_main_logic_partial_failure_preserves_aggregate_column_contract_full_flow(tmp_path: Path, monkeypatch) -> None:
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
                    "source_event_key": ["AAA|USD|2025-01-15"],
                    "underlying": universe["underlying"].tolist(),
                    "isin": universe["isin"].tolist(),
                    "market": ["NYSE"],
                    "currency": ["USD"],
                    "action_type": ["cash_dividend"],
                    "status": ["historical"],
                    "ex_date": ["2025-01-15"],
                    "amount": ["0.5"],
                    "amount_type": ["per_share"],
                    "amount_ccy": ["USD"],
                    "confidence": [35],
                    "evidence_json": ['{"test": true}'],
                    "asof_date": ["2025-01-31"],
                    "ingest_ts": ["2026-03-17T00:00:00Z"],
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
    run_root = next(p for p in runs_dir.iterdir() if p.is_dir())
    artefacts = rp.Artefacts(RunPaths(run_root))

    seed_all = pd.read_csv(artefacts.seed_dividends_all)
    err_all = pd.read_csv(artefacts.seed_errors_all)
    no_div_all = pd.read_csv(artefacts.seed_no_dividends_all)

    for col in STAGE1_DIVIDENDS_REQUIRED_COLUMNS:
        assert col in seed_all.columns

    for col in STAGE1_ERRORS_REQUIRED_COLUMNS:
        assert col in err_all.columns

    for col in STAGE1_NO_DIVIDENDS_REQUIRED_COLUMNS:
        assert col in no_div_all.columns

    assert len(seed_all) == 1
    assert len(err_all) == 0
    assert len(no_div_all) == 1

    assert "holdings_tag" in seed_all.columns
    assert "holdings_file" in seed_all.columns

    assert seed_all.iloc[0]["underlying"] == "AAA"
    assert no_div_all.iloc[0]["exists_ticker"] == "UNSUPPORTED_YF"

    failed_seed = pd.read_csv(artefacts.seed_dividends_tag("EEM"))
    failed_err = pd.read_csv(artefacts.seed_errors_tag("EEM"))
    failed_no_div = pd.read_csv(artefacts.seed_no_dividends_tag("EEM"))

    assert list(failed_seed.columns) == list(STAGE1_DIVIDENDS_REQUIRED_COLUMNS)
    assert list(failed_err.columns) == list(STAGE1_ERRORS_REQUIRED_COLUMNS)
    assert list(failed_no_div.columns) == list(STAGE1_NO_DIVIDENDS_REQUIRED_COLUMNS)

    assert failed_seed.empty
    assert failed_err.empty
    assert failed_no_div.empty
