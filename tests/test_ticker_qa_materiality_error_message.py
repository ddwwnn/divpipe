# tests/test_ticker_qa_materiality_error_message.py

from __future__ import annotations

import pytest
import pandas as pd

from src.engine.divpipe.pipeline.ticker_qa import (
    TickerMapMaterialityError,
    validate_ticker_map_materiality,
)


def _build_report_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "underlying": "LEGN",
                "chosen_ticker": "LEGN",
                "resolution_status": "VERIFIED_EXISTS_BUT_NO_DIVIDENDS",
                "weight": 0.0121,
                "is_failed": True,
            },
            {
                "underlying": "TMCV",
                "chosen_ticker": "TMCV.NS",
                "resolution_status": "CANDIDATE_UNVERIFIED",
                "weight": 0.0104,
                "is_failed": True,
            },
            {
                "underlying": "SUNMED",
                "chosen_ticker": "5555.KL",
                "resolution_status": "VERIFIED_EXISTS_BUT_NO_DIVIDENDS",
                "weight": 0.0087,
                "is_failed": True,
            },
            {
                "underlying": "STNE",
                "chosen_ticker": "STNE",
                "resolution_status": "VERIFIED_EXISTS_BUT_NO_DIVIDENDS",
                "weight": 0.0010,
                "is_failed": False,
            },
        ]
    )


def test_total_fail_weight_threshold_error_includes_top_failed_rows() -> None:
    report = _build_report_df()

    with pytest.raises(TickerMapMaterialityError) as exc_info:
        validate_ticker_map_materiality(
            report,
            total_fail_weight_threshold=0.02,
        )

    message = str(exc_info.value)

    assert "total failed weight threshold breached" in message
    assert "top_failed=[" in message
    assert "LEGN:LEGN:VERIFIED_EXISTS_BUT_NO_DIVIDENDS:0.0121" in message
    assert "TMCV:TMCV.NS:CANDIDATE_UNVERIFIED:0.0104" in message
    assert "SUNMED:5555.KL:VERIFIED_EXISTS_BUT_NO_DIVIDENDS:0.0087" in message


def test_single_fail_weight_threshold_error_includes_top_failed_rows() -> None:
    report = _build_report_df()

    with pytest.raises(TickerMapMaterialityError) as exc_info:
        validate_ticker_map_materiality(
            report,
            single_fail_weight_threshold=0.01,
        )

    message = str(exc_info.value)

    assert "single failed weight threshold breached" in message
    assert "top_failed=[" in message
    assert "LEGN:LEGN:VERIFIED_EXISTS_BUT_NO_DIVIDENDS:0.0121" in message


def test_unmatched_failed_error_includes_top_failed_rows() -> None:
    report = _build_report_df().copy()
    report["weight_match_method"] = ["unmatched", "exact_underlying_ccy_isin", "unmatched", "exact_underlying_ccy_isin"]

    with pytest.raises(TickerMapMaterialityError) as exc_info:
        validate_ticker_map_materiality(
            report,
            fail_on_unmatched_failed=True,
        )

    message = str(exc_info.value)

    assert "unmatched failed rows present" in message
    assert "top_failed=[" in message
    assert "LEGN:LEGN:VERIFIED_EXISTS_BUT_NO_DIVIDENDS:0.0121" in message