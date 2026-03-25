# tests/test_ticker_map_report.py

from __future__ import annotations

import pandas as pd

from engine.divpipe.pipeline.ticker_qa import build_ticker_map_report

EXPECTED_TICKER_QA_REPORT_COLUMNS = [
    "underlying",
    "underlying_ccy",
    "isin",
    "chosen_ticker",
    "candidate_market",
    "candidate_origin",
    "resolution_status",
    "resolution_reason",
    "resolution_method",
    "resolution_source",
    "candidate_count",
    "candidates_json",
    "exists_ticker",
    "exists_ns",
    "exists_bo",
    "is_failed",
]


def test_build_ticker_map_report_returns_empty_contract_frame_for_none_input() -> None:
    out = build_ticker_map_report(None)

    assert list(out.columns) == EXPECTED_TICKER_QA_REPORT_COLUMNS
    assert out.empty


def test_build_ticker_map_report_returns_empty_contract_frame_for_empty_input() -> None:
    out = build_ticker_map_report(pd.DataFrame())

    assert list(out.columns) == EXPECTED_TICKER_QA_REPORT_COLUMNS
    assert out.empty