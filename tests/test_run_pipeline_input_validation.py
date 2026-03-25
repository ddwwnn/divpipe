# tests/test_run_pipeline_input_validation.py

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from engine.divpipe import run_pipeline as rp


def test_input_rejections_are_written_and_summarised(tmp_path: Path, monkeypatch) -> None:
    holdings = tmp_path / "holdings_DEBUG.csv"
    holdings.write_text(
        "underlying,weight,underlying_ccy,isin\n"
        "-,0.5,USD,\n"
        "PDD,0.5,USD,US7223041028\n",
        encoding="utf-8",
    )

    out_root = tmp_path / "output"

    class DummyAdaptor:
        def fetch_dividends(self, universe: pd.DataFrame, **kwargs):
            assert len(universe) == 1
            assert universe.iloc[0]["underlying"] == "PDD"

            df = pd.DataFrame(
                [
                    {
                        "source": "yfinance",
                        "source_event_key": "PDD|USD|2025-01-01",
                        "underlying": "PDD",
                        "isin": "US7223041028",
                        "market": "US",
                        "currency": "USD",
                        "yfinance_ticker": "PDD",
                        "action_type": "cash_dividend",
                        "status": "historical",
                        "ex_date": "2025-01-01",
                        "amount": 1.0,
                        "amount_type": "per_share",
                        "amount_ccy": "USD",
                        "confidence": 35,
                        "evidence_json": "{}",
                        "asof_date": "20260213",
                    }
                ]
            )
            err_df = pd.DataFrame(columns=rp.STAGE1_ERRORS_REQUIRED_COLUMNS)
            no_div_df = pd.DataFrame(columns=rp.STAGE1_NO_DIVIDENDS_REQUIRED_COLUMNS)
            disc_df = pd.DataFrame(
                [
                    {
                        "source": "yfinance",
                        "underlying": "PDD",
                        "underlying_ccy": "USD",
                        "isin": "US7223041028",
                        "chosen_ticker": "PDD",
                        "candidate_market": "US",
                        "candidate_origin": "auto_search",
                        "resolution_status": "div_found",
                        "resolution_reason": "div_found",
                        "resolution_method": "heuristic",
                        "resolution_source": "auto_search",
                        "candidate_count": 1,
                        "candidates_json": '["PDD"]',
                        "exists_ticker": "PDD",
                        "exists_ns": False,
                        "exists_bo": False,
                        "start": "20240101",
                        "end": "20260213",
                    }
                ]
            )
            return df, err_df, no_div_df, disc_df

    monkeypatch.setattr(rp, "_build_stage1_adaptor", lambda: DummyAdaptor())

    args = rp.build_parser().parse_args(
        [
            "--holdings",
            str(holdings),
            "--regions",
            "EM",
            "--allow-tag-inference",
            "--bgn",
            "20240101",
            "--end",
            "20260213",
            "--out",
            str(out_root),
            "--publish-latest-on-partial-failure",
        ]
    )

    rp.main_logic(args)

    runs_dir = out_root / "runs"
    run_dirs = [p for p in runs_dir.iterdir() if p.is_dir() and p.name != "latest"]
    assert run_dirs
    latest_run = sorted(run_dirs)[-1]

    rej = pd.read_csv(latest_run / "stage1_seed" / "seed_input_rejections_all.csv")
    summary = json.loads((latest_run / "_meta" / "stage1_summary.json").read_text(encoding="utf-8"))

    assert len(rej) == 1
    assert rej.iloc[0]["underlying_raw"] == "-"
    assert rej.iloc[0]["reason"] == "placeholder_underlying"
    assert rej.iloc[0]["holdings_tag"] == "DEBUG"

    assert summary["input_rejection_rows"] == 1
    assert summary["input_rejections_by_reason"]["placeholder_underlying"] == 1
    assert summary["tag_metrics"][0]["valid_universe_rows"] == 1


def test_main_logic_requires_tags_when_tag_inference_not_allowed(tmp_path: Path) -> None:
    holdings = tmp_path / "holdings_EEM.csv"
    holdings.write_text(
        "underlying,weight,underlying_ccy,isin\n"
        "PDD,1.0,USD,US7223041028\n",
        encoding="utf-8",
    )

    args = rp.build_parser().parse_args(
        [
            "--holdings",
            str(holdings),
            "--regions",
            "EM",
            "--bgn",
            "20240101",
            "--end",
            "20241231",
            "--out",
            str(tmp_path / "output"),
        ]
    )

    import pytest
    with pytest.raises(Exception, match="tags|allow-tag-inference"):
        rp.main_logic(args)


def test_main_logic_allows_tag_inference_when_enabled(tmp_path: Path, monkeypatch) -> None:
    holdings = tmp_path / "holdings_EEM.csv"
    holdings.write_text(
        "underlying,weight,underlying_ccy,isin\n"
        "PDD,1.0,USD,US7223041028\n",
        encoding="utf-8",
    )

    class DummyAdaptor:
        def fetch_dividends(self, universe: pd.DataFrame, **kwargs):
            return (
                pd.DataFrame(columns=rp._DEFAULT_SEED_COLS),
                pd.DataFrame(columns=rp.STAGE1_ERRORS_REQUIRED_COLUMNS),
                pd.DataFrame(columns=rp.STAGE1_NO_DIVIDENDS_REQUIRED_COLUMNS),
                pd.DataFrame(),
            )

    monkeypatch.setattr(rp, "_build_stage1_adaptor", lambda: DummyAdaptor())

    args = rp.build_parser().parse_args(
        [
            "--holdings",
            str(holdings),
            "--regions",
            "EM",
            "--allow-tag-inference",
            "--bgn",
            "20240101",
            "--end",
            "20241231",
            "--out",
            str(tmp_path / "output"),
            "--publish-latest-on-partial-failure",
        ]
    )

    rp.main_logic(args)


def test_main_logic_rejects_tags_holdings_length_mismatch(tmp_path: Path) -> None:
    h1 = tmp_path / "holdings_EEM.csv"
    h2 = tmp_path / "holdings_EFA.csv"
    for p in [h1, h2]:
        p.write_text(
            "underlying,weight,underlying_ccy,isin\n"
            "PDD,1.0,USD,US7223041028\n",
            encoding="utf-8",
        )

    args = rp.build_parser().parse_args(
        [
            "--holdings",
            str(h1),
            str(h2),
            "--tags",
            "EEM",
            "--regions",
            "EM",
            "DM",
            "--bgn",
            "20240101",
            "--end",
            "20241231",
            "--out",
            str(tmp_path / "output"),
        ]
    )

    import pytest
    with pytest.raises(Exception, match="tags"):
        rp.main_logic(args)


def test_main_logic_allows_stem_based_tag_inference_when_enabled(tmp_path: Path, monkeypatch) -> None:
    holdings = tmp_path / "foo.csv"
    holdings.write_text(
        "underlying,weight,underlying_ccy,isin\n"
        "PDD,1.0,USD,US7223041028\n",
        encoding="utf-8",
    )

    class DummyAdaptor:
        def fetch_dividends(self, universe: pd.DataFrame, **kwargs):
            return (
                pd.DataFrame(columns=rp._DEFAULT_SEED_COLS),
                pd.DataFrame(columns=rp.STAGE1_ERRORS_REQUIRED_COLUMNS),
                pd.DataFrame(columns=rp.STAGE1_NO_DIVIDENDS_REQUIRED_COLUMNS),
                pd.DataFrame(),
            )

    monkeypatch.setattr(rp, "_build_stage1_adaptor", lambda: DummyAdaptor())

    args = rp.build_parser().parse_args(
        [
            "--holdings",
            str(holdings),
            "--regions",
            "EM",
            "--allow-tag-inference",
            "--bgn",
            "20240101",
            "--end",
            "20241231",
            "--out",
            str(tmp_path / "output"),
            "--publish-latest-on-partial-failure",
        ]
    )

    rp.main_logic(args)