# tests/test_yfinance_adaptor_contract.py

from __future__ import annotations

import pandas as pd

from engine.divpipe.adaptors.yfinance_adaptor import YFinanceAdaptor
from engine.divpipe.adaptors import yfinance_models as ym
from engine.divpipe.schema.columns import (
    DISCOVERED_CANDIDATE_REQUIRED_COLUMNS,
    STAGE1_ERRORS_REQUIRED_COLUMNS,
    STAGE1_NO_DIVIDENDS_REQUIRED_COLUMNS,
)


def test_fetch_dividends_absorbs_worker_exception_into_err_df(monkeypatch) -> None:
    adaptor = YFinanceAdaptor()

    universe = pd.DataFrame(
        [
            {
                "underlying": "AAA",
                "underlying_ccy": "USD",
                "isin": "US0000000001",
                "weight": 1.0,
            },
            {
                "underlying": "BBB",
                "underlying_ccy": "USD",
                "isin": "US0000000002",
                "weight": 2.0,
            },
        ]
    )

    def fake_fetch_single_row(self, r, **kwargs):
        if getattr(r, "underlying", "") == "AAA":
            raise RuntimeError("boom from worker")

        return ym.FetchSingleRowResult(
            rows=[],
            errs=[],
            no_divs=[],
            discovered_candidate_rows=[],
        )

    monkeypatch.setattr(YFinanceAdaptor, "_fetch_single_row", fake_fetch_single_row)

    df, err_df, no_div_df, discovered_df = adaptor.fetch_dividends(
        universe,
        start="20250101",
        end="20250131",
        max_workers=2,
    )

    assert isinstance(df, pd.DataFrame)
    assert isinstance(err_df, pd.DataFrame)
    assert isinstance(no_div_df, pd.DataFrame)
    assert isinstance(discovered_df, pd.DataFrame)

    assert df.empty
    assert no_div_df.empty
    assert discovered_df.empty

    assert len(err_df) == 1
    assert err_df.iloc[0]["error"] == "worker_exception"
    assert err_df.iloc[0]["underlying"] == "AAA"
    assert err_df.iloc[0]["underlying_ccy"] == "USD"
    assert err_df.iloc[0]["isin"] == "US0000000001"


def test_fetch_dividends_worker_exception_row_has_diagnostic_fields(monkeypatch) -> None:
    adaptor = YFinanceAdaptor()

    universe = pd.DataFrame(
        [
            {
                "underlying": "ERR1",
                "underlying_ccy": "HKD",
                "isin": "HK0000000001",
                "weight": 1.0,
            }
        ]
    )

    def fake_fetch_single_row(self, r, **kwargs):
        raise ValueError("simulated worker failure")

    monkeypatch.setattr(YFinanceAdaptor, "_fetch_single_row", fake_fetch_single_row)

    _, err_df, _, _ = adaptor.fetch_dividends(
        universe,
        start="20250101",
        end="20250131",
        max_workers=1,
    )

    assert len(err_df) == 1

    row = err_df.iloc[0]
    assert row["error"] == "worker_exception"
    assert row["exception_type"] == "ValueError"
    assert row["exception"] == "simulated worker failure"

    assert row["candidates_json"] == "[]"
    assert row["candidate_count"] == 0
    assert row["start"] == "20250101"
    assert row["end"] == "20250131"


def test_fetch_dividends_returns_contract_shaped_empty_frames(monkeypatch) -> None:
    adaptor = YFinanceAdaptor()

    def fake_fetch_single_row(self, *args, **kwargs):
        return ym.FetchSingleRowResult(
            rows=[],
            errs=[],
            no_divs=[],
            discovered_candidate_rows=[],
        )

    monkeypatch.setattr(YFinanceAdaptor, "_fetch_single_row", fake_fetch_single_row)

    universe = pd.DataFrame(
        {
            "underlying": ["AAA"],
            "underlying_ccy": ["USD"],
            "weight": [1.0],
            "isin": ["US0000000001"],
        }
    )

    df, err_df, no_div_df, discovered_df = adaptor.fetch_dividends(
        universe,
        start="20250101",
        end="20250131",
        chosen_map_path="",
    )

    assert isinstance(df, pd.DataFrame)
    assert list(err_df.columns)[: len(STAGE1_ERRORS_REQUIRED_COLUMNS)] == list(STAGE1_ERRORS_REQUIRED_COLUMNS)
    assert list(no_div_df.columns)[: len(STAGE1_NO_DIVIDENDS_REQUIRED_COLUMNS)] == list(STAGE1_NO_DIVIDENDS_REQUIRED_COLUMNS)
    assert list(discovered_df.columns)[: len(DISCOVERED_CANDIDATE_REQUIRED_COLUMNS)] == list(DISCOVERED_CANDIDATE_REQUIRED_COLUMNS)

    assert err_df.empty
    assert no_div_df.empty
    assert discovered_df.empty


def test_fetch_dividends_keeps_chosen_map_read_only(monkeypatch, tmp_path) -> None:
    adaptor = YFinanceAdaptor()

    chosen_map = tmp_path / "chosen_map.csv"
    original = (
        "underlying,underlying_ccy,chosen_ticker,resolution_reason,resolution_method,isin,exists_ns,exists_bo\n"
        "AAA,USD,AAA,override,manual,US0000000001,False,False\n"
    )
    chosen_map.write_text(original, encoding="utf-8")

    def fake_fetch_single_row(self, *args, **kwargs):
        return ym.FetchSingleRowResult(
            rows=[],
            errs=[],
            no_divs=[],
            discovered_candidate_rows=[
                {
                    "source": "yfinance",
                    "underlying": "AAA",
                    "underlying_ccy": "USD",
                    "isin": "US0000000001",
                    "chosen_ticker": "AAA",
                    "resolution_status": "div_found",
                    "resolution_reason": "override",
                    "resolution_method": "manual",
                    "candidate_count": 1,
                    "candidates_json": '["AAA"]',
                    "exists_ticker": "AAA",
                    "exists_ns": False,
                    "exists_bo": False,
                    "start": "20250101",
                    "end": "20250131",
                }
            ],
        )

    monkeypatch.setattr(YFinanceAdaptor, "_fetch_single_row", fake_fetch_single_row)

    universe = pd.DataFrame(
        {
            "underlying": ["AAA"],
            "underlying_ccy": ["USD"],
            "weight": [1.0],
            "isin": ["US0000000001"],
        }
    )

    _, _, _, discovered_df = adaptor.fetch_dividends(
        universe,
        start="20250101",
        end="20250131",
        chosen_map_path=str(chosen_map),
    )

    assert chosen_map.read_text(encoding="utf-8") == original
    assert len(discovered_df) == 1
    assert discovered_df.iloc[0]["chosen_ticker"] == "AAA"


def test_fetch_dividends_emits_candidates_json_and_count(monkeypatch) -> None:
    adaptor = YFinanceAdaptor()

    def fake_fetch_single_row(self, *args, **kwargs):
        return ym.FetchSingleRowResult(
            rows=[],
            errs=[
                {
                    "source": "yfinance",
                    "underlying": "AAA",
                    "underlying_ccy": "USD",
                    "isin": "US0000000001",
                    "error": "ticker_not_found",
                    "candidates": ["AAA", "AAA.US"],
                    "candidates_json": '["AAA", "AAA.US"]',
                    "candidate_count": 2,
                    "start": "20250101",
                    "end": "20250131",
                }
            ],
            no_divs=[
                {
                    "source": "yfinance",
                    "underlying": "BBB",
                    "underlying_ccy": "USD",
                    "isin": "US0000000002",
                    "status": "no_dividends_in_window",
                    "exists_ticker": "BBB",
                    "candidates": ["BBB"],
                    "candidates_json": '["BBB"]',
                    "candidate_count": 1,
                    "start": "20250101",
                    "end": "20250131",
                }
            ],
            discovered_candidate_rows=[],
        )

    monkeypatch.setattr(YFinanceAdaptor, "_fetch_single_row", fake_fetch_single_row)

    universe = pd.DataFrame(
        {
            "underlying": ["AAA"],
            "underlying_ccy": ["USD"],
            "weight": [1.0],
            "isin": ["US0000000001"],
        }
    )

    _, err_df, no_div_df, _ = adaptor.fetch_dividends(
        universe,
        start="20250101",
        end="20250131",
        chosen_map_path="",
    )

    assert "candidates_json" in err_df.columns
    assert "candidate_count" in err_df.columns
    assert "candidates_json" in no_div_df.columns
    assert "candidate_count" in no_div_df.columns

    assert err_df.iloc[0]["candidate_count"] == 2
    assert no_div_df.iloc[0]["candidate_count"] == 1