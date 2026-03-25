# tests/test_ticker_qa.py

from __future__ import annotations

import pandas as pd
import pytest

from engine.divpipe.pipeline.ticker_qa import build_ticker_map_report, failed_tickers


def test_build_ticker_map_report_accepts_legacy_reason_and_method_aliases() -> None:
    df = pd.DataFrame(
        [
            {
                "underlying": "INFY",
                "underlying_ccy": "inr",
                "chosen_ticker": "INFY.NS",
                "resolution_status": "success",
                "reason": "mapped",
                "method": "ns_first",
                "exists_ticker": "INFY.NS",
                "exists_ns": True,
                "exists_bo": False,
            }
        ]
    )

    out = build_ticker_map_report(df)

    assert out.loc[0, "resolution_reason"] == "mapped"
    assert out.loc[0, "resolution_method"] == "ns_first"
    assert bool(out.loc[0, "is_failed"]) is False
    assert bool(out.loc[0, "exists_ns"]) is True
    assert bool(out.loc[0, "exists_bo"]) is False


def test_build_ticker_map_report_accepts_resolution_columns() -> None:
    df = pd.DataFrame(
        [
            {
                "underlying": "TCS",
                "underlying_ccy": "inr",
                "chosen_ticker": "TCS.BO",
                "resolution_status": "success",
                "resolution_reason": "mapped",
                "resolution_method": "bo_fallback",
                "exists_ticker": "TCS.BO",
                "exists_ns": False,
                "exists_bo": True,
            }
        ]
    )

    out = build_ticker_map_report(df)

    assert out.loc[0, "resolution_reason"] == "mapped"
    assert out.loc[0, "resolution_method"] == "bo_fallback"
    assert bool(out.loc[0, "is_failed"]) is False
    assert bool(out.loc[0, "exists_ns"]) is False
    assert bool(out.loc[0, "exists_bo"]) is True


def test_build_ticker_map_report_preserves_ticker_casing() -> None:
    df = pd.DataFrame(
        [
            {
                "underlying": "abc",
                "underlying_ccy": "usd",
                "chosen_ticker": "Abc.Ns",
                "resolution_status": "success",
                "resolution_reason": "mapped",
                "resolution_method": "manual",
                "exists_ticker": "Abc.Ns",
            }
        ]
    )

    out = build_ticker_map_report(df)

    assert out.loc[0, "chosen_ticker"] == "Abc.Ns"
    assert out.loc[0, "exists_ticker"] == "Abc.Ns"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        (False, False),
        (1, True),
        (0, False),
        ("true", True),
        ("false", False),
        ("YES", True),
        ("no", False),
        ("", False),
        (None, False),
    ],
)
def test_build_ticker_map_report_parses_bool_like_values(value: object, expected: bool) -> None:
    df = pd.DataFrame(
        [
            {
                "underlying": "ABC",
                "underlying_ccy": "usd",
                "chosen_ticker": "ABC.NS",
                "resolution_status": "success",
                "resolution_reason": "mapped",
                "resolution_method": "test",
                "exists_ticker": "ABC.NS",
                "exists_ns": value,
                "exists_bo": False,
            }
        ]
    )

    out = build_ticker_map_report(df)

    assert bool(out.loc[0, "exists_ns"]) is expected


def test_build_ticker_map_report_raises_on_invalid_bool_like_value() -> None:
    df = pd.DataFrame(
        [
            {
                "underlying": "ABC",
                "underlying_ccy": "usd",
                "chosen_ticker": "ABC.NS",
                "resolution_status": "success",
                "resolution_reason": "mapped",
                "resolution_method": "test",
                "exists_ticker": "ABC.NS",
                "exists_ns": "maybe",
                "exists_bo": False,
            }
        ]
    )

    with pytest.raises(ValueError, match="invalid values in exists_ns"):
        build_ticker_map_report(df)


def test_build_ticker_map_report_marks_failure_when_ticker_blank() -> None:
    df = pd.DataFrame(
        [
            {
                "underlying": "ABC",
                "underlying_ccy": "usd",
                "chosen_ticker": "",
                "resolution_status": "success",
                "resolution_reason": "none",
                "resolution_method": "none",
                "exists_ticker": "",
            }
        ]
    )

    out = build_ticker_map_report(df)

    assert bool(out.loc[0, "is_failed"]) is True

def test_build_ticker_map_report_unsupported_vendor_is_failed() -> None:
    df = pd.DataFrame(
        [
            {
                "underlying": "ABC",
                "underlying_ccy": "usd",
                "chosen_ticker": "ABC",
                "resolution_status": "unsupported_vendor",
                "resolution_reason": "unsupported_vendor:yfinance",
                "resolution_method": "manual_tag",
                "exists_ticker": "ABC",
            }
        ]
    )

    out = build_ticker_map_report(df)

    assert bool(out.loc[0, "is_failed"]) is True

def test_build_ticker_map_report_marks_failure_when_status_is_ambiguous() -> None:
    df = pd.DataFrame(
        [
            {
                "underlying": "ABC",
                "underlying_ccy": "usd",
                "chosen_ticker": "ABC.NS",
                "resolution_status": "ambiguous",
                "resolution_reason": "multi_candidate",
                "resolution_method": "search",
                "exists_ticker": "ABC.NS",
            }
        ]
    )

    out = build_ticker_map_report(df)

    assert bool(out.loc[0, "is_failed"]) is True

def test_build_ticker_map_report_no_dividends_in_window_is_not_failed_when_ticker_exists() -> None:
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

    out = build_ticker_map_report(df)

    assert bool(out.loc[0, "is_failed"]) is False

def test_build_ticker_map_report_ticker_not_found_is_failed() -> None:
    df = pd.DataFrame(
        [
            {
                "underlying": "ABC",
                "underlying_ccy": "usd",
                "chosen_ticker": "",
                "resolution_status": "ticker_not_found",
                "resolution_reason": "not_found",
                "resolution_method": "probe",
                "exists_ticker": "",
            }
        ]
    )

    out = build_ticker_map_report(df)

    assert bool(out.loc[0, "is_failed"]) is True

def test_build_ticker_map_report_marks_failure_when_chosen_ticker_exists_check_missing() -> None:
    df = pd.DataFrame(
        [
            {
                "underlying": "ABC",
                "underlying_ccy": "usd",
                "chosen_ticker": "ABC.NS",
                "resolution_status": "success",
                "resolution_reason": "mapped",
                "resolution_method": "test",
                "exists_ticker": "",
            }
        ]
    )

    out = build_ticker_map_report(df)

    assert bool(out.loc[0, "is_failed"]) is True


def test_build_ticker_map_report_success_when_status_success_and_exists_ticker_present() -> None:
    df = pd.DataFrame(
        [
            {
                "underlying": "ABC",
                "underlying_ccy": "usd",
                "chosen_ticker": "ABC.NS",
                "resolution_status": "success",
                "resolution_reason": "mapped",
                "resolution_method": "test",
                "exists_ticker": "ABC.NS",
                "candidate_count": 1,
                "candidates_json": '["ABC.NS"]',
            }
        ]
    )

    out = build_ticker_map_report(df)

    assert bool(out.loc[0, "is_failed"]) is False
    assert out.loc[0, "candidate_count"] == 1
    assert out.loc[0, "candidates_json"] == '["ABC.NS"]'


def test_build_ticker_map_report_manual_override_is_not_failed_when_exists_ticker_present() -> None:
    df = pd.DataFrame(
        [
            {
                "underlying": "TCS",
                "underlying_ccy": "inr",
                "chosen_ticker": "TCS.BO",
                "resolution_status": "manual_override",
                "resolution_reason": "manual",
                "resolution_method": "override",
                "exists_ticker": "TCS.BO",
            }
        ]
    )

    out = build_ticker_map_report(df)

    assert bool(out.loc[0, "is_failed"]) is False


def test_build_ticker_map_report_normalises_candidate_defaults() -> None:
    df = pd.DataFrame(
        [
            {
                "underlying": "ABC",
                "underlying_ccy": "usd",
                "chosen_ticker": "ABC.NS",
                "resolution_status": "success",
                "resolution_reason": "mapped",
                "resolution_method": "test",
                "exists_ticker": "ABC.NS",
            }
        ]
    )

    out = build_ticker_map_report(df)

    assert out.loc[0, "candidate_count"] == 0
    assert out.loc[0, "candidates_json"] == ""


def test_build_ticker_map_report_raises_when_required_columns_missing() -> None:
    df = pd.DataFrame(
        [
            {
                "underlying": "ABC",
                "chosen_ticker": "ABC.NS",
                "resolution_status": "success",
            }
        ]
    )

    with pytest.raises(ValueError, match="ticker map df missing required columns"):
        build_ticker_map_report(df)


def test_build_ticker_map_report_returns_empty_contract_frame_for_none_input() -> None:
    out = build_ticker_map_report(None)

    assert list(out.columns) == [
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
    assert out.empty


def test_build_ticker_map_report_returns_empty_contract_frame_for_empty_input() -> None:
    out = build_ticker_map_report(pd.DataFrame())

    assert list(out.columns) == [
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
    assert out.empty

def test_failed_tickers_filters_failed_rows_only() -> None:
    df = pd.DataFrame(
        [
            {
                "underlying": "AAA",
                "underlying_ccy": "usd",
                "chosen_ticker": "AAA.NS",
                "resolution_status": "success",
                "resolution_reason": "mapped",
                "resolution_method": "test",
                "exists_ticker": "AAA.NS",
            },
            {
                "underlying": "BBB",
                "underlying_ccy": "usd",
                "chosen_ticker": "",
                "resolution_status": "not_found",
                "resolution_reason": "missing",
                "resolution_method": "test",
                "exists_ticker": "",
            },
        ]
    )

    out = failed_tickers(df)

    assert len(out) == 1
    assert out.loc[0, "underlying"] == "BBB"


@pytest.mark.parametrize(
    "status",
    ["ticker_not_found", "AmBiGuOuS", "UNSUPPORTED_vendor", "Error"],
)

def test_build_ticker_map_report_failure_statuses_are_case_insensitive(status: str) -> None:
    df = pd.DataFrame(
        [
            {
                "underlying": "ABC",
                "underlying_ccy": "usd",
                "chosen_ticker": "ABC.NS",
                "resolution_status": status,
                "resolution_reason": "test",
                "resolution_method": "test",
                "exists_ticker": "ABC.NS",
            }
        ]
    )

    out = build_ticker_map_report(df)

    assert bool(out.loc[0, "is_failed"]) is True