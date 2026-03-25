# tests/test_ticker_resolution_review.py

from __future__ import annotations

import json

import pandas as pd

from engine.divpipe.pipeline.ticker_resolution_canonical import FAILURE_STATUSES
from engine.divpipe.pipeline.ticker_resolution_review import (
    build_ticker_resolution_review_queue,
)


def test_build_ticker_resolution_review_queue_keeps_only_review_statuses() -> None:
    df = pd.DataFrame(
        [
            {
                "underlying": "AAA",
                "underlying_ccy": "USD",
                "chosen_ticker": "AAA",
                "exists_ticker": "AAA",
                "resolution_status": "div_found",
            },
            {
                "underlying": "BBB",
                "underlying_ccy": "USD",
                "chosen_ticker": "",
                "resolution_status": "ticker_not_found",
            },
            {
                "underlying": "CCC",
                "underlying_ccy": "USD",
                "chosen_ticker": "CCC.X",
                "exists_ticker": "CCC.X",
                "resolution_status": "candidate_unverified",
            },
        ]
    )

    out = build_ticker_resolution_review_queue(df)

    assert len(out) == 2
    assert set(out["underlying"]) == {"BBB", "CCC"}


def test_build_ticker_resolution_review_queue_adds_review_reason_and_preserves_extra_cols() -> None:
    df = pd.DataFrame(
        [
            {
                "underlying": "BBB",
                "underlying_ccy": "USD",
                "chosen_ticker": "",
                "resolution_status": "ticker_not_found",
                "extra_debug_col": "keep_me",
            },
            {
                "underlying": "CCC",
                "underlying_ccy": "USD",
                "chosen_ticker": "CCC.X",
                "exists_ticker": "CCC.X",
                "resolution_status": "candidate_unverified",
                "extra_debug_col": "keep_me_too",
            },
        ]
    )

    out = build_ticker_resolution_review_queue(df)

    assert len(out) == 2
    assert "review_reason" in out.columns
    assert "review_tags_json" in out.columns
    assert "review_tags_text" in out.columns
    assert "extra_debug_col" in out.columns

    reason_map = dict(zip(out["underlying"], out["review_reason"]))
    assert reason_map["BBB"] == "hard_failure"
    assert reason_map["CCC"] == "candidate_unverified"


def test_build_ticker_resolution_review_queue_marks_failure_statuses_as_hard_failure() -> None:
    rows = []
    for status in FAILURE_STATUSES:
        if str(status).strip().upper() == "CANDIDATE_UNVERIFIED":
            continue
        rows.append(
            {
                "underlying": f"U_{status}",
                "underlying_ccy": "USD",
                "chosen_ticker": "",
                "resolution_status": status,
            }
        )

    df = pd.DataFrame(rows)
    out = build_ticker_resolution_review_queue(df, include_statuses=tuple(FAILURE_STATUSES))

    assert len(out) == len(rows)
    assert set(out["review_reason"]) == {"hard_failure"}


def test_build_ticker_resolution_review_queue_marks_candidate_unverified_separately() -> None:
    df = pd.DataFrame(
        [
            {
                "underlying": "CCC",
                "underlying_ccy": "USD",
                "chosen_ticker": "CCC.X",
                "exists_ticker": "CCC.X",
                "resolution_status": "candidate_unverified",
            }
        ]
    )

    out = build_ticker_resolution_review_queue(df)

    assert len(out) == 1
    assert out.loc[0, "review_reason"] == "candidate_unverified"


def test_build_ticker_resolution_review_queue_dedupes_on_contract_key() -> None:
    df = pd.DataFrame(
        [
            {
                "underlying": "BBB",
                "underlying_ccy": "USD",
                "isin": "",
                "chosen_ticker": "",
                "resolution_status": "ticker_not_found",
                "candidate_origin": "auto_search",
            },
            {
                "underlying": "BBB",
                "underlying_ccy": "USD",
                "isin": "",
                "chosen_ticker": "",
                "resolution_status": "ticker_not_found",
                "candidate_origin": "auto_search_2",
            },
        ]
    )

    out = build_ticker_resolution_review_queue(df)

    assert len(out) == 1
    assert out.loc[0, "underlying"] == "BBB"
    assert out.loc[0, "resolution_status"] == "TICKER_NOT_FOUND"


def test_build_ticker_resolution_review_queue_includes_anomaly_only_rows() -> None:
    df = pd.DataFrame(
        [
            {
                "underlying": "AAA",
                "underlying_ccy": "USD",
                "isin": "US0000000001",
                "chosen_ticker": "AAA.X",
                "exists_ticker": "AAA.X",
                "resolution_status": "div_found",
                "guess_source": "ccy_fallback",
                "canonical_exchange": "",
                "isin_prefix": "US",
                "prefix_exchange_consistent": False,
            }
        ]
    )

    out = build_ticker_resolution_review_queue(df)

    assert len(out) == 1
    assert out.loc[0, "review_reason"] == "anomaly_review"


def test_build_ticker_resolution_review_queue_excludes_anomalies_when_disabled() -> None:
    df = pd.DataFrame(
        [
            {
                "underlying": "AAA",
                "underlying_ccy": "USD",
                "isin": "US0000000001",
                "chosen_ticker": "AAA.X",
                "exists_ticker": "AAA.X",
                "resolution_status": "div_found",
                "guess_source": "ccy_fallback",
                "canonical_exchange": "",
                "isin_prefix": "US",
                "prefix_exchange_consistent": False,
            }
        ]
    )

    out = build_ticker_resolution_review_queue(df, include_anomalies=False)

    assert out.empty


def test_build_ticker_resolution_review_queue_sets_review_tags_json() -> None:
    df = pd.DataFrame(
        [
            {
                "underlying": "CCC",
                "underlying_ccy": "USD",
                "chosen_ticker": "CCC.X",
                "exists_ticker": "CCC.X",
                "resolution_status": "candidate_unverified",
            }
        ]
    )

    out = build_ticker_resolution_review_queue(df)

    assert len(out) == 1
    tags = json.loads(out.loc[0, "review_tags_json"])
    assert "candidate_unverified" in tags


def test_build_ticker_resolution_review_queue_sets_review_tags_text() -> None:
    df = pd.DataFrame(
        [
            {
                "underlying": "AAA",
                "underlying_ccy": "USD",
                "isin": "US0000000001",
                "chosen_ticker": "AAA.X",
                "exists_ticker": "AAA.X",
                "resolution_status": "div_found",
                "guess_source": "ccy_fallback",
                "canonical_exchange": "",
                "isin_prefix": "US",
                "prefix_exchange_consistent": False,
            }
        ]
    )

    out = build_ticker_resolution_review_queue(df)

    assert len(out) == 1
    tags_text = out.loc[0, "review_tags_text"]
    assert "ccy_fallback" in tags_text
    assert "prefix_exchange_inconsistent" in tags_text


def test_build_ticker_resolution_review_queue_returns_empty_contract_for_none_input() -> None:
    out = build_ticker_resolution_review_queue(None)

    assert out.empty
    assert "review_reason" in out.columns
    assert "review_tags_json" in out.columns
    assert "review_tags_text" in out.columns


def test_build_ticker_resolution_review_queue_returns_empty_contract_for_empty_input() -> None:
    out = build_ticker_resolution_review_queue(pd.DataFrame())

    assert out.empty
    assert "review_reason" in out.columns
    assert "review_tags_json" in out.columns
    assert "review_tags_text" in out.columns