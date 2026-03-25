# tests/test_report_failed_tickers.py

from __future__ import annotations

import pandas as pd

from engine.divpipe.pipeline.ticker_qa import build_ticker_map_report


def test_no_dividends_in_window_is_risk_not_hard_fail() -> None:
    df = pd.DataFrame(
        [
            {
                "underlying": "ABC",
                "underlying_ccy": "usd",
                "chosen_ticker": "ABC",
                "resolution_status": "no_dividends_in_window",
                "resolution_reason": "no_dividends_in_window",
                "resolution_method": "probe",
                "exists_ticker": "ABC",
            }
        ]
    )

    qa_report = build_ticker_map_report(df)

    assert bool(qa_report.loc[0, "is_failed"]) is False
    assert qa_report.loc[0, "resolution_status"] == "NO_DIVIDENDS_IN_WINDOW"
    

def test_hard_fail_vs_risk_split() -> None:
    df = pd.DataFrame(
        [
            {
                "underlying": "A",
                "underlying_ccy": "usd",
                "chosen_ticker": "",
                "resolution_status": "ticker_not_found",
                "resolution_reason": "not_found",
                "resolution_method": "probe",
                "exists_ticker": "",
            },
            {
                "underlying": "B",
                "underlying_ccy": "usd",
                "chosen_ticker": "B.NS",
                "resolution_status": "manual_override",
                "resolution_reason": "manual",
                "resolution_method": "override",
                "exists_ticker": "B.NS",
            },
            {
                "underlying": "C",
                "underlying_ccy": "usd",
                "chosen_ticker": "C.L",
                "resolution_status": "div_found",
                "resolution_reason": "div_found",
                "resolution_method": "probe",
                "exists_ticker": "C.L",
            },
        ]
    )

    qa_report = build_ticker_map_report(df)

    m_hard = qa_report["is_failed"]
    m_risk = (~qa_report["is_failed"]) & qa_report["resolution_status"].isin(
        ["MANUAL_OVERRIDE", "NO_DIVIDENDS_IN_WINDOW"]
    )
    m_ok = (~qa_report["is_failed"]) & qa_report["resolution_status"].isin(
        ["DIV_FOUND", "SUCCESS"]
    )

    assert int(m_hard.sum()) == 1
    assert int(m_risk.sum()) == 1
    assert int(m_ok.sum()) == 1