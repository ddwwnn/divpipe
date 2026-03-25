# tests/test_ticker_qa_mapping_issue.py

from __future__ import annotations

import pandas as pd

from src.engine.divpipe.pipeline.ticker_qa import build_ticker_map_report


def _build_input_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "underlying": "LEGN",
                "underlying_ccy": "USD",
                "isin": "US52490G1022",
                "chosen_ticker": "LEGN",
                "candidate_market": "NASDAQ",
                "candidate_origin": "auto_search",
                "resolution_status": "VERIFIED_EXISTS_BUT_NO_DIVIDENDS",
                "resolution_reason": "",
                "resolution_method": "isin_search",
                "resolution_source": "auto_search",
                "candidate_count": 2,
                "candidates_json": '["LEGN", "US52490G1022.SG"]',
                "exists_ticker": "LEGN",
                "exists_ns": False,
                "exists_bo": False,
            },
            {
                "underlying": "TMCV",
                "underlying_ccy": "INR",
                "isin": "",
                "chosen_ticker": "TMCV.NS",
                "candidate_market": "NS",
                "candidate_origin": "auto_search",
                "resolution_status": "CANDIDATE_UNVERIFIED",
                "resolution_reason": "ns_missing",
                "resolution_method": "heuristic",
                "resolution_source": "auto_search",
                "candidate_count": 2,
                "candidates_json": '["TMCV.NS", "TMCV.BO"]',
                "exists_ticker": "",
                "exists_ns": False,
                "exists_bo": False,
            },
            {
                "underlying": "NVMI",
                "underlying_ccy": "USD",
                "isin": "IL0010845571",
                "chosen_ticker": "NVMI",
                "candidate_market": "US",
                "candidate_origin": "auto_search",
                "resolution_status": "VERIFIED_EXISTS_BUT_NO_DIVIDENDS",
                "resolution_reason": "",
                "resolution_method": "isin_search",
                "resolution_source": "auto_search",
                "candidate_count": 2,
                "candidates_json": '["NVMI", "NVMI.TA"]',
                "exists_ticker": "NVMI",
                "exists_ns": False,
                "exists_bo": False,
            },
            {
                "underlying": "SUNMED",
                "underlying_ccy": "USD",
                "isin": "MYL5555OO007",
                "chosen_ticker": "5555.KL",
                "candidate_market": "KL",
                "candidate_origin": "auto_search",
                "resolution_status": "VERIFIED_EXISTS_BUT_NO_DIVIDENDS",
                "resolution_reason": "",
                "resolution_method": "isin_search",
                "resolution_source": "auto_search",
                "candidate_count": 2,
                "candidates_json": '["5555.KL", "SUNMED.KL"]',
                "exists_ticker": "5555.KL",
                "exists_ns": False,
                "exists_bo": False,
            },
            {
                "underlying": "STNE",
                "underlying_ccy": "USD",
                "isin": "KYG851581069",
                "chosen_ticker": "STNE",
                "candidate_market": "NASDAQ",
                "candidate_origin": "auto_search",
                "resolution_status": "VERIFIED_EXISTS_BUT_NO_DIVIDENDS",
                "resolution_reason": "",
                "resolution_method": "isin_search",
                "resolution_source": "auto_search",
                "candidate_count": 1,
                "candidates_json": '["STNE"]',
                "exists_ticker": "STNE",
                "exists_ns": False,
                "exists_bo": False,
            },
        ]
    )


def test_mapping_issue_class_legn_isin_sg_alias_pollution() -> None:
    report = build_ticker_map_report(_build_input_df())
    row = report.loc[report["underlying"] == "LEGN"].iloc[0]

    assert row["mapping_issue_class"] == "isin_sg_alias_pollution"
    assert row["candidate_list_pretty"] == "LEGN | US52490G1022.SG"
    assert row["candidate_suffixes"] == "US/PLAIN,SG"


def test_mapping_issue_class_tmcv_india_ns_bo_dual() -> None:
    report = build_ticker_map_report(_build_input_df())
    row = report.loc[report["underlying"] == "TMCV"].iloc[0]

    assert row["mapping_issue_class"] == "india_ns_bo_dual"
    assert row["candidate_list_pretty"] == "TMCV.NS | TMCV.BO"
    assert row["candidate_suffixes"] == "NS,BO"


def test_mapping_issue_class_nvmi_plain_plus_local_alt() -> None:
    report = build_ticker_map_report(_build_input_df())
    row = report.loc[report["underlying"] == "NVMI"].iloc[0]

    assert row["mapping_issue_class"] == "plain_plus_local_alt"
    assert row["candidate_list_pretty"] == "NVMI | NVMI.TA"
    assert row["candidate_suffixes"] == "US/PLAIN,TA"


def test_mapping_issue_class_sunmed_same_venue_alias() -> None:
    report = build_ticker_map_report(_build_input_df())
    row = report.loc[report["underlying"] == "SUNMED"].iloc[0]

    assert row["mapping_issue_class"] == "same_venue_alias"
    assert row["candidate_list_pretty"] == "5555.KL | SUNMED.KL"
    assert row["candidate_suffixes"] == "KL,KL"


def test_mapping_issue_class_stne_single_candidate_no_div() -> None:
    report = build_ticker_map_report(_build_input_df())
    row = report.loc[report["underlying"] == "STNE"].iloc[0]

    assert row["mapping_issue_class"] == "single_candidate_no_div"
    assert row["candidate_list_pretty"] == "STNE"
    assert row["candidate_suffixes"] == "US/PLAIN"